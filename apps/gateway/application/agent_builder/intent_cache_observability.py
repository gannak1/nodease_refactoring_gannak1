from __future__ import annotations

import logging
from collections import Counter
from typing import ClassVar

from apps.gateway.application.agent_builder.intent_cache_coordinator import (
    IntentCacheDiagnostic,
)


logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter as PrometheusCounter
    from prometheus_client import Histogram as PrometheusHistogram
except Exception:
    PrometheusCounter = None
    PrometheusHistogram = None


try:
    INTENT_CACHE_EVENTS = (
        PrometheusCounter(
            "agent_builder_intent_cache_events_total",
            "Agent Builder Intent Plan cache outcomes.",
            ["outcome", "reason", "single_flight_role", "contract_version"],
        )
        if PrometheusCounter
        else None
    )
except ValueError:
    INTENT_CACHE_EVENTS = None

try:
    INTENT_CACHE_LATENCY_SECONDS = (
        PrometheusHistogram(
            "agent_builder_intent_cache_latency_seconds",
            "Agent Builder Intent Plan cache decision latency.",
            ["outcome", "reason", "single_flight_role", "contract_version"],
        )
        if PrometheusHistogram
        else None
    )
except ValueError:
    INTENT_CACHE_LATENCY_SECONDS = None


class IntentCacheObservability:
    """Record bounded cache metrics without cache keys, identities, or request data."""

    _OUTCOMES = frozenset({"hit", "miss", "bypass", "error"})
    _REASONS = frozenset(
        {
            "cache_unavailable",
            "cold_rehydration_failed",
            "invalid_cached_plan",
            "normalization_bypass",
            "not_found",
            "rehydration_failed",
            "request_canceled",
            "request_stale",
            "waiter_capacity_exceeded",
        }
    )
    _ROLES = frozenset({"none", "owner", "follower", "overflow"})
    _local_counters: ClassVar[Counter[tuple[str, str, str, str]]] = Counter()

    @classmethod
    def record(cls, diagnostic: IntentCacheDiagnostic) -> None:
        outcome = cls._safe_outcome(diagnostic.outcome)
        reason = cls._safe_reason(diagnostic.reason)
        role = cls._safe_role(diagnostic.single_flight_role)
        contract_version = cls._contract_version(diagnostic)
        labels = (outcome, reason, role, contract_version)
        cls._local_counters[labels] += 1
        if INTENT_CACHE_EVENTS is not None:
            INTENT_CACHE_EVENTS.labels(
                outcome=outcome,
                reason=reason,
                single_flight_role=role,
                contract_version=contract_version,
            ).inc()
        if INTENT_CACHE_LATENCY_SECONDS is not None:
            INTENT_CACHE_LATENCY_SECONDS.labels(
                outcome=outcome,
                reason=reason,
                single_flight_role=role,
                contract_version=contract_version,
            ).observe(max(0, diagnostic.latency_ms) / 1000)
        logger.info(
            "agent_builder.intent_cache outcome=%s reason=%s role=%s latency_ms=%s contract_version=%s",
            outcome,
            reason,
            role,
            max(0, diagnostic.latency_ms),
            contract_version,
            extra={
                "event": "agent_builder.intent_cache",
                "outcome": outcome,
                "reason": reason,
                "single_flight_role": role,
                "latency_ms": max(0, diagnostic.latency_ms),
                "contract_version": contract_version,
            },
        )

    @classmethod
    def get_local_counter(
        cls,
        *,
        outcome: str,
        reason: str,
        single_flight_role: str,
        contract_version: str,
    ) -> int:
        return cls._local_counters[(outcome, reason, single_flight_role, contract_version)]

    @classmethod
    def reset_local_counters(cls) -> None:
        cls._local_counters.clear()

    @classmethod
    def _safe_outcome(cls, value: str) -> str:
        return value if value in cls._OUTCOMES else "error"

    @classmethod
    def _safe_reason(cls, value: str | None) -> str:
        return value if value in cls._REASONS else "none" if value is None else "unknown"

    @classmethod
    def _safe_role(cls, value: str) -> str:
        return value if value in cls._ROLES else "none"

    @staticmethod
    def _contract_version(diagnostic: IntentCacheDiagnostic) -> str:
        def value(item: object) -> str:
            rendered = str(item) if item is not None else "unknown"
            return rendered if rendered.replace("-", "").replace("_", "").replace(".", "").isalnum() else "unknown"

        return "|".join(
            (
                f"cache-{value(diagnostic.cache_schema_version)}",
                f"normalizer-{value(diagnostic.normalizer_version)}",
                f"planner-{value(diagnostic.planner_contract_version)}",
                f"catalog-{value(diagnostic.catalog_version)}",
                f"registry-{value(diagnostic.canonical_text_registry_version)}",
                f"materializer-{value(diagnostic.materializer_version)}",
            )
        )
