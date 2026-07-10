from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from apps.gateway.application.deployment.schedule_models import (
    DispatchCanonicalContext,
    DispatchClaimSnapshot,
    ScheduleDefinitionSnapshot,
    ScheduleOccurrenceSnapshot,
)
from apps.shared.db.models.app import App
from apps.shared.db.models.schedule import Schedule
from apps.shared.db.models.schedule_dispatch import ScheduleDispatchClaim
from apps.shared.db.models.workflow_deployment import (
    DeploymentType,
    WorkflowDeployment,
)
from apps.shared.domain.schedule_dispatch import (
    REASON_BROKER_ENQUEUE_FAILED,
    REASON_BUDGET_EVALUATION_FAILED,
    REASON_ENQUEUE_ATTEMPTS_EXHAUSTED,
    REASON_EXECUTION_OUTCOME_UNKNOWN,
    STATUS_CANCELED,
    STATUS_DEAD_LETTERED,
    STATUS_DISPATCHING,
    STATUS_ENQUEUED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    retry_delay_seconds,
)


class SqlAlchemyScheduleDispatchRepository:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._locked_claims: dict[uuid.UUID, ScheduleDispatchClaim] = {}

    def database_now(self) -> datetime:
        return self.db.execute(select(func.now())).scalar_one()

    def lock_uninitialized_schedules(
        self, limit: int
    ) -> tuple[ScheduleDefinitionSnapshot, ...]:
        rows = self.db.execute(
            self._active_schedule_statement()
            .where(Schedule.next_run_at.is_(None))
            .order_by(Schedule.id)
            .limit(limit)
            .with_for_update(of=Schedule, skip_locked=True)
        ).all()
        return tuple(self._definition(row) for row in rows)

    def lock_due_occurrences(
        self, *, now: datetime, limit: int
    ) -> tuple[ScheduleOccurrenceSnapshot, ...]:
        rows = self.db.execute(
            self._active_schedule_statement()
            .where(Schedule.next_run_at.is_not(None), Schedule.next_run_at <= now)
            .order_by(Schedule.next_run_at, Schedule.id)
            .limit(limit)
            .with_for_update(of=Schedule, skip_locked=True)
        ).all()
        return tuple(
            ScheduleOccurrenceSnapshot(
                **self._definition_values(row),
                scheduled_for=row.Schedule.next_run_at,
            )
            for row in rows
        )

    def initialize_next_run(
        self, schedule_id: uuid.UUID, next_run_at: datetime
    ) -> None:
        schedule = self._locked_schedule(schedule_id)
        schedule.next_run_at = next_run_at

    def create_claim(
        self,
        occurrence: ScheduleOccurrenceSnapshot,
        *,
        status: str,
        idempotency_key: str,
        now: datetime,
        safe_reason_code: str | None = None,
        next_attempt_at: datetime | None = None,
    ) -> uuid.UUID:
        claim_id = uuid.uuid4()
        self.db.add(
            ScheduleDispatchClaim(
                id=claim_id,
                schedule_id=occurrence.schedule_id,
                organization_id=occurrence.organization_id,
                deployment_id=occurrence.deployment_id,
                scheduled_for=occurrence.scheduled_for,
                idempotency_key=idempotency_key,
                status=status,
                safe_reason_code=safe_reason_code,
                next_attempt_at=next_attempt_at,
                claimed_at=now,
                completed_at=now if status == STATUS_CANCELED else None,
            )
        )
        return claim_id

    def advance_schedule(
        self, schedule_id: uuid.UUID, next_run_at: datetime
    ) -> None:
        schedule = self._locked_schedule(schedule_id)
        schedule.next_run_at = next_run_at

    def lock_dispatch_candidates(
        self, *, now: datetime, limit: int
    ) -> tuple[DispatchClaimSnapshot, ...]:
        rows = self.db.execute(
            select(ScheduleDispatchClaim)
            .where(
                ScheduleDispatchClaim.status == STATUS_PENDING,
                or_(
                    ScheduleDispatchClaim.next_attempt_at.is_(None),
                    ScheduleDispatchClaim.next_attempt_at <= now,
                ),
            )
            .order_by(
                ScheduleDispatchClaim.next_attempt_at.nullsfirst(),
                ScheduleDispatchClaim.claimed_at,
                ScheduleDispatchClaim.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars()
        claims = tuple(rows)
        self._locked_claims.update({claim.id: claim for claim in claims})
        return tuple(self._claim_snapshot(claim) for claim in claims)

    def load_canonical_context(
        self, claim: DispatchClaimSnapshot
    ) -> DispatchCanonicalContext:
        schedule = self.db.execute(
            select(Schedule).where(Schedule.id == claim.schedule_id)
        ).scalar_one_or_none()
        deployment = self.db.execute(
            select(WorkflowDeployment).where(
                WorkflowDeployment.id == claim.deployment_id
            )
        ).scalar_one_or_none()
        app = None
        if deployment is not None:
            app = self.db.execute(
                select(App).where(App.id == deployment.app_id)
            ).scalar_one_or_none()
        return DispatchCanonicalContext(
            app_exists=app is not None,
            schedule_id=schedule.id if schedule is not None else None,
            deployment_id=(
                schedule.deployment_id
                if schedule is not None
                else (deployment.id if deployment is not None else None)
            ),
            organization_id=app.organization_id if app is not None else None,
            workflow_id=app.workflow_id if app is not None else None,
            deployment_type=deployment.type if deployment is not None else None,
            deployment_active=bool(deployment and deployment.is_active),
            deployment_current=bool(
                deployment
                and app
                and app.active_deployment_id == deployment.id
            ),
        )

    def mark_dispatching(
        self,
        claim: DispatchClaimSnapshot,
        *,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> None:
        row = self._locked_claim(claim.claim_id)
        row.status = STATUS_DISPATCHING
        row.lease_owner = owner
        row.lease_expires_at = lease_expires_at
        row.celery_task_id = row.idempotency_key
        row.attempt_count += 1
        row.next_attempt_at = None
        row.safe_reason_code = None
        row.updated_at = now

    def mark_pre_dispatch_terminal(
        self,
        claim: DispatchClaimSnapshot,
        *,
        status: str,
        reason: str,
        now: datetime,
    ) -> None:
        row = self._locked_claim(claim.claim_id)
        row.status = status
        row.safe_reason_code = reason
        row.next_attempt_at = None
        row.lease_owner = None
        row.lease_expires_at = None
        row.completed_at = now
        row.updated_at = now

    def mark_budget_unavailable(
        self,
        claim: DispatchClaimSnapshot,
        *,
        now: datetime,
        next_attempt_at: datetime | None,
        exhausted: bool,
    ) -> None:
        row = self._locked_claim(claim.claim_id)
        row.attempt_count += 1
        row.status = STATUS_DEAD_LETTERED if exhausted else STATUS_PENDING
        row.safe_reason_code = REASON_BUDGET_EVALUATION_FAILED
        row.next_attempt_at = next_attempt_at
        row.completed_at = now if exhausted else None
        row.updated_at = now

    def get_claim_for_publish_result(
        self, claim_id: uuid.UUID
    ) -> DispatchClaimSnapshot:
        claim = self.db.execute(
            select(ScheduleDispatchClaim)
            .where(ScheduleDispatchClaim.id == claim_id)
            .with_for_update()
        ).scalar_one()
        self._locked_claims[claim.id] = claim
        return self._claim_snapshot(claim)

    def record_publish_accepted(
        self,
        *,
        claim_id: uuid.UUID,
        owner: str,
        now: datetime,
        delivery_deadline_at: datetime,
    ) -> bool:
        claim = self._claim_for_publish_cas(claim_id, owner)
        if claim is None:
            return self._is_early_delivery(claim_id)
        claim.status = STATUS_ENQUEUED
        claim.lease_owner = None
        claim.lease_expires_at = delivery_deadline_at
        claim.enqueued_at = now
        claim.updated_at = now
        return True

    def record_publish_failed(
        self,
        *,
        claim_id: uuid.UUID,
        owner: str,
        now: datetime,
        next_attempt_at: datetime | None,
        exhausted: bool,
    ) -> bool:
        claim = self._claim_for_publish_cas(claim_id, owner)
        if claim is None:
            return self._is_early_delivery(claim_id)
        claim.status = STATUS_DEAD_LETTERED if exhausted else STATUS_PENDING
        claim.safe_reason_code = (
            REASON_ENQUEUE_ATTEMPTS_EXHAUSTED
            if exhausted
            else REASON_BROKER_ENQUEUE_FAILED
        )
        claim.lease_owner = None
        claim.lease_expires_at = None
        claim.next_attempt_at = next_attempt_at
        claim.completed_at = now if exhausted else None
        claim.updated_at = now
        return True

    def recover_expired_claims(
        self,
        *,
        now: datetime,
        limit: int,
        max_attempts: int,
        retry_base_seconds: int,
    ) -> int:
        claims = self.db.execute(
            select(ScheduleDispatchClaim)
            .where(
                ScheduleDispatchClaim.status.in_(
                    (STATUS_DISPATCHING, STATUS_ENQUEUED)
                ),
                ScheduleDispatchClaim.lease_expires_at <= now,
            )
            .order_by(ScheduleDispatchClaim.lease_expires_at, ScheduleDispatchClaim.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars()
        count = 0
        for claim in claims:
            exhausted = claim.attempt_count >= max_attempts
            claim.status = STATUS_DEAD_LETTERED if exhausted else STATUS_PENDING
            claim.safe_reason_code = (
                REASON_ENQUEUE_ATTEMPTS_EXHAUSTED
                if exhausted
                else REASON_BROKER_ENQUEUE_FAILED
            )
            claim.lease_owner = None
            claim.lease_expires_at = None
            claim.next_attempt_at = (
                None
                if exhausted
                else now
                + timedelta(
                    seconds=retry_delay_seconds(
                        max(claim.attempt_count, 1),
                        base_seconds=retry_base_seconds,
                    )
                )
            )
            claim.completed_at = now if exhausted else None
            claim.updated_at = now
            count += 1
        return count

    def quarantine_expired_running(self, *, now: datetime, limit: int) -> int:
        claims = self.db.execute(
            select(ScheduleDispatchClaim)
            .where(
                ScheduleDispatchClaim.status == STATUS_RUNNING,
                ScheduleDispatchClaim.execution_deadline_at <= now,
            )
            .order_by(
                ScheduleDispatchClaim.execution_deadline_at,
                ScheduleDispatchClaim.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars()
        count = 0
        for claim in claims:
            claim.status = STATUS_DEAD_LETTERED
            claim.safe_reason_code = REASON_EXECUTION_OUTCOME_UNKNOWN
            claim.lease_owner = None
            claim.execution_deadline_at = None
            claim.completed_at = now
            claim.updated_at = now
            count += 1
        return count

    def cleanup_terminal_claims(
        self,
        *,
        now: datetime,
        retention_days: int,
        dead_letter_retention_days: int,
        limit: int,
    ) -> int:
        ids = self.db.execute(
            select(ScheduleDispatchClaim.id)
            .where(
                or_(
                    and_(
                        ScheduleDispatchClaim.status.in_(
                            (STATUS_SUCCEEDED, STATUS_CANCELED)
                        ),
                        ScheduleDispatchClaim.completed_at
                        < now - timedelta(days=retention_days),
                    ),
                    and_(
                        ScheduleDispatchClaim.status == STATUS_DEAD_LETTERED,
                        ScheduleDispatchClaim.completed_at
                        < now - timedelta(days=dead_letter_retention_days),
                    ),
                )
            )
            .order_by(ScheduleDispatchClaim.completed_at, ScheduleDispatchClaim.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars().all()
        if ids:
            self.db.execute(
                delete(ScheduleDispatchClaim).where(
                    ScheduleDispatchClaim.id.in_(ids)
                )
            )
        return len(ids)

    @staticmethod
    def _active_schedule_statement():
        return (
            select(Schedule, WorkflowDeployment, App)
            .join(
                WorkflowDeployment,
                Schedule.deployment_id == WorkflowDeployment.id,
            )
            .join(App, App.id == WorkflowDeployment.app_id)
            .where(
                WorkflowDeployment.is_active.is_(True),
                WorkflowDeployment.type == DeploymentType.SCHEDULE,
                App.active_deployment_id == WorkflowDeployment.id,
            )
        )

    @staticmethod
    def _definition_values(row) -> dict:
        return {
            "schedule_id": row.Schedule.id,
            "deployment_id": row.WorkflowDeployment.id,
            "organization_id": row.App.organization_id,
            "workflow_id": row.App.workflow_id,
            "deployment_type": row.WorkflowDeployment.type,
            "cron_expression": row.Schedule.cron_expression,
            "timezone": row.Schedule.timezone,
        }

    def _definition(self, row) -> ScheduleDefinitionSnapshot:
        return ScheduleDefinitionSnapshot(**self._definition_values(row))

    def _locked_schedule(self, schedule_id: uuid.UUID) -> Schedule:
        return self.db.execute(
            select(Schedule)
            .where(Schedule.id == schedule_id)
            .with_for_update()
        ).scalar_one()

    def _locked_claim(self, claim_id: uuid.UUID) -> ScheduleDispatchClaim:
        return self._locked_claims[claim_id]

    def _claim_for_publish_cas(
        self, claim_id: uuid.UUID, owner: str
    ) -> ScheduleDispatchClaim | None:
        return self.db.execute(
            select(ScheduleDispatchClaim)
            .where(
                ScheduleDispatchClaim.id == claim_id,
                ScheduleDispatchClaim.status == STATUS_DISPATCHING,
                ScheduleDispatchClaim.lease_owner == owner,
            )
            .with_for_update()
        ).scalar_one_or_none()

    def _is_early_delivery(self, claim_id: uuid.UUID) -> bool:
        status = self.db.execute(
            select(ScheduleDispatchClaim.status).where(
                ScheduleDispatchClaim.id == claim_id
            )
        ).scalar_one_or_none()
        return status in {STATUS_RUNNING, STATUS_SUCCEEDED}

    @staticmethod
    def _claim_snapshot(claim: ScheduleDispatchClaim) -> DispatchClaimSnapshot:
        return DispatchClaimSnapshot(
            claim_id=claim.id,
            schedule_id=claim.schedule_id,
            deployment_id=claim.deployment_id,
            organization_id=claim.organization_id,
            idempotency_key=claim.idempotency_key,
            attempt_count=claim.attempt_count,
            status=claim.status,
        )
