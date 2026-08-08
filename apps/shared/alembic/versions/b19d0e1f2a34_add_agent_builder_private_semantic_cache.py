"""Add the private Agent Builder dense semantic intent-plan index.

Revision ID: b19d0e1f2a34
Revises: b18c9d0e1f23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b19d0e1f2a34"
down_revision: str | Sequence[str] | None = "b18c9d0e1f23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEMANTIC_DOWNGRADE_GUARD = (
    "Cannot remove Agent Builder semantic cache while entries exist."
)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_agent_builder_intent_plan_cache_records_org_id",
        "agent_builder_intent_plan_cache_records",
        ("organization_id", "id"),
    )
    op.create_table(
        "agent_builder_intent_plan_semantic_cache_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "intent_plan_record_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("generation_mode", sa.String(length=32), nullable=False),
        sa.Column(
            "semantic_query_projection_version",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("embedding_profile_version", sa.String(length=128), nullable=False),
        sa.Column("embedding_model_version", sa.String(length=128), nullable=False),
        sa.Column("planner_contract_version", sa.String(length=128), nullable=False),
        sa.Column("catalog_version", sa.Integer(), nullable=False),
        sa.Column("normalizer_version", sa.String(length=128), nullable=False),
        sa.Column(
            "rehydration_contract_version", sa.String(length=128), nullable=False
        ),
        sa.Column("safe_query_embedding", Vector(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_agent_builder_semantic_cache_expiry",
        ),
        sa.ForeignKeyConstraint(
            ("organization_id",),
            ("organization.id",),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("user_id",),
            ("users.id",),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("organization_id", "intent_plan_record_id"),
            (
                "agent_builder_intent_plan_cache_records.organization_id",
                "agent_builder_intent_plan_cache_records.id",
            ),
            name="fk_agent_builder_semantic_cache_parent_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
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
    )
    op.create_index(
        "ix_agent_builder_semantic_cache_scope_versions_expiry",
        "agent_builder_intent_plan_semantic_cache_entries",
        (
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
        unique=False,
    )
    op.create_index(
        "ix_agent_builder_semantic_cache_expires_at",
        "agent_builder_intent_plan_semantic_cache_entries",
        ("expires_at",),
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(
        sa.text(
            "SELECT 1 FROM agent_builder_intent_plan_semantic_cache_entries LIMIT 1"
        )
    ).first():
        raise RuntimeError(SEMANTIC_DOWNGRADE_GUARD)
    op.drop_index(
        "ix_agent_builder_semantic_cache_expires_at",
        table_name="agent_builder_intent_plan_semantic_cache_entries",
    )
    op.drop_index(
        "ix_agent_builder_semantic_cache_scope_versions_expiry",
        table_name="agent_builder_intent_plan_semantic_cache_entries",
    )
    op.drop_table("agent_builder_intent_plan_semantic_cache_entries")
    op.drop_constraint(
        "uq_agent_builder_intent_plan_cache_records_org_id",
        "agent_builder_intent_plan_cache_records",
        type_="unique",
    )
