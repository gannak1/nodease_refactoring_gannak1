from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AdminUsagePeriodResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start_at: datetime = Field(alias="startAt")
    end_at: datetime = Field(alias="endAt")


class AdminWorkflowUsageItem(BaseModel):
    workflow_id: UUID
    workflow_name: str
    prompt_tokens: int
    completion_tokens: int
    call_count: int
    total_cost: float


class AdminWorkflowUsageResponse(BaseModel):
    total: int
    period: AdminUsagePeriodResponse
    items: list[AdminWorkflowUsageItem]
