from __future__ import annotations

from collections import defaultdict

from tests.evaluation.agent_builder_cache_live_collector import (
    FINAL_ATTEMPTS_PER_GROUP,
    MBA350_CANDIDATE_GROUPS,
    BenchmarkScenario,
    LiveAttemptObservation,
    RuntimePreflight,
    collect_paired_rows,
)


def _ready_preflight() -> RuntimePreflight:
    return RuntimePreflight(
        permission_checked=True,
        gpt55_available=True,
        graph_context_ready=True,
        cache_contract_ready=True,
        scenario_fingerprint="a" * 64,
    )


def test_final_collection_preserves_every_pair_and_failure_with_one_scenario() -> None:
    scenario = BenchmarkScenario(
        case_id="workflow_create_basic",
        scenario_fingerprint="a" * 64,
        generation_mode="guided_generate",
    )
    requests = []

    def execute(request):
        requests.append(request)
        if (
            request.comparison_group == "negative_control"
            and request.run_id == "fin-01"
            and request.cache_enabled
        ):
            return LiveAttemptObservation(
                cache_outcome="error",
                planning_latency_ms=None,
                end_to_end_latency_ms=None,
                provider_call_count=0,
                repair_call_count=0,
                terminal_status="provider_error",
                validation_passed=False,
                result_fingerprint="",
            )
        return LiveAttemptObservation(
            cache_outcome=request.expected_cache_state,
            planning_latency_ms=10.0,
            end_to_end_latency_ms=15.0,
            provider_call_count=0 if request.expected_cache_state == "hit" else 1,
            repair_call_count=0,
            terminal_status="success",
            validation_passed=True,
            result_fingerprint="b" * 64,
        )

    rows = collect_paired_rows(
        cases=(scenario,),
        preflight=_ready_preflight(),
        phase="final",
        execute=execute,
    )

    assert len(rows) == len(MBA350_CANDIDATE_GROUPS) * (FINAL_ATTEMPTS_PER_GROUP + 1) * 2
    assert any(
        row.comparison_group == "negative_control"
        and row.terminal_status == "provider_error"
        and row.validation_passed is False
        for row in rows
    )

    by_group = defaultdict(list)
    for row in rows:
        by_group[row.comparison_group].append(row)
    assert len(by_group["cache_disabled_baseline"]) == (
        len(MBA350_CANDIDATE_GROUPS) * (FINAL_ATTEMPTS_PER_GROUP + 1)
    )
    for group in MBA350_CANDIDATE_GROUPS:
        assert len(by_group[group]) == FINAL_ATTEMPTS_PER_GROUP + 1

    by_pair = defaultdict(list)
    for request in requests:
        by_pair[request.pair_id].append(request)
    assert len(by_pair) == len(MBA350_CANDIDATE_GROUPS) * (FINAL_ATTEMPTS_PER_GROUP + 1)
    assert sum(request.is_warmup for request in requests) == len(MBA350_CANDIDATE_GROUPS) * 2
    for pair in by_pair.values():
        assert len(pair) == 2
        assert {request.cache_enabled for request in pair} == {False, True}
        assert {request.scenario_fingerprint for request in pair} == {"a" * 64}
        assert {request.generation_mode for request in pair} == {"guided_generate"}
