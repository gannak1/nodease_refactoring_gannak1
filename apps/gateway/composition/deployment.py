from __future__ import annotations

import uuid
from collections.abc import Mapping

from sqlalchemy.orm import Session

from apps.gateway.adapters.db.deployment_preflight_repository import (
    SqlAlchemyDeploymentPreflightRepository,
)
from apps.gateway.application.deployment.preflight import DeploymentPreflightUseCase


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
