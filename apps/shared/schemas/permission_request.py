from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from apps.shared.db.models.permission_request import (
    PERMISSION_REQUEST_APPROVED,
    PERMISSION_REQUEST_PENDING,
    PERMISSION_REQUEST_REJECTED,
    REQUESTED_PERMISSION_APP_CREATE,
)

PERMISSION_REQUEST_STATUSES = {
    PERMISSION_REQUEST_PENDING,
    PERMISSION_REQUEST_APPROVED,
    PERMISSION_REQUEST_REJECTED,
}


class PermissionRequestCreateRequest(BaseModel):
    """권한 신청 제출 요청 (ADR-0016)."""

    reason: str
    requested_permission: str = REQUESTED_PERMISSION_APP_CREATE

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason must not be blank")
        return stripped

    @field_validator("requested_permission")
    @classmethod
    def validate_requested_permission(cls, value: str) -> str:
        if value != REQUESTED_PERMISSION_APP_CREATE:
            raise ValueError(
                f"requested_permission must be '{REQUESTED_PERMISSION_APP_CREATE}'"
            )
        return value


class PermissionRequestUserSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str


class PermissionRequestResponse(BaseModel):
    id: UUID
    user: Optional[PermissionRequestUserSchema] = None
    requested_permission: str
    reason: str
    status: str
    created_at: datetime
    decided_by: Optional[UUID] = None
    decided_at: Optional[datetime] = None


class PermissionRequestListResponse(BaseModel):
    total: int
    items: list[PermissionRequestResponse]
