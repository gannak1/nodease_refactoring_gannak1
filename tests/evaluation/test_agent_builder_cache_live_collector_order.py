from __future__ import annotations

from collections import defaultdict

from tests.evaluation.agent_builder_cache_live_collector import (
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


def _observation(request) -> LiveAttemptObservation:
    return LiveAttemptObservation(
        cache_outcome=request.expected_cache_state,
        planning_latency_ms=1.0,
        end_to_end_latency_ms=2.0,
        provider_call_count=0 if request.expected_cache_state == "hit" else 1,
        repair_call_count=0,
        terminal_status="success",
        validation_passed=True,
        result_fingerprint="b" * 64,
    )


def test_measured_pairs_alternate_baseline_and_candidate_execution_order() -> None:
    requests = []

    def execute(request):
        requests.append(request)
        return _observation(request)

    collect_paired_rows(
        cases=(
            BenchmarkScenario(
                case_id="safe-case",
                scenario_fingerprint="a" * 64,
                generation_mode="configure_and_generate",
            ),
        ),
        preflight=_ready_preflight(),
        phase="development",
        execute=execute,
    )

    by_pair = defaultdict(list)
    pair_groups = {}
    for request in requests:
        if not request.is_warmup:
            by_pair[request.pair_id].append(request.comparison_group)
            pair_groups[request.pair_id] = request.paired_comparison_group

    by_candidate_group = defaultdict(list)
    for pair_id, order in by_pair.items():
        by_candidate_group[pair_groups[pair_id]].append(order)

    for orders in by_candidate_group.values():
        assert orders
        assert any(order[0] == "cache_disabled_baseline" for order in orders)
        assert any(order[1] == "cache_disabled_baseline" for order in orders)
        for index, order in enumerate(orders):
            assert "cache_disabled_baseline" in order
            assert (order[0] == "cache_disabled_baseline") is (index % 2 == 0)
