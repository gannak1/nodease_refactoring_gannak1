import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.db.base import Base


class BudgetAlertState(Base):
    """예산 알림 전이 원장 (docs/features/budget-alerts).

    (workflow, 당월)당 1 row로 마지막 알린 상태(high-water mark)를 유지한다.
    상향 전이 감지와 중복 방지(BGA-REQ-011)의 원천이다.
    """

    __tablename__ = "budget_alert_states"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "period_month",
            name="uq_budget_alert_states_workflow_month",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    last_notified_status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )


class BudgetAlert(Base):
    """예산 알림 수신자별 항목 (docs/features/budget-alerts).

    한 상향 전이가 수신자(제작자 + 조직 관리자)별로 1 row씩 생성된다.
    표시값은 발생 시점 스냅샷이고(BGA-REQ-031), read_at은 사용자별 읽음 여부다.
    """

    __tablename__ = "budget_alerts"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "period_month",
            "status",
            "user_id",
            name="uq_budget_alerts_workflow_month_status_user",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization.id"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # 스냅샷 수치는 월 누적 비용/비율(예산 초과 포함)을 담으므로 예산 정수부(10자리) 이상.
    usage_ratio: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    monthly_budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_month_cost: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
