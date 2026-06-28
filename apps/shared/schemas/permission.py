from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

# Workflow auth_state는 docs/data-model/rbac-permission-policy.md의 matrix 순서대로 비교한다.
WORKFLOW_AUTH_STATE_RANK = {
    "none": 0,
    "viewer": 1,
    "operator": 2,
    "builder": 3,
    "manager": 4,
}
WORKFLOW_AUTH_STATES = set(WORKFLOW_AUTH_STATE_RANK)


class PermissionGrantRequest(BaseModel):
    auth_state: str

    @field_validator("auth_state")
    @classmethod
    def validate_workflow_auth_state(cls, value: str) -> str:
        """요청 auth_state를 표준 소문자 값으로 정규화한다."""
        normalized = value.strip().lower()
        if normalized not in WORKFLOW_AUTH_STATES:
            allowed = ", ".join(sorted(WORKFLOW_AUTH_STATES))
            raise ValueError(f"auth_state must be one of: {allowed}")
        return normalized


class TeamWorkflowPermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    grantee_organization_id: UUID
    workflow_id: UUID
    team_id: UUID
    auth_state: str
    assigned_by: UUID
    assigned_at: datetime
    options: dict[str, Any]
    flags: int


class TeamLLMPermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    grantee_organization_id: UUID
    llm_credential_id: UUID
    team_id: UUID
    auth_state: str
    assigned_by: UUID
    assigned_at: datetime
    options: dict[str, Any]
    flags: int


class UserWorkflowPermissionResponse(BaseModel):
    """user direct workflow permission upsert 응답 schema."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    grantee_organization_id: UUID
    workflow_id: UUID
    user_id: UUID
    auth_state: str
    assigned_by: UUID
    assigned_at: datetime
    options: dict[str, Any]
    flags: int
