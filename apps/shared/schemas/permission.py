from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

RESOURCE_AUTH_STATE_RANKS = {
    "workflow": {
        "none": 0,
        "viewer": 1,
        "operator": 2,
        "builder": 3,
        "manager": 4,
    },
    "knowledge_base": {
        "none": 0,
        "viewer": 1,
        "operator": 2,
        "builder": 3,
        "manager": 4,
    },
    "llm_credential": {
        "none": 0,
        "viewer": 1,
        "operator": 2,
        "builder": 3,
        "manager": 4,
    },
    "audit": {
        "none": 0,
        "auditor": 1,
        "raw_auditor": 2,
        "manager": 3,
    },
}

# auth_state ranks follow docs/data-model/rbac-permission-policy.md resource matrices.
WORKFLOW_AUTH_STATE_RANK = RESOURCE_AUTH_STATE_RANKS["workflow"]
KNOWLEDGE_AUTH_STATE_RANK = RESOURCE_AUTH_STATE_RANKS["knowledge_base"]
LLM_AUTH_STATE_RANK = RESOURCE_AUTH_STATE_RANKS["llm_credential"]
AUDIT_AUTH_STATE_RANK = RESOURCE_AUTH_STATE_RANKS["audit"]

WORKFLOW_AUTH_STATES = set(WORKFLOW_AUTH_STATE_RANK)
KNOWLEDGE_AUTH_STATES = set(KNOWLEDGE_AUTH_STATE_RANK)
LLM_AUTH_STATES = set(LLM_AUTH_STATE_RANK)
AUDIT_AUTH_STATES = set(AUDIT_AUTH_STATE_RANK)


def _normalize_auth_state(value: str, allowed_states: set[str]) -> str:
    """Normalize and validate an auth_state value against one resource matrix."""
    normalized = value.strip().lower()
    if normalized not in allowed_states:
        allowed = ", ".join(sorted(allowed_states))
        raise ValueError(f"auth_state must be one of: {allowed}")
    return normalized


class WorkflowPermissionGrantRequest(BaseModel):
    auth_state: str

    @field_validator("auth_state")
    @classmethod
    def validate_workflow_auth_state(cls, value: str) -> str:
        return _normalize_auth_state(value, WORKFLOW_AUTH_STATES)


class KnowledgePermissionGrantRequest(BaseModel):
    auth_state: str

    @field_validator("auth_state")
    @classmethod
    def validate_knowledge_auth_state(cls, value: str) -> str:
        return _normalize_auth_state(value, KNOWLEDGE_AUTH_STATES)


class LLMPermissionGrantRequest(BaseModel):
    auth_state: str

    @field_validator("auth_state")
    @classmethod
    def validate_llm_auth_state(cls, value: str) -> str:
        return _normalize_auth_state(value, LLM_AUTH_STATES)


class AuditPermissionGrantRequest(BaseModel):
    auth_state: str

    @field_validator("auth_state")
    @classmethod
    def validate_audit_auth_state(cls, value: str) -> str:
        return _normalize_auth_state(value, AUDIT_AUTH_STATES)


class PermissionGrantRequest(WorkflowPermissionGrantRequest):
    """Backward-compatible alias for workflow permission grant requests."""


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


class UserLLMPermissionResponse(BaseModel):
    """user direct LLM credential permission upsert 응답 schema."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    grantee_organization_id: UUID
    llm_credential_id: UUID
    user_id: UUID
    auth_state: str
    assigned_by: UUID
    assigned_at: datetime
    options: dict[str, Any]
    flags: int
