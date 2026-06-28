from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_by: UUID
    managed_by: Optional[UUID] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    is_manager: bool = False
