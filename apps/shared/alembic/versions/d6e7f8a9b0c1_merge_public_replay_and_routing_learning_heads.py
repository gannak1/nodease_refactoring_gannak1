"""Merge public replay and routing learning migration heads.

Revision ID: d6e7f8a9b0c1
Revises: af4a5b6c7d83, c4e5f6a7b8c9
"""

from collections.abc import Sequence

revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = (
    "af4a5b6c7d83",
    "c4e5f6a7b8c9",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join independent additive migration branches without DDL."""


def downgrade() -> None:
    """Split the graph without changing schema objects."""
