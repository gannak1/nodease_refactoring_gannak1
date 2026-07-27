from __future__ import annotations

from tests.evaluation.agent_builder_cache_http_runtime import (
    HttpBenchmarkConfiguration,
    HttpLiveBenchmarkRuntime,
)
from tests.evaluation.agent_builder_cache_live_collector import LiveAttemptRequest


def _configuration() -> HttpBenchmarkConfiguration:
    return HttpBenchmarkConfiguration(
        cache_off_base_url="http://127.0.0.1:8010/api/v1/agent-builder",
        cache_on_base_url="http://127.0.0.1:8011/api/v1/agent-builder",
        authorization="Bearer test-token",
        organization_id="00000000-0000-0000-0000-000000000001",
        workflow_id="00000000-0000-0000-0000-000000000002",
        credential_id="00000000-0000-0000-0000-000000000003",
        model_id="00000000-0000-0000-0000-000000000004",
        fingerprint_key=b"test-fingerprint-key",
    )


def _scenarios() -> dict[str, object]:
    return {
        "schema_version": "mba-350-live-scenarios-v1",
        "development": {},
        "final": {},
    }


def test_admission_rejects_gateway_workflow_context_version_mismatch() -> None:
    configuration = _configuration()
    session_calls: list[str] = []

    def request_json(method, url, *, headers, payload, timeout_seconds):
        if url.endswith("/model-options"):
            return [
                {
                    "options": [
                        {
                            "model": {
                                "id": configuration.model_id,
                                "model_id_for_api_call": "gpt-5.5",
                            },
                            "credential": {"id": configuration.credential_id},
                        }
                    ]
                }
            ]
        if url.endswith(f"/workflows/{configuration.workflow_id}"):
            return {
                "id": configuration.workflow_id,
                "app_id": "00000000-0000-0000-0000-000000000099",
                "updated_at": "2026-07-23T00:00:00+00:00"
                if ":8010/" in url
                else "2026-07-23T00:00:01+00:00",
            }
        if url.endswith("/sessions"):
            session_calls.append(url)
            return {
                "session_id": "00000000-0000-0000-0000-000000000005",
                "workflow_id": configuration.workflow_id,
                "status": "active",
            }
        raise AssertionError(url)

    admission = HttpLiveBenchmarkRuntime(
        configuration,
        _scenarios(),
        request_json=request_json,
    ).admission()

    assert admission.permission_checked is False
    assert admission.graph_context_ready is False
    assert session_calls == []


def test_execute_rejects_workflow_context_change_after_admission() -> None:
    configuration = _configuration()
    version = {"updated_at": "2026-07-23T00:00:00+00:00"}
    message_calls: list[str] = []

    def request_json(method, url, *, headers, payload, timeout_seconds):
        if url.endswith("/model-options"):
            return [
                {
                    "options": [
                        {
                            "model": {
                                "id": configuration.model_id,
                                "model_id_for_api_call": "gpt-5.5",
                            },
                            "credential": {"id": configuration.credential_id},
                        }
                    ]
                }
            ]
        if url.endswith(f"/workflows/{configuration.workflow_id}"):
            return {
                "id": configuration.workflow_id,
                "app_id": "00000000-0000-0000-0000-000000000099",
                "updated_at": version["updated_at"],
            }
        if url.endswith("/sessions"):
            return {
                "session_id": "00000000-0000-0000-0000-000000000005",
                "workflow_id": configuration.workflow_id,
                "status": "active",
            }
        if url.endswith("/messages"):
            message_calls.append(url)
            raise AssertionError("message must not be submitted")
        raise AssertionError(url)

    runtime = HttpLiveBenchmarkRuntime(
        configuration,
        {
            "schema_version": "mba-350-live-scenarios-v1",
            "development": {
                "cold_miss": ["cold request"],
                "exact_warm_hit": ["exact request"],
                "normalization_warm_hit": [
                    {"prime": "normalized", "measure": "normalized  "}
                ],
                "semantic_bypass": ["bypass request"],
                "negative_control": ["negative request"],
            },
            "final": {},
        },
        request_json=request_json,
    )
    assert runtime.admission().permission_checked is True
    version["updated_at"] = "2026-07-23T00:00:01+00:00"

    observation = runtime.execute(
        LiveAttemptRequest(
            case_id="safe-case",
            scenario_fingerprint="a" * 64,
            generation_mode="configure_and_generate",
            comparison_group="cold_miss",
            cache_enabled=True,
            expected_cache_state="cold",
            pair_id="p-safe",
            run_id="development-01",
            paired_comparison_group="cold_miss",
        )
    )

    assert observation.terminal_status == "provider_error"
    assert observation.result_fingerprint == ""
    assert message_calls == []