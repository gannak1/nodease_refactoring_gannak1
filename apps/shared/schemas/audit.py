from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from apps.shared.db.models.audit_log import ActorType, AuditCategory, AuditStatus
from pydantic import BaseModel, ConfigDict, Field


class AuditLogSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    occurred_at: datetime
    actor_id: Optional[UUID]
    actor_type: ActorType
    category: AuditCategory
    action: str
    target_type: Optional[str]
    target_id: Optional[str]
    status: AuditStatus
    request_id: Optional[str] = None


class AuditLogListResponse(BaseModel):
    total: int
    items: List[AuditLogSchema]


class AuditChangeSummary(BaseModel):
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


class AuditLogDetailResponse(AuditLogSchema):
    audit_metadata: dict[str, Any] = Field(default_factory=dict)
    change_summary: AuditChangeSummary | None = None
