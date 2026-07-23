"""Safe, paired row collection for the MBA-350 live benchmark.

This module deliberately does not construct an Agent Builder request, call a
provider, connect to Redis, or persist a bundle by itself.  A later
environment-specific executor receives only a safe case key and measurement
mode, then returns the allowlisted observation consumed by CACHE-05 tooling.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Sequence

from tests.evaluation.agent_builder_cache_latency_report import (
    BenchmarkMetadata,
    LatencyDataset,
    RunRow,
    SCHEMA_VERSION,
    generate_bundle,
)


DEVELOPMENT_ATTEMPTS_PER_GROUP = 10
FINAL_ATTEMPTS_PER_GROUP = 30
MBA350_CANDIDATE_GROUPS = (
    "cold_miss",
    "exact_warm_hit",
    "normalization_warm_hit",
    "semantic_bypass",
    "negative_control",
)
FIXED_BUNDLE_ROOT = Path("docs/features/agent-builder-cache/benchmarks")
_SAFE_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SAFE_FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")
_UUID_TEXT = re.compile(
    r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


class CollectorPreflightError(ValueError):
    """Raised without exposing permission, model, or runtime details."""


@dataclass(frozen=True)
class RuntimePreflight:
    """Safe yes/no evidence required before an external benchmark executor runs."""

    permission_checked: bool
    gpt55_available: bool
    graph_context_ready: bool
    cache_contract_ready: bool
    scenario_fingerprint: str

    def require_ready(self) -> None:
        if not all(
            (
                self.permission_checked,
                self.gpt55_available,
                self.graph_context_ready,
                self.cache_contract_ready,
            )
        ):
            raise CollectorPreflightError("Live benchmark preflight is not ready")
        if not _SAFE_FINGERPRINT.fullmatch(self.scenario_fingerprint):
            raise CollectorPreflightError("Live benchmark scenario is invalid")


@dataclass(frozen=True)
class BenchmarkScenario:
    """Safe binding for the current permission, model, graph, and context."""

    case_id: str
    scenario_fingerprint: str
    generation_mode: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.case_id, str)
            or not _SAFE_IDENTIFIER.fullmatch(self.case_id)
            or _UUID_TEXT.search(self.case_id)
        ):
            raise CollectorPreflightError("Benchmark case identifier is invalid")
        if not _SAFE_FINGERPRINT.fullmatch(self.scenario_fingerprint):
            raise CollectorPreflightError("Benchmark scenario is invalid")
        if (
            not isinstance(self.generation_mode, str)
            or not _SAFE_IDENTIFIER.fullmatch(self.generation_mode)
        ):
            raise CollectorPreflightError("Benchmark generation mode is invalid")


@dataclass(frozen=True)
class LiveBenchmarkCase:
    """Backward-compatible safe case with deterministic default binding."""

    case_id: str
    scenario_fingerprint: str = "a" * 64
    generation_mode: str = "configure_and_generate"

    def __post_init__(self) -> None:
        BenchmarkScenario(
            case_id=self.case_id,
            scenario_fingerprint=self.scenario_fingerprint,
            generation_mode=self.generation_mode,
        )


@dataclass(frozen=True)
class LiveAttemptRequest:
    """Allowlisted executor input with no raw request or protected identity."""

    case_id: str
    scenario_fingerprint: str
    generation_mode: str
    comparison_group: str
    cache_enabled: bool
    expected_cache_state: str
    pair_id: str
    run_id: str
    paired_comparison_group: str | None = None
    is_warmup: bool = False


@dataclass(frozen=True)
class LiveAttemptObservation:
    """The complete allowlisted observation required for one report row."""

    cache_outcome: str
    planning_latency_ms: float | None
    end_to_end_latency_ms: float | None
    provider_call_count: int
    repair_call_count: int
    terminal_status: str
    validation_passed: bool
    result_fingerprint: str


AttemptExecutor = Callable[[LiveAttemptRequest], LiveAttemptObservation]
TrackingPreflight = Callable[[Path], None]


def _attempt_count(phase: Literal["development", "final"]) -> int:
    if phase == "development":
        return DEVELOPMENT_ATTEMPTS_PER_GROUP
    if phase == "final":
        return FINAL_ATTEMPTS_PER_GROUP
    raise CollectorPreflightError("Benchmark phase is invalid")


def _cache_state(comparison_group: str) -> str:
    states = {
        "cache_disabled_baseline": "disabled",
        "cold_miss": "cold",
        "exact_warm_hit": "exact_warm",
        "normalization_warm_hit": "normalization_warm",
        "semantic_bypass": "semantic_bypass",
        "negative_control": "negative_control",
    }
    try:
        return states[comparison_group]
    except KeyError as exc:
        raise CollectorPreflightError("Benchmark comparison group is invalid") from exc


def _pair_id(
    case_id: str,
    scenario_fingerprint: str,
    comparison_group: str,
    phase: Literal["development", "final"],
    attempt: int,
) -> str:
    source = (
        f"{case_id}:{scenario_fingerprint}:{comparison_group}:{phase}:{attempt}"
    ).encode("ascii")
    return "p-" + hashlib.sha256(source).hexdigest()[:24]


def _run_id(
    phase: Literal["development", "final"],
    attempt: int,
    *,
    is_warmup: bool,
) -> str:
    prefix = f"{phase[:3]}-warmup" if is_warmup else phase[:3]
    return f"{prefix}-{attempt:02d}"


def _failure_observation(comparison_group: str) -> LiveAttemptObservation:
    outcome = {
        "cache_disabled_baseline": "disabled",
        "cold_miss": "miss",
        "exact_warm_hit": "miss",
        "normalization_warm_hit": "miss",
        "semantic_bypass": "bypass",
        "negative_control": "error",
    }[comparison_group]
    return LiveAttemptObservation(
        cache_outcome=outcome,
        planning_latency_ms=None,
        end_to_end_latency_ms=None,
        provider_call_count=0,
        repair_call_count=0,
        terminal_status="provider_error",
        validation_passed=False,
        result_fingerprint="",
    )


def _execute_safely(
    execute: AttemptExecutor,
    request: LiveAttemptRequest,
) -> LiveAttemptObservation:
    try:
        observation = execute(request)
    except Exception:
        return _failure_observation(request.comparison_group)
    if not isinstance(observation, LiveAttemptObservation):
        return _failure_observation(request.comparison_group)
    return observation


def _to_row(
    request: LiveAttemptRequest,
    observation: LiveAttemptObservation,
) -> RunRow:
    return RunRow(
        case_id=request.case_id,
        pair_id=request.pair_id,
        run_id=request.run_id,
        comparison_group=request.comparison_group,
        is_warmup=request.is_warmup,
        cache_outcome=observation.cache_outcome,
        planning_latency_ms=observation.planning_latency_ms,
        end_to_end_latency_ms=observation.end_to_end_latency_ms,
        provider_call_count=observation.provider_call_count,
        repair_call_count=observation.repair_call_count,
        terminal_status=observation.terminal_status,
        validation_passed=observation.validation_passed,
        result_fingerprint=observation.result_fingerprint,
    )


def collect_paired_rows(
    *,
    cases: Sequence[BenchmarkScenario],
    preflight: RuntimePreflight,
    phase: Literal["development", "final"],
    execute: AttemptExecutor,
) -> tuple[RunRow, ...]:
    """Collect every paired attempt once; executor failures become safe rows.

    The executor owns pair-local cache preparation.  It must use the same
    server-loaded graph/context for the baseline and candidate represented by a
    pair id, but it never returns that graph or context to this collector.
    """

    preflight.require_ready()
    if not cases:
        raise CollectorPreflightError("At least one benchmark case is required")
    attempt_count = _attempt_count(phase)
    rows: list[RunRow] = []
    for case in cases:
        if case.scenario_fingerprint != preflight.scenario_fingerprint:
            raise CollectorPreflightError("Benchmark scenario does not match preflight")
        for comparison_group in MBA350_CANDIDATE_GROUPS:
            for is_warmup in (True, False):
                attempts = (1,) if is_warmup else range(1, attempt_count + 1)
                for attempt in attempts:
                    pair_id = _pair_id(
                        case.case_id,
                        case.scenario_fingerprint,
                        comparison_group,
                        phase,
                        0 if is_warmup else attempt,
                    )
                    run_id = _run_id(phase, attempt, is_warmup=is_warmup)
                    groups = (
                        ("cache_disabled_baseline", comparison_group)
                        if attempt % 2
                        else (comparison_group, "cache_disabled_baseline")
                    )
                    for group in groups:
                        request = LiveAttemptRequest(
                            case_id=case.case_id,
                            scenario_fingerprint=case.scenario_fingerprint,
                            generation_mode=case.generation_mode,
                            comparison_group=group,
                            cache_enabled=group != "cache_disabled_baseline",
                            expected_cache_state=_cache_state(group),
                            pair_id=pair_id,
                            run_id=run_id,
                            paired_comparison_group=comparison_group,
                            is_warmup=is_warmup,
                        )
                        rows.append(_to_row(request, _execute_safely(execute, request)))
    return tuple(rows)


def build_live_metadata(
    *,
    dataset_version: str,
    cache_contract_version: str,
    run_date: str,
    git_sha: str,
) -> BenchmarkMetadata:
    """Create the exact CACHE-05 metadata shape for a future live run."""

    return BenchmarkMetadata(
        schema_version=SCHEMA_VERSION,
        dataset_version=dataset_version,
        cache_contract_version=cache_contract_version,
        benchmark_kind="live_measurement",
        run_date=run_date,
        git_sha=git_sha,
        benchmark_id="-".join(
            (
                run_date,
                git_sha[:12],
                dataset_version,
                cache_contract_version,
            )
        ),
    )


def fixed_bundle_path(repository_root: Path, benchmark_id: str) -> Path:
    """Return the only approved final bundle path for a safe benchmark id."""

    if (
        not isinstance(benchmark_id, str)
        or not _SAFE_IDENTIFIER.fullmatch(benchmark_id)
        or _UUID_TEXT.search(benchmark_id)
    ):
        raise CollectorPreflightError("Benchmark identifier is invalid")
    return repository_root / FIXED_BUNDLE_ROOT / benchmark_id


def publish_live_bundle(
    rows: Sequence[RunRow],
    *,
    metadata: BenchmarkMetadata,
    repository_root: Path,
    tracking_preflight: TrackingPreflight,
) -> dict:
    """Run structural tracking preflight, then delegate artifact safety to CACHE-05."""

    output = fixed_bundle_path(repository_root, metadata.benchmark_id)
    tracking_preflight(output)
    return generate_bundle(LatencyDataset(metadata=metadata, runs=tuple(rows)), output)
