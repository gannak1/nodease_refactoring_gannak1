"""Store safe Judge task requirements for local routing learning.

Revision ID: c4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-20 10:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "c4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_node_model_routing_learning_labels",
        sa.Column("task_requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_node_model_routing_learning_labels", "task_requirements")
