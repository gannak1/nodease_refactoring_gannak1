"""Application contracts for one Workflow LLM provider execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from apps.workflow_engine.domain.execution import NodeExecutionControl


class ProviderExecutionConfigurationError(ValueError):
    """Fail-closed error for an incomplete provider execution contract."""

    code = "provider_capability.configuration_required"


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
class ProviderExecutionAttribution:
    """Safe runtime identity; it never contains credential material."""

    credential_id: uuid.UUID
    credential_principal_user_id: uuid.UUID
    organization_id: uuid.UUID
    model_id: str
    model_db_id: uuid.UUID | None
    capability_id: uuid.UUID | None = None
    capability_revision: int | None = None


class ProviderInvocationLease(Protocol):
    @property
    def attribution(self) -> ProviderExecutionAttribution | None: ...

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
    "ProviderExecutionRequest",
    "ProviderExecutionRuntime",
    "ProviderInvocationLease",
]
