from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from apps.gateway.application.deployment.browser_access_models import (
    BrowserAccessSourceSnapshot,
)
from apps.gateway.application.deployment.preflight import DeploymentPreflightUseCase
from apps.gateway.services.workflow_service import WorkflowService

BrowserAccessPreflightFactory = Callable[
    [BrowserAccessSourceSnapshot, uuid.UUID],
    DeploymentPreflightUseCase,
]


class DeploymentBrowserAccessActivationGuard:
    def __init__(
        self,
        db: Session,
        *,
        preflight_factory: BrowserAccessPreflightFactory,
    ) -> None:
        self.db = db
        self.preflight_factory = preflight_factory

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
        self.preflight_factory(source, actor_id).enforce_active_publish(
            deployment_type=source.deployment_type,
            graph_snapshot=source.graph_snapshot,
        )
