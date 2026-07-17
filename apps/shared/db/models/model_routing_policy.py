import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from apps.shared.db.base import Base
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column


class LLMNodeModelRoutingPolicy(Base):
    """배포된 workflow의 LLM node가 사용할 자동 모델 라우팅 정책 snapshot."""

    __tablename__ = "llm_node_model_routing_policies"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "deployment_id",
            "node_id",
            name="uq_model_routing_policy_workflow_deployment_node",
        ),
        Index(
            "ix_model_routing_policy_runtime_lookup",
            "workflow_id",
            "deployment_id",
            "node_id",
            "enabled",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow_deployments.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String, nullable=False)
    bootstrap_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("llm_node_model_routing_bootstraps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="초기 난이도 분류 artifact. 배포 policy는 이 bootstrap의 task fingerprint를 따른다.",
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="collecting"
    )
    policy_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    active_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    performance_checkpoint: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    pending_policy: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    refresh_every_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    eligible_runs_since_last_refresh: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    refresh_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_refresh_result: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    judge_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # 배포 실행자가 실제로 사용할 수 있는 credential/model만 정책에 들어가게 한다.
    execution_subject_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    validation_budget_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=3
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LLMNodeModelRoutingBootstrap(Base):
    """초안 단계부터 존재할 수 있는 자동 라우팅 초기 학습 artifact."""

    __tablename__ = "llm_node_model_routing_bootstraps"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "node_id",
            "task_fingerprint",
            name="uq_model_routing_bootstrap_workflow_node_fingerprint",
        ),
        Index(
            "ix_model_routing_bootstrap_workflow_node_status",
            "workflow_id",
            "node_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id: Mapped[str] = mapped_column(String, nullable=False)
    task_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    task_description: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    default_model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    fallback_model_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    initial_budget_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=1
    )
    planner_model_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    planner_cost_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    classifier_artifact: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    generation_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    stale_reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LLMNodeModelRoutingBootstrapSample(Base):
    """Bootstrap이 사용한 안전 요약 표본. 원문 input/prompt는 저장하지 않는다."""

    __tablename__ = "llm_node_model_routing_bootstrap_samples"
    __table_args__ = (
        Index(
            "ix_model_routing_bootstrap_sample_bootstrap_ordinal",
            "bootstrap_id",
            "ordinal",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    bootstrap_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("llm_node_model_routing_bootstraps.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_node_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow_node_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    complexity_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("50"),
        comment="회귀형 요청 복잡도 점수(0~100). difficulty는 과거 정책 호환용 표시값이다.",
    )
    safe_input_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    feature_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    knowledge_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    output_format: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    planner_reason: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class LLMNodeModelRoutingPolicyUpdate(Base):
    """정책 refresh 시도와 judge safe summary를 남기는 감사 가능한 이력."""

    __tablename__ = "llm_node_model_routing_policy_updates"
    __table_args__ = (
        Index(
            "ix_model_routing_policy_update_policy_created", "policy_id", "created_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("llm_node_model_routing_policies.id", ondelete="CASCADE"),
        nullable=False,
    )
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    eligible_run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    excluded_run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    excluded_reason_summary: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    judge_provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    judge_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    judge_usage_log_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("llm_usage_logs.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    input_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    new_policy_version: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class LLMNodeModelRoutingPolicyRunEvent(Base):
    """정책 갱신 카운터에 반영된 배포 후 운영 run의 중복 방지 event."""

    __tablename__ = "llm_node_model_routing_policy_run_events"
    __table_args__ = (
        UniqueConstraint(
            "policy_id",
            "workflow_run_id",
            name="uq_model_routing_policy_run_event",
        ),
        Index(
            "ix_model_routing_policy_run_event_policy_created",
            "policy_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("llm_node_model_routing_policies.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class LLMNodeModelRoutingPerformance(Base):
    """배포 정책의 모델·입력 길이별 운영 성적 누계."""

    __tablename__ = "llm_node_model_routing_performances"
    __table_args__ = (
        UniqueConstraint(
            "policy_id",
            "model_id",
            "input_profile",
            name="uq_model_routing_performance_policy_model_profile",
        ),
        Index(
            "ix_model_routing_performance_policy_updated",
            "policy_id",
            "updated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("llm_node_model_routing_policies.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    input_profile: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown"
    )
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_pass_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_eval_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    downstream_success_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    downstream_eval_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    fallback_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 9), nullable=False, default=0
    )
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LLMModelRoutingGlobalProfile(Base):
    """모델 catalog에 연결되는 전역 라우팅 사전 지식 profile.

    이 row는 모든 workflow가 공유하지만, 실제 실행 성적은 여기에 누적하지
    않는다. 노드별·배포별 성적은 `LLMNodeModelRoutingPerformance`가 소유한다.
    """

    __tablename__ = "llm_model_routing_global_profiles"
    __table_args__ = (
        UniqueConstraint(
            "llm_model_id",
            name="uq_model_routing_global_profile_llm_model",
        ),
        Index(
            "ix_model_routing_global_profile_source_active",
            "source",
            "is_active",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    llm_model_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("llm_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    capability_tier: Mapped[str] = mapped_column(
        String(16), nullable=False, default="balanced"
    )
    quality_by_difficulty: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    uncertainty_by_difficulty: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    expected_latency_ms_by_input_profile: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    fallback_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), nullable=False, default=Decimal("0.02")
    )
    prior_strength: Mapped[Decimal] = mapped_column(
        Numeric(10, 3), nullable=False, default=Decimal("6")
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
