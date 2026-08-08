from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol, runtime_checkable

from pydantic import model_validator

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CacheBoundaryDecision,
    CachedIntentPlanV1,
    IntentCacheKey,
    IntentNormalizationResult,
    IntentPlanLoadResult,
    IntentPlanL2StoredReceipt,
    IntentPlanSaveResult,
    IntentPlanningContext,
    _StrictFrozenModel,
)
from apps.gateway.application.agent_builder.intent_semantic_cache import (
    SemanticCachePolicy,
    SemanticEmbedding,
    SemanticExternalCallBinding,
    SemanticExternalCallAdmissionResult,
    SemanticIntentPlanCandidate,
    SemanticQueryProjectionV1,
    SemanticVerificationResult,
)
from apps.shared.schemas.agent_builder import AgentBuilderStructuredRequest


class _StrictPortResult(_StrictFrozenModel):
    pass


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

    def save_if_lease_owner(
        self,
        key: IntentCacheKey,
        plan: CachedIntentPlanV1,
        owner_token: str,
        lease_generation: int,
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


@runtime_checkable
class SemanticExternalCallAdmissionPort(Protocol):
    def authorize(
        self,
        *,
        context: IntentPlanningContext,
        policy: SemanticCachePolicy,
        purpose: Literal["query_embedding", "semantic_verification"],
    ) -> SemanticExternalCallAdmissionResult: ...


@runtime_checkable
class SemanticEmbeddingProviderPort(Protocol):
    def embed(
        self,
        projection: SemanticQueryProjectionV1,
        *,
        binding: SemanticExternalCallBinding,
    ) -> SemanticEmbedding: ...


@runtime_checkable
class SemanticIntentPlanIndexPort(Protocol):
    def search(
        self,
        *,
        context: IntentPlanningContext,
        policy: SemanticCachePolicy,
        projection: SemanticQueryProjectionV1,
        embedding: SemanticEmbedding,
    ) -> tuple[SemanticIntentPlanCandidate, ...]: ...

    def append(
        self,
        *,
        context: IntentPlanningContext,
        policy: SemanticCachePolicy,
        embedding: SemanticEmbedding,
        receipt: IntentPlanL2StoredReceipt,
    ) -> bool: ...


@runtime_checkable
class SemanticCandidateVerifierPort(Protocol):
    @property
    def provider_call_free(self) -> bool: ...

    def verify(
        self,
        *,
        projection: SemanticQueryProjectionV1,
        candidate: SemanticIntentPlanCandidate,
        context: IntentPlanningContext,
        binding: SemanticExternalCallBinding | None,
    ) -> SemanticVerificationResult: ...
