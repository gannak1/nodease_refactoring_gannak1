from __future__ import annotations

import logging

from apps.gateway.application.agent_builder.intent_cache_coordinator import (
    IntentCacheDiagnostic,
)
from apps.gateway.application.agent_builder.intent_cache_observability import (
    IntentCacheObservability,
)


def _diagnostic(*, outcome: str = "hit", reason: str | None = None) -> IntentCacheDiagnostic:
    return IntentCacheDiagnostic(
        outcome=outcome,  # type: ignore[arg-type]
        reason=reason,
        single_flight_role="none",
        latency_ms=12,
        cache_schema_version=1,
        normalizer_version="intent-normalizer-v1",
        planner_contract_version="agent-builder-intent-v1",
        catalog_version=3,
        canonical_text_registry_version="intent-text-v1",
        materializer_version="agent-builder-direct-edit-v1",
    )


def test_observability_records_allowlisted_outcome_reason_and_contract_version():
    IntentCacheObservability.reset_local_counters()

    IntentCacheObservability.record(_diagnostic(outcome="error", reason="cold_rehydration_failed"))

    assert (
        IntentCacheObservability.get_local_counter(
            outcome="error",
            reason="cold_rehydration_failed",
            single_flight_role="none",
            contract_version="cache-1|normalizer-intent-normalizer-v1|planner-agent-builder-intent-v1|catalog-3|registry-intent-text-v1|materializer-agent-builder-direct-edit-v1",
        )
        == 1
    )


def test_observability_rejects_untrusted_labels_without_recording_them():
    IntentCacheObservability.reset_local_counters()

    IntentCacheObservability.record(_diagnostic(reason="provider raw payload"))

    assert (
        IntentCacheObservability.get_local_counter(
            outcome="hit",
            reason="unknown",
            single_flight_role="none",
            contract_version="cache-1|normalizer-intent-normalizer-v1|planner-agent-builder-intent-v1|catalog-3|registry-intent-text-v1|materializer-agent-builder-direct-edit-v1",
        )
        == 1
    )

def test_observability_log_includes_only_safe_cache_diagnostic_labels(caplog):
    with caplog.at_level(
        logging.INFO,
        logger="apps.gateway.application.agent_builder.intent_cache_observability",
    ):
        IntentCacheObservability.record(
            _diagnostic(outcome="miss", reason="not_found")
        )

    assert "outcome=miss reason=not_found role=none" in caplog.messages[-1]