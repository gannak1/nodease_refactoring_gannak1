import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.shared.db.base import Base

if TYPE_CHECKING:
    from apps.shared.db.models.organization import Organization
    from apps.shared.db.models.team import TeamPermission
    from apps.shared.db.models.user import User


class UserTeamPermissions(Base):
    __tablename__ = "user_team_permissions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "team_permission_id",
            name="uq_user_team_permissions_tenant_user_permission",
        ),
    )

    # 고유 ID
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    # 조직 ID, organization 아이디 참조
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    # 유저 ID, user 아이디 참조
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # 팀 아이디, team_permission 아이디 참조
    team_permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("team_permission.id"),
        nullable=False,
        index=True,
    )
    # tag 부여한 user의 야이디
    assigned_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # tag 부여한 시점
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # 연관관계 매핑
    organization: Mapped["Organization"] = relationship("Organization")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    team_permission: Mapped["TeamPermission"] = relationship("TeamPermission")
    assigner: Mapped["User"] = relationship("User", foreign_keys=[assigned_by])
