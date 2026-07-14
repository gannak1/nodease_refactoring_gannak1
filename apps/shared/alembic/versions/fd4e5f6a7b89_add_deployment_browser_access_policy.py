"""Add immutable deployment browser access policy.

Revision ID: fd4e5f6a7b89
Revises: 0f4a5b6c7d89
Create Date: 2026-07-14 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "fd4e5f6a7b89"
down_revision: Union[str, Sequence[str], None] = "0f4a5b6c7d89"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_deployments",
        sa.Column(
            "browser_access_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_deployments", "browser_access_policy")
