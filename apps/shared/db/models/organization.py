import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.shared.db.base import Base

if TYPE_CHECKING:
    from apps.shared.db.models.user import User


class Organization(Base):
    __tablename__ = "organization"
    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_organization_parent_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization.id"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    managed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
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
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])
    manager: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[managed_by]
    )


class OrganizationStructure(Base):
    """Closure table for fast organization ancestor/descendant lookups."""

    __tablename__ = "organization_structure"
    __table_args__ = (
        CheckConstraint(
            "depth >= 0",
            name="ck_organization_structure_depth_nonnegative",
        ),
    )

    ancestor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization.id"),
        primary_key=True,
        nullable=False,
    )
    descendant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization.id"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False)

    ancestor: Mapped["Organization"] = relationship(
        "Organization",
        foreign_keys=[ancestor_id],
    )
    descendant: Mapped["Organization"] = relationship(
        "Organization",
        foreign_keys=[descendant_id],
    )
