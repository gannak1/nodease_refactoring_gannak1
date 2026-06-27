from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TeamCreateRequest(BaseModel):
    organization_id: UUID
    name: str
    description: Optional[str] = None
    is_auto_add: bool = False


class TeamUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    managed_by: Optional[UUID] = None
    is_auto_add: Optional[bool] = None


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
    description: Optional[str] = None
    created_by: UUID
    managed_by: Optional[UUID] = None
    is_active: bool
    is_auto_add: bool
    created_at: datetime
    updated_at: datetime


class PermissionMutationResponse(BaseModel):
    id: Optional[UUID] = None
    status: str
