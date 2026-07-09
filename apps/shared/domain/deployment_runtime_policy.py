"""Pure deployment runtime surface policy.

This module intentionally avoids FastAPI, SQLAlchemy, Celery, and concrete
Gateway/Workflow Engine imports so both runtimes can share one allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, FrozenSet

SURFACE_PUBLIC_INFO = "public_info"
SURFACE_AUTHENTICATED_RUN_INFO = "authenticated_run_info"
SURFACE_AUTHENTICATED_RUN = "authenticated_run"
SURFACE_API_SECRET_RUN = "api_secret_run"
SURFACE_APP_PUBLIC_RUN = "app_public_run"
SURFACE_WEBHOOK_RUN = "webhook_run"
SURFACE_SCHEDULE_RUN = "schedule_run"
SURFACE_WORKFLOW_NODE_CHILD_RUN = "workflow_node_child_run"

DEPLOYMENT_API = "api"
DEPLOYMENT_WEBAPP = "webapp"
DEPLOYMENT_WIDGET = "widget"
DEPLOYMENT_CHATBOT = "chatbot"
DEPLOYMENT_MCP = "mcp"
DEPLOYMENT_WORKFLOW_NODE = "workflow_node"
DEPLOYMENT_SCHEDULE = "schedule"
DEPLOYMENT_WEBHOOK = "webhook"

DIRECT_NON_WORKFLOW_NODE_DEPLOYMENT_TYPES = frozenset(
    {
        DEPLOYMENT_API,
        DEPLOYMENT_WEBAPP,
        DEPLOYMENT_WIDGET,
        DEPLOYMENT_CHATBOT,
        DEPLOYMENT_MCP,
        DEPLOYMENT_SCHEDULE,
        DEPLOYMENT_WEBHOOK,
    }
)

_ALLOWED_TYPES_BY_SURFACE: dict[str, FrozenSet[str]] = {
    SURFACE_PUBLIC_INFO: DIRECT_NON_WORKFLOW_NODE_DEPLOYMENT_TYPES,
    SURFACE_AUTHENTICATED_RUN_INFO: DIRECT_NON_WORKFLOW_NODE_DEPLOYMENT_TYPES,
    SURFACE_AUTHENTICATED_RUN: DIRECT_NON_WORKFLOW_NODE_DEPLOYMENT_TYPES,
    SURFACE_API_SECRET_RUN: frozenset({DEPLOYMENT_API}),
    SURFACE_APP_PUBLIC_RUN: frozenset(
        {DEPLOYMENT_WEBAPP, DEPLOYMENT_WIDGET, DEPLOYMENT_CHATBOT}
    ),
    SURFACE_WEBHOOK_RUN: frozenset({DEPLOYMENT_WEBHOOK}),
    SURFACE_SCHEDULE_RUN: frozenset({DEPLOYMENT_SCHEDULE}),
    SURFACE_WORKFLOW_NODE_CHILD_RUN: frozenset({DEPLOYMENT_WORKFLOW_NODE}),
}

_SURFACE_BY_TRIGGER_MODE: dict[str, str] = {
    "api": SURFACE_API_SECRET_RUN,
    "api_secret": SURFACE_API_SECRET_RUN,
    "app": SURFACE_APP_PUBLIC_RUN,
    "webhook": SURFACE_WEBHOOK_RUN,
    "schedule": SURFACE_SCHEDULE_RUN,
    "workflow_node": SURFACE_WORKFLOW_NODE_CHILD_RUN,
}


@dataclass(frozen=True)
class DeploymentRuntimePolicyResult:
    allowed: bool
    surface: str | None
    deployment_type: str | None
    reason: str | None = None


def deployment_type_value(value: Any) -> str | None:
    """Normalize enum-like or string deployment type values."""
    if value is None:
        return None
    enum_value = getattr(value, "value", None)
    raw = enum_value if enum_value is not None else value
    normalized = str(raw).strip().lower()
    return normalized or None


def trigger_mode_to_surface(trigger_mode: Any) -> str | None:
    normalized = deployment_type_value(trigger_mode)
    if normalized is None:
        return None
    return _SURFACE_BY_TRIGGER_MODE.get(normalized)


def allowed_deployment_types_for_surface(surface: Any) -> FrozenSet[str]:
    normalized = deployment_type_value(surface)
    if normalized is None:
        return frozenset()
    return _ALLOWED_TYPES_BY_SURFACE.get(normalized, frozenset())


def evaluate_deployment_runtime_surface(
    deployment_type: Any,
    surface: Any,
) -> DeploymentRuntimePolicyResult:
    normalized_surface = deployment_type_value(surface)
    normalized_deployment_type = deployment_type_value(deployment_type)
    if normalized_surface is None:
        return DeploymentRuntimePolicyResult(
            allowed=False,
            surface=None,
            deployment_type=normalized_deployment_type,
            reason="unknown_surface",
        )

    allowed_types = _ALLOWED_TYPES_BY_SURFACE.get(normalized_surface)
    if not allowed_types:
        return DeploymentRuntimePolicyResult(
            allowed=False,
            surface=normalized_surface,
            deployment_type=normalized_deployment_type,
            reason="unknown_surface",
        )

    if normalized_deployment_type not in allowed_types:
        return DeploymentRuntimePolicyResult(
            allowed=False,
            surface=normalized_surface,
            deployment_type=normalized_deployment_type,
            reason="deployment_type_not_allowed_for_surface",
        )

    return DeploymentRuntimePolicyResult(
        allowed=True,
        surface=normalized_surface,
        deployment_type=normalized_deployment_type,
    )


def is_deployment_type_allowed_for_surface(
    deployment_type: Any,
    surface: Any,
) -> bool:
    return evaluate_deployment_runtime_surface(deployment_type, surface).allowed


def evaluate_deployment_runtime_trigger(
    deployment_type: Any,
    trigger_mode: Any,
) -> DeploymentRuntimePolicyResult:
    surface = trigger_mode_to_surface(trigger_mode)
    if surface is None:
        return DeploymentRuntimePolicyResult(
            allowed=False,
            surface=None,
            deployment_type=deployment_type_value(deployment_type),
            reason="unknown_trigger_mode",
        )
    return evaluate_deployment_runtime_surface(deployment_type, surface)


def is_deployment_type_allowed_for_trigger(
    deployment_type: Any,
    trigger_mode: Any,
) -> bool:
    return evaluate_deployment_runtime_trigger(deployment_type, trigger_mode).allowed
