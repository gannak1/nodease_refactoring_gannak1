import logging
from collections import Counter
from typing import Any, ClassVar, Optional

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter as PrometheusCounter
except Exception:
    PrometheusCounter = None

try:
    RAW_PAYLOAD_DECRYPT_FAILURES = (
        PrometheusCounter(
            "tracing_raw_payload_decrypt_failures_total",
            "Raw trace payload decryption failure count.",
            ["payload_kind", "scope"],
        )
        if PrometheusCounter
        else None
    )
except ValueError:
    RAW_PAYLOAD_DECRYPT_FAILURES = None


class TraceObservabilityService:
    """추적 전용 서버 로그와 메트릭을 기록하는 얇은 경계."""

    _local_counters: ClassVar[Counter[tuple[str, str, str]]] = Counter()

    @classmethod
    def record_raw_payload_decryption_failed(
        cls, payload: Any, error: Optional[Exception] = None
    ) -> None:
        payload_kind = str(getattr(payload, "payload_kind", "unknown") or "unknown")
        scope = str(getattr(payload, "scope", "unknown") or "unknown")
        cls._local_counters[
            ("raw_payload_decryption_failed", payload_kind, scope)
        ] += 1

        if RAW_PAYLOAD_DECRYPT_FAILURES is not None:
            RAW_PAYLOAD_DECRYPT_FAILURES.labels(
                payload_kind=payload_kind,
                scope=scope,
            ).inc()

        logger.error(
            "tracing.raw_payload_decryption_failed",
            extra={
                "event": "tracing.raw_payload_decryption_failed",
                "trace_id": cls._safe_str(getattr(payload, "workflow_run_id", None)),
                "span_id": cls._safe_str(
                    getattr(payload, "workflow_node_run_id", None)
                ),
                "payload_id": cls._safe_str(getattr(payload, "id", None)),
                "payload_kind": payload_kind,
                "scope": scope,
                "storage_mode": cls._safe_str(getattr(payload, "storage_mode", None)),
                "error_type": type(error).__name__ if error else "unknown",
            },
        )

    @classmethod
    def get_local_counter(cls, name: str, payload_kind: str, scope: str) -> int:
        return cls._local_counters[(name, payload_kind, scope)]

    @classmethod
    def reset_local_counters(cls) -> None:
        cls._local_counters.clear()

    @staticmethod
    def _safe_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value)
