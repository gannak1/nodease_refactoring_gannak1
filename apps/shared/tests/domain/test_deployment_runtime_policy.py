from enum import Enum

import pytest
from apps.shared.domain.deployment_runtime_policy import (
    DEPLOYMENT_API,
    DEPLOYMENT_CHATBOT,
    DEPLOYMENT_MCP,
    DEPLOYMENT_SCHEDULE,
    DEPLOYMENT_WEBAPP,
    DEPLOYMENT_WEBHOOK,
    DEPLOYMENT_WIDGET,
    DEPLOYMENT_WORKFLOW_NODE,
    SURFACE_API_SECRET_RUN,
    SURFACE_APP_PUBLIC_RUN,
    SURFACE_AUTHENTICATED_RUN,
    SURFACE_AUTHENTICATED_RUN_INFO,
    SURFACE_PUBLIC_INFO,
    SURFACE_SCHEDULE_RUN,
    SURFACE_WEBHOOK_RUN,
    SURFACE_WORKFLOW_NODE_CHILD_RUN,
    allowed_deployment_types_for_surface,
    deployment_type_value,
    evaluate_deployment_runtime_surface,
    is_deployment_type_allowed_for_surface,
    is_deployment_type_allowed_for_trigger,
    trigger_mode_to_surface,
)


class FakeDeploymentType(str, Enum):
    API = "api"
    WORKFLOW_NODE = "workflow_node"


@pytest.mark.parametrize(
    ("surface", "allowed"),
    [
        (
            SURFACE_PUBLIC_INFO,
            {
                DEPLOYMENT_API,
                DEPLOYMENT_WEBAPP,
                DEPLOYMENT_WIDGET,
                DEPLOYMENT_CHATBOT,
                DEPLOYMENT_MCP,
                DEPLOYMENT_SCHEDULE,
                DEPLOYMENT_WEBHOOK,
            },
        ),
        (
            SURFACE_AUTHENTICATED_RUN_INFO,
            {
                DEPLOYMENT_API,
                DEPLOYMENT_WEBAPP,
                DEPLOYMENT_WIDGET,
                DEPLOYMENT_CHATBOT,
                DEPLOYMENT_MCP,
                DEPLOYMENT_SCHEDULE,
                DEPLOYMENT_WEBHOOK,
            },
        ),
        (
            SURFACE_AUTHENTICATED_RUN,
            {
                DEPLOYMENT_API,
                DEPLOYMENT_WEBAPP,
                DEPLOYMENT_WIDGET,
                DEPLOYMENT_CHATBOT,
                DEPLOYMENT_MCP,
                DEPLOYMENT_SCHEDULE,
                DEPLOYMENT_WEBHOOK,
            },
        ),
        (SURFACE_API_SECRET_RUN, {DEPLOYMENT_API}),
        (
            SURFACE_APP_PUBLIC_RUN,
            {DEPLOYMENT_WEBAPP, DEPLOYMENT_WIDGET, DEPLOYMENT_CHATBOT},
        ),
        (SURFACE_WEBHOOK_RUN, {DEPLOYMENT_WEBHOOK}),
        (SURFACE_SCHEDULE_RUN, {DEPLOYMENT_SCHEDULE}),
        (SURFACE_WORKFLOW_NODE_CHILD_RUN, {DEPLOYMENT_WORKFLOW_NODE}),
    ],
)
def test_runtime_surface_matrix_allows_only_documented_types(surface, allowed):
    all_types = {
        DEPLOYMENT_API,
        DEPLOYMENT_WEBAPP,
        DEPLOYMENT_WIDGET,
        DEPLOYMENT_CHATBOT,
        DEPLOYMENT_MCP,
        DEPLOYMENT_WORKFLOW_NODE,
        DEPLOYMENT_SCHEDULE,
        DEPLOYMENT_WEBHOOK,
    }

    assert allowed_deployment_types_for_surface(surface) == allowed
    for deployment_type in all_types:
        assert (
            is_deployment_type_allowed_for_surface(deployment_type, surface)
            is (deployment_type in allowed)
        )


def test_runtime_policy_fails_closed_for_unknown_surface_or_type():
    unknown_surface = evaluate_deployment_runtime_surface(DEPLOYMENT_API, "future")
    assert unknown_surface.allowed is False
    assert unknown_surface.reason == "unknown_surface"

    unknown_type = evaluate_deployment_runtime_surface("future", SURFACE_PUBLIC_INFO)
    assert unknown_type.allowed is False
    assert unknown_type.reason == "deployment_type_not_allowed_for_surface"


def test_runtime_policy_normalizes_enum_like_values():
    assert deployment_type_value(FakeDeploymentType.API) == "api"
    assert is_deployment_type_allowed_for_surface(
        FakeDeploymentType.API,
        SURFACE_API_SECRET_RUN,
    )
    assert not is_deployment_type_allowed_for_surface(
        FakeDeploymentType.WORKFLOW_NODE,
        SURFACE_AUTHENTICATED_RUN,
    )


@pytest.mark.parametrize(
    ("trigger_mode", "surface", "deployment_type"),
    [
        ("api", SURFACE_API_SECRET_RUN, DEPLOYMENT_API),
        ("api_secret", SURFACE_API_SECRET_RUN, DEPLOYMENT_API),
        ("app", SURFACE_APP_PUBLIC_RUN, DEPLOYMENT_CHATBOT),
        ("webhook", SURFACE_WEBHOOK_RUN, DEPLOYMENT_WEBHOOK),
        ("schedule", SURFACE_SCHEDULE_RUN, DEPLOYMENT_SCHEDULE),
        ("workflow_node", SURFACE_WORKFLOW_NODE_CHILD_RUN, DEPLOYMENT_WORKFLOW_NODE),
    ],
)
def test_trigger_mode_maps_to_surface(trigger_mode, surface, deployment_type):
    assert trigger_mode_to_surface(trigger_mode) == surface
    assert is_deployment_type_allowed_for_trigger(deployment_type, trigger_mode)


def test_unknown_trigger_mode_fails_closed():
    assert trigger_mode_to_surface("future") is None
    assert not is_deployment_type_allowed_for_trigger(DEPLOYMENT_API, "future")
