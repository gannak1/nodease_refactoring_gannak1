import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

SENSITIVE_METADATA_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "body",
    "chunk",
    "completion",
    "content",
    "cookie",
    "credential",
    "credentials",
    "filename",
    "headers",
    "input",
    "inputs",
    "message",
    "messages",
    "output",
    "outputs",
    "password",
    "prompt",
    "query",
    "raw",
    "raw_source_path",
    "raw_source_title",
    "raw_source_url",
    "refresh_token",
    "request",
    "response",
    "secret",
    "set_cookie",
    "source_acl",
    "source_path",
    "source_principal",
    "source_title",
    "source_url",
    "text",
    "token",
    "url",
}

SENSITIVE_METADATA_PATTERNS = (
    "access_token",
    "api_key",
    "authorization",
    "bearer",
    "body",
    "chunk",
    "completion",
    "content",
    "cookie",
    "credential",
    "header",
    "input",
    "message",
    "output",
    "password",
    "prompt",
    "query",
    "raw",
    "raw_source_path",
    "raw_source_title",
    "raw_source_url",
    "refresh_token",
    "request",
    "response",
    "secret",
    "source_acl",
    "source_path",
    "source_principal",
    "source_title",
    "source_url",
    "token",
)

RUN_SCALAR_FIELDS = {
    "correlation_id",
    "request_id",
    "trace_id",
    "workflow_task_id",
}
RUN_SECTION_FIELDS = {
    "auth": {
        "authenticated",
        "latency_ms",
        "principal_type",
        "status",
    },
    "celery": {
        "enqueue_latency_ms",
        "queue",
        "status",
        "task_id",
    },
    "deployment": {
        "deployment_id",
        "lookup_latency_ms",
        "status",
        "workflow_version",
    },
}

RETENTION_FIELDS = {
    "action",
    "dry_run",
    "purged",
    "purged_at",
    "scope_id",
    "scope_type",
}

GATEWAY_FIELDS = {
    "auth_latency_ms",
    "celery_enqueue_latency_ms",
    "client_ip",
    "content_type",
    "deployment_lookup_latency_ms",
    "latency_ms",
    "method",
    "path",
    "request_id",
    "route",
    "status_code",
    "trace_id",
    "user_agent_family",
}

COMMON_SPAN_FIELDS = {
    "error",
    "external_effect_output",
    "latency_ms",
}
SPAN_TOP_LEVEL_BY_NODE_TYPE = {
    "llmNode": {"llm", "rag"},
    "httpRequestNode": {"http", "external_effect"},
    "slackPostNode": {"http", "slack", "external_effect"},
    "githubNode": {"http", "external_effect"},
    "codeNode": {"sandbox"},
    "workflowNode": {"workflow"},
}
SPAN_SECTION_FIELDS = {
    "error": {
        "error_code",
        "error_type",
        "type",
    },
    "external_effect": {
        "error_code",
        "operation",
        "outcome",
        "provider",
        "replay_decision",
    },
    "external_effect_output": {"sensitive"},
    "guardrail": {
        "blocked",
        "decision",
        "latency_ms",
        "policy_id",
        "reason_code",
        "reason_payload_id",
        "reason_redacted",
        "rule_id",
        "severity",
        "type",
    },
    "http": {
        "content_type",
        "host",
        "latency_ms",
        "method",
        "path",
        "request_payload_id",
        "request_size",
        "response_payload_id",
        "response_size",
        "retry_count",
        "status_code",
    },
    "llm": {
        "completion_payload_id",
        "completion_tokens",
        "credential_id",
        "confidence",
        "fallback_model",
        "recommended_fallback_model",
        "recommended_model",
        "recommendation_type",
        "analysis_stage",
        "customer_facing",
        "decision_source",
        "downstream_status",
        "fallback_used",
        "finish_reason",
        "has_file_input",
        "input_length_bucket",
        "judge_called",
        "knowledge_enabled",
        "latency_ms",
        "cohort_matcher",
        "matched_rule_id",
        "matched_cohort_id",
        "model",
        "node_task",
        "output_format",
        "policy_id",
        "prompt_payload_id",
        "prompt_tokens",
        "prompt_length_bucket",
        "provider",
        "reason",
        "reason_code",
        "repetition_rate",
        "retry_count",
        "routing_stage",
        "schema_required",
        "schema_status",
        "selected_model",
        "semantic_encoder_model",
        "semantic_candidate_cohort_id",
        "semantic_candidate_label",
        "semantic_cohort_scores",
        "semantic_decision_source",
        "semantic_lexical_score",
        "semantic_lexical_signal_count",
        "semantic_margin",
        "semantic_match_status",
        "semantic_min_margin",
        "semantic_route_label",
        "semantic_runner_up_score",
        "semantic_similarity",
        "semantic_safety_override",
        "semantic_threshold",
        "route_catalog_version",
        "policy_version",
        "total_cost",
        "total_tokens",
    },
    "rag": {
        "citation_ids",
        "context_token_estimate",
        "document_ids",
        "evidence_sufficient",
        "fanout_concurrency",
        "fanout_timeout_seconds",
        "failed_candidate_count_bucket",
        "failure_policy",
        "hierarchy_fallback",
        "insufficiency_reason",
        "knowledge_base_id",
        "authorized_kb_count",
        "authorized_kb_count_bucket",
        "permission_filter_applied",
        "latency_ms",
        "partial_result",
        "query_rewrite_applied",
        "query_rewrite_strategy",
        "raw_content_returned",
        "rag_mode",
        "retrieval_payload_id",
        "retrieval_strategy",
        "retrieved_chunk_summary_truncated",
        "retrieved_context_payload_id",
        "retrieved_chunk_count",
        "safe_exclusion_summary",
        "score_summary",
        "selected_kb_count",
        "selected_kb_count_bucket",
        "source_tier_policy",
        "source_tier_used",
        "stored_result_count",
    },
    "slack": {
        "delivery_mode",
        "delivery_status",
        "has_message_ref",
        "latency_ms",
        "provider_reason",
        "provider_retryable",
        "request_size",
        "response_size",
        "retry_after_seconds",
        "status_code",
    },
    "sandbox": {
        "execution_time_ms",
        "exit_code",
        "latency_ms",
        "stderr_payload_id",
        "stdout_payload_id",
        "timeout",
    },
    "workflow": {
        "latency_ms",
    },
}
RAG_RESULT_FIELDS = {
    "document_id",
    "chunk_id",
    "parent_chunk_id",
    "rank",
    "evidence_rank",
    "knowledge_base_id",
    "metadata_summary",
    "hierarchy_path",
    "hierarchy_fallback",
    "page_number",
    "similarity_score",
    "score",
    "token_count",
}


class TraceMetadataSanitizer:
    """Tracing metadata를 scope별 allowlist로 제한하는 공용 경계."""

    @staticmethod
    def sanitize_json_safe(value: Any) -> Any:
        """JSONB 저장과 응답 직렬화가 가능한 값으로 정규화합니다."""
        if isinstance(value, dict):
            return {
                str(key): TraceMetadataSanitizer.sanitize_json_safe(child)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [TraceMetadataSanitizer.sanitize_json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [TraceMetadataSanitizer.sanitize_json_safe(item) for item in value]
        if isinstance(value, set):
            return [TraceMetadataSanitizer.sanitize_json_safe(item) for item in value]
        if hasattr(value, "model_dump"):
            return TraceMetadataSanitizer.sanitize_json_safe(value.model_dump())
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        return value

    @staticmethod
    def is_sensitive_metadata_key(key: Any) -> bool:
        """allowlist 밖의 임의 키가 원문성/비밀값 성격인지 판별합니다."""
        normalized = str(key).strip().lower().replace("-", "_")
        if normalized in SENSITIVE_METADATA_KEYS:
            return True
        return any(pattern in normalized for pattern in SENSITIVE_METADATA_PATTERNS)

    @classmethod
    def sanitize_retention_metadata(cls, metadata: Any) -> dict[str, Any]:
        return cls._filter_allowed_dict(metadata, RETENTION_FIELDS)

    @classmethod
    def sanitize_gateway_metadata(cls, metadata: Any) -> dict[str, Any]:
        return cls._filter_allowed_dict(metadata, GATEWAY_FIELDS)

    @classmethod
    def sanitize_run_metadata(cls, metadata: Any) -> dict[str, Any]:
        safe_metadata = cls.sanitize_json_safe(metadata)
        if not isinstance(safe_metadata, dict):
            return {}

        sanitized: dict[str, Any] = {}
        for key in RUN_SCALAR_FIELDS:
            if key in safe_metadata:
                sanitized[key] = cls._sanitize_allowed_value(safe_metadata[key])

        if "gateway" in safe_metadata:
            gateway = cls.sanitize_gateway_metadata(safe_metadata["gateway"])
            if gateway:
                sanitized["gateway"] = gateway
        if "retention" in safe_metadata:
            retention = cls.sanitize_retention_metadata(safe_metadata["retention"])
            if retention:
                sanitized["retention"] = retention

        for section, allowed_fields in RUN_SECTION_FIELDS.items():
            if section not in safe_metadata:
                continue
            section_value = cls._filter_allowed_dict(
                safe_metadata[section], allowed_fields
            )
            if section_value:
                sanitized[section] = section_value

        return sanitized

    @classmethod
    def sanitize_span_metadata(cls, node_type: str | None, metadata: Any) -> dict[str, Any]:
        safe_metadata = cls.sanitize_json_safe(metadata)
        if not isinstance(safe_metadata, dict):
            return {}

        node_type_key = str(node_type or "")
        allowed_top_level = set(COMMON_SPAN_FIELDS)
        allowed_top_level.update(SPAN_TOP_LEVEL_BY_NODE_TYPE.get(node_type_key, set()))
        if "guardrail" in node_type_key.lower():
            allowed_top_level.add("guardrail")

        sanitized: dict[str, Any] = {}
        for key in allowed_top_level:
            if key not in safe_metadata:
                continue
            if key == "latency_ms":
                sanitized[key] = cls._sanitize_allowed_value(safe_metadata[key])
                continue
            if key == "rag":
                rag = cls._sanitize_rag_section(safe_metadata[key])
                if rag:
                    sanitized[key] = rag
                continue
            section_value = cls._filter_allowed_dict(
                safe_metadata[key], SPAN_SECTION_FIELDS.get(key, set())
            )
            if section_value:
                sanitized[key] = section_value

        return sanitized

    @classmethod
    def sanitize_rag_metadata(cls, value: Any) -> Any:
        safe_value = cls.sanitize_json_safe(value)
        if isinstance(safe_value, list):
            return [
                item
                for item in (cls.sanitize_rag_metadata(child) for child in safe_value)
                if item
            ]
        if isinstance(safe_value, dict):
            filtered = cls._filter_allowed_dict(safe_value, RAG_RESULT_FIELDS)
            evidence_rank = filtered.get("evidence_rank")
            if evidence_rank is not None and (
                isinstance(evidence_rank, bool)
                or not isinstance(evidence_rank, int)
                or evidence_rank < 1
            ):
                filtered.pop("evidence_rank", None)
            return filtered
        return None

    @classmethod
    def summarize_rag_metadata(cls, value: Any) -> dict[str, Any]:
        """Per-chunk evidence에서 run/node trace에 둘 수 있는 요약만 만든다."""
        safe_results = cls.sanitize_rag_metadata(value)
        if isinstance(safe_results, dict):
            results = [safe_results]
        elif isinstance(safe_results, list):
            results = [item for item in safe_results if isinstance(item, dict)]
        else:
            results = []
        if not results:
            return {}

        document_ids: list[Any] = []
        citation_ids: list[Any] = []
        knowledge_base_ids: list[Any] = []
        scores: list[float] = []
        hierarchy_fallback = False

        for item in results:
            document_id = item.get("document_id")
            if document_id is not None:
                document_ids.append(document_id)
            chunk_id = item.get("chunk_id")
            if chunk_id is not None:
                citation_ids.append(chunk_id)
            knowledge_base_id = item.get("knowledge_base_id")
            if knowledge_base_id is not None:
                knowledge_base_ids.append(knowledge_base_id)
            raw_score = item.get("score", item.get("similarity_score"))
            try:
                if raw_score is not None:
                    scores.append(float(raw_score))
            except (TypeError, ValueError):
                pass
            hierarchy_fallback = hierarchy_fallback or bool(item.get("hierarchy_fallback"))

        summary: dict[str, Any] = {
            "retrieved_chunk_count": len(results),
            "raw_content_returned": False,
        }
        unique_kb_ids = cls._unique_preserving_order(knowledge_base_ids)
        if len(unique_kb_ids) == 1:
            summary["knowledge_base_id"] = unique_kb_ids[0]
        if document_ids:
            summary["document_ids"] = cls._unique_preserving_order(document_ids)
        if citation_ids:
            summary["citation_ids"] = cls._unique_preserving_order(citation_ids)
        if scores:
            summary["score_summary"] = {
                "min": min(scores),
                "max": max(scores),
            }
        if hierarchy_fallback:
            summary["hierarchy_fallback"] = True
        return summary

    @classmethod
    def _sanitize_rag_section(cls, value: Any) -> dict[str, Any]:
        safe_value = cls.sanitize_json_safe(value)
        if not isinstance(safe_value, dict):
            return {}

        sanitized: dict[str, Any] = {}
        for key in SPAN_SECTION_FIELDS["rag"]:
            if key in safe_value:
                sanitized_value = cls._sanitize_allowed_value(safe_value[key])
                if sanitized_value is not None:
                    sanitized[key] = sanitized_value
        if "retrieval_results" in safe_value:
            summary = cls.summarize_rag_metadata(safe_value["retrieval_results"])
            sanitized.update({key: value for key, value in summary.items() if value is not None})
        return sanitized

    @classmethod
    def _filter_allowed_dict(cls, value: Any, allowed_keys: set[str]) -> dict[str, Any]:
        safe_value = cls.sanitize_json_safe(value)
        if not isinstance(safe_value, dict):
            return {}

        sanitized: dict[str, Any] = {}
        for key in allowed_keys:
            if key not in safe_value:
                continue
            sanitized_value = cls._sanitize_allowed_value(safe_value[key])
            if sanitized_value is not None:
                sanitized[key] = sanitized_value
        return sanitized

    @classmethod
    def _sanitize_allowed_value(cls, value: Any) -> Any:
        safe_value = cls.sanitize_json_safe(value)
        if isinstance(safe_value, dict):
            sanitized: dict[str, Any] = {}
            for key, child in safe_value.items():
                # exact allowlist 이후에만 임의 하위 키 패턴 denylist를 적용합니다.
                if cls.is_sensitive_metadata_key(key):
                    continue
                sanitized_child = cls._sanitize_allowed_value(child)
                if sanitized_child is not None:
                    sanitized[key] = sanitized_child
            return sanitized
        if isinstance(safe_value, list):
            sanitized_items = []
            for item in safe_value:
                sanitized_item = cls._sanitize_allowed_value(item)
                if sanitized_item is not None:
                    sanitized_items.append(sanitized_item)
            return sanitized_items
        return safe_value

    @staticmethod
    def _unique_preserving_order(values: list[Any]) -> list[Any]:
        unique: list[Any] = []
        seen: set[str] = set()
        for value in values:
            key = str(value)
            if key in seen:
                continue
            seen.add(key)
            unique.append(value)
        return unique
