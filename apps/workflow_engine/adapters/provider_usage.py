"""PostgreSQL adapter for the current Workflow LLM usage projection."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping

from sqlalchemy.orm import Session

from apps.shared.domain.provider_execution_capability import (
    CapabilityPurpose,
    PrincipalKind,
    ProviderExecutionBinding,
    RuntimeIdentityContext,
    RuntimePrincipal,
)
from apps.shared.domain.provider_usage_ledger import (
    ProviderUsageIntentSnapshot,
    ProviderUsageLedgerError,
    ProviderUsageMeasurement,
    ProviderUsageState,
)
from apps.shared.services.llm_model_pricing import (
    calculate_text_token_cost_from_rates,
)
from apps.shared.services.provider_usage_ledger import (
    ProviderUsageIntentCommand,
    ProviderUsageLedgerService,
)
from apps.workflow_engine.application.provider_execution import (
    ProviderExecutionPrincipal,
    ProviderExecutionUsageContext,
)
from apps.workflow_engine.application.provider_usage import (
    ProviderUsageIntent,
    ProviderUsageRecord,
    ProviderUsageRuntimeError,
)
from apps.workflow_engine.services.llm_service import LLMService


_MICROUSD_PER_USD = Decimal("1000000")


class _LegacyProviderUsageAttempt:
    durable = False

    def __init__(
        self,
        *,
        recorder: "PostgresProviderUsageRecorder",
        intent: ProviderUsageIntent,
    ) -> None:
        self._recorder = recorder
        self._intent = intent

    def mark_provider_started(self) -> None:
        return None

    def record_success(self, *, usage: Mapping[str, Any], latency_ms: int) -> float:
        normalized = dict(usage)
        normalized["latency_ms"] = latency_ms
        return self._recorder.record(
            ProviderUsageRecord(
                attribution=self._intent.attribution,
                usage=normalized,
                workflow_id=self._intent.workflow_id,
                workflow_run_id=self._intent.workflow_run_id,
                node_id=self._intent.node_id,
                cost_optimizer_candidate_id=(
                    self._intent.cost_optimizer_candidate_id
                ),
            )
        )

    def mark_outcome_unknown(self, *, reason_code: str) -> None:
        return None


class _LedgerProviderUsageAttempt:
    durable = True

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        service: ProviderUsageLedgerService,
        operation_id: uuid.UUID,
        state_version: int,
        pricing: tuple[Decimal, Decimal],
        admitted_input_tokens: int,
        admitted_output_tokens: int,
        cost_cap_microusd: int,
    ) -> None:
        self._session_factory = session_factory
        self._service = service
        self._operation_id = operation_id
        self._state_version = state_version
        self._pricing = pricing
        self._admitted_input_tokens = admitted_input_tokens
        self._admitted_output_tokens = admitted_output_tokens
        self._cost_cap_microusd = cost_cap_microusd
        self._started = False
        self._terminal = False

    def mark_provider_started(self) -> None:
        if self._started or self._terminal:
            raise ProviderUsageRuntimeError("provider_usage.replay_blocked")
        db = self._session_factory()
        try:
            operation = self._service.mark_provider_started(
                db,
                operation_id=self._operation_id,
                expected_state_version=self._state_version,
            )
        except ProviderUsageLedgerError as exc:
            raise ProviderUsageRuntimeError(exc.code) from exc
        finally:
            db.close()
        self._state_version = operation.state_version
        self._started = True

    def record_success(self, *, usage: Mapping[str, Any], latency_ms: int) -> float:
        if not self._started or self._terminal:
            raise ProviderUsageRuntimeError("provider_usage.outcome_not_allowed")
        try:
            prompt_tokens = self._usage_integer(usage, "prompt_tokens")
            completion_tokens = self._usage_integer(usage, "completion_tokens")
            if "total_tokens" in usage:
                total_tokens = self._usage_integer(usage, "total_tokens")
                if total_tokens != prompt_tokens + completion_tokens:
                    raise ProviderUsageRuntimeError(
                        "provider_usage.measurement_invalid"
                    )
            normalized_latency = self._nonnegative_integer(latency_ms)
            cost_usd = (
                Decimal(prompt_tokens) * self._pricing[0]
                + Decimal(completion_tokens) * self._pricing[1]
            ) / Decimal(1000)
            cost_microusd = int(
                (cost_usd * _MICROUSD_PER_USD).to_integral_value(
                    rounding=ROUND_HALF_UP
                )
            )
            if (
                prompt_tokens > self._admitted_input_tokens
                or completion_tokens > self._admitted_output_tokens
                or cost_microusd > self._cost_cap_microusd
            ):
                raise ProviderUsageRuntimeError(
                    "provider_usage.measurement_invalid"
                )
            measurement = ProviderUsageMeasurement(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_cost_microusd=cost_microusd,
                latency_ms=normalized_latency,
            )
        except (ProviderUsageRuntimeError, ValueError) as exc:
            self._classify_outcome_unknown("provider_usage_invalid")
            raise ProviderUsageRuntimeError(
                "provider_usage.outcome_unknown"
            ) from exc
        db = self._session_factory()
        try:
            operation = self._service.record_success(
                db,
                operation_id=self._operation_id,
                expected_state_version=self._state_version,
                measurement=measurement,
            )
        except ProviderUsageLedgerError as exc:
            self._classify_outcome_unknown("terminal_record_failed")
            raise ProviderUsageRuntimeError(
                "provider_usage.outcome_unknown"
            ) from exc
        finally:
            db.close()
        self._state_version = operation.state_version
        self._terminal = True
        self._project_best_effort()
        return float(cost_usd)

    def mark_outcome_unknown(self, *, reason_code: str) -> None:
        if not self._started or self._terminal:
            raise ProviderUsageRuntimeError("provider_usage.outcome_not_allowed")
        db = self._session_factory()
        try:
            operation = self._service.mark_outcome_unknown(
                db,
                operation_id=self._operation_id,
                expected_state_version=self._state_version,
                reason_code=reason_code,
            )
        except (ProviderUsageLedgerError, ValueError) as exc:
            code = getattr(exc, "code", "provider_usage.outcome_unknown_commit_failed")
            raise ProviderUsageRuntimeError(code) from exc
        finally:
            db.close()
        self._state_version = operation.state_version
        self._terminal = True

    def _classify_outcome_unknown(self, reason_code: str) -> None:
        db = self._session_factory()
        try:
            self._service.mark_outcome_unknown(
                db,
                operation_id=self._operation_id,
                expected_state_version=self._state_version,
                reason_code=reason_code,
            )
        except (ProviderUsageLedgerError, ValueError):
            return
        finally:
            db.close()
        self._terminal = True

    def _project_best_effort(self) -> None:
        db = self._session_factory()
        try:
            self._service.project_compatibility_usage(
                db,
                operation_id=self._operation_id,
            )
        except ProviderUsageLedgerError:
            return
        finally:
            db.close()

    @classmethod
    def _usage_integer(cls, usage: Mapping[str, Any], field_name: str) -> int:
        if field_name not in usage:
            raise ProviderUsageRuntimeError("provider_usage.measurement_invalid")
        return cls._nonnegative_integer(usage[field_name])

    @staticmethod
    def _nonnegative_integer(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ProviderUsageRuntimeError("provider_usage.measurement_invalid")
        return value


class PostgresProviderUsageRecorder:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        ledger_service: ProviderUsageLedgerService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._ledger_service = ledger_service or ProviderUsageLedgerService()

    def begin(
        self,
        request: ProviderUsageIntent,
    ) -> _LegacyProviderUsageAttempt | _LedgerProviderUsageAttempt:
        context = request.attribution.usage_context
        if context is None:
            return _LegacyProviderUsageAttempt(recorder=self, intent=request)
        if (
            request.workflow_id not in (None, context.binding.workflow_id)
            or request.node_id != context.binding.node_id
        ):
            raise ProviderUsageRuntimeError("provider_usage.binding_mismatch")
        snapshot = self._shared_snapshot(context)
        db = self._session_factory()
        try:
            operation = self._ledger_service.record_intent(
                db,
                command=ProviderUsageIntentCommand(
                    snapshot=snapshot,
                    workflow_run_id=request.workflow_run_id,
                    cost_optimizer_candidate_id=(
                        request.cost_optimizer_candidate_id
                    ),
                ),
            )
        except ProviderUsageLedgerError as exc:
            raise ProviderUsageRuntimeError(exc.code) from exc
        finally:
            db.close()
        if operation.state is not ProviderUsageState.INTENT:
            raise ProviderUsageRuntimeError("provider_usage.replay_blocked")
        return _LedgerProviderUsageAttempt(
            session_factory=self._session_factory,
            service=self._ledger_service,
            operation_id=operation.id,
            state_version=operation.state_version,
            pricing=(
                context.pricing_snapshot.input_price_per_1k,
                context.pricing_snapshot.output_price_per_1k,
            ),
            admitted_input_tokens=context.admitted_input_tokens,
            admitted_output_tokens=context.admitted_output_tokens,
            cost_cap_microusd=context.cost_cap_microusd,
        )

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

    @classmethod
    def _shared_snapshot(
        cls,
        context: ProviderExecutionUsageContext,
    ) -> ProviderUsageIntentSnapshot:
        binding = context.binding
        identities = context.identities
        return ProviderUsageIntentSnapshot(
            binding=ProviderExecutionBinding(
                organization_id=binding.organization_id,
                workflow_id=binding.workflow_id,
                deployment_id=binding.deployment_id,
                deployment_version=binding.deployment_version,
                node_id=binding.node_id,
                node_invocation_id=binding.node_invocation_id,
                execution_admission_id=binding.execution_admission_id,
                provider_attempt_id=binding.provider_attempt_id,
                purpose=CapabilityPurpose(binding.purpose.value),
                container_path=binding.container_path,
            ),
            capability_id=context.capability_id,
            capability_revision=context.capability_revision,
            policy_id=context.policy_id,
            policy_revision=context.policy_revision,
            provider_id=context.provider_id,
            model_id=context.model_id,
            model_api_id=context.model_api_id,
            credential_id=context.credential_id,
            identities=RuntimeIdentityContext(
                execution_subject=cls._shared_principal(
                    identities.execution_subject
                ),
                credential_principal=cls._shared_principal(
                    identities.credential_principal
                ),
                billing_principal=cls._shared_principal(
                    identities.billing_principal
                ),
                audit_actor=cls._shared_principal(identities.audit_actor),
            ),
            permission_revision=context.permission_revision,
            relation_revision=context.relation_revision,
            egress_revision=context.egress_revision,
            pricing_revision=context.pricing_snapshot.revision,
            input_price_per_1k=str(context.pricing_snapshot.input_price_per_1k),
            output_price_per_1k=str(context.pricing_snapshot.output_price_per_1k),
            input_token_cap=context.input_token_cap,
            output_token_cap=context.output_token_cap,
            cost_cap_microusd=context.cost_cap_microusd,
            admitted_input_tokens=context.admitted_input_tokens,
            admitted_output_tokens=context.admitted_output_tokens,
            expires_at=context.capability_expires_at,
        )

    @staticmethod
    def _shared_principal(principal: ProviderExecutionPrincipal) -> RuntimePrincipal:
        return RuntimePrincipal(
            PrincipalKind(principal.kind.value),
            principal.reference_id,
        )


__all__ = ["PostgresProviderUsageRecorder"]
