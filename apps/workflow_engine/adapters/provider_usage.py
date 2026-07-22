"""PostgreSQL adapter for the current Workflow LLM usage projection."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from apps.shared.services.llm_model_pricing import (
    calculate_text_token_cost_from_rates,
)
from apps.workflow_engine.application.provider_usage import ProviderUsageRecord
from apps.workflow_engine.services.llm_service import LLMService


class PostgresProviderUsageRecorder:
    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def record(self, request: ProviderUsageRecord) -> float:
        db = self._session_factory()
        try:
            attribution = request.attribution
            prompt_tokens = int(request.usage.get("prompt_tokens") or 0)
            completion_tokens = int(request.usage.get("completion_tokens") or 0)
            canonical_model = (
                {"model_db_id": attribution.model_db_id}
                if attribution.model_db_id is not None
                else {}
            )
            if attribution.capability_id is not None:
                snapshot = attribution.pricing_snapshot
                if snapshot is None:
                    raise ValueError("capability pricing snapshot is required")
                cost = calculate_text_token_cost_from_rates(
                    input_price_per_1k=snapshot.input_price_per_1k,
                    output_price_per_1k=snapshot.output_price_per_1k,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            else:
                cost = LLMService.calculate_cost(
                    db,
                    attribution.model_id,
                    prompt_tokens,
                    completion_tokens,
                    usage=request.usage,
                    allow_catalog_fallback=True,
                    **canonical_model,
                )
            LLMService.log_usage(
                db=db,
                user_id=attribution.credential_principal_user_id,
                model_id=attribution.model_id,
                usage=dict(request.usage),
                cost=cost,
                organization_id=attribution.organization_id,
                workflow_id=request.workflow_id,
                workflow_run_id=request.workflow_run_id,
                node_id=request.node_id,
                credential_id=attribution.credential_id,
                cost_optimizer_candidate_id=request.cost_optimizer_candidate_id,
                **canonical_model,
            )
            return cost
        finally:
            db.close()


__all__ = ["PostgresProviderUsageRecorder"]
