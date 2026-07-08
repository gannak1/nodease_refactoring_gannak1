from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from apps.shared.schemas.permission import WorkflowPermissionSource


class AppIcon(BaseModel):
    type: str
    content: str
    background_color: str


class AppCreateRequest(BaseModel):
    """앱 생성 요청 스키마"""

    name: str
    description: Optional[str] = None
    icon: AppIcon
    is_market: bool = False


class AppUpdateRequest(BaseModel):
    """앱 수정 요청 스키마"""

    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[AppIcon] = None
    is_market: Optional[bool] = None


class AppBudgetStatus(BaseModel):
    usage_ratio: float
    status: Literal["normal", "at_risk", "exceeded"]


class AppOperationMetrics(BaseModel):
    current_month_cost: float
    projected_month_cost: Optional[float] = None
    previous_month_cost: float
    trend_percent: Optional[float] = None


class AppResponse(BaseModel):
    """앱 응답 스키마"""

    id: UUID
    name: str
    description: Optional[str]
    icon: AppIcon
    workflow_id: Optional[UUID] = None  # App의 작업실 Workflow
    url_slug: Optional[str] = None  # 첫 배포 시 생성
    auth_secret: Optional[str] = None  # Webhook 인증용 시크릿
    is_market: bool
    forked_from: Optional[UUID] = None
    active_deployment_id: Optional[UUID] = None
    active_deployment_type: Optional[str] = None
    active_deployment_is_active: Optional[bool] = None  # 활성 배포의 is_active 상태
    owner_name: Optional[str] = None  # UI 표시용 (생성자 이름)
    budget_status: Optional[AppBudgetStatus] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AppOperationAppSummary(BaseModel):
    """Safe app summary for the module operations list."""

    id: UUID
    name: str
    description: Optional[str] = None
    icon: Optional[AppIcon] = None
    workflow_id: Optional[UUID] = None
    owner_name: Optional[str] = None
    budget_status: Optional[AppBudgetStatus] = None
    operation_metrics: Optional[AppOperationMetrics] = None
    created_at: datetime
    updated_at: datetime


class AppOperationPermissionSummary(BaseModel):
    workflow_id: UUID
    organization_id: Optional[UUID] = None
    auth_state: str
    can_read: bool
    can_write: bool
    can_execute: bool
    can_deploy: bool
    can_manage: bool


class AppOperationDeploymentSummary(BaseModel):
    state: Literal["active", "inactive", "undeployed"]
    deployment_id: Optional[UUID] = None
    type: Optional[str] = None
    is_active: Optional[bool] = None


class AppOperationLatestRunSummary(BaseModel):
    state: Literal["running", "success", "failed", "not_started", "unavailable"]
    run_id: Optional[UUID] = None
    raw_status: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None


class AppOperationRow(BaseModel):
    app: AppOperationAppSummary
    permission: Optional[AppOperationPermissionSummary] = None
    permission_status: Literal["loaded", "failed", "not_available"]
    permission_sources: list[WorkflowPermissionSource] = Field(default_factory=list)
    permission_error: Optional[str] = None
    deployment: AppOperationDeploymentSummary
    latest_run: AppOperationLatestRunSummary
