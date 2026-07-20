"""Capability-authorized provider execution strategy."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from sqlalchemy.orm import Session

from apps.shared.domain.provider_execution_capability import (
    CapabilityPurpose,
    PrincipalKind,
    ProviderExecutionBinding,
    RuntimePrincipal,
)
from apps.shared.services.llm_client import get_llm_client
from apps.shared.services.llm_credential_config import (
    LLMCredentialConfigError,
    load_llm_credential_config,
)
from apps.shared.services.provider_execution_capability import (
    ProviderExecutionCapabilityAdmissionCommand,
    ProviderExecutionCapabilityIssueCommand,
    ProviderExecutionCapabilityService,
    ProviderExecutionPolicyError,
)
from apps.workflow_engine.adapters.provider_invocation import (
    ProviderClientInvocationLease,
)
from apps.workflow_engine.application.provider_execution import (
    LLMCredentialNotAvailableError,
    ProviderExecutionAttribution,
    ProviderExecutionConfigurationError,
    ProviderExecutionPlan,
    ProviderExecutionPreflight,
    ProviderExecutionRequest,
)


@dataclass(frozen=True, slots=True)
class _CapabilityPlanState:
    issue_command: ProviderExecutionCapabilityIssueCommand
    configured_model_id: str


def provider_visible_request_bounds(
    *,
    messages: tuple[Mapping[str, Any], ...],
    parameters: Mapping[str, Any],
    output_token_cap: int,
) -> tuple[int, int, dict[str, Any]]:
    """Normalize and conservatively bound the complete provider request."""

    normalized = dict(parameters)
    if "model" in normalized:
        raise ProviderExecutionConfigurationError()

    for field_name in ("n", "best_of"):
        value = normalized.get(field_name, 1)
        if isinstance(value, bool) or not isinstance(value, int) or value != 1:
            raise ProviderExecutionConfigurationError()

    if {"max_completion_tokens", "max_output_tokens"}.intersection(normalized):
        raise ProviderExecutionConfigurationError()

    output_tokens = normalized.get("max_tokens")
    if output_tokens is None:
        if isinstance(output_token_cap, bool) or output_token_cap <= 0:
            raise ProviderExecutionConfigurationError()
        output_tokens = output_token_cap
        normalized["max_tokens"] = output_tokens
    if (
        isinstance(output_tokens, bool)
        or not isinstance(output_tokens, int)
        or output_tokens <= 0
    ):
        raise ProviderExecutionConfigurationError()

    try:
        encoded = json.dumps(
            {
                "messages": [dict(message) for message in messages],
                "parameters": normalized,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProviderExecutionConfigurationError() from exc
    if not encoded:
        raise ProviderExecutionConfigurationError()
    return len(encoded), output_tokens, normalized


class CapabilityProviderExecutionAdapter:
    """Translate Workflow execution controls into authoritative capability use."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        capability_service: Any = None,
        credential_loader: Callable[[Any], Mapping[str, Any]] | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._capability_service = (
            capability_service
            if capability_service is not None
            else ProviderExecutionCapabilityService
        )
        self._credential_loader = credential_loader or load_llm_credential_config
        self._client_factory = client_factory or get_llm_client

    def preflight(
        self,
        request: ProviderExecutionPreflight,
    ) -> ProviderExecutionPlan:
        if (
            request.execution_context.get("provider_execution_capability_required")
            is not True
            or request.knowledge_enabled
            or request.auto_model_routing
            or request.fallback_model_id
            or request.client_override is not None
        ):
            raise ProviderExecutionConfigurationError()
        command = self._issue_command(request)
        return ProviderExecutionPlan(
            fixed_model_id=request.configured_model_id,
            allow_legacy_memory_summary=False,
            routing_metadata={"provider_execution_capability": "required"},
            state=_CapabilityPlanState(
                issue_command=command,
                configured_model_id=request.configured_model_id,
            ),
        )

    def resolve(
        self,
        request: ProviderExecutionRequest,
    ) -> ProviderClientInvocationLease:
        state = request.plan.state
        if not isinstance(state, _CapabilityPlanState):
            raise ProviderExecutionConfigurationError()
        if request.model_id != state.configured_model_id:
            raise ProviderExecutionConfigurationError()
        issue_command = state.issue_command
        input_tokens, output_tokens, parameters = provider_visible_request_bounds(
            messages=request.messages,
            parameters=request.parameters,
            output_token_cap=issue_command.output_token_cap,
        )
        db = self._new_isolated_session(request.shared_session)
        try:
            try:
                capability = self._capability_service.issue_capability(
                    db,
                    command=issue_command,
                )
                lease = self._capability_service.admit_capability(
                    db,
                    command=ProviderExecutionCapabilityAdmissionCommand(
                        capability_id=capability.id,
                        capability_revision=capability.revision,
                        binding=issue_command.binding,
                        requested_input_tokens=input_tokens,
                        requested_output_tokens=output_tokens,
                    ),
                )
            except ProviderExecutionPolicyError as exc:
                raise LLMCredentialNotAvailableError(
                    f"provider_capability_{exc.code}",
                    "Provider execution capability is not available.",
                    organization_id=issue_command.binding.organization_id,
                ) from exc

            admitted_model_id = getattr(lease.model, "model_id_for_api_call", None)
            if admitted_model_id != request.model_id:
                raise LLMCredentialNotAvailableError(
                    "provider_capability_model_mismatch",
                    "Provider execution capability is not available.",
                    organization_id=issue_command.binding.organization_id,
                )
            principal = getattr(lease.capability, "credential_principal", None)
            try:
                credential_id = uuid.UUID(str(lease.credential.id))
                model_db_id = uuid.UUID(str(lease.model.id))
                principal_id = uuid.UUID(str(principal.reference_id))
            except (AttributeError, TypeError, ValueError):
                raise LLMCredentialNotAvailableError(
                    "provider_capability_attribution_invalid",
                    "Provider execution capability is not available.",
                    organization_id=issue_command.binding.organization_id,
                ) from None
            if principal.kind is not PrincipalKind.USER:
                raise LLMCredentialNotAvailableError(
                    "provider_capability_attribution_invalid",
                    "Provider execution capability is not available.",
                    organization_id=issue_command.binding.organization_id,
                )

            try:
                config = self._credential_loader(lease.credential)
                api_key = config.get("apiKey")
                base_url = lease.provider.base_url
                provider_name = lease.provider.name
                if (
                    not isinstance(api_key, str)
                    or not api_key.strip()
                    or not isinstance(base_url, str)
                    or not base_url
                    or base_url != base_url.strip()
                    or not isinstance(provider_name, str)
                    or not provider_name.strip()
                ):
                    raise ValueError("invalid provider materialization input")
                client = self._client_factory(
                    provider=provider_name,
                    model_id=admitted_model_id,
                    credentials={"apiKey": api_key, "baseUrl": base_url},
                )
            except (LLMCredentialConfigError, TypeError, ValueError, AttributeError):
                raise LLMCredentialNotAvailableError(
                    "credential_config_invalid",
                    "Provider execution capability is not available.",
                    organization_id=issue_command.binding.organization_id,
                ) from None
            except Exception:
                raise LLMCredentialNotAvailableError(
                    "provider_client_initialization_failed",
                    "Provider execution capability is not available.",
                    organization_id=issue_command.binding.organization_id,
                ) from None

            attribution = ProviderExecutionAttribution(
                credential_id=credential_id,
                credential_principal_user_id=principal_id,
                organization_id=issue_command.binding.organization_id,
                model_id=admitted_model_id,
                model_db_id=model_db_id,
                capability_id=capability.id,
                capability_revision=capability.revision,
            )
            db.commit()
        finally:
            db.close()

        return ProviderClientInvocationLease(
            client=client,
            messages=request.messages,
            parameters=parameters,
            attribution=attribution,
        )

    def _new_isolated_session(self, shared_session: Any | None) -> Session:
        try:
            db = self._session_factory()
        except Exception as exc:
            raise ProviderExecutionConfigurationError() from exc
        if db is None or db is shared_session:
            raise ProviderExecutionConfigurationError()
        return db

    @staticmethod
    def _required_uuid(
        context: Mapping[str, Any],
        field_name: str,
    ) -> uuid.UUID:
        try:
            return uuid.UUID(str(context[field_name]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderExecutionConfigurationError() from exc

    def _issue_command(
        self,
        request: ProviderExecutionPreflight,
    ) -> ProviderExecutionCapabilityIssueCommand:
        control = request.runtime_control
        effect_context = (
            control.external_effect_context if control is not None else None
        )
        if (
            control is None
            or not control.external_effect_enforced
            or effect_context is None
            or effect_context.node_id != request.node_id
        ):
            raise ProviderExecutionConfigurationError()

        context = request.execution_context
        deployment_id = self._required_uuid(context, "deployment_id")
        organization_id = self._required_uuid(context, "organization_id")
        workflow_id = self._required_uuid(context, "workflow_id")
        try:
            raw_version = context["workflow_version"]
            if isinstance(raw_version, bool):
                raise ValueError
            deployment_version = int(raw_version)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderExecutionConfigurationError() from exc
        if (
            deployment_version < 1
            or organization_id != effect_context.organization_id
            or workflow_id != effect_context.workflow_id
        ):
            raise ProviderExecutionConfigurationError()

        execution_subject, audit_actor = self._execution_identities(context)
        caps = context.get("provider_execution_capability_limits")
        if not isinstance(caps, Mapping):
            raise ProviderExecutionConfigurationError()
        values = (
            caps.get("input_token_cap"),
            caps.get("output_token_cap"),
            caps.get("cost_cap_microusd"),
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise ProviderExecutionConfigurationError()
        input_cap, output_cap, cost_cap = values
        provider_attempt_id = uuid.uuid5(
            control.execution_id,
            f"provider_execution:{effect_context.node_invocation_id}:main_generation",
        )
        return ProviderExecutionCapabilityIssueCommand(
            binding=ProviderExecutionBinding(
                organization_id=effect_context.organization_id,
                workflow_id=effect_context.workflow_id,
                deployment_id=deployment_id,
                deployment_version=deployment_version,
                node_id=request.node_id,
                node_invocation_id=effect_context.node_invocation_id,
                execution_admission_id=control.execution_id,
                provider_attempt_id=provider_attempt_id,
                purpose=CapabilityPurpose.MAIN_GENERATION,
            ),
            execution_subject=execution_subject,
            billing_principal=RuntimePrincipal.organization(
                effect_context.organization_id
            ),
            audit_actor=audit_actor,
            input_token_cap=input_cap,
            output_token_cap=output_cap,
            cost_cap_microusd=cost_cap,
        )

    @staticmethod
    def _execution_identities(
        context: Mapping[str, Any],
    ) -> tuple[RuntimePrincipal, RuntimePrincipal]:
        subject = context.get("execution_subject")
        if isinstance(subject, Mapping):
            subject_type = subject.get("subject_type") or subject.get("type")
            subject_id = subject.get("subject_id") or subject.get("id")
            if subject_type != "user":
                raise ProviderExecutionConfigurationError()
            try:
                user = RuntimePrincipal.user(uuid.UUID(str(subject_id)))
            except (TypeError, ValueError) as exc:
                raise ProviderExecutionConfigurationError() from exc
            return user, user
        audience = context.get("provider_execution_audience")
        if audience == "anonymous_public":
            return RuntimePrincipal.anonymous_public(), RuntimePrincipal.public_actor()
        if audience == "system":
            system = RuntimePrincipal.system_actor()
            return system, system
        raise ProviderExecutionConfigurationError()


__all__ = [
    "CapabilityProviderExecutionAdapter",
    "provider_visible_request_bounds",
]
