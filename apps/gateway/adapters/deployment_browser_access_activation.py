from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from apps.gateway.adapters.db.deployment_preflight_repository import (
    SqlAlchemyDeploymentPreflightRepository,
)
from apps.gateway.application.deployment.browser_access_models import (
    BrowserAccessSourceSnapshot,
)
from apps.gateway.application.deployment.preflight import DeploymentPreflightUseCase
from apps.gateway.services.workflow_service import WorkflowService


class DeploymentBrowserAccessActivationGuard:
    def __init__(self, db: Session) -> None:
        self.db = db

    def enforce(
        self,
        source: BrowserAccessSourceSnapshot,
        *,
        actor_id: uuid.UUID,
    ) -> None:
        WorkflowService.validate_mail_credential_references(
            self.db,
            source.graph_snapshot,
            user_id=str(actor_id),
            organization_id=source.organization_id,
            require_resolved=True,
        )
        _build_preflight_use_case(self.db, source).enforce_active_publish(
            deployment_type=source.deployment_type,
            graph_snapshot=source.graph_snapshot,
        )


def _build_preflight_use_case(
    db: Session,
    source: BrowserAccessSourceSnapshot,
) -> DeploymentPreflightUseCase:
    return DeploymentPreflightUseCase(
        SqlAlchemyDeploymentPreflightRepository(db),
        organization_id=source.organization_id,
        candidate_graphs_by_app_id={source.app_id: source.graph_snapshot},
        candidate_deployment_types_by_app_id={
            source.app_id: source.deployment_type
        },
    )
