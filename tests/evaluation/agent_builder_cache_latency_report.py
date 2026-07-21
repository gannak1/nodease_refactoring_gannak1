"""Deterministic offline reports for Agent Builder cache latency samples.

This module deliberately has no product-runtime, database, provider, or Redis
dependency. It consumes only an allowlisted synthetic dataset or ``runs.csv``.
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "agent-builder-cache-latency-runs-v1"

RUNS_CSV_FIELDS = (
    "case_id",
    "pair_id",
    "run_id",
    "comparison_group",
    "is_warmup",
    "cache_outcome",
    "planning_latency_ms",
    "end_to_end_latency_ms",
    "provider_call_count",
    "repair_call_count",
    "terminal_status",
    "validation_passed",
    "result_fingerprint",
)

SUMMARY_CSV_FIELDS = (
    "record_type",
    "comparison_group",
    "surface",
    "metric",
    "value",
    "unit",
    "sample_count",
    "baseline_group",
    "hit_rate",
    "estimate_type",
)

ARTIFACT_FILENAMES = (
    "README.md",
    "runs.csv",
    "summary.json",
    "summary.csv",
    "summary.md",
    "latency-comparison.svg",
    "cache-hit-scenarios.svg",
)

COMPARISON_GROUPS = (
    "cache_disabled_baseline",
    "cold_miss",
    "exact_warm_hit",
    "normalization_warm_hit",
    "semantic_bypass",
    "negative_control",
    "redis_fail_open",
)

CANDIDATE_GROUPS = COMPARISON_GROUPS[1:]
WARM_GROUPS = ("exact_warm_hit", "normalization_warm_hit")
MISS_PATH_GROUPS = (
    "cold_miss",
    "semantic_bypass",
    "negative_control",
    "redis_fail_open",
)
SURFACES = ("planning_latency_ms", "end_to_end_latency_ms")
STATISTIC_KEYS = (
    "mean_ms",
    "p50_ms",
    "p95_ms",
    "stddev_ms",
    "min_ms",
    "max_ms",
)

ALLOWED_OUTCOMES = {
    "cache_disabled_baseline": frozenset({"disabled"}),
    "cold_miss": frozenset({"miss"}),
    "exact_warm_hit": frozenset({"hit", "miss"}),
    "normalization_warm_hit": frozenset({"hit", "miss"}),
    "semantic_bypass": frozenset({"bypass"}),
    "negative_control": frozenset({"miss", "bypass", "error"}),
    "redis_fail_open": frozenset({"error"}),
}

TERMINAL_STATUSES = {
    "success",
    "provider_error",
    "validation_error",
    "timeout",
    "canceled",
}

DATASET_FIELDS = {
    "schema_version",
    "dataset_version",
    "cache_contract_version",
    "benchmark_kind",
    "run_date",
    "git_sha",
    "benchmark_id",
    "runs",
}

SAFE_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{7,40}$")
UUID_TEXT = re.compile(
    r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)

FORBIDDEN_STRUCTURED_FIELDS = (
    "prompt",
    "message",
    "provider_payload",
    "credential_id",
    "user_id",
    "organization_id",
    "workflow_id",
    "request_id",
    "access_token",
    "api_key",
    "secret",
)


class ReportValidationError(ValueError):
    """Raised when metadata, rows, or pair structure violates the contract."""


class ArtifactSafetyError(ValueError):
    """Raised without echoing the unsafe value found in rendered content."""


@dataclass(frozen=True)
class BenchmarkMetadata:
    schema_version: str
    dataset_version: str
    cache_contract_version: str
    benchmark_kind: str
    run_date: str
    git_sha: str
    benchmark_id: str


@dataclass(frozen=True)
class RunRow:
    case_id: str
    pair_id: str
    run_id: str
    comparison_group: str
    is_warmup: bool
    cache_outcome: str
    planning_latency_ms: float | None
    end_to_end_latency_ms: float | None
    provider_call_count: int
    repair_call_count: int
    terminal_status: str
    validation_passed: bool
    result_fingerprint: str

    @property
    def is_success(self) -> bool:
        return self.terminal_status == "success" and self.validation_passed

    @property
    def artifact_key(self) -> str:
        return ":".join(
            (
                self.case_id,
                self.pair_id,
                self.run_id,
                self.comparison_group,
            )
        )


@dataclass(frozen=True)
class LatencyDataset:
    metadata: BenchmarkMetadata
    runs: tuple[RunRow, ...]


def _error(field: str, reason: str) -> ReportValidationError:
    return ReportValidationError(f"Invalid {field}: {reason}")


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise _error(field, "expected string")
    return value


def _safe_identifier(value: Any, field: str) -> str:
    text = _require_string(value, field)
    if UUID_TEXT.search(text):
        raise _error(field, "protected identifier is not allowed")
    if not SAFE_IDENTIFIER.fullmatch(text):
        raise _error(field, "expected short ASCII slug")
    return text


def _strict_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise _error(field, "expected boolean")
    return value


def _strict_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise _error(field, "expected non-negative integer")
    return value


def _latency(value: Any, field: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(field, "expected finite non-negative number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise _error(field, "expected finite non-negative number")
    return parsed


def _validate_metadata(metadata: BenchmarkMetadata) -> BenchmarkMetadata:
    if metadata.schema_version != SCHEMA_VERSION:
        raise _error("schema_version", "unknown version")
    if not SAFE_VERSION.fullmatch(metadata.dataset_version):
        raise _error("dataset_version", "expected safe version")
    if not SAFE_VERSION.fullmatch(metadata.cache_contract_version):
        raise _error("cache_contract_version", "expected safe version")
    if metadata.benchmark_kind not in {
        "synthetic_comparison",
        "live_measurement",
    }:
        raise _error("benchmark_kind", "unknown kind")
    try:
        date.fromisoformat(metadata.run_date)
    except ValueError as exc:
        raise _error("run_date", "expected ISO date") from exc
    if not GIT_SHA.fullmatch(metadata.git_sha):
        raise _error("git_sha", "expected hexadecimal revision")
    expected_id = "-".join(
        (
            metadata.run_date,
            metadata.git_sha[:12],
            metadata.dataset_version,
            metadata.cache_contract_version,
        )
    )
    if metadata.benchmark_id != expected_id:
        raise _error("benchmark_id", "does not match metadata")
    return metadata


def _metadata_from_mapping(values: Mapping[str, Any]) -> BenchmarkMetadata:
    return _validate_metadata(
        BenchmarkMetadata(
            schema_version=_require_string(
                values.get("schema_version"), "schema_version"
            ),
            dataset_version=_require_string(
                values.get("dataset_version"), "dataset_version"
            ),
            cache_contract_version=_require_string(
                values.get("cache_contract_version"),
                "cache_contract_version",
            ),
            benchmark_kind=_require_string(
                values.get("benchmark_kind"), "benchmark_kind"
            ),
            run_date=_require_string(values.get("run_date"), "run_date"),
            git_sha=_require_string(values.get("git_sha"), "git_sha"),
            benchmark_id=_require_string(
                values.get("benchmark_id"), "benchmark_id"
            ),
        )
    )


def _row_from_mapping(values: Mapping[str, Any], row_number: int) -> RunRow:
    def field(name: str) -> str:
        return f"row {row_number} {name}"

    fields = set(values)
    expected = set(RUNS_CSV_FIELDS)
    if fields != expected:
        raise ReportValidationError(
            f"Invalid row {row_number}: field set does not match schema"
        )
    row = RunRow(
        case_id=_safe_identifier(values["case_id"], field("case_id")),
        pair_id=_safe_identifier(values["pair_id"], field("pair_id")),
        run_id=_safe_identifier(values["run_id"], field("run_id")),
        comparison_group=_require_string(
            values["comparison_group"], field("comparison_group")
        ),
        is_warmup=_strict_bool(values["is_warmup"], field("is_warmup")),
        cache_outcome=_require_string(
            values["cache_outcome"], field("cache_outcome")
        ),
        planning_latency_ms=_latency(
            values["planning_latency_ms"], field("planning_latency_ms")
        ),
        end_to_end_latency_ms=_latency(
            values["end_to_end_latency_ms"], field("end_to_end_latency_ms")
        ),
        provider_call_count=_strict_int(
            values["provider_call_count"], field("provider_call_count")
        ),
        repair_call_count=_strict_int(
            values["repair_call_count"], field("repair_call_count")
        ),
        terminal_status=_require_string(
            values["terminal_status"], field("terminal_status")
        ),
        validation_passed=_strict_bool(
            values["validation_passed"], field("validation_passed")
        ),
        result_fingerprint=_require_string(
            values["result_fingerprint"], field("result_fingerprint")
        ),
    )
    _validate_row(row, row_number)
    return row


def _validate_row(row: RunRow, row_number: int) -> None:
    prefix = f"row {row_number}"
    _safe_identifier(row.case_id, f"{prefix} case_id")
    _safe_identifier(row.pair_id, f"{prefix} pair_id")
    _safe_identifier(row.run_id, f"{prefix} run_id")
    _strict_bool(row.is_warmup, f"{prefix} is_warmup")
    _strict_bool(row.validation_passed, f"{prefix} validation_passed")
    _latency(row.planning_latency_ms, f"{prefix} planning_latency_ms")
    _latency(
        row.end_to_end_latency_ms,
        f"{prefix} end_to_end_latency_ms",
    )
    _strict_int(row.provider_call_count, f"{prefix} provider_call_count")
    _strict_int(row.repair_call_count, f"{prefix} repair_call_count")
    if row.comparison_group not in COMPARISON_GROUPS:
        raise _error(f"{prefix} comparison_group", "unknown group")
    allowed_outcomes = ALLOWED_OUTCOMES[row.comparison_group]
    if row.cache_outcome not in allowed_outcomes:
        if row.cache_outcome == "disabled":
            raise _error(
                f"{prefix} cache_outcome",
                "disabled is baseline-only",
            )
        raise _error(f"{prefix} cache_outcome", "unexpected group outcome")
    if row.terminal_status not in TERMINAL_STATUSES:
        raise _error(f"{prefix} terminal_status", "unknown status")
    if row.validation_passed and row.terminal_status != "success":
        raise _error(
            f"{prefix} validation_passed",
            "terminal failure cannot pass validation",
        )
    if row.provider_call_count > 2:
        raise _error(
            f"{prefix} provider_call_count",
            "cannot exceed two planner attempts",
        )
    if row.repair_call_count > row.provider_call_count:
        raise _error(
            f"{prefix} repair_call_count",
            "cannot exceed provider calls",
        )
    if row.repair_call_count > 1:
        raise _error(
            f"{prefix} repair_call_count",
            "semantic repair is limited to one attempt",
        )
    if (
        row.provider_call_count > 0
        and row.provider_call_count != row.repair_call_count + 1
    ):
        raise _error(
            f"{prefix} repair_call_count",
            "provider calls must equal initial attempt plus repairs",
        )
    if row.cache_outcome == "hit" and (
        row.provider_call_count != 0 or row.repair_call_count != 0
    ):
        raise _error(
            f"{prefix} provider_call_count",
            "hit must not call provider",
        )
    if row.is_success:
        if (
            row.planning_latency_ms is None
            or row.end_to_end_latency_ms is None
        ):
            raise _error(f"{prefix} latency", "success requires both values")
        if not SHA256_HEX.fullmatch(row.result_fingerprint):
            raise _error(
                f"{prefix} result_fingerprint",
                "success requires SHA-256 hex",
            )
        if row.cache_outcome != "hit" and row.provider_call_count < 1:
            raise _error(
                f"{prefix} provider_call_count",
                "miss path success requires provider call",
            )
    elif row.result_fingerprint and not SHA256_HEX.fullmatch(
        row.result_fingerprint
    ):
        raise _error(
            f"{prefix} result_fingerprint",
            "expected empty or SHA-256 hex",
        )


def _pair_key(row: RunRow) -> tuple[str, str, str, bool]:
    return (row.case_id, row.pair_id, row.run_id, row.is_warmup)


def _validate_rows(
    rows: Iterable[RunRow], *, validate_pairs: bool
) -> tuple[RunRow, ...]:
    validated = tuple(rows)
    if not validated:
        raise ReportValidationError("At least one run row is required")
    for index, row in enumerate(validated, start=1):
        if not isinstance(row, RunRow):
            raise ReportValidationError(
                f"Invalid row {index}: expected RunRow"
            )
        _validate_row(row, index)
    if validate_pairs:
        pairs: dict[tuple[str, str, str, bool], list[RunRow]] = defaultdict(
            list
        )
        for row in validated:
            pairs[_pair_key(row)].append(row)
        for pair_rows in pairs.values():
            baseline = [
                row
                for row in pair_rows
                if row.comparison_group == "cache_disabled_baseline"
            ]
            candidate = [
                row
                for row in pair_rows
                if row.comparison_group != "cache_disabled_baseline"
            ]
            if len(pair_rows) != 2 or len(baseline) != 1 or len(candidate) != 1:
                raise ReportValidationError(
                    "Invalid pair: expected one baseline and one candidate"
                )
            if baseline[0].is_success and candidate[0].is_success:
                if (
                    baseline[0].result_fingerprint
                    != candidate[0].result_fingerprint
                ):
                    raise ReportValidationError(
                        "Invalid pair: successful fingerprint mismatch"
                    )
    return validated


def load_dataset(path: Path) -> LatencyDataset:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportValidationError("Unable to read dataset") from exc
    if not isinstance(payload, dict) or set(payload) != DATASET_FIELDS:
        raise ReportValidationError(
            "Invalid dataset: top-level field set does not match schema"
        )
    runs = payload["runs"]
    if not isinstance(runs, list):
        raise _error("runs", "expected array")
    metadata = _metadata_from_mapping(payload)
    parsed = tuple(
        _row_from_mapping(row, index)
        if isinstance(row, dict)
        else (_ for _ in ()).throw(
            ReportValidationError(
                f"Invalid row {index}: expected object"
            )
        )
        for index, row in enumerate(runs, start=1)
    )
    return LatencyDataset(
        metadata=metadata,
        runs=_validate_rows(parsed, validate_pairs=True),
    )


def _parse_csv_bool(value: str, field: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise _error(field, "expected canonical true or false")


def _parse_csv_int(value: str, field: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(
        r"0|[1-9][0-9]*", value
    ):
        raise _error(field, "expected canonical non-negative integer")
    return int(value)


def _parse_csv_latency(value: str, field: str) -> float | None:
    if not isinstance(value, str):
        raise _error(field, "expected finite non-negative number")
    if value == "":
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise _error(field, "expected finite non-negative number") from exc
    return _latency(parsed, field)


def read_runs_csv(path: Path) -> tuple[RunRow, ...]:
    try:
        handle = path.open(newline="", encoding="utf-8")
    except OSError as exc:
        raise ReportValidationError("Unable to read runs CSV") from exc
    with handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != RUNS_CSV_FIELDS:
            raise ReportValidationError(
                "Invalid runs CSV header: exact schema required"
            )
        rows: list[RunRow] = []
        for index, values in enumerate(reader, start=1):
            if None in values:
                raise ReportValidationError(
                    f"Invalid CSV row {index}: unexpected extra field"
                )
            prefix = f"row {index}"
            converted: dict[str, Any] = dict(values)
            converted["is_warmup"] = _parse_csv_bool(
                values["is_warmup"], f"{prefix} is_warmup"
            )
            converted["validation_passed"] = _parse_csv_bool(
                values["validation_passed"], f"{prefix} validation_passed"
            )
            converted["provider_call_count"] = _parse_csv_int(
                values["provider_call_count"], f"{prefix} provider_call_count"
            )
            converted["repair_call_count"] = _parse_csv_int(
                values["repair_call_count"], f"{prefix} repair_call_count"
            )
            converted["planning_latency_ms"] = _parse_csv_latency(
                values["planning_latency_ms"], f"{prefix} planning_latency_ms"
            )
            converted["end_to_end_latency_ms"] = _parse_csv_latency(
                values["end_to_end_latency_ms"],
                f"{prefix} end_to_end_latency_ms",
            )
            rows.append(_row_from_mapping(converted, index))
    return _validate_rows(rows, validate_pairs=True)


def _format_number(value: float | int | None) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if value.is_integer():
        return str(int(value))
    return format(value, ".15g")


def _row_to_csv(row: RunRow) -> dict[str, str]:
    return {
        "case_id": row.case_id,
        "pair_id": row.pair_id,
        "run_id": row.run_id,
        "comparison_group": row.comparison_group,
        "is_warmup": str(row.is_warmup).lower(),
        "cache_outcome": row.cache_outcome,
        "planning_latency_ms": _format_number(row.planning_latency_ms),
        "end_to_end_latency_ms": _format_number(
            row.end_to_end_latency_ms
        ),
        "provider_call_count": str(row.provider_call_count),
        "repair_call_count": str(row.repair_call_count),
        "terminal_status": row.terminal_status,
        "validation_passed": str(row.validation_passed).lower(),
        "result_fingerprint": row.result_fingerprint,
    }


def _render_runs_csv(rows: Sequence[RunRow]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=RUNS_CSV_FIELDS,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(_row_to_csv(row) for row in rows)
    return output.getvalue()


def write_runs_csv(rows: Iterable[RunRow], path: Path) -> None:
    validated = _validate_rows(rows, validate_pairs=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_runs_csv(validated), encoding="utf-8", newline="")


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def _percentile(values: Sequence[float], proportion: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * proportion
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _latency_statistics(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {key: None for key in STATISTIC_KEYS}
    return {
        "mean_ms": _rounded(statistics.fmean(values)),
        "p50_ms": _rounded(_percentile(values, 0.50)),
        "p95_ms": _rounded(_percentile(values, 0.95)),
        "stddev_ms": _rounded(statistics.pstdev(values)),
        "min_ms": _rounded(min(values)),
        "max_ms": _rounded(max(values)),
    }


def _group_summary(rows: Sequence[RunRow]) -> dict[str, Any]:
    warmups = [row for row in rows if row.is_warmup]
    measured = [row for row in rows if not row.is_warmup]
    successful = [row for row in measured if row.is_success]
    failed = [row for row in measured if not row.is_success]
    return {
        "row_count": len(rows),
        "warmup_run_count": len(warmups),
        "measured_run_count": len(measured),
        "successful_run_count": len(successful),
        "failed_run_count": len(failed),
        "failure_rate": _rounded(
            len(failed) / len(measured) if measured else 0.0
        ),
        "cache_outcome_counts": dict(
            sorted(Counter(row.cache_outcome for row in rows).items())
        ),
        "provider_call_count": sum(
            row.provider_call_count for row in measured
        ),
        "repair_call_count": sum(row.repair_call_count for row in measured),
        "planning_latency_ms": _latency_statistics(
            [
                row.planning_latency_ms
                for row in successful
                if row.planning_latency_ms is not None
            ]
        ),
        "end_to_end_latency_ms": _latency_statistics(
            [
                row.end_to_end_latency_ms
                for row in successful
                if row.end_to_end_latency_ms is not None
            ]
        ),
    }


def _paired_surface(
    pairs: Sequence[tuple[RunRow, RunRow]], surface: str
) -> dict[str, float | None]:
    baseline_values = [float(getattr(pair[0], surface)) for pair in pairs]
    candidate_values = [float(getattr(pair[1], surface)) for pair in pairs]
    baseline_mean = statistics.fmean(baseline_values)
    candidate_mean = statistics.fmean(candidate_values)
    delta_mean = statistics.fmean(
        baseline - candidate
        for baseline, candidate in zip(
            baseline_values, candidate_values, strict=True
        )
    )
    improvement = (
        delta_mean / baseline_mean * 100 if baseline_mean else None
    )
    speedup = baseline_mean / candidate_mean if candidate_mean else None
    return {
        "baseline_mean_ms": _rounded(baseline_mean),
        "candidate_mean_ms": _rounded(candidate_mean),
        "mean_paired_delta_ms": _rounded(delta_mean),
        "improvement_rate_percent": _rounded(improvement),
        "speedup": _rounded(speedup),
    }


def _empty_paired_surface() -> dict[str, None]:
    return {
        "baseline_mean_ms": None,
        "candidate_mean_ms": None,
        "mean_paired_delta_ms": None,
        "improvement_rate_percent": None,
        "speedup": None,
    }


def _paired_comparisons(rows: Sequence[RunRow]) -> dict[str, Any]:
    pairs_by_key: dict[tuple[str, str, str, bool], list[RunRow]] = defaultdict(
        list
    )
    for row in rows:
        pairs_by_key[_pair_key(row)].append(row)
    by_group: dict[str, list[tuple[RunRow, RunRow]]] = defaultdict(list)
    excluded: Counter[str] = Counter()
    present: set[str] = set()
    for pair_rows in pairs_by_key.values():
        baseline = next(
            row
            for row in pair_rows
            if row.comparison_group == "cache_disabled_baseline"
        )
        candidate = next(
            row
            for row in pair_rows
            if row.comparison_group != "cache_disabled_baseline"
        )
        group = candidate.comparison_group
        present.add(group)
        if baseline.is_warmup or not baseline.is_success or not candidate.is_success:
            excluded[group] += 1
            continue
        by_group[group].append((baseline, candidate))
    result: dict[str, Any] = {}
    for group in CANDIDATE_GROUPS:
        if group not in present:
            continue
        pairs = by_group[group]
        result[group] = {
            "baseline_group": "cache_disabled_baseline",
            "paired_success_count": len(pairs),
            "excluded_pair_count": excluded[group],
            "planning_latency_ms": (
                _paired_surface(pairs, "planning_latency_ms")
                if pairs
                else _empty_paired_surface()
            ),
            "end_to_end_latency_ms": (
                _paired_surface(pairs, "end_to_end_latency_ms")
                if pairs
                else _empty_paired_surface()
            ),
        }
    return result


def _successful_values(
    rows: Sequence[RunRow],
    groups: set[str],
    surface: str,
    *,
    required_cache_outcome: str | None = None,
) -> list[float]:
    return [
        float(getattr(row, surface))
        for row in rows
        if row.comparison_group in groups
        and not row.is_warmup
        and row.is_success
        and (
            required_cache_outcome is None
            or row.cache_outcome == required_cache_outcome
        )
        and getattr(row, surface) is not None
    ]


def _modeled_estimates(rows: Sequence[RunRow]) -> list[dict[str, Any]]:
    surface_means: dict[str, tuple[float | None, float | None]] = {}
    for surface in SURFACES:
        warm = _successful_values(
            rows,
            set(WARM_GROUPS),
            surface,
            required_cache_outcome="hit",
        )
        cold = _successful_values(rows, {"cold_miss"}, surface)
        surface_means[surface] = (
            statistics.fmean(warm) if warm else None,
            statistics.fmean(cold) if cold else None,
        )
    estimates: list[dict[str, Any]] = []
    for hit_rate in (0.25, 0.50, 0.75):
        row: dict[str, Any] = {
            "estimate_type": "modeled_estimate",
            "hit_rate": hit_rate,
        }
        for surface in SURFACES:
            warm_mean, cold_mean = surface_means[surface]
            expected = (
                hit_rate * warm_mean + (1 - hit_rate) * cold_mean
                if warm_mean is not None and cold_mean is not None
                else None
            )
            row[surface] = _rounded(expected)
        estimates.append(row)
    return estimates


def build_summary(
    rows: Iterable[RunRow],
    metadata: BenchmarkMetadata,
    *,
    validate_pairs: bool = True,
) -> dict[str, Any]:
    metadata = _validate_metadata(metadata)
    validated = _validate_rows(rows, validate_pairs=validate_pairs)
    grouped: dict[str, list[RunRow]] = defaultdict(list)
    for row in validated:
        grouped[row.comparison_group].append(row)
    measured = [row for row in validated if not row.is_warmup]
    successful = [row for row in measured if row.is_success]
    failed = [row for row in measured if not row.is_success]
    summary = {
        "schema_version": "agent-builder-cache-latency-summary-v1",
        "benchmark": asdict(metadata),
        "totals": {
            "row_count": len(validated),
            "warmup_run_count": sum(row.is_warmup for row in validated),
            "measured_run_count": len(measured),
            "successful_run_count": len(successful),
            "failed_run_count": len(failed),
            "failure_rate": _rounded(
                len(failed) / len(measured) if measured else 0.0
            ),
        },
        "groups": {
            group: _group_summary(grouped[group])
            for group in COMPARISON_GROUPS
            if group in grouped
        },
        "paired_comparisons": (
            _paired_comparisons(validated) if validate_pairs else {}
        ),
        "modeled_path_classification": {
            "warm": list(WARM_GROUPS),
            "miss": list(MISS_PATH_GROUPS),
        },
        "modeled_estimates": _modeled_estimates(validated),
        "artifact_safety": {"status": "pending", "files_scanned": 0},
    }
    return summary


def _summary_csv(summary: Mapping[str, Any]) -> str:
    rows: list[dict[str, str]] = []

    def add(**values: Any) -> None:
        row = {field: "" for field in SUMMARY_CSV_FIELDS}
        for key, value in values.items():
            row[key] = _format_number(value) if isinstance(value, float) else str(value)
        rows.append(row)

    for group in COMPARISON_GROUPS:
        group_data = summary["groups"].get(group)
        if not group_data:
            continue
        for metric in (
            "row_count",
            "warmup_run_count",
            "measured_run_count",
            "successful_run_count",
            "failed_run_count",
            "failure_rate",
            "provider_call_count",
            "repair_call_count",
        ):
            unit = "ratio" if metric == "failure_rate" else "count"
            add(
                record_type="measurement",
                comparison_group=group,
                surface="runs",
                metric=metric,
                value=group_data[metric],
                unit=unit,
                sample_count=group_data["measured_run_count"],
            )
        for surface in SURFACES:
            for metric in STATISTIC_KEYS:
                add(
                    record_type="measurement",
                    comparison_group=group,
                    surface=surface,
                    metric=metric,
                    value=(
                        group_data[surface][metric]
                        if group_data[surface][metric] is not None
                        else ""
                    ),
                    unit="ms",
                    sample_count=group_data["successful_run_count"],
                )
    for group in CANDIDATE_GROUPS:
        paired = summary["paired_comparisons"].get(group)
        if not paired:
            continue
        for surface in SURFACES:
            for metric, value in paired[surface].items():
                unit = (
                    "percent"
                    if metric == "improvement_rate_percent"
                    else "ratio"
                    if metric == "speedup"
                    else "ms"
                )
                add(
                    record_type="paired_comparison",
                    comparison_group=group,
                    surface=surface,
                    metric=metric,
                    value=value if value is not None else "",
                    unit=unit,
                    sample_count=paired["paired_success_count"],
                    baseline_group=paired["baseline_group"],
                )
    for estimate in summary["modeled_estimates"]:
        for surface in SURFACES:
            add(
                record_type="modeled_estimate",
                comparison_group="modeled_hit_rate",
                surface=surface,
                metric="expected_mean_ms",
                value=(
                    estimate[surface]
                    if estimate[surface] is not None
                    else ""
                ),
                unit="ms",
                sample_count="",
                hit_rate=estimate["hit_rate"],
                estimate_type=estimate["estimate_type"],
            )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=SUMMARY_CSV_FIELDS,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _display(value: Any) -> str:
    return "n/a" if value is None else str(value)


def _summary_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Agent Builder Cache Offline Latency Summary",
        "",
        f"Benchmark: `{summary['benchmark']['benchmark_id']}`",
        "",
        "## Measured groups",
        "",
        "| Group | Surface | Measured | Success | Failed | Warm-up | Failure rate | Mean | P50 | P95 | Stddev | Min | Max |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group in COMPARISON_GROUPS:
        values = summary["groups"].get(group)
        if not values:
            continue
        for surface in SURFACES:
            latency = values[surface]
            lines.append(
                "| "
                + " | ".join(
                    (
                        group,
                        surface,
                        str(values["measured_run_count"]),
                        str(values["successful_run_count"]),
                        str(values["failed_run_count"]),
                        str(values["warmup_run_count"]),
                        str(values["failure_rate"]),
                        _display(latency["mean_ms"]),
                        _display(latency["p50_ms"]),
                        _display(latency["p95_ms"]),
                        _display(latency["stddev_ms"]),
                        _display(latency["min_ms"]),
                        _display(latency["max_ms"]),
                    )
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## Paired comparisons",
            "",
            "| Group | Surface | Pairs | Excluded | Delta ms | Improvement % | Speedup |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for group in CANDIDATE_GROUPS:
        paired = summary["paired_comparisons"].get(group)
        if not paired:
            continue
        for surface in SURFACES:
            values = paired[surface]
            lines.append(
                "| "
                + " | ".join(
                    (
                        group,
                        surface,
                        str(paired["paired_success_count"]),
                        str(paired["excluded_pair_count"]),
                        _display(values["mean_paired_delta_ms"]),
                        _display(values["improvement_rate_percent"]),
                        _display(values["speedup"]),
                    )
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## Modeled estimates",
            "",
            "These values are `modeled_estimate`, not measured results.",
            "",
            "| Hit rate | Planning expected mean ms | End-to-end expected mean ms |",
            "| ---: | ---: | ---: |",
        ]
    )
    for estimate in summary["modeled_estimates"]:
        lines.append(
            "| "
            + " | ".join(
                (
                    str(estimate["hit_rate"]),
                    _display(estimate["planning_latency_ms"]),
                    _display(estimate["end_to_end_latency_ms"]),
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _bundle_readme(summary: Mapping[str, Any]) -> str:
    benchmark = summary["benchmark"]
    totals = summary["totals"]
    cold = summary["groups"].get("cold_miss", {})
    exact = summary["groups"].get("exact_warm_hit", {})
    cold_planning_mean = cold.get("planning_latency_ms", {}).get("mean_ms")
    cold_end_to_end_mean = cold.get("end_to_end_latency_ms", {}).get("mean_ms")
    warm_planning_mean = exact.get("planning_latency_ms", {}).get("mean_ms")
    warm_end_to_end_mean = exact.get("end_to_end_latency_ms", {}).get("mean_ms")
    lines = [
        "# Agent Builder Cache Offline Latency Bundle",
        "",
        f"- Benchmark: `{benchmark['benchmark_id']}`",
        f"- Kind: `{benchmark['benchmark_kind']}`",
        f"- Dataset: `{benchmark['dataset_version']}`",
        f"- Cache contract: `{benchmark['cache_contract_version']}`",
        "",
        "## Key result",
        "",
        f"- Measured success/failure: {totals['successful_run_count']}/{totals['failed_run_count']}",
        "- Cold-miss measured mean (planning/end-to-end): "
        f"{_display(cold_planning_mean)} / "
        f"{_display(cold_end_to_end_mean)} ms",
        "- Exact warm-hit measured mean (planning/end-to-end): "
        f"{_display(warm_planning_mean)} / "
        f"{_display(warm_end_to_end_mean)} ms",
        "- Artifact safety check: passed.",
        "",
        "## Modeled estimates",
        "",
        "These 25/50/75% values are modeled estimates, not live measurements.",
        "",
        "| Hit rate | Planning expected mean ms | End-to-end expected mean ms |",
        "| ---: | ---: | ---: |",
    ]
    for estimate in summary["modeled_estimates"]:
        lines.append(
            "| "
            + " | ".join(
                (
                    str(estimate["hit_rate"]),
                    _display(estimate["planning_latency_ms"]),
                    _display(estimate["end_to_end_latency_ms"]),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- [Round data](runs.csv)",
            "- [Latency comparison graph](latency-comparison.svg)",
            "- [Cache scenario graph](cache-hit-scenarios.svg)",
            "- [JSON summary](summary.json)",
            "- [CSV summary](summary.csv)",
            "- [Markdown summary](summary.md)",
            "",
        ]
    )
    return "\n".join(lines)


def _svg_document(width: int, height: int, body: Sequence[str]) -> str:
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{width}" height="{height}" '
                f'viewBox="0 0 {width} {height}">'
            ),
            '<rect width="100%" height="100%" fill="#ffffff"/>',
            *body,
            "</svg>",
            "",
        ]
    )


def _svg_marker_style(color: str, *, is_warmup: bool) -> str:
    if is_warmup:
        return f'fill="none" stroke="{color}" stroke-width="2"'
    return f'fill="{color}"'


def _latency_svg(rows: Sequence[RunRow]) -> str:
    width = max(900, 120 + len(rows) * 24)
    height = 420
    values = [
        value
        for row in rows
        for value in (row.planning_latency_ms, row.end_to_end_latency_ms)
        if value is not None
    ]
    maximum = max(values, default=1.0) or 1.0

    def y(value: float) -> float:
        return 350 - value / maximum * 280

    body = [
        '<text x="40" y="32" font-family="sans-serif" font-size="20">Latency comparison by round</text>',
        '<line x1="60" y1="350" x2="{}" y2="350" stroke="#64748b"/>'.format(
            width - 30
        ),
        '<text x="40" y="382" font-family="sans-serif" font-size="12">Every input row is retained; open markers are warm-up and crosses are failures.</text>',
    ]
    for index, row in enumerate(rows):
        x = 75 + index * 24
        key = html.escape(row.artifact_key, quote=True)
        opacity = "0.45" if row.is_warmup else "1"
        body.append(
            f'<g data-run="{key}" data-warmup="{str(row.is_warmup).lower()}" opacity="{opacity}">'
        )
        title = html.escape(
            f"{row.artifact_key} {row.cache_outcome} {row.terminal_status}"
        )
        body.append(f"<title>{title}</title>")
        if row.is_success:
            if row.planning_latency_ms is not None:
                body.append(
                    f'<circle cx="{x}" cy="{y(row.planning_latency_ms):.3f}" r="4" '
                    f'{_svg_marker_style("#2563eb", is_warmup=row.is_warmup)}/>'
                )
            if row.end_to_end_latency_ms is not None:
                body.append(
                    f'<circle cx="{x}" cy="{y(row.end_to_end_latency_ms):.3f}" r="4" '
                    f'{_svg_marker_style("#16a34a", is_warmup=row.is_warmup)}/>'
                )
        else:
            failure_surfaces = (
                (row.planning_latency_ms, "#2563eb"),
                (row.end_to_end_latency_ms, "#16a34a"),
            )
            rendered_failure_surface = False
            for latency, color in failure_surfaces:
                if latency is None:
                    continue
                marker_y = y(latency)
                if row.is_warmup:
                    body.append(
                        f'<circle cx="{x}" cy="{marker_y:.3f}" r="4" '
                        f'{_svg_marker_style(color, is_warmup=True)}/>'
                    )
                body.append(
                    f'<path d="M {x-5} {marker_y-5:.3f} L {x+5} {marker_y+5:.3f} M {x+5} {marker_y-5:.3f} L {x-5} {marker_y+5:.3f}" stroke="#dc2626" stroke-width="2"/>'
                )
                rendered_failure_surface = True
            if not rendered_failure_surface:
                body.append(
                    f'<path d="M {x-5} 345 L {x+5} 355 M {x+5} 345 L {x-5} 355" stroke="#dc2626" stroke-width="2"/>'
                )
        body.append("</g>")
    body.extend(
        [
            '<circle cx="70" cy="405" r="4" fill="#2563eb"/><text x="80" y="409" font-family="sans-serif" font-size="12">planning</text>',
            '<circle cx="160" cy="405" r="4" fill="#16a34a"/><text x="170" y="409" font-family="sans-serif" font-size="12">end-to-end</text>',
        ]
    )
    return _svg_document(width, height, body)


def _scenario_svg(rows: Sequence[RunRow]) -> str:
    width = max(900, 160 + len(rows) * 24)
    height = 360
    lane_y = {
        group: 70 + index * 38 for index, group in enumerate(COMPARISON_GROUPS)
    }
    colors = {
        "disabled": "#64748b",
        "hit": "#16a34a",
        "miss": "#f59e0b",
        "bypass": "#7c3aed",
        "error": "#dc2626",
    }
    body = [
        '<text x="40" y="30" font-family="sans-serif" font-size="20">Cache outcomes and provider calls by round</text>'
    ]
    for group in COMPARISON_GROUPS:
        body.append(
            f'<text x="15" y="{lane_y[group]+4}" font-family="sans-serif" font-size="11">{html.escape(group)}</text>'
        )
    for index, row in enumerate(rows):
        x = 185 + index * 24
        y = lane_y[row.comparison_group]
        key = html.escape(row.artifact_key, quote=True)
        opacity = "0.45" if row.is_warmup else "1"
        body.append(
            f'<g data-run="{key}" data-warmup="{str(row.is_warmup).lower()}" opacity="{opacity}">'
        )
        title = html.escape(
            f"{row.artifact_key} outcome={row.cache_outcome} "
            f"calls={row.provider_call_count}/{row.repair_call_count} "
            f"terminal={row.terminal_status} "
            f"validation_passed={str(row.validation_passed).lower()}"
        )
        body.append(f"<title>{title}</title>")
        color = colors[row.cache_outcome]
        body.append(
            f'<rect x="{x-6}" y="{y-7}" width="12" height="14" rx="2" '
            f'{_svg_marker_style(color, is_warmup=row.is_warmup)}/>'
        )
        if not row.is_success:
            body.append(
                f'<path d="M {x-6} {y-7} L {x+6} {y+7} M {x+6} {y-7} L {x-6} {y+7}" stroke="#111827" stroke-width="2"/>'
            )
        body.append(
            f'<text x="{x-4}" y="{y+22}" font-family="sans-serif" font-size="8">{row.provider_call_count}</text>'
        )
        body.append("</g>")
    return _svg_document(width, height, body)


def inspect_artifact_safety(files: Mapping[str, str]) -> None:
    structured = "|".join(
        re.escape(field) for field in FORBIDDEN_STRUCTURED_FIELDS
    )
    patterns = (
        UUID_TEXT,
        re.compile(r"authorization\s*[:=,]\s*bearer\b", re.IGNORECASE),
        re.compile(r"\bbearer\s+\S+", re.IGNORECASE),
        re.compile(r"\bsk-[A-Za-z0-9_-]{4,}\b", re.IGNORECASE),
        re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
        re.compile(r"\bgh[pousr]_[0-9A-Za-z]{20,}\b", re.IGNORECASE),
        re.compile(r"\bgithub_pat_[0-9A-Za-z_]{20,}\b", re.IGNORECASE),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"https?://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE),
        re.compile(
            rf"(?:^|[\r\n,{{])\s*[\"']?(?:{structured})[\"']?\s*[:=,]",
            re.IGNORECASE,
        ),
    )
    for name, content in files.items():
        if not isinstance(name, str) or not isinstance(content, str):
            raise ArtifactSafetyError("Artifact safety input is invalid")
        for pattern in patterns:
            if pattern.search(content):
                raise ArtifactSafetyError(
                    f"Artifact safety check failed for {Path(name).name}"
                )


def _render_artifacts(dataset: LatencyDataset) -> dict[str, str]:
    summary = build_summary(dataset.runs, dataset.metadata)
    summary["artifact_safety"] = {
        "status": "passed",
        "files_scanned": len(ARTIFACT_FILENAMES),
    }
    artifacts = {
        "runs.csv": _render_runs_csv(dataset.runs),
        "summary.json": json.dumps(
            summary, ensure_ascii=False, indent=2
        )
        + "\n",
        "summary.csv": _summary_csv(summary),
        "summary.md": _summary_markdown(summary),
        "latency-comparison.svg": _latency_svg(dataset.runs),
        "cache-hit-scenarios.svg": _scenario_svg(dataset.runs),
        "README.md": _bundle_readme(summary),
    }
    return {name: artifacts[name] for name in ARTIFACT_FILENAMES}


def _validate_output_directory(output: Path) -> None:
    if not output.exists():
        return
    if output.is_symlink() or not output.is_dir():
        raise ReportValidationError(
            "Output path must be a non-symlink directory"
        )
    try:
        entries = tuple(output.iterdir())
    except OSError as exc:
        raise ReportValidationError(
            "Unable to inspect output directory"
        ) from exc
    allowed = set(ARTIFACT_FILENAMES)
    if any(
        entry.name not in allowed
        or entry.is_symlink()
        or not entry.is_file()
        for entry in entries
    ):
        raise ReportValidationError(
            "Output directory contains unexpected entries"
        )


def generate_bundle(dataset: LatencyDataset, output: Path) -> dict[str, Any]:
    dataset = LatencyDataset(
        metadata=_validate_metadata(dataset.metadata),
        runs=_validate_rows(dataset.runs, validate_pairs=True),
    )
    artifacts = _render_artifacts(dataset)
    inspect_artifact_safety(artifacts)
    _validate_output_directory(output)
    output.mkdir(parents=True, exist_ok=True)
    for name in ARTIFACT_FILENAMES:
        (output / name).write_text(
            artifacts[name], encoding="utf-8", newline=""
        )
    return json.loads(artifacts["summary.json"])


def _metadata_from_cli(args: argparse.Namespace) -> BenchmarkMetadata:
    required = (
        "dataset_version",
        "cache_contract_version",
        "run_date",
        "git_sha",
        "benchmark_kind",
    )
    missing = [name for name in required if getattr(args, name) is None]
    if missing:
        raise ReportValidationError(
            "CSV input requires explicit benchmark metadata"
        )
    benchmark_id = "-".join(
        (
            args.run_date,
            args.git_sha[:12],
            args.dataset_version,
            args.cache_contract_version,
        )
    )
    return _validate_metadata(
        BenchmarkMetadata(
            schema_version=SCHEMA_VERSION,
            dataset_version=args.dataset_version,
            cache_contract_version=args.cache_contract_version,
            benchmark_kind=args.benchmark_kind,
            run_date=args.run_date,
            git_sha=args.git_sha,
            benchmark_id=benchmark_id,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an offline Agent Builder cache latency bundle."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset", type=Path)
    source.add_argument("--runs-csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-version")
    parser.add_argument("--cache-contract-version")
    parser.add_argument("--run-date")
    parser.add_argument("--git-sha")
    parser.add_argument(
        "--benchmark-kind",
        choices=("synthetic_comparison", "live_measurement"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.dataset is not None:
            dataset = load_dataset(args.dataset)
        else:
            dataset = LatencyDataset(
                metadata=_metadata_from_cli(args),
                runs=read_runs_csv(args.runs_csv),
            )
        generate_bundle(dataset, args.output)
    except (ArtifactSafetyError, ReportValidationError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
