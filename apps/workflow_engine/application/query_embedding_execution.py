"""Application contracts for one Workflow RAG query-embedding operation."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, Protocol

from apps.workflow_engine.domain.execution import NodeExecutionControl


class QueryEmbeddingConfigurationError(ValueError):
    """Safe fail-closed error for an incomplete embedding execution."""

    code = "query_embedding.configuration_required"


@dataclass(frozen=True, slots=True)
class QueryEmbeddingPreflight:
    node_id: str
    organization_id: uuid.UUID
    legacy_credential_user_id: uuid.UUID | None
    execution_context: Mapping[str, Any]
    runtime_control: NodeExecutionControl | None


@dataclass(frozen=True, slots=True)
class QueryEmbeddingPlan:
    capability_required: bool
    state: object = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class QueryEmbeddingModelBinding:
    model_id: uuid.UUID
    provider_id: uuid.UUID
    model_identifier: str


@dataclass(frozen=True, slots=True)
class QueryEmbeddingRequest:
    plan: QueryEmbeddingPlan
    model_binding: QueryEmbeddingModelBinding
    query: str = field(repr=False)
    shared_session: Any | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class QueryEmbeddingAttribution:
    organization_id: uuid.UUID
    model_id: uuid.UUID
    provider_id: uuid.UUID
    credential_id: uuid.UUID = field(repr=False)
    credential_principal_user_id: uuid.UUID = field(repr=False)
    provider_attempt_id: uuid.UUID
    capability_id: uuid.UUID
    capability_revision: int
    pricing_revision: str
    egress_revision: str
    input_price_per_1k: Decimal


@dataclass(frozen=True, slots=True)
class QueryEmbeddingOperationRequest:
    attribution: QueryEmbeddingAttribution = field(repr=False)
    provider_attempt_id: uuid.UUID
    requested_input_tokens: int
    cost_cap_microusd: int


@dataclass(frozen=True, slots=True)
class QueryEmbeddingEgressScope:
    organization_id: uuid.UUID
    provider_id: uuid.UUID
    model_id: uuid.UUID
    capability_id: uuid.UUID
    capability_revision: int
    egress_revision: str
    provider_name: str
    provider_base_url: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class QueryEmbeddingProviderResult:
    vector: tuple[float, ...] = field(repr=False)
    input_tokens: int

    def __post_init__(self) -> None:
        if not self.vector or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in self.vector
        ):
            raise QueryEmbeddingConfigurationError()
        object.__setattr__(self, "vector", tuple(float(value) for value in self.vector))
        if (
            isinstance(self.input_tokens, bool)
            or not isinstance(self.input_tokens, int)
            or self.input_tokens < 0
        ):
            raise QueryEmbeddingConfigurationError()


class QueryEmbeddingInvocationLease(Protocol):
    @property
    def attribution(self) -> QueryEmbeddingAttribution | None: ...

    def invoke(self) -> QueryEmbeddingProviderResult: ...


class QueryEmbeddingExecutionRuntime(Protocol):
    def preflight(self, request: QueryEmbeddingPreflight) -> QueryEmbeddingPlan: ...

    def resolve(
        self,
        request: QueryEmbeddingRequest,
    ) -> QueryEmbeddingInvocationLease: ...


class QueryEmbeddingOperationLease(Protocol):
    def mark_provider_started(self) -> None: ...

    def complete_before_effect_failure(self) -> None: ...

    def complete_success(self, *, input_tokens: int) -> None: ...

    def complete_outcome_unknown(self) -> None: ...


class QueryEmbeddingOperationLedger(Protocol):
    def begin(
        self,
        request: QueryEmbeddingOperationRequest,
    ) -> QueryEmbeddingOperationLease: ...


class QueryEmbeddingEgressLease(Protocol):
    def invoke(self, query: str) -> QueryEmbeddingProviderResult: ...


class QueryEmbeddingEgressRuntime(Protocol):
    def authorize(
        self,
        *,
        scope: QueryEmbeddingEgressScope,
        client: Any,
    ) -> QueryEmbeddingEgressLease: ...


__all__ = [
    "QueryEmbeddingAttribution",
    "QueryEmbeddingConfigurationError",
    "QueryEmbeddingEgressLease",
    "QueryEmbeddingEgressRuntime",
    "QueryEmbeddingEgressScope",
    "QueryEmbeddingExecutionRuntime",
    "QueryEmbeddingInvocationLease",
    "QueryEmbeddingModelBinding",
    "QueryEmbeddingOperationLedger",
    "QueryEmbeddingOperationLease",
    "QueryEmbeddingOperationRequest",
    "QueryEmbeddingPlan",
    "QueryEmbeddingPreflight",
    "QueryEmbeddingProviderResult",
    "QueryEmbeddingRequest",
]
