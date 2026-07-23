"""Merge Conversation Memory runtime and current development heads.

Revision ID: b19d0e1f2a34
Revises: b17c8d9e0f12, b18c9d0e1f23
"""

from collections.abc import Sequence

revision: str = "b19d0e1f2a34"
down_revision: str | Sequence[str] | None = (
    "b17c8d9e0f12",
    "b18c9d0e1f23",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
