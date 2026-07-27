from __future__ import annotations

from tests.evaluation.agent_builder_cache_http_runtime import (
    HttpBenchmarkConfiguration,
    HttpLiveBenchmarkRuntime,
)


def _runtime() -> HttpLiveBenchmarkRuntime:
    configuration = HttpBenchmarkConfiguration(
        cache_off_base_url="http://127.0.0.1:8010",
        cache_on_base_url="http://127.0.0.1:8011",
        authorization="Bearer test-token",
        organization_id="00000000-0000-0000-0000-000000000001",
        workflow_id="00000000-0000-0000-0000-000000000002",
        credential_id="00000000-0000-0000-0000-000000000003",
        model_id="00000000-0000-0000-0000-000000000004",
        fingerprint_key=b"test-fingerprint-key",
    )
    scenarios = {
        "schema_version": "mba-350-live-scenarios-v1",
        "development": {group: ["message"] for group in ("cold_miss", "exact_warm_hit", "semantic_bypass", "negative_control")},
        "final": {group: ["message"] for group in ("cold_miss", "exact_warm_hit", "semantic_bypass", "negative_control")},
    }
    scenarios["development"]["normalization_warm_hit"] = [{"prime": "message", "measure": "message"}]
    scenarios["final"]["normalization_warm_hit"] = [{"prime": "message", "measure": "message"}]
    return HttpLiveBenchmarkRuntime(configuration, scenarios)


def _response(*, request_id: str, node_id: str, operation_id: str, summary: str) -> dict:
    return {
        "request_id": request_id,
        "status": "draft_ready",
        "structured_plan": {
            "request_type": "new_workflow",
            "intent_summary": summary,
            "steps": [{"step_id": "input", "capability": "start_input"}],
        },
        "graph_mutation": {
            "operation_id": operation_id,
            "graph": {"nodes": [{"id": node_id, "type": "input"}], "edges": []},
        },
        "parameter_group": {
            "group_id": f"group-{node_id}",
            "status": "active",
            "tasks": [
                {"task_id": f"task-{node_id}", "group_id": f"group-{node_id}", "node_id": node_id, "step_id": "input", "reason": "same task"}
            ],
        },
    }


def test_parity_fingerprint_ignores_request_and_materialization_identity_but_not_semantics() -> None:
    runtime = _runtime()
    baseline = _response(
        request_id="request-off",
        node_id="node-off",
        operation_id="operation-off",
        summary="same semantic plan",
    )
    candidate = _response(
        request_id="request-on",
        node_id="node-on",
        operation_id="operation-on",
        summary="same semantic plan",
    )
    changed = _response(
        request_id="request-changed",
        node_id="node-changed",
        operation_id="operation-changed",
        summary="different semantic plan",
    )

    baseline_fingerprint = runtime._result_fingerprint(  # noqa: SLF001
        baseline,
        {"cache_outcome": "disabled", "planning_latency_ms": 20},
    )
    candidate_fingerprint = runtime._result_fingerprint(  # noqa: SLF001
        candidate,
        {"cache_outcome": "hit", "planning_latency_ms": 2},
    )
    changed_fingerprint = runtime._result_fingerprint(  # noqa: SLF001
        changed,
        {"cache_outcome": "hit", "planning_latency_ms": 2},
    )

    assert baseline_fingerprint == candidate_fingerprint
    assert changed_fingerprint != candidate_fingerprint
