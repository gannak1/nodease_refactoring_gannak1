from apps.shared.db.session import get_db
from apps.shared.domain.deployment_runtime_policy import (
    DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
    DeploymentRuntimePolicy,
)


def get_deployment_runtime_policy() -> DeploymentRuntimePolicy:
    """Return the immutable default policy for FastAPI dependency injection."""
    return DEFAULT_DEPLOYMENT_RUNTIME_POLICY


__all__ = ["get_db", "get_deployment_runtime_policy"]
