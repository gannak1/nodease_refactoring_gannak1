from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TeamCreateRequest(BaseModel):
    organization_id: UUID
    name: str
    description: str | None = None
    is_auto_add: bool = False


class TeamUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    managed_by: UUID | None = None
    is_auto_add: bool | None = None


class TeamMembershipRequest(BaseModel):
    user_id: UUID


class ResourceAuthStateRequest(BaseModel):
    auth_state: str


class ResourcePermissionGrantRequest(BaseModel):
    organization_id: UUID
    resource_type: Literal["workflow", "llm_credential"]
    resource_id: UUID
    grantee_type: Literal["team", "user"]
    grantee_id: UUID
    auth_state: str


class ResourcePermissionRevokeRequest(BaseModel):
    organization_id: UUID
    resource_type: Literal["workflow", "llm_credential"]
    resource_id: UUID
    grantee_type: Literal["team", "user"]
    grantee_id: UUID


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    options: dict[str, Any]
    flags: int
    created_by: UUID
    managed_by: UUID | None
    is_active: bool
    is_auto_add: bool
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None


class PermissionMutationResponse(BaseModel):
    id: UUID | None = None
    status: str
