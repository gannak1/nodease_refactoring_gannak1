from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from apps.shared.db.base import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from apps.shared.db.models.organization import Organization
    from apps.shared.db.models.user import User


EXTERNAL_ACTION_CREDENTIAL_ACTIVE = "active"
EXTERNAL_ACTION_CREDENTIAL_REVOKED = "revoked"
EXTERNAL_ACTION_CREDENTIAL_STATUSES = {
    EXTERNAL_ACTION_CREDENTIAL_ACTIVE,
    EXTERNAL_ACTION_CREDENTIAL_REVOKED,
}
EXTERNAL_ACTION_CREDENTIAL_PROVIDERS = {
    "github",
    "slack_api",
    "slack_webhook",
}


class ExternalActionCredential(Base):
    """Organization-scoped encrypted credential for an external workflow action."""

    __tablename__ = "external_action_credentials"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_external_action_credentials_id_organization_id",
        ),
        CheckConstraint(
            "provider IN ('github', 'slack_api', 'slack_webhook')",
            name="ck_external_action_credentials_provider",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_external_action_credentials_status",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_external_action_credentials_revision_positive",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization.id"),
        nullable=False,
        index=True,
    )
    credential_name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    encryption_algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EXTERNAL_ACTION_CREDENTIAL_ACTIVE,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
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
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    organization: Mapped["Organization"] = relationship("Organization")
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])
