import uuid
from datetime import datetime, timezone
from typing import Optional

from apps.shared.db.base import Base
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


class AgentBuilderSession(Base):
    __tablename__ = "agent_builder_sessions"
    __table_args__ = (
        Index("ix_agent_builder_sessions_user_org", "user_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    workflow_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    app_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("apps.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    protocol_version: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
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
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    requests: Mapped[list["AgentBuilderRequest"]] = relationship(
        "AgentBuilderRequest", back_populates="session"
    )


class AgentBuilderRequest(Base):
    __tablename__ = "agent_builder_requests"
    __mapper_args__ = {"eager_defaults": False}
    __table_args__ = (
        Index("ix_agent_builder_requests_session_status", "session_id", "status"),
        CheckConstraint(
            "intent_cache_outcome IS NULL OR intent_cache_outcome IN "
            "('disabled', 'hit', 'miss', 'bypass', 'error')",
            name="ck_agent_builder_requests_intent_cache_outcome",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_builder_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    intent_cache_outcome: Mapped[Optional[str]] = mapped_column(
        String(16),
        nullable=True,
        server_default=FetchedValue(),
        deferred=True,
    )
    message_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    structured_request: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    response_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    canceled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    session: Mapped[AgentBuilderSession] = relationship(
        "AgentBuilderSession", back_populates="requests"
    )
    draft: Mapped[Optional["AgentBuilderDraft"]] = relationship(
        "AgentBuilderDraft", back_populates="request", uselist=False
    )


class AgentBuilderIntentPlanCacheRecord(Base):
    """Encrypted organization-scoped L2 candidate; never a request replay."""

    __tablename__ = "agent_builder_intent_plan_cache_records"
    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at",
            name="ck_agent_builder_intent_plan_cache_records_expiry",
        ),
        CheckConstraint(
            "envelope_version = 1",
            name="ck_agent_builder_intent_plan_cache_records_envelope_version",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_agent_builder_intent_plan_cache_records_org_id",
        ),
        Index(
            "uq_agent_builder_intent_plan_cache_records_lookup",
            "organization_id",
            "lookup_key_version",
            "lookup_token",
            unique=True,
        ),
        Index(
            "ix_agent_builder_intent_plan_cache_records_expires_at",
            "expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False,
    )
    lookup_key_version: Mapped[str] = mapped_column(String(128), nullable=False)
    lookup_token: Mapped[str] = mapped_column(String(64), nullable=False)
    envelope_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    envelope_mac: Mapped[str] = mapped_column(String(64), nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(128), nullable=False)
    encryption_algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    envelope_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class AgentBuilderIntentPlanSemanticCacheEntry(Base):
    """Private derived-sensitive vector index into an encrypted L2 plan row."""

    __tablename__ = "agent_builder_intent_plan_semantic_cache_entries"
    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at",
            name="ck_agent_builder_semantic_cache_expiry",
        ),
        ForeignKeyConstraint(
            ("organization_id", "intent_plan_record_id"),
            (
                "agent_builder_intent_plan_cache_records.organization_id",
                "agent_builder_intent_plan_cache_records.id",
            ),
            name="fk_agent_builder_semantic_cache_parent_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "intent_plan_record_id",
            "user_id",
            "generation_mode",
            "semantic_query_projection_version",
            "embedding_profile_version",
            "embedding_model_version",
            "planner_contract_version",
            "catalog_version",
            "normalizer_version",
            "rehydration_contract_version",
            name="uq_agent_builder_semantic_cache_parent_profile_contract",
        ),
        Index(
            "ix_agent_builder_semantic_cache_scope_versions_expiry",
            "organization_id",
            "user_id",
            "generation_mode",
            "semantic_query_projection_version",
            "embedding_profile_version",
            "embedding_model_version",
            "planner_contract_version",
            "catalog_version",
            "normalizer_version",
            "rehydration_contract_version",
            "expires_at",
        ),
        Index(
            "ix_agent_builder_semantic_cache_expires_at",
            "expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    intent_plan_record_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    generation_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    semantic_query_projection_version: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    embedding_profile_version: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    embedding_model_version: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    planner_contract_version: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    catalog_version: Mapped[int] = mapped_column(Integer, nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(128), nullable=False)
    rehydration_contract_version: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    safe_query_embedding: Mapped[list[float]] = mapped_column(
        Vector(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AgentBuilderDraft(Base):
    __tablename__ = "agent_builder_drafts"
    __table_args__ = (
        Index("ix_agent_builder_drafts_session_status", "session_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_builder_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_builder_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    draft_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    workflow_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    app_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("apps.id", ondelete="SET NULL"), nullable=True
    )
    preview_graph: Mapped[dict] = mapped_column(JSONB, nullable=False)
    node_detail_previews: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    validation_result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    draft_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    base_graph_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    base_workflow_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ready", server_default="ready"
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
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    request: Mapped[AgentBuilderRequest] = relationship(
        "AgentBuilderRequest", back_populates="draft"
    )
