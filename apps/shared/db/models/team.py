import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from apps.shared.db.base import Base

if TYPE_CHECKING:
    from apps.shared.db.models.organization import Organization
    from apps.shared.db.models.user import User
    from apps.shared.db.models.workflow import Workflow


class TeamPermission(Base):
    __tablename__ = "team_permission"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_permission_team_organization_name",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    managed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_auto_add: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Permission state: none, read, write, execute, admin.
    auth_state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="none",
    )

    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])
    manager: Mapped[Optional["User"]] = relationship("User", foreign_keys=[managed_by])


class TeamPermissionAssignmentMixin:
    @declared_attr
    def organization_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("organization.id"),
            nullable=False,
            index=True,
        )

    @declared_attr
    def team_permission_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("team_permission.id"),
            nullable=False,
            index=True,
        )

    @declared_attr
    def assigned_by(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("users.id"),
            nullable=False,
            index=True,
        )

    @declared_attr
    def assigned_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(timezone.utc),
        )

    @declared_attr
    def organization(cls) -> Mapped["Organization"]:
        return relationship("Organization")

    @declared_attr
    def team_permission(cls) -> Mapped["TeamPermission"]:
        return relationship("TeamPermission")

    @declared_attr
    def assigner(cls) -> Mapped["User"]:
        return relationship("User", foreign_keys=lambda: [cls.assigned_by])


class UserTeamPermissions(TeamPermissionAssignmentMixin, Base):
    __tablename__ = "user_team_permissions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            "team_permission_id",
            name="uq_user_team_permissions_organization_user_permission",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])


class WorkflowTeamPermission(TeamPermissionAssignmentMixin, Base):
    __tablename__ = "workflow_team_permissions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "workflow_id",
            "team_permission_id",
            name="uq_workflow_team_permissions_organization_workflow_team",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id"),
        nullable=False,
        index=True,
    )

    workflow: Mapped["Workflow"] = relationship("Workflow")
