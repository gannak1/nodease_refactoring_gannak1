import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.shared.db.base import Base

if TYPE_CHECKING:
    from apps.shared.db.models.user import User


class Organization(Base):
    __tablename__ = "organization"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_teams_tenant_name"),
    )

    # 고유 ID
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    # 상위 조직 ID
    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True, 
    )
    # 조직 이름
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # DB에 조직을 누가 넣었는지 ID
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    # 조직 관리자 ID
    managed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )

    # 비활성화 여부
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 생성 시간
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # 가장 최근 수정 시간
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    # 비활성화 시간
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 연관관계 매핑
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])
    manager: Mapped[Optional["User"]] = relationship("User", foreign_keys=[managed_by])