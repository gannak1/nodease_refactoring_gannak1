from typing import get_args

from apps.gateway.services.resource_permission_registry import (
    permission_model_and_filters,
    registered_resource_types,
    resource_permission_spec,
)
from apps.shared.db.models.knowledge import KnowledgeBase
from apps.shared.db.models.llm import LLMCredential
from apps.shared.db.models.team import (
    TeamKnowledgePermission,
    TeamLLMPermission,
    TeamWorkflowPermission,
    UserKnowledgePermission,
    UserLLMPermission,
    UserWorkflowPermission,
)
from apps.shared.db.models.workflow import Workflow
from apps.shared.schemas.team import (
    ResourcePermissionGrantRequest,
    ResourcePermissionListResponse,
    ResourcePermissionRevokeRequest,
)


def _literal_values(model, field_name: str) -> set[str]:
    return set(get_args(model.model_fields[field_name].annotation))


def test_registry_resource_types_match_public_schemas():
    registry_types = registered_resource_types()

    assert registry_types == _literal_values(
        ResourcePermissionGrantRequest,
        "resource_type",
    )
    assert registry_types == _literal_values(
        ResourcePermissionRevokeRequest,
        "resource_type",
    )
    assert registry_types == _literal_values(
        ResourcePermissionListResponse,
        "resource_type",
    )


def test_registry_maps_resource_targets_and_permission_tables():
    workflow = resource_permission_spec("workflow")
    assert workflow.target_model is Workflow
    assert workflow.team_route.model is TeamWorkflowPermission
    assert workflow.user_route.model is UserWorkflowPermission

    knowledge = resource_permission_spec("knowledge_base")
    assert knowledge.target_model is KnowledgeBase
    assert knowledge.team_route.model is TeamKnowledgePermission
    assert knowledge.user_route.model is UserKnowledgePermission

    llm = resource_permission_spec("llm_credential")
    assert llm.target_model is LLMCredential
    assert llm.team_route.model is TeamLLMPermission
    assert llm.user_route.model is UserLLMPermission


def test_knowledge_base_route_cannot_fall_back_to_llm_or_workflow_tables():
    team_model, team_filters = permission_model_and_filters(
        resource_type="knowledge_base",
        grantee_type="team",
        resource_id="kb-1",
        grantee_id="team-1",
    )
    user_model, user_filters = permission_model_and_filters(
        resource_type="knowledge_base",
        grantee_type="user",
        resource_id="kb-1",
        grantee_id="user-1",
    )

    assert team_model is TeamKnowledgePermission
    assert team_filters == {
        "knowledge_base_id": "kb-1",
        "team_id": "team-1",
    }
    assert user_model is UserKnowledgePermission
    assert user_filters == {
        "knowledge_base_id": "kb-1",
        "user_id": "user-1",
    }
