import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.shared.db.base import Base

if TYPE_CHECKING:
    from apps.shared.db.models.user import User
    from apps.shared.db.models.organization import Organization


class TeamPermission(Base):
    __tablename__ = "team_permission"
    # 조직 아이디의 이름은 중복 불가
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_permission_team_tenant_name"),
    )

    # 고유 ID
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # 조직 ID, team ID에 FK
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    # 태그 이름
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 설명, 생략가능
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 태그를 만든 사용자 ID
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])
    # 태그를 관리하는 사용자 ID
    managed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    manager: Mapped[Optional["User"]] = relationship("User", foreign_keys=[managed_by])

    # 태그 활성화 여부, 
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 태그가 만들어진 시간
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # 가장 최근에 바뀐 시간
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # 태그 비활성화 시간
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 워크플로우 읽기 권한
    can_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 워크플로우 쓰기 권한
    can_write: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 워크플로우 실행권한
    can_execute: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 워크플로우 삭제 권한
    can_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 워크플로우 태그 관리 권한, 태그 이름 수정, 태그 권한값 변경, 태그 비활성화
    can_manage_tag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 워크플로우 태그 부여 권한, 팀이나 사용자에게 해당 태그를 부여
    can_assign_tag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
