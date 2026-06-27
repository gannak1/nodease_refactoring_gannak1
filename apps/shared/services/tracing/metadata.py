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
    "refresh_token",
    "request",
    "response",
    "secret",
    "set_cookie",
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
    "refresh_token",
    "request",
    "response",
    "secret",
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
    "latency_ms",
}
SPAN_TOP_LEVEL_BY_NODE_TYPE = {
    "llmNode": {"llm", "rag"},
    "httpRequestNode": {"http"},
    "slackPostNode": {"http"},
    "codeNode": {"sandbox"},
    "workflowNode": {"workflow"},
}
SPAN_SECTION_FIELDS = {
    "error": {
        "error_code",
        "error_type",
        "type",
    },
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
        "latency_ms",
        "model",
        "prompt_payload_id",
        "prompt_tokens",
        "provider",
        "retry_count",
        "total_cost",
        "total_tokens",
    },
    "rag": {
        "latency_ms",
        "retrieval_results",
        "retrieved_context_payload_id",
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
    "filename",
    "knowledge_base_id",
    "page_number",
    "similarity_score",
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
            return cls._filter_allowed_dict(safe_value, RAG_RESULT_FIELDS)
        return None

    @classmethod
    def _sanitize_rag_section(cls, value: Any) -> dict[str, Any]:
        safe_value = cls.sanitize_json_safe(value)
        if not isinstance(safe_value, dict):
            return {}

        sanitized: dict[str, Any] = {}
        if "latency_ms" in safe_value:
            sanitized["latency_ms"] = cls._sanitize_allowed_value(
                safe_value["latency_ms"]
            )
        if "retrieved_context_payload_id" in safe_value:
            sanitized["retrieved_context_payload_id"] = cls._sanitize_allowed_value(
                safe_value["retrieved_context_payload_id"]
            )
        if "retrieval_results" in safe_value:
            retrieval_results = cls.sanitize_rag_metadata(
                safe_value["retrieval_results"]
            )
            if retrieval_results:
                sanitized["retrieval_results"] = retrieval_results
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
