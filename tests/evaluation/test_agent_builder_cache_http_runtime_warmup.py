from __future__ import annotations

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
    )


def _request(run_id: str) -> LiveAttemptRequest:
    return LiveAttemptRequest(
        case_id="safe-case",
        scenario_fingerprint="a" * 64,
        generation_mode="configure_and_generate",
        comparison_group="cold_miss",
        cache_enabled=True,
        expected_cache_state="cold",
        pair_id="p-safe",
        run_id=run_id,
        paired_comparison_group="cold_miss",
        is_warmup="warmup" in run_id,
    )


def test_warmup_uses_its_dedicated_private_scenario_index():
    messages: list[str] = []

    def request_json(method, url, *, headers, payload, timeout_seconds):
        if url.endswith("/sessions"):
            return {"session_id": "00000000-0000-0000-0000-000000000005", "workflow_id": _config().workflow_id}
        if url.endswith("/messages"):
            messages.append(payload["message"])
            return {"request_id": "00000000-0000-0000-0000-000000000006"}
        if "/benchmark/diagnostics/" in url:
            return {"cache_outcome": "miss", "planning_latency_ms": 1, "provider_call_count": 1, "repair_call_count": 0, "terminal_status": "success", "validation_passed": True}
        raise AssertionError(url)

    runtime = HttpLiveBenchmarkRuntime(
        _config(),
        {
            "schema_version": "mba-350-live-scenarios-v1",
            "development": {
                "cold_miss": ["measured-first"] + ["unused"] * 9 + ["warmup-only"],
                "exact_warm_hit": ["x"],
                "normalization_warm_hit": [{"prime": "x", "measure": "x"}],
                "semantic_bypass": ["x"],
                "negative_control": ["x"],
            },
            "final": {},
        },
        request_json=request_json,
    )

    runtime.execute(_request("dev-warmup-01"))
    runtime.execute(_request("dev-01"))

    assert messages == ["warmup-only", "measured-first"]
