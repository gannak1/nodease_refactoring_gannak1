import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.db.base import Base


class ActorType(str, Enum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"


class AuditCategory(str, Enum):
    ACTION = "action"  # 사용자 행동 (계층 A)
    DATA_CHANGE = "data_change"  # 데이터 변경 이력 (계층 B)


class AuditStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"


class AuditLog(Base):
    """
    사용자 작업 감사(Audit) 로그 테이블.

    - 계층 A(action): 엔드포인트에서 발생한 의미 있는 사용자 행동
    - 계층 B(data_change): 추적 대상 모델의 변경 전/후(before/after)

    Append-only로 운영하며(생성만, 수정/삭제 없음), `relationship`은 의도적으로
    생략하고 `actor_id`로 직접 조회한다(기존 Connection/App 컨벤션).
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # 행위 주체. 유저 삭제 시에도 로그는 보존(append-only)되도록 SET NULL.
    # 누가 했는지는 audit_metadata.actor 스냅샷으로 별도 보존한다.
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_type: Mapped[ActorType] = mapped_column(
        SQLEnum(ActorType, name="audit_actor_type"), nullable=False
    )

    category: Mapped[AuditCategory] = mapped_column(
        SQLEnum(AuditCategory, name="audit_category"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    target_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    before: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    after: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    status: Mapped[AuditStatus] = mapped_column(
        SQLEnum(AuditStatus, name="audit_status"),
        nullable=False,
        default=AuditStatus.SUCCESS,
    )

    # ip, user_agent, request_id, actor 스냅샷 등 부가정보
    audit_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_audit_logs_target", "target_type", "target_id"),
    )
