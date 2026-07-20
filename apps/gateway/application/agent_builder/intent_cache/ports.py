from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CacheBoundaryDecision,
    CachedIntentPlanV1,
    IntentCacheKey,
    IntentNormalizationResult,
    IntentPlanLoadResult,
    IntentPlanSaveResult,
    IntentPlanningContext,
)
from apps.shared.schemas.agent_builder import AgentBuilderStructuredRequest


class _StrictPortResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
    )


class IntentRehydrationResult(_StrictPortResult):
    status: Literal["success", "failure"]
    structured_request: AgentBuilderStructuredRequest | None = None
    reason: Literal[
        "contract_version_mismatch",
        "catalog_member_missing",
        "canonical_reference_missing",
        "guidance_input_type_incompatible",
        "logical_reference_invalid",
        "summary_projection_failed",
        "current_context_invalid",
    ] | None = None

    @model_validator(mode="after")
    def validate_result(self):
        if self.status == "success":
            if self.structured_request is None or self.reason is not None:
                raise ValueError("invalid successful rehydration result")
        elif self.structured_request is not None or self.reason is None:
            raise ValueError("invalid failed rehydration result")
        return self


class IntentPlanExecution(_StrictPortResult):
    structured_request: AgentBuilderStructuredRequest
    decision: CacheBoundaryDecision


PlannerCall = Callable[[], AgentBuilderStructuredRequest]


@runtime_checkable
class IntentNormalizerPort(Protocol):
    def normalize(
        self,
        context: IntentPlanningContext,
    ) -> IntentNormalizationResult: ...


@runtime_checkable
class IntentPlanStorePort(Protocol):
    def load(self, key: IntentCacheKey) -> IntentPlanLoadResult: ...

    def save(
        self,
        key: IntentCacheKey,
        plan: CachedIntentPlanV1,
    ) -> IntentPlanSaveResult: ...


@runtime_checkable
class IntentPlanRehydratorPort(Protocol):
    def rehydrate(
        self,
        plan: CachedIntentPlanV1,
        context: IntentPlanningContext,
    ) -> IntentRehydrationResult: ...


@runtime_checkable
class IntentPlanCacheBoundary(Protocol):
    def execute(
        self,
        planner_call: PlannerCall,
        context: IntentPlanningContext | None = None,
    ) -> IntentPlanExecution: ...
