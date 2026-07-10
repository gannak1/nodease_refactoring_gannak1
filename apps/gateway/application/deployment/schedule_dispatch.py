from __future__ import annotations

from datetime import timedelta

from apps.gateway.application.deployment.schedule_models import (
    DispatchCanonicalContext,
    DispatchClaimSnapshot,
    SchedulePublishRequest,
)
from apps.gateway.application.deployment.schedule_ports import (
    BudgetDecisionPort,
    ScheduleDispatchAuditRecorderPort,
    ScheduleDispatchRepositoryPort,
    ScheduleDispatchUnitOfWork,
)
from apps.shared.domain.deployment_runtime_policy import (
    SURFACE_SCHEDULE_RUN,
    DeploymentRuntimePolicy,
    is_deployment_type_allowed_for_surface,
)
from apps.shared.domain.schedule_dispatch import (
    REASON_APP_NOT_FOUND,
    REASON_BUDGET_BLOCKED,
    REASON_DEPLOYMENT_INACTIVE,
    REASON_DEPLOYMENT_NOT_CURRENT,
    REASON_DEPLOYMENT_NOT_FOUND,
    REASON_DEPLOYMENT_TYPE_NOT_ALLOWED,
    REASON_ORGANIZATION_SCOPE_MISMATCH,
    REASON_ORGANIZATION_SCOPE_MISSING,
    REASON_SCHEDULE_DEPLOYMENT_MISMATCH,
    REASON_SCHEDULE_NOT_FOUND,
    STATUS_CANCELED,
    ScheduleDispatchSettings,
    retry_delay_seconds,
)


class ScheduleDispatchUseCase:
    def __init__(
        self,
        *,
        settings: ScheduleDispatchSettings,
        runtime_policy: DeploymentRuntimePolicy,
    ) -> None:
        self.settings = settings
        self.runtime_policy = runtime_policy

    def prepare_publish_batch(
        self,
        *,
        repository: ScheduleDispatchRepositoryPort,
        budget: BudgetDecisionPort,
        audit: ScheduleDispatchAuditRecorderPort,
        uow: ScheduleDispatchUnitOfWork,
        owner: str,
    ) -> tuple[SchedulePublishRequest, ...]:
        if not self.settings.processes_existing_claims:
            return ()
        prepared: list[SchedulePublishRequest] = []
        try:
            now = repository.database_now()
            for claim in repository.lock_dispatch_candidates(
                now=now,
                limit=self.settings.dispatch_batch_size,
            ):
                context = repository.load_canonical_context(claim)
                reason = self._canonical_rejection_reason(claim, context)
                if reason is not None:
                    repository.mark_pre_dispatch_terminal(
                        claim,
                        status=STATUS_CANCELED,
                        reason=reason,
                        now=now,
                    )
                    audit.record_policy_result(
                        organization_id=claim.organization_id,
                        claim_id=claim.claim_id,
                        action="schedule_dispatch.canceled",
                        reason=reason,
                    )
                    continue

                decision = budget.evaluate(workflow_id=context.workflow_id, now=now)
                if decision.status == "blocked":
                    repository.mark_pre_dispatch_terminal(
                        claim,
                        status=STATUS_CANCELED,
                        reason=REASON_BUDGET_BLOCKED,
                        now=now,
                    )
                    audit.record_policy_result(
                        organization_id=claim.organization_id,
                        claim_id=claim.claim_id,
                        action="schedule_dispatch.blocked",
                        reason=REASON_BUDGET_BLOCKED,
                    )
                    continue
                if decision.status == "unavailable":
                    next_attempt = claim.attempt_count + 1
                    exhausted = next_attempt >= self.settings.max_attempts
                    repository.mark_budget_unavailable(
                        claim,
                        now=now,
                        exhausted=exhausted,
                        next_attempt_at=(
                            None
                            if exhausted
                            else now
                            + timedelta(
                                seconds=retry_delay_seconds(
                                    next_attempt,
                                    base_seconds=self.settings.retry_base_seconds,
                                )
                            )
                        ),
                    )
                    continue

                repository.mark_dispatching(
                    claim,
                    owner=owner,
                    now=now,
                    lease_expires_at=now
                    + timedelta(seconds=self.settings.lease_seconds),
                )
                prepared.append(
                    SchedulePublishRequest(
                        claim_id=claim.claim_id,
                        task_id=claim.idempotency_key,
                        lease_owner=owner,
                    )
                )
            uow.commit()
            return tuple(prepared)
        except Exception:
            uow.rollback()
            raise

    def record_publish_result(
        self,
        *,
        repository: ScheduleDispatchRepositoryPort,
        uow: ScheduleDispatchUnitOfWork,
        request: SchedulePublishRequest,
        accepted: bool,
    ) -> bool:
        try:
            now = repository.database_now()
            if accepted:
                changed = repository.record_publish_accepted(
                    claim_id=request.claim_id,
                    owner=request.lease_owner,
                    now=now,
                    delivery_deadline_at=now
                    + timedelta(seconds=self.settings.delivery_timeout_seconds),
                )
            else:
                claim = repository.get_claim_for_publish_result(request.claim_id)
                next_attempt = claim.attempt_count
                exhausted = next_attempt >= self.settings.max_attempts
                changed = repository.record_publish_failed(
                    claim_id=request.claim_id,
                    owner=request.lease_owner,
                    now=now,
                    exhausted=exhausted,
                    next_attempt_at=(
                        None
                        if exhausted
                        else now
                        + timedelta(
                            seconds=retry_delay_seconds(
                                max(next_attempt, 1),
                                base_seconds=self.settings.retry_base_seconds,
                            )
                        )
                    ),
                )
            uow.commit()
            return changed
        except Exception:
            uow.rollback()
            raise

    def recover(
        self,
        *,
        repository: ScheduleDispatchRepositoryPort,
        uow: ScheduleDispatchUnitOfWork,
    ) -> tuple[int, int, int]:
        if not self.settings.processes_existing_claims:
            return (0, 0, 0)
        try:
            now = repository.database_now()
            retried = repository.recover_expired_claims(
                now=now,
                limit=self.settings.recovery_batch_size,
                max_attempts=self.settings.max_attempts,
                retry_base_seconds=self.settings.retry_base_seconds,
            )
            unknown = repository.quarantine_expired_running(
                now=now,
                limit=self.settings.recovery_batch_size,
            )
            cleaned = repository.cleanup_terminal_claims(
                now=now,
                retention_days=self.settings.retention_days,
                dead_letter_retention_days=self.settings.dead_letter_retention_days,
                limit=self.settings.cleanup_batch_size,
            )
            uow.commit()
            return (retried, unknown, cleaned)
        except Exception:
            uow.rollback()
            raise

    def _canonical_rejection_reason(
        self,
        claim: DispatchClaimSnapshot,
        context: DispatchCanonicalContext,
    ) -> str | None:
        if context.schedule_id is None:
            return REASON_SCHEDULE_NOT_FOUND
        if context.schedule_id != claim.schedule_id:
            return REASON_SCHEDULE_NOT_FOUND
        if context.deployment_id is None:
            return REASON_DEPLOYMENT_NOT_FOUND
        if context.deployment_id != claim.deployment_id:
            return REASON_SCHEDULE_DEPLOYMENT_MISMATCH
        if not context.app_exists:
            return REASON_APP_NOT_FOUND
        if context.organization_id is None:
            return REASON_ORGANIZATION_SCOPE_MISSING
        if context.organization_id != claim.organization_id:
            return REASON_ORGANIZATION_SCOPE_MISMATCH
        if not context.deployment_active:
            return REASON_DEPLOYMENT_INACTIVE
        if not context.deployment_current:
            return REASON_DEPLOYMENT_NOT_CURRENT
        if not is_deployment_type_allowed_for_surface(
            context.deployment_type,
            SURFACE_SCHEDULE_RUN,
            policy=self.runtime_policy,
        ):
            return REASON_DEPLOYMENT_TYPE_NOT_ALLOWED
        return None
