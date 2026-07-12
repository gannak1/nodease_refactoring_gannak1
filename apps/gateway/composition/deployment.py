from __future__ import annotations

import uuid
from collections.abc import Mapping

from sqlalchemy.orm import Session

from apps.gateway.adapters.audit.sqlalchemy_schedule_dispatch_audit import (
    SqlAlchemyScheduleDispatchAuditRecorder,
)
from apps.gateway.adapters.db.deployment_preflight_repository import (
    SqlAlchemyDeploymentPreflightRepository,
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
from apps.gateway.application.deployment.preflight import DeploymentPreflightUseCase
from apps.gateway.application.deployment.workflow_node_binding import (
    WorkflowNodeBindingUseCase,
)
from apps.shared.services.workflow_node_catalog import node_side_effect_mapping
from apps.gateway.services.scheduler_service import ScheduleDispatchDependencies
from apps.gateway.services.workflow_budget_service import WorkflowBudgetDecisionAdapter


def build_schedule_dispatch_dependencies(
    db: Session,
) -> ScheduleDispatchDependencies:
    return ScheduleDispatchDependencies(
        repository=SqlAlchemyScheduleDispatchRepository(db),
        audit=SqlAlchemyScheduleDispatchAuditRecorder(db),
        budget=WorkflowBudgetDecisionAdapter(db),
        uow=SqlAlchemyUnitOfWork(db),
    )


def build_schedule_next_fire_calculator() -> ApschedulerNextFireCalculator:
    return ApschedulerNextFireCalculator()


def build_schedule_task_publisher() -> CeleryScheduleTaskPublisher:
    from apps.shared.celery_app import celery_app

    return CeleryScheduleTaskPublisher(celery_app)


def build_deployment_preflight_use_case(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    candidate_graphs_by_app_id: Mapping[uuid.UUID, dict] | None = None,
    candidate_deployment_types_by_app_id: Mapping[uuid.UUID, str] | None = None,
) -> DeploymentPreflightUseCase:
    repository = SqlAlchemyDeploymentPreflightRepository(db)
    return DeploymentPreflightUseCase(
        repository,
        organization_id=organization_id,
        candidate_graphs_by_app_id=candidate_graphs_by_app_id,
        candidate_deployment_types_by_app_id=candidate_deployment_types_by_app_id,
    )


def build_workflow_node_binding_use_case(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
) -> WorkflowNodeBindingUseCase:
    return WorkflowNodeBindingUseCase(
        SqlAlchemyDeploymentPreflightRepository(db),
        organization_id=organization_id,
        side_effect_by_node_type=node_side_effect_mapping(),
    )
