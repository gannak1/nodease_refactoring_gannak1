"""Process-lifetime Agent Builder intent-cache composition and cleanup."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import FastAPI

from apps.gateway.adapters.cache.agent_builder_intent_plan import (
    RedisIntentPlanCacheAdapter,
)
from apps.gateway.application.agent_builder.intent_cache import (
    DisabledIntentPlanCacheBoundary,
    IntentPlanCacheBoundary,
)
from apps.gateway.application.agent_builder.intent_cache_coordinator import (
    AgentBuilderIntentCacheCoordinator,
    IntentCacheDiagnostic,
)
from apps.gateway.application.agent_builder.intent_cache_observability import (
    IntentCacheObservability,
)
from apps.gateway.application.agent_builder.intent_normalization import (
    DeterministicIntentNormalizer,
)
from apps.gateway.core.config import settings
from apps.gateway.services.agent_builder.intent_cache_integration import (
    current_rehydrator_for,
    project_structured_intent_plan,
)
from apps.gateway.services.agent_builder.intent_cache_knowledge import (
    current_knowledge_context_fingerprint,
)


logger = logging.getLogger(__name__)
_STATE_ATTRIBUTE = "agent_builder_intent_cache_application"


def _record_intent_cache_diagnostic(diagnostic: IntentCacheDiagnostic) -> None:
    IntentCacheObservability.record(diagnostic)


@dataclass
class AgentBuilderIntentCacheApplication:
    """Owns the optional Redis adapter for one Gateway process lifetime."""

    cache: IntentPlanCacheBoundary
    owned_adapter: RedisIntentPlanCacheAdapter | None = None

    def close(self) -> None:
        adapter = self.owned_adapter
        self.owned_adapter = None
        if adapter is None:
            return
        try:
            adapter.close()
        except Exception as exc:
            logger.error(
                "Agent Builder intent cache Redis shutdown failed: error_type=%s",
                type(exc).__name__,
            )


def initialize_agent_builder_intent_cache_application(
    app: FastAPI,
) -> AgentBuilderIntentCacheApplication:
    """Initialize one cache boundary per app, after Gateway startup succeeds."""
    existing = getattr(app.state, _STATE_ATTRIBUTE, None)
    if isinstance(existing, AgentBuilderIntentCacheApplication):
        return existing

    config = settings.agent_builder_intent_cache_config()
    if not config.enabled:
        logger.debug(
            "agent_builder.intent_cache_disabled reason=%s",
            config.disabled_reason or "unknown",
        )
        application = AgentBuilderIntentCacheApplication(
            cache=DisabledIntentPlanCacheBoundary()
        )
    else:
        application = _enabled_application(config)

    setattr(app.state, _STATE_ATTRIBUTE, application)
    return application


def intent_plan_cache_for_app(app: FastAPI) -> IntentPlanCacheBoundary:
    """Return the app-owned boundary, preserving Planner behavior before startup."""
    application = getattr(app.state, _STATE_ATTRIBUTE, None)
    if isinstance(application, AgentBuilderIntentCacheApplication):
        return application.cache
    return DisabledIntentPlanCacheBoundary()


def shutdown_agent_builder_intent_cache_application(app: FastAPI) -> None:
    """Close the app-owned Redis pool exactly once during Gateway shutdown."""
    application = getattr(app.state, _STATE_ATTRIBUTE, None)
    if not isinstance(application, AgentBuilderIntentCacheApplication):
        return
    delattr(app.state, _STATE_ATTRIBUTE)
    application.close()


def _enabled_application(config) -> AgentBuilderIntentCacheApplication:
    try:
        adapter = RedisIntentPlanCacheAdapter.from_url(
            config.redis_url or "",
            hmac_key=config.hmac_key or b"",
            hmac_key_version=config.hmac_key_version or "",
            ttl_seconds=config.ttl_seconds,
            max_payload_bytes=config.max_payload_bytes,
            operation_timeout_ms=config.operation_timeout_ms,
            lease_seconds=config.lease_seconds,
            follower_wait_ms=config.follower_wait_ms,
            max_follower_waiters=config.max_follower_waiters,
        )
        cache = AgentBuilderIntentCacheCoordinator(
            normalizer=DeterministicIntentNormalizer(),
            store=adapter,
            rehydrator_factory=current_rehydrator_for,
            plan_projector=project_structured_intent_plan,
            diagnostic_observer=_record_intent_cache_diagnostic,
            knowledge_context_fingerprint_factory=(
                lambda **kwargs: current_knowledge_context_fingerprint(
                    hmac_key=config.hmac_key or b"",
                    **kwargs,
                )
            ),
        )
        return AgentBuilderIntentCacheApplication(cache=cache, owned_adapter=adapter)
    except Exception:
        logger.info(
            "agent_builder.intent_cache_disabled reason=%s",
            "adapter_initialization_failed",
        )
        return AgentBuilderIntentCacheApplication(cache=DisabledIntentPlanCacheBoundary())


__all__ = [
    "AgentBuilderIntentCacheApplication",
    "initialize_agent_builder_intent_cache_application",
    "intent_plan_cache_for_app",
    "shutdown_agent_builder_intent_cache_application",
]
