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


class AdminOrganizationSummaryResponse(BaseModel):
    month: str
    total_cost: float
    # 예산 관리 feature(PRD FR-051) 확정 전에는 budget 블록을 null로 반환한다.
    budget: None = None
