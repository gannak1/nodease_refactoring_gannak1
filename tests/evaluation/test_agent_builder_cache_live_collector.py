from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from tests.evaluation.agent_builder_cache_latency_report import ARTIFACT_FILENAMES
from tests.evaluation.agent_builder_cache_live_collector import (
    DEVELOPMENT_ATTEMPTS_PER_GROUP,
    MBA350_CANDIDATE_GROUPS,
    CollectorPreflightError,
    BenchmarkScenario,
    LiveAttemptObservation,
    LiveBenchmarkCase,
    RuntimePreflight,
    build_live_metadata,
    collect_paired_rows,
    fixed_bundle_path,
    publish_live_bundle,
)


def _ready_preflight() -> RuntimePreflight:
    return RuntimePreflight(
        permission_checked=True,
        gpt55_available=True,
        graph_context_ready=True,
        cache_contract_ready=True,
        scenario_fingerprint="a" * 64,
    )


def _successful_observation(request) -> LiveAttemptObservation:
    outcome_by_group = {
        "cache_disabled_baseline": ("disabled", 1),
        "cold_miss": ("miss", 1),
        "exact_warm_hit": ("hit", 0),
        "normalization_warm_hit": ("hit", 0),
        "semantic_bypass": ("bypass", 1),
        "negative_control": ("error", 1),
    }
    outcome, provider_calls = outcome_by_group[request.comparison_group]
    return LiveAttemptObservation(
        cache_outcome=outcome,
        planning_latency_ms=10.0,
        end_to_end_latency_ms=20.0,
        provider_call_count=provider_calls,
        repair_call_count=0,
        terminal_status="success",
        validation_passed=True,
        result_fingerprint="a" * 64,
    )


def test_development_collection_emits_paired_rows_for_every_required_group():
    rows = collect_paired_rows(
        cases=(BenchmarkScenario(
                case_id="case-a",
                scenario_fingerprint="a" * 64,
                generation_mode="guided_generate",
            ),),
        preflight=_ready_preflight(),
        phase="development",
        execute=_successful_observation,
    )

    assert len(rows) == len(MBA350_CANDIDATE_GROUPS) * (DEVELOPMENT_ATTEMPTS_PER_GROUP + 1) * 2
    by_group = Counter(row.comparison_group for row in rows)
    assert by_group["cache_disabled_baseline"] == (
        len(MBA350_CANDIDATE_GROUPS) * (DEVELOPMENT_ATTEMPTS_PER_GROUP + 1)
    )
    for group in MBA350_CANDIDATE_GROUPS:
        assert by_group[group] == DEVELOPMENT_ATTEMPTS_PER_GROUP + 1
    assert all(not hasattr(row, "message") for row in rows)


def test_collection_requires_permission_aware_runtime_preflight():
    with pytest.raises(CollectorPreflightError):
        collect_paired_rows(
            cases=(LiveBenchmarkCase(case_id="case-a"),),
            preflight=RuntimePreflight(
                permission_checked=False,
                gpt55_available=True,
                graph_context_ready=True,
                cache_contract_ready=True,
                scenario_fingerprint="a" * 64,
            ),
            phase="development",
            execute=_successful_observation,
        )


def test_executor_failure_is_preserved_as_a_safe_terminal_row():
    def failing_execute(_request):
        raise RuntimeError("provider detail must not be retained")

    rows = collect_paired_rows(
        cases=(LiveBenchmarkCase(case_id="case-a"),),
        preflight=_ready_preflight(),
        phase="development",
        execute=failing_execute,
    )

    assert len(rows) == len(MBA350_CANDIDATE_GROUPS) * (DEVELOPMENT_ATTEMPTS_PER_GROUP + 1) * 2
    assert {row.terminal_status for row in rows} == {"provider_error"}
    assert all(not row.validation_passed for row in rows)
    assert all(row.result_fingerprint == "" for row in rows)
    assert all(row.provider_call_count == 0 for row in rows)


def test_publish_uses_fixed_path_and_report_tool_artifact_allowlist(tmp_path: Path):
    rows = collect_paired_rows(
        cases=(LiveBenchmarkCase(case_id="case-a"),),
        preflight=_ready_preflight(),
        phase="development",
        execute=_successful_observation,
    )
    metadata = build_live_metadata(
        dataset_version="mba350-live-v1",
        cache_contract_version="agent-builder-cache-v1",
        run_date="2026-07-22",
        git_sha="a" * 40,
    )
    tracked_paths: list[Path] = []

    summary = publish_live_bundle(
        rows,
        metadata=metadata,
        repository_root=tmp_path,
        tracking_preflight=tracked_paths.append,
    )

    output = fixed_bundle_path(tmp_path, metadata.benchmark_id)
    assert tracked_paths == [output]
    assert {path.name for path in output.iterdir()} == set(ARTIFACT_FILENAMES)
    assert summary["benchmark"]["benchmark_kind"] == "live_measurement"


def test_collection_rejects_a_scenario_that_does_not_match_preflight():
    with pytest.raises(CollectorPreflightError):
        collect_paired_rows(
            cases=(
                BenchmarkScenario(
                    case_id="case-a",
                    scenario_fingerprint="b" * 64,
                    generation_mode="guided_generate",
                ),
            ),
            preflight=_ready_preflight(),
            phase="development",
            execute=_successful_observation,
        )
