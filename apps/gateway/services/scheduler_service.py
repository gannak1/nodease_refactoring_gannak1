"""Durable distributed schedule dispatch composition and lifecycle facade."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.gateway.adapters.audit.sqlalchemy_schedule_dispatch_audit import (
    SqlAlchemyScheduleDispatchAuditRecorder,
)
from apps.gateway.adapters.db.schedule_dispatch_repository import (
    SqlAlchemyScheduleDispatchRepository,
)
from apps.gateway.adapters.db.sqlalchemy_unit_of_work import SqlAlchemyUnitOfWork
from apps.gateway.adapters.queue.celery_schedule_publisher import (
    CeleryScheduleTaskPublisher,
)
from apps.gateway.adapters.schedule.apscheduler_next_fire import (
    ApschedulerNextFireCalculator,
)
from apps.gateway.application.deployment.schedule_dispatch import (
    ScheduleDispatchUseCase,
)
from apps.gateway.application.deployment.schedule_occurrence import (
    ScheduleOccurrenceUseCase,
)
from apps.gateway.application.deployment.schedule_ports import (
    ScheduleTaskPublisherPort,
)
from apps.gateway.services.workflow_budget_service import (
    WorkflowBudgetDecisionAdapter,
)
from apps.shared.db.models.schedule import Schedule
from apps.shared.domain.deployment_runtime_policy import DeploymentRuntimePolicy
from apps.shared.domain.schedule_dispatch import (
    ScheduleDispatchSettings,
    schedule_dispatch_settings_from_environment,
)

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


class SchedulerService:
    """Own one process-local tick; PostgreSQL claims own cross-replica correctness."""

    def __init__(
        self,
        *,
        runtime_policy: DeploymentRuntimePolicy,
        settings: ScheduleDispatchSettings,
        session_factory: SessionFactory,
        publisher: ScheduleTaskPublisherPort,
        start_background: bool = True,
    ) -> None:
        self.runtime_policy = runtime_policy
        self.settings = settings
        self.session_factory = session_factory
        self.publisher = publisher
        self.instance_id = str(uuid.uuid4())
        self.next_fire = ApschedulerNextFireCalculator()
        self.occurrence_use_case = ScheduleOccurrenceUseCase(
            settings=settings,
            runtime_policy=runtime_policy,
            next_fire=self.next_fire,
        )
        self.dispatch_use_case = ScheduleDispatchUseCase(
            settings=settings,
            runtime_policy=runtime_policy,
        )
        self.scheduler: BackgroundScheduler | None = None
        if start_background and settings.processes_existing_claims:
            scheduler = BackgroundScheduler(timezone="UTC")
            scheduler.add_job(
                self._tick,
                "interval",
                seconds=settings.poll_seconds,
                id="schedule-dispatch-tick",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
                next_run_time=datetime.now(timezone.utc),
            )
            scheduler.start()
            self.scheduler = scheduler
        logger.info("Schedule dispatcher initialized: mode=%s", settings.mode)

    def load_schedules_from_db(self, db: Session) -> None:
        """Compatibility facade; durable reconciliation is owned by the tick."""
        del db

    def add_schedule(self, schedule: Schedule, db: Session) -> None:
        """Validate configuration and initialize its cursor without committing."""
        now = db.execute(select(func.now())).scalar_one()
        schedule.next_run_at = self.next_fire.first_after(
            cron_expression=schedule.cron_expression,
            timezone_name=schedule.timezone,
            now=now,
        )
        schedule.configuration_error_code = None

    def update_schedule(self, schedule: Schedule, db: Session) -> None:
        self.add_schedule(schedule, db)

    def remove_schedule(self, schedule_id: uuid.UUID) -> None:
        """No local job exists; lifecycle rows exclude the schedule from future ticks."""
        del schedule_id

    def run_tick_once(self) -> None:
        """Synchronous bounded tick for scheduler callback and deterministic tests."""
        self._tick()

    def _tick(self) -> None:
        if not self.settings.processes_existing_claims:
            return
        try:
            self._recover()
            if self.settings.claims_new_occurrences:
                self._reconcile_uninitialized()
                self._claim_due_occurrences()
            requests = self._prepare_publish_batch()
            for request in requests:
                accepted = True
                try:
                    self.publisher.publish(request)
                except Exception:
                    accepted = False
                    logger.warning(
                        "Schedule dispatch publish failed: claim_id=%s",
                        request.claim_id,
                    )
                self._record_publish_result(request, accepted=accepted)
        except Exception as exc:
            logger.error(
                "Schedule dispatch tick failed: error_type=%s",
                type(exc).__name__,
            )

    def _reconcile_uninitialized(self) -> None:
        db = self.session_factory()
        try:
            self.occurrence_use_case.reconcile_uninitialized(
                repository=SqlAlchemyScheduleDispatchRepository(db),
                audit=SqlAlchemyScheduleDispatchAuditRecorder(db),
                uow=SqlAlchemyUnitOfWork(db),
            )
        finally:
            db.close()

    def _claim_due_occurrences(self) -> None:
        db = self.session_factory()
        try:
            self.occurrence_use_case.claim_due_occurrences(
                repository=SqlAlchemyScheduleDispatchRepository(db),
                budget=WorkflowBudgetDecisionAdapter(db),
                audit=SqlAlchemyScheduleDispatchAuditRecorder(db),
                uow=SqlAlchemyUnitOfWork(db),
            )
        finally:
            db.close()

    def _prepare_publish_batch(self):
        db = self.session_factory()
        try:
            return self.dispatch_use_case.prepare_publish_batch(
                repository=SqlAlchemyScheduleDispatchRepository(db),
                budget=WorkflowBudgetDecisionAdapter(db),
                audit=SqlAlchemyScheduleDispatchAuditRecorder(db),
                uow=SqlAlchemyUnitOfWork(db),
                owner=self.instance_id,
            )
        finally:
            db.close()

    def _record_publish_result(self, request, *, accepted: bool) -> None:
        db = self.session_factory()
        try:
            self.dispatch_use_case.record_publish_result(
                repository=SqlAlchemyScheduleDispatchRepository(db),
                uow=SqlAlchemyUnitOfWork(db),
                request=request,
                accepted=accepted,
            )
        finally:
            db.close()

    def _recover(self) -> None:
        db = self.session_factory()
        try:
            self.dispatch_use_case.recover(
                repository=SqlAlchemyScheduleDispatchRepository(db),
                audit=SqlAlchemyScheduleDispatchAuditRecorder(db),
                uow=SqlAlchemyUnitOfWork(db),
            )
        finally:
            db.close()

    def shutdown(self) -> None:
        if self.scheduler is not None:
            self.scheduler.shutdown()
            self.scheduler = None


scheduler_service: Optional[SchedulerService] = None


def get_scheduler_service() -> SchedulerService:
    if scheduler_service is None:
        raise RuntimeError("SchedulerService is not initialized")
    return scheduler_service


def init_scheduler_service(
    db: Session,
    *,
    runtime_policy: DeploymentRuntimePolicy,
    settings: ScheduleDispatchSettings | None = None,
    session_factory: SessionFactory | None = None,
    celery_application: Any | None = None,
) -> SchedulerService:
    global scheduler_service

    from apps.shared.celery_app import celery_app
    from apps.shared.db.session import SessionLocal

    validated_settings = settings or schedule_dispatch_settings_from_environment(
        os.environ
    )
    factory = session_factory or SessionLocal
    application = celery_application or celery_app
    scheduler_service = SchedulerService(
        runtime_policy=runtime_policy,
        settings=validated_settings,
        session_factory=factory,
        publisher=CeleryScheduleTaskPublisher(application),
    )
    scheduler_service.load_schedules_from_db(db)
    return scheduler_service
