import uuid
from types import SimpleNamespace

from apps.shared.services.tracing.metadata import TraceMetadataSanitizer
from apps.shared.services.tracing.query import TraceQueryService


def test_span_metadata_allowlist_preserves_safe_response_summary_fields():
    metadata = TraceMetadataSanitizer.sanitize_span_metadata(
        "httpRequestNode",
        {
            "http": {
                "method": "POST",
                "content_type": "application/json",
                "response_size": 123,
                "response": {"body": "raw response"},
                "authorization": "Bearer token",
            }
        },
    )

    assert metadata["http"]["method"] == "POST"
    assert metadata["http"]["content_type"] == "application/json"
    assert metadata["http"]["response_size"] == 123
    assert "response" not in metadata["http"]
    assert "authorization" not in metadata["http"]


def test_run_metadata_is_sanitized_by_scope():
    metadata = TraceMetadataSanitizer.sanitize_run_metadata(
        {
            "gateway": {
                "method": "POST",
                "path": "/v1/workflows/run",
                "status_code": 202,
                "latency_ms": 42,
                "content_type": "application/json",
                "body": {"prompt": "raw"},
            },
            "retention": {
                "purged_at": "2026-06-25T00:00:00+00:00",
                "action": "summarize",
                "content": "raw",
            },
            "auth": {
                "authenticated": True,
                "authorization": "Bearer token",
            },
            "prompt": "raw prompt",
        }
    )

    assert metadata["gateway"]["content_type"] == "application/json"
    assert metadata["gateway"]["status_code"] == 202
    assert "body" not in metadata["gateway"]
    assert metadata["retention"] == {
        "purged_at": "2026-06-25T00:00:00+00:00",
        "action": "summarize",
    }
    assert metadata["auth"] == {"authenticated": True}
    assert "prompt" not in metadata


def test_rag_metadata_drops_scalar_retrieval_results():
    metadata = TraceMetadataSanitizer.sanitize_span_metadata(
        "llmNode",
        {
            "rag": {
                "retrieval_results": "raw chunk text",
                "retrieved_context_payload_id": "payload-1",
            }
        },
    )

    assert metadata["rag"] == {"retrieved_context_payload_id": "payload-1"}


def test_trace_detail_metadata_view_hides_error_message_and_sanitizes_metadata():
    run = SimpleNamespace(
        id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        deployment_id=None,
        status="failed",
        trigger_mode="api",
        started_at=None,
        finished_at=None,
        duration=None,
        total_tokens=0,
        total_cost=0,
        redaction_applied=True,
        pii_detected=False,
        payload_storage_mode="redacted_only",
        inputs={},
        outputs={},
        error_message="redacted compatibility error",
        trace_metadata={
            "gateway": {
                "status_code": 500,
                "response": {"body": "raw response"},
            }
        },
    )

    detail = TraceQueryService.trace_detail(run, view_level="metadata")

    assert detail["error_message"] is None
    assert detail["trace_metadata"] == {"gateway": {"status_code": 500}}
