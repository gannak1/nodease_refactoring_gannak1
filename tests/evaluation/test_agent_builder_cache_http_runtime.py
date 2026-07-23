from __future__ import annotations

import json

from tests.evaluation.agent_builder_cache_live_collector import LiveAttemptRequest
from tests.evaluation.agent_builder_cache_http_runtime import (
    HttpBenchmarkConfiguration,
    HttpLiveBenchmarkRuntime,
)


def _config() -> HttpBenchmarkConfiguration:
    return HttpBenchmarkConfiguration(
        cache_off_base_url="http://127.0.0.1:8010",
        cache_on_base_url="http://127.0.0.1:8011",
        authorization="Bearer test-token",
        organization_id="00000000-0000-0000-0000-000000000001",
        workflow_id="00000000-0000-0000-0000-000000000002",
        credential_id="00000000-0000-0000-0000-000000000003",
        model_id="00000000-0000-0000-0000-000000000004",
        fingerprint_key=b"test-fingerprint-key",
        timeout_seconds=5,
    )


def _scenarios() -> dict:
    return {
        "schema_version": "mba-350-live-scenarios-v1",
        "development": {
            "cold_miss": ["cold request"],
            "exact_warm_hit": ["exact request"],
            "normalization_warm_hit": [
                {"prime": "normalized request", "measure": "normalized   request"}
            ],
            "semantic_bypass": ["bypass request"],
            "negative_control": ["negative request"],
        },
        "final": {
            "cold_miss": ["cold final request"],
            "exact_warm_hit": ["exact final request"],
            "normalization_warm_hit": [
                {"prime": "normalized final request", "measure": "normalized   final request"}
            ],
            "semantic_bypass": ["bypass final request"],
            "negative_control": ["negative final request"],
        },
    }


def _request(group: str, *, cache_enabled: bool = True) -> LiveAttemptRequest:
    return LiveAttemptRequest(
        case_id="safe-case",
        scenario_fingerprint="a" * 64,
        generation_mode="configure_and_generate",
        comparison_group=group,
        cache_enabled=cache_enabled,
        expected_cache_state="disabled" if not cache_enabled else "hit",
        pair_id="p-safe",
        run_id="development-01",
        paired_comparison_group=group,
    )


def test_preflight_checks_both_servers_and_gpt55_relation_without_retaining_payload():
    calls: list[tuple[str, str, dict | None]] = []

    def request_json(method, url, *, headers, payload, timeout_seconds):
        calls.append((method, url, payload))
        if url.endswith("/model-options"):
            return [{"provider_name": "openai", "options": [{"model": {"id": _config().model_id, "model_api_id": "gpt-5.5"}, "credential": {"id": _config().credential_id}}]}]
        if url.endswith(f"/workflows/{_config().workflow_id}"):
            return {
                "id": _config().workflow_id,
                "app_id": "00000000-0000-0000-0000-000000000099",
                "updated_at": "2026-07-23T00:00:00+00:00",
            }
        if url.endswith("/sessions"):
            return {"session_id": "00000000-0000-0000-0000-000000000005", "workflow_id": _config().workflow_id, "status": "active"}
        raise AssertionError(url)

    runtime = HttpLiveBenchmarkRuntime(_config(), _scenarios(), request_json=request_json)

    admission = runtime.admission()

    assert admission.permission_checked
    assert admission.gpt55_available
    assert admission.graph_context_ready
    assert admission.cache_contract_ready
    assert b"test-token" not in admission.fingerprint_material
    assert b"00000000" not in admission.fingerprint_material
    assert [call[0] for call in calls].count("GET") == 4


def test_exact_warm_candidate_primes_cache_then_uses_allowlisted_diagnostic():
    calls: list[tuple[str, str, dict | None]] = []
    request_id = "00000000-0000-0000-0000-000000000006"

    def request_json(method, url, *, headers, payload, timeout_seconds):
        calls.append((method, url, payload))
        if url.endswith("/sessions"):
            return {"session_id": "00000000-0000-0000-0000-000000000005", "workflow_id": _config().workflow_id, "status": "active"}
        if url.endswith("/messages"):
            return {"request_id": request_id, "status": "completed", "structured_plan": {"intent_summary": "private response"}}
        if url.endswith(f"/benchmark/diagnostics/{request_id}"):
            return {"cache_outcome": "hit", "planning_latency_ms": 12.5, "provider_call_count": 0, "repair_call_count": 0, "terminal_status": "success", "validation_passed": True}
        raise AssertionError(url)

    runtime = HttpLiveBenchmarkRuntime(_config(), _scenarios(), request_json=request_json)
    observation = runtime.execute(_request("exact_warm_hit"))

    message_calls = [call for call in calls if call[1].endswith("/messages")]
    assert len(message_calls) == 2
    assert all(call[2] is not None and call[2]["message"] == "exact request" for call in message_calls)
    assert observation.cache_outcome == "hit"
    assert observation.provider_call_count == 0
    assert observation.result_fingerprint
    assert "private response" not in repr(observation)


def test_non_loopback_or_unexpected_diagnostic_becomes_safe_failure():
    try:
        HttpBenchmarkConfiguration(
            **{**_config().__dict__, "cache_on_base_url": "https://example.test"}
        )
    except ValueError as exc:
        assert "loopback" in str(exc).lower()
    else:
        raise AssertionError("expected loopback rejection")

    def request_json(method, url, *, headers, payload, timeout_seconds):
        if url.endswith("/messages"):
            return {"request_id": "00000000-0000-0000-0000-000000000006", "status": "completed"}
        if "/benchmark/diagnostics/" in url:
            return {"cache_outcome": "hit", "planning_latency_ms": 1, "provider_call_count": 1, "repair_call_count": 0, "terminal_status": "success", "validation_passed": True}
        raise AssertionError(url)

    observation = HttpLiveBenchmarkRuntime(_config(), _scenarios(), request_json=request_json).execute(_request("exact_warm_hit"))
    assert observation.terminal_status == "provider_error"
    assert observation.result_fingerprint == ""


def test_scenarios_are_loaded_only_from_private_json_shape():
    scenarios = _scenarios()
    assert json.loads(json.dumps(scenarios))["schema_version"] == "mba-350-live-scenarios-v1"
