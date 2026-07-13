from fastapi import Depends, HTTPException, Request, status

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.composition.access_management import (
    AccessManagementApplication,
    build_access_management_application,
)
from apps.shared.db.session import get_db
from apps.shared.db.models.user import User
from sqlalchemy.orm import Session
from apps.shared.domain.deployment_runtime_policy import (
    DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
    DeploymentRuntimePolicy,
)


def get_deployment_runtime_policy() -> DeploymentRuntimePolicy:
    """Return the immutable default policy for FastAPI dependency injection."""
    return DEFAULT_DEPLOYMENT_RUNTIME_POLICY


def require_json_content_type(request: Request) -> None:
    """Reject browser-simple mutation payloads before service dispatch."""
    content_type = request.headers.get("content-type", "")
    media_type = content_type.partition(";")[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Content-Type must be application/json",
        )


def get_access_management_application(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AccessManagementApplication:
    return build_access_management_application(db, actor=current_user)


__all__ = [
    "get_access_management_application",
    "get_db",
    "get_deployment_runtime_policy",
    "require_json_content_type",
]
