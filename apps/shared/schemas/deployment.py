from datetime import datetime
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from apps.shared.db.models.workflow_deployment import DeploymentType
from apps.shared.domain.workflow_node_binding import strip_workflow_node_bindings
from pydantic import BaseModel, ConfigDict, Field, field_serializer

DeploymentPreflightStatus = Literal["passed", "warning", "blocked"]
DeploymentPreflightAudience = Literal[
    "anonymous_public",
    "authenticated_user",
    "workflow_node_inherited",
]


class DeploymentBase(BaseModel):
    type: DeploymentType = DeploymentType.API
    url_slug: Optional[str] = Field(
        None, max_length=255, pattern=r"^[a-z0-9-]+$"
    )  # 소문자, 숫자, 하이픈만 허용
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = {}
    is_active: bool = True


class DeploymentCreate(DeploymentBase):
    app_id: UUID  # App ID
    # TODO: 프론트엔드에서 localStorage에 저장된 스냅샷을 보내주는 방식으로 변경
    # 현재는 백엔드에서 DB의 draft를 읽어서 저장함
    graph_snapshot: Optional[Dict[str, Any]] = None
    auth_secret: Optional[str] = None  # 생성 시에만 입력 가능


class DeploymentPreflightRequest(DeploymentBase):
    app_id: UUID
    graph_snapshot: Optional[Dict[str, Any]] = None
    audience: Optional[DeploymentPreflightAudience] = None


class DeploymentPreflightSummary(BaseModel):
    blocked_reason: Optional[str] = None
    affected_node_count: int = 0
    affected_kb_count_bucket: str = "0"
    affected_collection_count_bucket: str = "0"
    candidate_budget_limited: bool = False


class DeploymentPreflightRequiredAction(BaseModel):
    action: str
    label: str


class DeploymentPreflightNodeResult(BaseModel):
    node_id: Optional[str] = None
    node_type: str
    status: DeploymentPreflightStatus
    reason_codes: list[str] = Field(default_factory=list)
    knowledge_base_count_bucket: str = "0"
    knowledge_collection_count_bucket: str = "0"
    candidate_budget_limited: bool = False


class DeploymentPreflightResponse(BaseModel):
    status: DeploymentPreflightStatus
    audience: DeploymentPreflightAudience
    safe_summary: DeploymentPreflightSummary = Field(
        default_factory=DeploymentPreflightSummary
    )
    required_actions: list[DeploymentPreflightRequiredAction] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)
    nodes: list[DeploymentPreflightNodeResult] = Field(default_factory=list)


class DeploymentResponse(DeploymentBase):
    id: UUID
    app_id: UUID
    version: int
    auth_secret: Optional[str] = None  # 보안상 일부만 보여주거나 숨길 수 있음
    created_by: UUID
    created_at: datetime
    graph_snapshot: Dict[str, Any]
    input_schema: Optional[Dict[str, Any]] = None  # StartNode 입력 스키마
    output_schema: Optional[Dict[str, Any]] = None  # AnswerNode 출력 스키마

    class Config:
        from_attributes = True

    @field_serializer("graph_snapshot")
    def serialize_graph_snapshot(self, value: Dict[str, Any]) -> Dict[str, Any]:
        return strip_workflow_node_bindings(value)


class DeploymentInfoResponse(BaseModel):
    """공개 배포 정보 응답 (인증 불필요)"""

    url_slug: str
    name: str
    version: int
    description: Optional[str] = None
    type: str
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None


class DeploymentRunInfoResponse(BaseModel):
    """인증된 내부 실행 화면용 safe 배포 정보 응답"""

    deployment_id: UUID
    app_id: UUID
    workflow_id: UUID
    name: str
    version: int
    description: Optional[str] = None
    type: str
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None


class DeploymentConversationControl(BaseModel):
    """인증 실행의 legacy conversation namespace용 bounded client control."""

    model_config = ConfigDict(extra="forbid")

    client_id: UUID


class AuthenticatedDeploymentRunRequest(BaseModel):
    """인증 배포 실행 요청. Conversation control은 업무 inputs와 분리한다."""

    model_config = ConfigDict(extra="forbid")

    # Endpoint가 기존 400 계약을 유지하며 object 여부를 판정한다.
    inputs: Any = Field(default_factory=dict)
    conversation: Optional[DeploymentConversationControl] = None
