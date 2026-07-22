"""Capability-backed adapter for one RAG query-embedding operation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from threading import Lock
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
from apps.workflow_engine.application.query_embedding_execution import (
    QueryEmbeddingAttribution,
    QueryEmbeddingConfigurationError,
    QueryEmbeddingEgressRuntime,
    QueryEmbeddingEgressScope,
    QueryEmbeddingInvocationLease,
    QueryEmbeddingOperationLedger,
    QueryEmbeddingOperationRequest,
    QueryEmbeddingPlan,
    QueryEmbeddingPreflight,
    QueryEmbeddingProviderResult,
    QueryEmbeddingRequest,
)


class _ModelResolveGuard:
    def __init__(self) -> None:
        self._lock = Lock()
        self._consumed_model_ids: set[uuid.UUID] = set()

    def consume(self, model_id: uuid.UUID) -> None:
        with self._lock:
            if model_id in self._consumed_model_ids:
                raise QueryEmbeddingConfigurationError()
            self._consumed_model_ids.add(model_id)


class _SingleUseInvokeGuard:
    def __init__(self) -> None:
        self._lock = Lock()
        self._consumed = False

    def consume(self) -> None:
        with self._lock:
            if self._consumed:
                raise QueryEmbeddingConfigurationError()
            self._consumed = True


@dataclass(frozen=True, slots=True)
class _CapabilityQueryEmbeddingPlanState:
    organization_id: uuid.UUID
    workflow_id: uuid.UUID
    deployment_id: uuid.UUID
    deployment_version: int
    node_id: str
    node_invocation_id: uuid.UUID
    execution_admission_id: uuid.UUID
    execution_subject: RuntimePrincipal
    billing_principal: RuntimePrincipal
    audit_actor: RuntimePrincipal
    query_byte_cap: int
    input_token_cap: int
    cost_cap_microusd: int
    resolve_guard: _ModelResolveGuard


class _CapabilityQueryEmbeddingLease(QueryEmbeddingInvocationLease):
    def __init__(
        self,
        *,
        attribution: QueryEmbeddingAttribution,
        query: str,
        admitted_input_tokens: int,
        operation: Any,
        egress_lease: Any,
    ) -> None:
        self._attribution = attribution
        self._query = query
        self._admitted_input_tokens = admitted_input_tokens
        self._operation = operation
        self._egress_lease = egress_lease
        self._guard = _SingleUseInvokeGuard()

    @property
    def attribution(self) -> QueryEmbeddingAttribution:
        return self._attribution

    def invoke(self) -> QueryEmbeddingProviderResult:
        self._guard.consume()
        try:
            self._operation.mark_provider_started()
        except Exception as exc:
            raise QueryEmbeddingConfigurationError() from exc
        try:
            result = self._egress_lease.invoke(self._query)
        except Exception:
            try:
                self._operation.complete_outcome_unknown()
            except Exception:
                pass
            raise QueryEmbeddingConfigurationError() from None
        if not isinstance(result, QueryEmbeddingProviderResult):
            try:
                self._operation.complete_outcome_unknown()
            except Exception:
                pass
            raise QueryEmbeddingConfigurationError()
        if result.input_tokens > self._admitted_input_tokens:
            try:
                self._operation.complete_outcome_unknown()
            except Exception:
                pass
            raise QueryEmbeddingConfigurationError()
        try:
            self._operation.complete_success(input_tokens=result.input_tokens)
        except Exception as exc:
            try:
                self._operation.complete_outcome_unknown()
            except Exception:
                pass
            raise QueryEmbeddingConfigurationError() from exc
        return result


class CapabilityQueryEmbeddingAdapter:
    """Maps a trusted Workflow invocation to a query-embedding capability."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        operation_ledger: QueryEmbeddingOperationLedger | None = None,
        egress_runtime: QueryEmbeddingEgressRuntime | None = None,
        capability_service: Any = None,
        credential_loader: Callable[[Any], Mapping[str, Any]] | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._operation_ledger = operation_ledger
        self._egress_runtime = egress_runtime
        self._capability_service = (
            capability_service
            if capability_service is not None
            else ProviderExecutionCapabilityService
        )
        self._credential_loader = credential_loader or load_llm_credential_config
        self._client_factory = client_factory or get_llm_client

    def preflight(self, request: QueryEmbeddingPreflight) -> QueryEmbeddingPlan:
        if (
            request.execution_context.get("provider_execution_capability_required")
            is not True
            or request.legacy_credential_user_id is not None
            or self._operation_ledger is None
            or self._egress_runtime is None
        ):
            raise QueryEmbeddingConfigurationError()
        state = self._resolve_plan_state(request)
        return QueryEmbeddingPlan(capability_required=True, state=state)

    def resolve(
        self,
        request: QueryEmbeddingRequest,
    ) -> QueryEmbeddingInvocationLease:
        state = request.plan.state
        if not isinstance(state, _CapabilityQueryEmbeddingPlanState):
            raise QueryEmbeddingConfigurationError()
        binding = request.model_binding
        if (
            not isinstance(binding.model_id, uuid.UUID)
            or not isinstance(binding.provider_id, uuid.UUID)
            or not isinstance(binding.model_identifier, str)
            or not binding.model_identifier.strip()
            or binding.model_identifier != binding.model_identifier.strip()
            or not isinstance(request.query, str)
            or not request.query
        ):
            raise QueryEmbeddingConfigurationError()
        state.resolve_guard.consume(binding.model_id)
        query_bytes = len(request.query.encode("utf-8"))
        if (
            query_bytes > state.query_byte_cap
            or query_bytes > state.input_token_cap
        ):
            raise QueryEmbeddingConfigurationError()

        provider_attempt_id = uuid.uuid5(
            state.execution_admission_id,
            (
                "provider_execution:"
                f"{state.node_invocation_id}:query_embedding:{binding.model_id}"
            ),
        )
        provider_binding = ProviderExecutionBinding(
            organization_id=state.organization_id,
            workflow_id=state.workflow_id,
            deployment_id=state.deployment_id,
            deployment_version=state.deployment_version,
            node_id=state.node_id,
            node_invocation_id=state.node_invocation_id,
            execution_admission_id=state.execution_admission_id,
            provider_attempt_id=provider_attempt_id,
            purpose=CapabilityPurpose.QUERY_EMBEDDING,
        )
        issue_command = ProviderExecutionCapabilityIssueCommand(
            binding=provider_binding,
            execution_subject=state.execution_subject,
            billing_principal=state.billing_principal,
            audit_actor=state.audit_actor,
            input_token_cap=state.input_token_cap,
            output_token_cap=0,
            cost_cap_microusd=state.cost_cap_microusd,
            policy_model_id=binding.model_id,
        )

        db = self._new_isolated_session(request.shared_session)
        try:
            try:
                capability = self._capability_service.issue_capability(
                    db,
                    command=issue_command,
                )
                admitted = self._capability_service.admit_capability(
                    db,
                    command=ProviderExecutionCapabilityAdmissionCommand(
                        capability_id=capability.id,
                        capability_revision=capability.revision,
                        binding=provider_binding,
                        requested_input_tokens=query_bytes,
                        requested_output_tokens=0,
                        policy_model_id=binding.model_id,
                    ),
                )
            except ProviderExecutionPolicyError as exc:
                raise QueryEmbeddingConfigurationError() from exc
            attribution, client, egress_scope = self._materialize(
                admitted=admitted,
                expected_binding=binding,
                provider_attempt_id=provider_attempt_id,
                organization_id=state.organization_id,
            )
            db.commit()
        finally:
            db.close()

        try:
            operation = self._operation_ledger.begin(
                QueryEmbeddingOperationRequest(
                    attribution=attribution,
                    provider_attempt_id=provider_attempt_id,
                    requested_input_tokens=query_bytes,
                    cost_cap_microusd=state.cost_cap_microusd,
                )
            )
            egress_lease = self._egress_runtime.authorize(
                scope=egress_scope,
                client=client,
            )
        except Exception:
            if "operation" in locals():
                try:
                    operation.complete_before_effect_failure()
                except Exception:
                    pass
            raise QueryEmbeddingConfigurationError() from None
        return _CapabilityQueryEmbeddingLease(
            attribution=attribution,
            query=request.query,
            admitted_input_tokens=query_bytes,
            operation=operation,
            egress_lease=egress_lease,
        )

    def _materialize(
        self,
        *,
        admitted: Any,
        expected_binding: Any,
        provider_attempt_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> tuple[QueryEmbeddingAttribution, Any, QueryEmbeddingEgressScope]:
        capability = admitted.capability
        model = admitted.model
        provider = admitted.provider
        credential = admitted.credential
        principal = capability.credential_principal
        try:
            model_id = uuid.UUID(str(model.id))
            provider_id = uuid.UUID(str(provider.id))
            credential_id = uuid.UUID(str(credential.id))
            principal_id = uuid.UUID(str(principal.reference_id))
            capability_id = uuid.UUID(str(capability.id))
            capability_revision = int(capability.revision)
            input_price = Decimal(str(model.input_price_1k))
            pricing_revision = str(capability.pricing_revision)
            egress_revision = str(capability.egress_revision)
            provider_name = str(provider.name)
            provider_base_url = str(provider.base_url)
        except (AttributeError, InvalidOperation, TypeError, ValueError) as exc:
            raise QueryEmbeddingConfigurationError() from exc
        if (
            model_id != expected_binding.model_id
            or provider_id != expected_binding.provider_id
            or getattr(model, "provider_id", None) != provider_id
            or getattr(model, "model_id_for_api_call", None)
            != expected_binding.model_identifier
            or getattr(model, "type", None) != "embedding"
            or principal.kind is not PrincipalKind.USER
            or capability_revision < 1
            or len(pricing_revision) != 64
            or len(egress_revision) != 64
            or not input_price.is_finite()
            or input_price < 0
            or not provider_name.strip()
            or provider_name != provider_name.strip()
            or not provider_base_url
            or provider_base_url != provider_base_url.strip()
        ):
            raise QueryEmbeddingConfigurationError()
        try:
            config = self._credential_loader(credential)
            api_key = config.get("apiKey")
            if not isinstance(api_key, str) or not api_key.strip():
                raise QueryEmbeddingConfigurationError()
            client = self._client_factory(
                provider=provider_name,
                model_id=expected_binding.model_identifier,
                credentials={"apiKey": api_key, "baseUrl": provider_base_url},
            )
        except QueryEmbeddingConfigurationError:
            raise
        except (LLMCredentialConfigError, TypeError, ValueError, AttributeError):
            raise QueryEmbeddingConfigurationError() from None
        except Exception:
            raise QueryEmbeddingConfigurationError() from None

        attribution = QueryEmbeddingAttribution(
            organization_id=organization_id,
            model_id=model_id,
            provider_id=provider_id,
            credential_id=credential_id,
            credential_principal_user_id=principal_id,
            provider_attempt_id=provider_attempt_id,
            capability_id=capability_id,
            capability_revision=capability_revision,
            pricing_revision=pricing_revision,
            egress_revision=egress_revision,
            input_price_per_1k=input_price,
        )
        return (
            attribution,
            client,
            QueryEmbeddingEgressScope(
                organization_id=organization_id,
                provider_id=provider_id,
                model_id=model_id,
                capability_id=capability_id,
                capability_revision=capability_revision,
                egress_revision=egress_revision,
                provider_name=provider_name,
                provider_base_url=provider_base_url,
            ),
        )

    def _new_isolated_session(self, shared_session: Any | None) -> Session:
        try:
            db = self._session_factory()
        except Exception as exc:
            raise QueryEmbeddingConfigurationError() from exc
        if db is None or db is shared_session:
            raise QueryEmbeddingConfigurationError()
        return db

    def _resolve_plan_state(
        self,
        request: QueryEmbeddingPreflight,
    ) -> _CapabilityQueryEmbeddingPlanState:
        control = request.runtime_control
        effect = control.external_effect_context if control is not None else None
        if (
            control is None
            or not control.external_effect_enforced
            or effect is None
            or effect.node_id != request.node_id
            or effect.organization_id != request.organization_id
            or not isinstance(control.execution_id, uuid.UUID)
            or effect.execution_id != control.execution_id
        ):
            raise QueryEmbeddingConfigurationError()
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
            raise QueryEmbeddingConfigurationError() from exc
        if (
            deployment_version < 1
            or organization_id != request.organization_id
            or organization_id != effect.organization_id
            or workflow_id != effect.workflow_id
        ):
            raise QueryEmbeddingConfigurationError()

        limits = context.get("query_embedding_capability_limits")
        if not isinstance(limits, Mapping):
            raise QueryEmbeddingConfigurationError()
        values = (
            limits.get("query_byte_cap"),
            limits.get("input_token_cap"),
            limits.get("cost_cap_microusd"),
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise QueryEmbeddingConfigurationError()
        query_byte_cap, input_token_cap, cost_cap_microusd = values
        execution_subject, audit_actor = self._execution_identities(context)
        return _CapabilityQueryEmbeddingPlanState(
            organization_id=organization_id,
            workflow_id=workflow_id,
            deployment_id=deployment_id,
            deployment_version=deployment_version,
            node_id=request.node_id,
            node_invocation_id=effect.node_invocation_id,
            execution_admission_id=control.execution_id,
            execution_subject=execution_subject,
            billing_principal=RuntimePrincipal.organization(organization_id),
            audit_actor=audit_actor,
            query_byte_cap=query_byte_cap,
            input_token_cap=input_token_cap,
            cost_cap_microusd=cost_cap_microusd,
            resolve_guard=_ModelResolveGuard(),
        )

    @staticmethod
    def _required_uuid(
        context: Mapping[str, Any],
        field_name: str,
    ) -> uuid.UUID:
        try:
            return uuid.UUID(str(context[field_name]))
        except (KeyError, TypeError, ValueError) as exc:
            raise QueryEmbeddingConfigurationError() from exc

    @staticmethod
    def _execution_identities(
        context: Mapping[str, Any],
    ) -> tuple[RuntimePrincipal, RuntimePrincipal]:
        subject = context.get("execution_subject")
        if isinstance(subject, Mapping):
            subject_type = subject.get("subject_type") or subject.get("type")
            subject_id = subject.get("subject_id") or subject.get("id")
            if subject_type != "user":
                raise QueryEmbeddingConfigurationError()
            try:
                user = RuntimePrincipal.user(uuid.UUID(str(subject_id)))
            except (TypeError, ValueError) as exc:
                raise QueryEmbeddingConfigurationError() from exc
            return user, user
        audience = context.get("provider_execution_audience")
        if audience == "anonymous_public":
            return RuntimePrincipal.anonymous_public(), RuntimePrincipal.public_actor()
        if audience == "system":
            system = RuntimePrincipal.system_actor()
            return system, system
        raise QueryEmbeddingConfigurationError()


__all__ = ["CapabilityQueryEmbeddingAdapter"]
