"""Application contracts for one Workflow LLM provider execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Protocol

from apps.workflow_engine.domain.execution import NodeExecutionControl


class ProviderExecutionConfigurationError(ValueError):
    """Fail-closed error for an incomplete provider execution contract."""

    code = "provider_capability.configuration_required"


class ProviderInvocationOutcomeUnknownError(RuntimeError):
    """Provider I/O completed far enough that automatic replay is unsafe."""

    code = "provider_outcome_unknown"
    failure_phase = "outcome_unknown"

    def __init__(self) -> None:
        super().__init__(self.code)


class LLMCredentialNotAvailableError(ValueError):
    """Safe provider credential-selection failure with structured attribution."""

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
        organization_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.credential_id = credential_id
        self.model_id = model_id
        self.organization_id = organization_id


class ProviderExecutionAuditActorKind(str, Enum):
    USER = "user"
    SYSTEM = "system"
    PUBLIC = "public"


@dataclass(frozen=True, slots=True)
class ProviderExecutionAuditActor:
    """Redaction-safe actor identity for provider permission-denial audit."""

    kind: ProviderExecutionAuditActorKind
    reference_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ProviderExecutionAuditActorKind):
            raise ValueError("audit actor kind is invalid")
        if self.kind is ProviderExecutionAuditActorKind.USER:
            if not isinstance(self.reference_id, uuid.UUID):
                raise ValueError("user audit actor requires a UUID reference")
        elif self.reference_id is not None:
            raise ValueError("non-user audit actor cannot carry a reference")


@dataclass(frozen=True, slots=True)
class ProviderExecutionPreflight:
    """Inputs available before Knowledge or provider-backed work starts."""

    node_id: str
    configured_model_id: str
    auto_model_routing: bool
    fallback_model_id: str | None
    knowledge_enabled: bool
    memory_summary_requested: bool
    client_override: Any | None
    execution_context: Mapping[str, Any]
    runtime_control: NodeExecutionControl | None


@dataclass(frozen=True, slots=True)
class ProviderExecutionPlan:
    """Opaque preflight result consumed by the same runtime adapter."""

    fixed_model_id: str | None
    allow_legacy_memory_summary: bool
    audit_actor: ProviderExecutionAuditActor | None = None
    routing_metadata: Mapping[str, Any] = field(default_factory=dict)
    state: object = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ProviderExecutionRequest:
    plan: ProviderExecutionPlan
    model_id: str
    messages: tuple[Mapping[str, Any], ...]
    parameters: Mapping[str, Any]
    shared_session: Any | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ProviderExecutionPricingSnapshot:
    """Immutable non-secret rates approved by capability admission."""

    revision: str
    input_price_per_1k: Decimal
    output_price_per_1k: Decimal

    def __post_init__(self) -> None:
        if len(self.revision) != 64 or any(
            char not in "0123456789abcdef" for char in self.revision
        ):
            raise ValueError("pricing revision must be a SHA-256 digest")
        for rate in (self.input_price_per_1k, self.output_price_per_1k):
            if not isinstance(rate, Decimal) or not rate.is_finite() or rate < 0:
                raise ValueError("pricing rates must be finite non-negative decimals")


@dataclass(frozen=True, slots=True)
class ProviderExecutionAttribution:
    """Safe runtime identity; it never contains credential material."""

    credential_id: uuid.UUID
    credential_principal_user_id: uuid.UUID
    organization_id: uuid.UUID
    model_id: str
    model_db_id: uuid.UUID | None
    capability_id: uuid.UUID | None = None
    capability_revision: int | None = None
    pricing_snapshot: ProviderExecutionPricingSnapshot | None = None

    def __post_init__(self) -> None:
        if self.capability_id is None:
            if (
                self.capability_revision is not None
                or self.pricing_snapshot is not None
            ):
                raise ValueError("legacy attribution cannot carry capability state")
            return
        if (
            not isinstance(self.capability_id, uuid.UUID)
            or not isinstance(self.model_db_id, uuid.UUID)
            or not isinstance(self.capability_revision, int)
            or isinstance(self.capability_revision, bool)
            or self.capability_revision < 1
            or not isinstance(self.pricing_snapshot, ProviderExecutionPricingSnapshot)
        ):
            raise ValueError("capability attribution requires revision and pricing")


class ProviderInvocationLease(Protocol):
    @property
    def attribution(self) -> ProviderExecutionAttribution | None: ...

    def apply_json_schema_response_format(
        self,
        *,
        name: str,
        schema: Mapping[str, Any],
    ) -> bool: ...

    def invoke(self) -> Mapping[str, Any]: ...


class ProviderExecutionRuntime(Protocol):
    def preflight(
        self,
        request: ProviderExecutionPreflight,
    ) -> ProviderExecutionPlan: ...

    def resolve(
        self,
        request: ProviderExecutionRequest,
    ) -> ProviderInvocationLease: ...


__all__ = [
    "LLMCredentialNotAvailableError",
    "ProviderExecutionAttribution",
    "ProviderExecutionAuditActor",
    "ProviderExecutionAuditActorKind",
    "ProviderExecutionConfigurationError",
    "ProviderExecutionPlan",
    "ProviderExecutionPreflight",
    "ProviderExecutionPricingSnapshot",
    "ProviderExecutionRequest",
    "ProviderExecutionRuntime",
    "ProviderInvocationOutcomeUnknownError",
    "ProviderInvocationLease",
]
