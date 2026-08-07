"""Add encrypted Agent Builder durable intent-plan cache records.

Revision ID: b18c9d0e1f23
Revises: b17c8d9e0f12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b18c9d0e1f23"
down_revision: str | Sequence[str] | None = "b17c8d9e0f12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

L2_DOWNGRADE_GUARD = (
    "Cannot remove Agent Builder durable intent-plan cache while records exist."
)


def upgrade() -> None:
    op.create_table(
        "agent_builder_intent_plan_cache_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lookup_key_version", sa.String(length=128), nullable=False),
        sa.Column("lookup_token", sa.String(length=64), nullable=False),
        sa.Column("envelope_ciphertext", sa.Text(), nullable=False),
        sa.Column("envelope_mac", sa.String(length=64), nullable=False),
        sa.Column("encryption_key_version", sa.String(length=128), nullable=False),
        sa.Column("encryption_algorithm", sa.String(length=32), nullable=False),
        sa.Column(
            "envelope_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_agent_builder_intent_plan_cache_records_expiry",
        ),
        sa.CheckConstraint(
            "envelope_version = 1",
            name="ck_agent_builder_intent_plan_cache_records_envelope_version",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_agent_builder_intent_plan_cache_records_lookup",
        "agent_builder_intent_plan_cache_records",
        ["organization_id", "lookup_key_version", "lookup_token"],
        unique=True,
    )
    op.create_index(
        "ix_agent_builder_intent_plan_cache_records_expires_at",
        "agent_builder_intent_plan_cache_records",
        ["expires_at"],
        unique=False,
    )
    op.add_column(
        "agent_builder_requests",
        sa.Column("intent_cache_outcome", sa.String(length=16), nullable=True),
    )
    op.create_check_constraint(
        "ck_agent_builder_requests_intent_cache_outcome",
        "agent_builder_requests",
        "intent_cache_outcome IS NULL OR intent_cache_outcome IN "
        "('disabled', 'hit', 'miss', 'bypass', 'error')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    record_exists = connection.execute(
        sa.text(
            "SELECT 1 FROM agent_builder_intent_plan_cache_records LIMIT 1"
        )
    ).first()
    if record_exists is not None:
        raise RuntimeError(L2_DOWNGRADE_GUARD)

    op.drop_constraint(
        "ck_agent_builder_requests_intent_cache_outcome",
        "agent_builder_requests",
        type_="check",
    )
    op.drop_column("agent_builder_requests", "intent_cache_outcome")
    op.drop_index(
        "ix_agent_builder_intent_plan_cache_records_expires_at",
        table_name="agent_builder_intent_plan_cache_records",
    )
    op.drop_index(
        "uq_agent_builder_intent_plan_cache_records_lookup",
        table_name="agent_builder_intent_plan_cache_records",
    )
    op.drop_table("agent_builder_intent_plan_cache_records")
