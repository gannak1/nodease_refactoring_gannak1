from __future__ import annotations

from tests.evaluation.agent_builder_cache_live_collector import LiveAttemptRequest
from tests.evaluation.agent_builder_cache_http_runtime import (
    HttpBenchmarkConfiguration,
    HttpLiveBenchmarkRuntime,
)


def _configuration() -> HttpBenchmarkConfiguration:
    return HttpBenchmarkConfiguration(
        cache_off_base_url="http://127.0.0.1:8010",
        cache_on_base_url="http://127.0.0.1:8011",
        authorization="Bearer test-token",
        organization_id="00000000-0000-0000-0000-000000000001",
        workflow_id="00000000-0000-0000-0000-000000000002",
        credential_id="00000000-0000-0000-0000-000000000003",
        model_id="00000000-0000-0000-0000-000000000004",
        fingerprint_key=b"test-fingerprint-key",
    )


def _scenarios() -> dict:
    return {
        "schema_version": "mba-350-live-scenarios-v1",
        "development": {
            "cold_miss": ["cold request"],
            "exact_warm_hit": ["exact request"],
            "normalization_warm_hit": [{"prime": "normalized request", "measure": "normalized   request"}],
            "semantic_bypass": ["bypass request"],
            "negative_control": ["negative request"],
        },
        "final": {
            "cold_miss": ["cold final request"],
            "exact_warm_hit": ["exact final request"],
            "normalization_warm_hit": [{"prime": "normalized final request", "measure": "normalized   final request"}],
            "semantic_bypass": ["bypass final request"],
            "negative_control": ["negative final request"],
        },
    }


def _request(group: str, pair_id: str) -> LiveAttemptRequest:
    return LiveAttemptRequest(
        case_id="safe-case",
        scenario_fingerprint="a" * 64,
        generation_mode="configure_and_generate",
        comparison_group=group,
        cache_enabled=True,
        expected_cache_state="hit" if group == "exact_warm_hit" else "miss",
        pair_id=pair_id,
        run_id="development-01",
        paired_comparison_group=group,
    )


def test_prime_and_measurement_use_fresh_pair_scoped_sessions() -> None:
    calls: list[str] = []
    session_count = 0
    message_count = 0

    def request_json(method, url, *, headers, payload, timeout_seconds):
        nonlocal session_count, message_count
        calls.append(url)
        if url.endswith("/sessions"):
            session_count += 1
            return {
                "session_id": f"session-{session_count}",
                "workflow_id": _configuration().workflow_id,
                "status": "active",
            }
        if url.endswith("/messages"):
            message_count += 1
            return {"request_id": f"request-{message_count}", "status": "completed"}
        if "/benchmark/diagnostics/" in url:
            return {
                "cache_outcome": "hit",
                "planning_latency_ms": 1.0,
                "provider_call_count": 0,
                "repair_call_count": 0,
                "terminal_status": "success",
                "validation_passed": True,
            }
        raise AssertionError(url)

    runtime = HttpLiveBenchmarkRuntime(_configuration(), _scenarios(), request_json=request_json)

    runtime.execute(_request("exact_warm_hit", "pair-one"))
    runtime.execute(_request("cold_miss", "pair-two"))

    message_urls = [url for url in calls if url.endswith("/messages")]
    assert len(message_urls) == 3
    assert any(url.endswith("/sessions/session-1/messages") for url in message_urls)
    assert any(url.endswith("/sessions/session-2/messages") for url in message_urls)
    assert any(url.endswith("/sessions/session-3/messages") for url in message_urls)
