"""Add user direct resource permissions

Revision ID: e1f2a3b4c5d6
Revises: c2d3e4f5a6b7
Create Date: 2026-06-27 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_direct_permission_table(
    table_name: str,
    resource_column: str,
    resource_table: str,
    unique_name: str,
    check_name: str,
) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("grantee_organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(resource_column, sa.UUID(), nullable=False),
        sa.Column(
            "auth_state",
            sa.String(length=50),
            nullable=False,
            server_default="none",
        ),
        sa.Column("assigned_by", sa.UUID(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("flags", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("flags >= 0", name=check_name),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["grantee_organization_id"], ["organization.id"]),
        sa.ForeignKeyConstraint([resource_column], [f"{resource_table}.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "grantee_organization_id",
            "user_id",
            resource_column,
            name=unique_name,
        ),
    )
    op.create_index(f"ix_{table_name}_assigned_by", table_name, ["assigned_by"])
    op.create_index(
        f"ix_{table_name}_grantee_organization_id",
        table_name,
        ["grantee_organization_id"],
    )
    op.create_index(f"ix_{table_name}_{resource_column}", table_name, [resource_column])
    op.create_index(f"ix_{table_name}_user_id", table_name, ["user_id"])
    op.alter_column(table_name, "auth_state", server_default=None)


def upgrade() -> None:
    _create_direct_permission_table(
        "user_workflow_permissions",
        "workflow_id",
        "workflows",
        "uq_user_workflow_permissions_org_user_workflow",
        "ck_user_workflow_permissions_flags_nonnegative",
    )
    _create_direct_permission_table(
        "user_llm_permissions",
        "llm_credential_id",
        "llm_credentials",
        "uq_user_llm_permissions_org_user_credential",
        "ck_user_llm_permissions_flags_nonnegative",
    )


def downgrade() -> None:
    for table_name, resource_column in (
        ("user_llm_permissions", "llm_credential_id"),
        ("user_workflow_permissions", "workflow_id"),
    ):
        op.drop_index(f"ix_{table_name}_user_id", table_name=table_name)
        op.drop_index(f"ix_{table_name}_{resource_column}", table_name=table_name)
        op.drop_index(
            f"ix_{table_name}_grantee_organization_id", table_name=table_name
        )
        op.drop_index(f"ix_{table_name}_assigned_by", table_name=table_name)
        op.drop_table(table_name)
