"""MBA-350 live benchmark orchestration.

This module keeps raw requests, protected identifiers, credentials, and graph
content inside a runtime adapter.  The collector receives only safe case labels,
an irreversible scenario fingerprint, and allowlisted observations.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
from datetime import date
from pathlib import Path
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from tests.evaluation.agent_builder_cache_latency_report import (
    BenchmarkMetadata,
    RunRow,
    build_summary,
)
from tests.evaluation.agent_builder_cache_live_collector import (
    BenchmarkScenario,
    LiveAttemptObservation,
    LiveAttemptRequest,
    RuntimePreflight,
    collect_paired_rows,
    build_live_metadata,
    publish_live_bundle,
)


@dataclass(frozen=True)
class RuntimeAdmission:
    """Private runtime checks; fingerprint material must never be published."""

    permission_checked: bool
    gpt55_available: bool
    graph_context_ready: bool
    cache_contract_ready: bool
    fingerprint_material: bytes


class LiveBenchmarkRuntime(ABC):
    """Environment-specific bridge to the real Agent Builder request boundary."""

    @abstractmethod
    def admission(self) -> RuntimeAdmission:
        """Verify permission, model, current graph/context, and cache readiness."""

    @abstractmethod
    def execute(self, request: LiveAttemptRequest) -> LiveAttemptObservation:
        """Run one baseline or candidate attempt without exposing protected input."""


def build_runtime_preflight(runtime: LiveBenchmarkRuntime) -> RuntimePreflight:
    """Turn private admission material into the collector's safe preflight DTO."""

    admission = runtime.admission()
    if not isinstance(admission.fingerprint_material, bytes) or not admission.fingerprint_material:
        raise ValueError("Runtime preflight material is invalid")
    fingerprint = hashlib.sha256(
        b"mba-350-agent-builder-cache-live-v1\x00" + admission.fingerprint_material
    ).hexdigest()
    return RuntimePreflight(
        permission_checked=admission.permission_checked,
        gpt55_available=admission.gpt55_available,
        graph_context_ready=admission.graph_context_ready,
        cache_contract_ready=admission.cache_contract_ready,
        scenario_fingerprint=fingerprint,
    )


def run_live_phase(
    *,
    runtime: LiveBenchmarkRuntime,
    cases: Sequence[BenchmarkScenario],
    preflight: RuntimePreflight,
    phase: Literal["development", "final"],
):
    """Execute only after the collector validates the safe preflight."""

    try:
        preflight.require_ready()
    except Exception as exc:
        raise ValueError("Live benchmark preflight rejected") from exc
    return collect_paired_rows(
        cases=cases,
        preflight=preflight,
        phase=phase,
        execute=runtime.execute,
    )

_REQUIRED_SUCCESS_OUTCOMES = {
    "cache_disabled_baseline": "disabled",
    "cold_miss": "miss",
    "exact_warm_hit": "hit",
    "normalization_warm_hit": "hit",
    "semantic_bypass": "bypass",
}


def validate_live_rows(
    rows: Sequence[RunRow], *, metadata: BenchmarkMetadata
) -> dict:
    """Apply the CACHE-05 row, pair, and outcome contract before persistence."""

    summary = build_summary(rows, metadata)
    for row in rows:
        required_outcome = _REQUIRED_SUCCESS_OUTCOMES.get(row.comparison_group)
        if (
            row.is_success
            and required_outcome
            and row.cache_outcome != required_outcome
        ):
            raise ValueError("Live benchmark observed outcome is invalid")
    return summary


_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_EVIDENCE_ROOT = Path("local/mba-350/evidence")
_PRIVATE_ENVIRONMENT_KEYS = (
    "NODEASE_EVAL_CACHE_OFF_URL",
    "NODEASE_EVAL_CACHE_ON_URL",
    "NODEASE_EVAL_AUTHORIZATION",
    "NODEASE_EVAL_ORGANIZATION_ID",
    "NODEASE_EVAL_WORKFLOW_ID",
    "NODEASE_EVAL_CREDENTIAL_ID",
    "NODEASE_EVAL_MODEL_ID",
    "NODEASE_EVAL_FINGERPRINT_KEY",
)


def load_private_scenarios(path: Path) -> dict[str, object]:
    """Load raw test messages only from an ignored, local file."""

    try:
        if not path.is_file() or path.stat().st_size > 256 * 1024:
            raise ValueError
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Live benchmark private scenario is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("Live benchmark private scenario is invalid")
    return payload


def _scenario_attempts(phase: Literal["development", "final"]) -> int:
    return 10 if phase == "development" else 30


def validate_private_scenario_capacity(
    scenarios: Mapping[str, object],
    phase: Literal["development", "final"],
) -> None:
    """Require one distinct warm-up input plus every measured input per group."""

    phase_data = scenarios.get(phase)
    required = _scenario_attempts(phase) + 1
    if not isinstance(phase_data, Mapping):
        raise ValueError("Live benchmark private scenario is invalid")
    for group in (
        "cold_miss",
        "exact_warm_hit",
        "normalization_warm_hit",
        "semantic_bypass",
        "negative_control",
    ):
        entries = phase_data.get(group)
        if not isinstance(entries, list) or len(entries) < required:
            raise ValueError("Live benchmark private scenario is incomplete")
        for entry in entries[:required]:
            if group == "normalization_warm_hit":
                if (
                    not isinstance(entry, Mapping)
                    or not isinstance(entry.get("prime"), str)
                    or not entry.get("prime")
                    or not isinstance(entry.get("measure"), str)
                    or not entry.get("measure")
                ):
                    raise ValueError("Live benchmark private scenario is invalid")
            elif not isinstance(entry, str) or not entry:
                raise ValueError("Live benchmark private scenario is invalid")


def runtime_from_environment(
    environment: Mapping[str, str],
    scenarios: Mapping[str, object],
) -> LiveBenchmarkRuntime:
    """Construct the loopback executor without logging private configuration."""

    missing = [key for key in _PRIVATE_ENVIRONMENT_KEYS if not environment.get(key)]
    if missing:
        raise ValueError("Live benchmark private configuration is incomplete")
    from tests.evaluation.agent_builder_cache_http_runtime import (
        HttpBenchmarkConfiguration,
        HttpLiveBenchmarkRuntime,
    )

    timeout_raw = environment.get("NODEASE_EVAL_TIMEOUT_SECONDS", "60")
    try:
        timeout_seconds = float(timeout_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Live benchmark timeout is invalid") from exc
    configuration = HttpBenchmarkConfiguration(
        cache_off_base_url=environment["NODEASE_EVAL_CACHE_OFF_URL"],
        cache_on_base_url=environment["NODEASE_EVAL_CACHE_ON_URL"],
        authorization=environment["NODEASE_EVAL_AUTHORIZATION"],
        organization_id=environment["NODEASE_EVAL_ORGANIZATION_ID"],
        workflow_id=environment["NODEASE_EVAL_WORKFLOW_ID"],
        credential_id=environment["NODEASE_EVAL_CREDENTIAL_ID"],
        model_id=environment["NODEASE_EVAL_MODEL_ID"],
        fingerprint_key=environment["NODEASE_EVAL_FINGERPRINT_KEY"].encode("utf-8"),
        timeout_seconds=timeout_seconds,
    )
    return HttpLiveBenchmarkRuntime(configuration, scenarios)


def _write_development_rows(rows: Sequence[object], output: Path) -> None:
    """Keep development raw rows in local evidence, never in the final bundle path."""

    fields = (
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
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field) for field in fields})


def _tracked_bundle_preflight(output: Path) -> None:
    if output.is_symlink() or "benchmarks" not in output.parts:
        raise ValueError("Live benchmark artifact destination is invalid")
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(output)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ignored.returncode == 0:
        raise ValueError("Live benchmark artifact destination is ignored")


def _resolve_repository_root(value: Path) -> Path:
    repository_root = value.resolve()
    if repository_root != _WORKSPACE_ROOT:
        raise ValueError("Live benchmark repository root is invalid")
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    git_root = Path(completed.stdout.strip()).resolve() if completed.returncode == 0 else None
    if git_root != repository_root:
        raise ValueError("Live benchmark repository root is invalid")
    return repository_root


def _resolve_private_scenarios(value: Path, repository_root: Path) -> Path:
    scenarios = value if value.is_absolute() else repository_root / value
    scenarios = scenarios.resolve()
    private_root = (repository_root / "local" / "mba-350").resolve()
    if scenarios.suffix != ".json":
        raise ValueError("Live benchmark private scenario is invalid")
    try:
        scenarios.relative_to(private_root)
    except ValueError as exc:
        raise ValueError("Live benchmark private scenario is invalid") from exc
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(scenarios)],
        cwd=repository_root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ignored.returncode != 0:
        raise ValueError("Live benchmark private scenario is not ignored")
    return scenarios


def _resolve_development_output(value: Path, repository_root: Path) -> Path:
    output = value if value.is_absolute() else repository_root / value
    output = output.resolve()
    evidence_root = (repository_root / _LOCAL_EVIDENCE_ROOT).resolve()
    if output.suffix != ".csv" or output == evidence_root:
        raise ValueError("Live benchmark development output is invalid")
    try:
        output.relative_to(evidence_root)
    except ValueError as exc:
        raise ValueError("Live benchmark development output is invalid") from exc
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(output)],
        cwd=repository_root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ignored.returncode != 0:
        raise ValueError("Live benchmark development output is not ignored")
    return output


def _git_sha(repository_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    candidate = completed.stdout.strip()
    if completed.returncode != 0 or len(candidate) != 40:
        raise ValueError("Live benchmark git revision is unavailable")
    return candidate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a loopback-only MBA-350 Agent Builder cache benchmark."
    )
    parser.add_argument(
        "--phase",
        choices=("development", "final", "all"),
        required=True,
    )
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=_WORKSPACE_ROOT)
    parser.add_argument("--run-date", default=date.today().isoformat())
    parser.add_argument("--git-sha")
    parser.add_argument("--dataset-version", default="mba350-live-v1")
    parser.add_argument("--cache-contract-version", default="agent-builder-cache-v1")
    parser.add_argument(
        "--development-output",
        type=Path,
        default=Path("local/mba-350/evidence/live-development-runs.csv"),
    )
    return parser


def _safe_failure_reason(stage: str, exc: Exception) -> str:
    """Return an allowlisted failure reason without exception detail."""

    if not stage.endswith("_validation"):
        return "unclassified"
    detail = str(exc)
    if "fingerprint mismatch" in detail:
        return "pair_fingerprint_mismatch"
    if detail.startswith("Invalid pair:"):
        return "pair_shape"
    if detail.startswith("Invalid row"):
        return "row_contract"
    return "validation_contract"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repository_root = _resolve_repository_root(args.repository_root)
        development_output = _resolve_development_output(
            args.development_output,
            repository_root,
        )
        scenarios = load_private_scenarios(
            _resolve_private_scenarios(args.scenarios, repository_root)
        )
        phases: tuple[Literal["development", "final"], ...] = (
            ("development", "final")
            if args.phase == "all"
            else (args.phase,)
        )
        git_sha = args.git_sha or _git_sha(repository_root)
        for phase in phases:
            validate_private_scenario_capacity(scenarios, phase)
            runtime = runtime_from_environment(os.environ, scenarios)
            preflight = build_runtime_preflight(runtime)
            case = BenchmarkScenario(
                case_id="local-live",
                scenario_fingerprint=preflight.scenario_fingerprint,
                generation_mode="configure_and_generate",
            )
            rows = run_live_phase(
                runtime=runtime,
                cases=(case,),
                preflight=preflight,
                phase=phase,
            )
            metadata = build_live_metadata(
                dataset_version=args.dataset_version,
                cache_contract_version=args.cache_contract_version,
                run_date=args.run_date,
                git_sha=git_sha,
            )
            stage = f"{phase}_validation"
            validate_live_rows(rows, metadata=metadata)
            if phase == "development":
                _write_development_rows(rows, development_output)
                continue
            publish_live_bundle(
                rows,
                metadata=metadata,
                repository_root=repository_root,
                tracking_preflight=_tracked_bundle_preflight,
            )
    except Exception as exc:
        print("Live benchmark did not run; private preflight or validation rejected. " f"failure_stage={stage} failure_reason={_safe_failure_reason(stage, exc)}")
        return 2
    if phases == ("development",):
        print("Live benchmark development confirmation completed with validated local evidence.")
    else:
        print("Live benchmark final measurement completed with safe rows and validated artifacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
