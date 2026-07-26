from __future__ import annotations

from tests.evaluation.agent_builder_cache_http_runtime import (
    HttpBenchmarkConfiguration,
    HttpLiveBenchmarkRuntime,
)


def test_session_creation_marks_the_evaluation_only_fresh_session_boundary() -> None:
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
    captured_headers: list[dict[str, str]] = []

    def request_json(method, url, *, headers, payload, timeout_seconds):
        if url.endswith("/sessions"):
            captured_headers.append(dict(headers))
            return {
                "session_id": "00000000-0000-0000-0000-000000000005",
                "workflow_id": configuration.workflow_id,
                "status": "active",
            }
        raise AssertionError(url)

    runtime = HttpLiveBenchmarkRuntime(
        configuration,
        {"schema_version": "mba-350-live-scenarios-v1", "development": {}, "final": {}},
        request_json=request_json,
    )

    runtime._create_session(True, "pair")  # noqa: SLF001

    assert captured_headers == [
        {
            "Cookie": "auth_token=test-token",
            "X-Organization-Id": configuration.organization_id,
            "Accept": "application/json",
            "X-Agent-Builder-Benchmark-Fresh-Session": "true",
        }
    ]


def test_fresh_session_marker_is_not_sent_to_preflight_requests() -> None:
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
    preflight_headers: list[dict[str, str]] = []

    def request_json(method, url, *, headers, payload, timeout_seconds):
        if url.endswith("/model-options"):
            preflight_headers.append(dict(headers))
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
            preflight_headers.append(dict(headers))
            return {
                "id": configuration.workflow_id,
                "app_id": "00000000-0000-0000-0000-000000000099",
                "updated_at": "2026-07-23T00:00:00+00:00",
            }
        if url.endswith("/sessions"):
            return {
                "session_id": "00000000-0000-0000-0000-000000000005",
                "workflow_id": configuration.workflow_id,
                "status": "active",
            }
        raise AssertionError(url)

    runtime = HttpLiveBenchmarkRuntime(
        configuration,
        {"schema_version": "mba-350-live-scenarios-v1", "development": {}, "final": {}},
        request_json=request_json,
    )

    assert runtime.admission().permission_checked is True
    assert preflight_headers
    assert all(
        "X-Agent-Builder-Benchmark-Fresh-Session" not in headers
        for headers in preflight_headers
    )