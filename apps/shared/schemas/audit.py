from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from apps.shared.db.models.audit_log import ActorType, AuditCategory, AuditStatus


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
