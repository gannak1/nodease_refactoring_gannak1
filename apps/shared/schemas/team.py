from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
