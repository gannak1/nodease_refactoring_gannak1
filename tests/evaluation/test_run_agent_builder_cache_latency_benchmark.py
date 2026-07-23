from __future__ import annotations

import pytest

from tests.evaluation.agent_builder_cache_live_collector import (
    BenchmarkScenario,
    LiveAttemptObservation,
)
from tests.evaluation.agent_builder_cache_latency_report import (
    BenchmarkMetadata,
    RunRow,
)
from tests.evaluation.run_agent_builder_cache_latency_benchmark import (
    LiveBenchmarkRuntime,
    RuntimeAdmission,
    build_runtime_preflight,
    run_live_phase,
    validate_live_rows,
)


class _Runtime(LiveBenchmarkRuntime):
    def __init__(self) -> None:
        self.calls = []

    def admission(self) -> RuntimeAdmission:
        return RuntimeAdmission(
            permission_checked=True,
            gpt55_available=True,
            graph_context_ready=True,
            cache_contract_ready=True,
            fingerprint_material=b"private-runtime-material",
        )

    def execute(self, request):
        self.calls.append(request)
        return LiveAttemptObservation(
            cache_outcome=request.expected_cache_state.replace("_warm", "").replace("cold", "miss"),
            planning_latency_ms=10.0,
            end_to_end_latency_ms=20.0,
            provider_call_count=0 if request.cache_enabled else 1,
            repair_call_count=0,
            terminal_status="success",
            validation_passed=True,
            result_fingerprint="b" * 64,
        )


def test_live_phase_uses_safe_preflight_fingerprint_for_both_pair_arms():
    runtime = _Runtime()
    preflight = build_runtime_preflight(runtime)
    scenario = BenchmarkScenario(
        case_id="safe-case",
        scenario_fingerprint=preflight.scenario_fingerprint,
        generation_mode="configure_and_generate",
    )

    rows = run_live_phase(
        runtime=runtime,
        cases=(scenario,),
        preflight=preflight,
        phase="development",
    )

    assert len(rows) == 110
    assert len(runtime.calls) == 110
    assert all(row.result_fingerprint == "b" * 64 for row in rows)
    assert "private-runtime-material" not in preflight.scenario_fingerprint


def test_incomplete_runtime_admission_rejects_before_any_attempt():
    class _BlockedRuntime(_Runtime):
        def admission(self) -> RuntimeAdmission:
            return RuntimeAdmission(
                permission_checked=False,
                gpt55_available=True,
                graph_context_ready=True,
                cache_contract_ready=True,
                fingerprint_material=b"private-runtime-material",
            )

    runtime = _BlockedRuntime()
    preflight = build_runtime_preflight(runtime)
    scenario = BenchmarkScenario(
        case_id="safe-case",
        scenario_fingerprint=preflight.scenario_fingerprint,
        generation_mode="configure_and_generate",
    )

    try:
        run_live_phase(
            runtime=runtime,
            cases=(scenario,),
            preflight=preflight,
            phase="development",
        )
    except ValueError as exc:
        assert "preflight" in str(exc).lower()
    else:
        raise AssertionError("expected preflight rejection")
    assert runtime.calls == []

def _live_metadata() -> BenchmarkMetadata:
    return BenchmarkMetadata(
        schema_version="agent-builder-cache-latency-runs-v1",
        dataset_version="mba350-live-v1",
        cache_contract_version="agent-builder-cache-v1",
        benchmark_kind="live_measurement",
        run_date="2026-07-23",
        git_sha="a" * 40,
        benchmark_id=(
            "2026-07-23-aaaaaaaaaaaa-mba350-live-v1-agent-builder-cache-v1"
        ),
    )


def _successful_pair(
    comparison_group: str,
    candidate_outcome: str,
) -> tuple[RunRow, RunRow]:
    common = {
        "case_id": "safe-case",
        "pair_id": "p-safe",
        "run_id": "fin-01",
        "is_warmup": False,
        "planning_latency_ms": 10.0,
        "end_to_end_latency_ms": 20.0,
        "repair_call_count": 0,
        "terminal_status": "success",
        "validation_passed": True,
        "result_fingerprint": "b" * 64,
    }
    return (
        RunRow(
            comparison_group="cache_disabled_baseline",
            cache_outcome="disabled",
            provider_call_count=1,
            **common,
        ),
        RunRow(
            comparison_group=comparison_group,
            cache_outcome=candidate_outcome,
            provider_call_count=0 if candidate_outcome == "hit" else 1,
            **common,
        ),
    )


@pytest.mark.parametrize(
    "comparison_group",
    ("exact_warm_hit", "normalization_warm_hit"),
)
def test_live_rows_reject_successful_warm_measurement_without_hit(
    comparison_group: str,
) -> None:
    with pytest.raises(ValueError, match="observed outcome"):
        validate_live_rows(
            _successful_pair(comparison_group, "miss"),
            metadata=_live_metadata(),
        )


def test_live_rows_accept_successful_warm_measurement_with_hit() -> None:
    summary = validate_live_rows(
        _successful_pair("exact_warm_hit", "hit"),
        metadata=_live_metadata(),
    )

    assert summary["groups"]["exact_warm_hit"]["successful_run_count"] == 1


def test_live_rows_preserve_failed_warm_measurement_without_reclassifying_it() -> None:
    baseline, successful_candidate = _successful_pair("exact_warm_hit", "hit")
    failed_candidate = RunRow(
        case_id=successful_candidate.case_id,
        pair_id=successful_candidate.pair_id,
        run_id=successful_candidate.run_id,
        comparison_group=successful_candidate.comparison_group,
        is_warmup=successful_candidate.is_warmup,
        cache_outcome="miss",
        planning_latency_ms=None,
        end_to_end_latency_ms=None,
        provider_call_count=0,
        repair_call_count=0,
        terminal_status="provider_error",
        validation_passed=False,
        result_fingerprint="",
    )

    summary = validate_live_rows(
        (baseline, failed_candidate),
        metadata=_live_metadata(),
    )

    assert summary["groups"]["exact_warm_hit"]["failed_run_count"] == 1
