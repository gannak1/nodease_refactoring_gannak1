"""tracing payload 보안 경계 보강

Revision ID: c0d1e2f3a4b5
Revises: f7a8b9c0d1e2
Create Date: 2026-06-25 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("retention_purged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_workflow_runs_retention_purged_at",
        "workflow_runs",
        ["retention_purged_at"],
        unique=False,
    )

    op.add_column(
        "trace_payloads",
        sa.Column("retention_purged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_trace_payloads_retention_purged_at",
        "trace_payloads",
        ["retention_purged_at"],
        unique=False,
    )
    op.drop_column("trace_payloads", "raw_payload_hash")
    op.create_index(
        "ix_trace_payloads_latest_view",
        "trace_payloads",
        [
            "workflow_run_id",
            "scope",
            "workflow_node_run_id",
            "payload_kind",
            "created_at",
            "sequence",
            "attempt",
        ],
        unique=False,
    )
    op.create_index(
        "ix_trace_payloads_retention_scan",
        "trace_payloads",
        ["retention_purged_at", "payload_kind", "created_at", "retention_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_trace_payloads_raw_retention",
        "trace_payloads",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("raw_payload_encrypted IS NOT NULL"),
    )

    op.drop_constraint(
        "trace_payload_access_events_actor_user_id_fkey",
        "trace_payload_access_events",
        type_="foreignkey",
    )
    op.alter_column(
        "trace_payload_access_events",
        "actor_user_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_trace_payload_access_events_actor_user_id",
        "trace_payload_access_events",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "trace_payload_access_events",
        sa.Column("actor_user_ref", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_trace_payload_access_events_actor_user_ref",
        "trace_payload_access_events",
        ["actor_user_ref"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trace_payload_access_events_actor_user_ref",
        table_name="trace_payload_access_events",
    )
    op.drop_column("trace_payload_access_events", "actor_user_ref")
    op.drop_constraint(
        "fk_trace_payload_access_events_actor_user_id",
        "trace_payload_access_events",
        type_="foreignkey",
    )
    op.alter_column(
        "trace_payload_access_events",
        "actor_user_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_foreign_key(
        "trace_payload_access_events_actor_user_id_fkey",
        "trace_payload_access_events",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_index("ix_trace_payloads_raw_retention", table_name="trace_payloads")
    op.drop_index("ix_trace_payloads_retention_scan", table_name="trace_payloads")
    op.drop_index("ix_trace_payloads_latest_view", table_name="trace_payloads")
    op.add_column(
        "trace_payloads",
        sa.Column("raw_payload_hash", sa.String(length=128), nullable=True),
    )
    op.drop_index("ix_trace_payloads_retention_purged_at", table_name="trace_payloads")
    op.drop_column("trace_payloads", "retention_purged_at")

    op.drop_index(
        "ix_workflow_runs_retention_purged_at",
        table_name="workflow_runs",
    )
    op.drop_column("workflow_runs", "retention_purged_at")
