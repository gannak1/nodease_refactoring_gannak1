import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from apps.shared.schemas.tracing import TraceDetailSchema, TraceSummarySchema
from apps.shared.services.tracing.metadata import TraceMetadataSanitizer
from apps.shared.services.tracing.query import TraceQueryService


def _trace_schema_values(*, user_id):
    return {
        "id": uuid.uuid4(),
        "workflow_id": uuid.uuid4(),
        "app_id": uuid.uuid4(),
        "user_id": user_id,
        "deployment_id": uuid.uuid4(),
        "status": "success",
        "trigger_mode": "scheduler",
        "started_at": datetime.now(timezone.utc),
    }


def test_trace_summary_and_detail_allow_null_system_schedule_actor():
    values = _trace_schema_values(user_id=None)

    summary = TraceSummarySchema.model_validate(values)
    detail = TraceDetailSchema.model_validate(values)

    assert summary.user_id is None
    assert detail.user_id is None


def test_trace_summary_preserves_interactive_user_actor():
    user_id = uuid.uuid4()

    summary = TraceSummarySchema.model_validate(
        _trace_schema_values(user_id=user_id)
    )

    assert summary.user_id == user_id


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


def test_llm_span_metadata_preserves_model_routing_summary_only():
    metadata = TraceMetadataSanitizer.sanitize_span_metadata(
        "llmNode",
        {
            "llm": {
                "recommendation_type": "user_click_model_routing",
                "analysis_stage": "optimized",
                "recommended_model": "gpt-4.1-mini",
                "recommended_fallback_model": "gpt-4.1",
                "reason": "최근 운영 로그의 품질 gate를 통과했습니다.",
                "policy_version": "model-router-v1",
                "confidence": 0.9,
                "raw_prompt": "secret prompt",
                "api_key": "sk-secret",
            }
        },
    )

    assert metadata["llm"] == {
        "recommendation_type": "user_click_model_routing",
        "analysis_stage": "optimized",
        "recommended_model": "gpt-4.1-mini",
        "recommended_fallback_model": "gpt-4.1",
        "reason": "최근 운영 로그의 품질 gate를 통과했습니다.",
        "policy_version": "model-router-v1",
        "confidence": 0.9,
    }


def test_llm_span_metadata_preserves_safe_runtime_policy_outcome_fields():
    metadata = TraceMetadataSanitizer.sanitize_span_metadata(
        "llmNode",
        {
            "llm": {
                "finish_reason": "stop",
                "schema_status": "passed",
                "repetition_rate": 0.125,
                "downstream_status": "passed",
                "fallback_used": True,
                "policy_id": "policy-1",
                "matched_rule_id": "short-json",
                "decision_source": "active_policy",
                "reason_code": "quality_gate_passed",
                "judge_called": False,
                "input_length_bucket": "short",
                "prompt_length_bucket": "medium",
                "output_format": "json",
                "schema_required": True,
                "knowledge_enabled": False,
                "raw_input": "secret input",
            }
        },
    )

    assert metadata["llm"]["fallback_used"] is True
    assert metadata["llm"]["finish_reason"] == "stop"
    assert metadata["llm"]["repetition_rate"] == 0.125
    assert metadata["llm"]["input_length_bucket"] == "short"
    assert "raw_input" not in metadata["llm"]


def test_rag_metadata_preserves_payload_reference_and_summarizes_evidence():
    metadata = TraceMetadataSanitizer.sanitize_span_metadata(
        "llmNode",
        {
            "rag": {
                "retrieval_payload_id": "payload-2",
                "retrieval_results": [
                    {
                        "knowledge_base_id": "kb-1",
                        "chunk_id": "chunk-1",
                        "parent_chunk_id": "parent-1",
                        "document_id": "doc-1",
                        "filename": "sensitive-title.pdf",
                        "rank": 1,
                        "similarity_score": 0.9,
                        "score": 0.91,
                        "token_count": 210,
                        "metadata_summary": {
                            "classification": "internal",
                            "source_path": "/private/source/path",
                            "raw_source_url": "https://internal.example/private",
                        },
                        "hierarchy_fallback": True,
                        "content": "raw chunk text",
                    }
                ],
            }
        },
    )

    assert metadata["rag"]["retrieval_payload_id"] == "payload-2"
    assert metadata["rag"]["knowledge_base_id"] == "kb-1"
    assert metadata["rag"]["retrieved_chunk_count"] == 1
    assert metadata["rag"]["document_ids"] == ["doc-1"]
    assert metadata["rag"]["citation_ids"] == ["chunk-1"]
    assert metadata["rag"]["score_summary"] == {"min": 0.91, "max": 0.91}
    assert metadata["rag"]["hierarchy_fallback"] is True
    assert metadata["rag"]["raw_content_returned"] is False
    assert "retrieval_results" not in metadata["rag"]
    assert "raw chunk text" not in str(metadata)
    assert "sensitive-title.pdf" not in str(metadata)
    assert "internal.example" not in str(metadata)
    assert "/private/source/path" not in str(metadata)


def test_rag_span_metadata_preserves_evidence_summary_fields_only():
    metadata = TraceMetadataSanitizer.sanitize_span_metadata(
        "llmNode",
        {
            "rag": {
                "evidence_sufficient": False,
                "insufficiency_reason": "minimum_score_not_met",
                "source_tier_used": "company_policy",
                "partial_result": True,
                "failed_candidate_count_bucket": "2-10",
                "failure_policy": "safe_no_result",
                "stored_result_count": 20,
                "retrieved_chunk_summary_truncated": True,
                "retrieval_strategy": "permission_scoped_hierarchical_hybrid",
                "rag_mode": "explicit_kb",
                "authorized_kb_count": 2,
                "authorized_kb_count_bucket": "2-10",
                "selected_kb_count": 1,
                "selected_kb_count_bucket": "1",
                "retrieved_chunk_count": 3,
                "context_token_estimate": 123,
                "permission_filter_applied": True,
                "safe_exclusion_summary": {
                    "operational_failure_count_bucket": "1"
                },
                "query_rewrite_applied": False,
                "query_rewrite_strategy": "off",
                "source_tier_policy": "tie_break",
                "hidden_candidate_ids": ["kb-hidden"],
                "raw_rewritten_query": "raw query",
            }
        },
    )

    assert metadata["rag"]["evidence_sufficient"] is False
    assert metadata["rag"]["insufficiency_reason"] == "minimum_score_not_met"
    assert metadata["rag"]["source_tier_used"] == "company_policy"
    assert metadata["rag"]["partial_result"] is True
    assert metadata["rag"]["failed_candidate_count_bucket"] == "2-10"
    assert metadata["rag"]["failure_policy"] == "safe_no_result"
    assert metadata["rag"]["stored_result_count"] == 20
    assert metadata["rag"]["retrieved_chunk_summary_truncated"] is True
    assert (
        metadata["rag"]["retrieval_strategy"]
        == "permission_scoped_hierarchical_hybrid"
    )
    assert metadata["rag"]["rag_mode"] == "explicit_kb"
    assert metadata["rag"]["authorized_kb_count"] == 2
    assert metadata["rag"]["authorized_kb_count_bucket"] == "2-10"
    assert metadata["rag"]["selected_kb_count"] == 1
    assert metadata["rag"]["selected_kb_count_bucket"] == "1"
    assert metadata["rag"]["retrieved_chunk_count"] == 3
    assert metadata["rag"]["context_token_estimate"] == 123
    assert metadata["rag"]["permission_filter_applied"] is True
    assert metadata["rag"]["safe_exclusion_summary"] == {
        "operational_failure_count_bucket": "1"
    }
    assert metadata["rag"]["query_rewrite_applied"] is False
    assert metadata["rag"]["query_rewrite_strategy"] == "off"
    assert metadata["rag"]["source_tier_policy"] == "tie_break"
    assert "hidden_candidate_ids" not in metadata["rag"]
    assert "raw_rewritten_query" not in metadata["rag"]


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
