"""Add INTERNAL_CHATBOT to DeploymentType enum.

Revision ID: fc9d0e1f2a34
Revises: fa7c8d9e0f12, fb8c9d0e1f23
Create Date: 2026-07-13 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "fc9d0e1f2a34"
down_revision: Union[str, Sequence[str], None] = (
    "fa7c8d9e0f12",
    "fb8c9d0e1f23",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the authenticated internal chatbot deployment type."""
    op.execute("COMMIT")
    op.execute(
        "ALTER TYPE deploymenttype ADD VALUE IF NOT EXISTS 'INTERNAL_CHATBOT'"
    )


def downgrade() -> None:
    """PostgreSQL enum values are not removed automatically."""
    pass
