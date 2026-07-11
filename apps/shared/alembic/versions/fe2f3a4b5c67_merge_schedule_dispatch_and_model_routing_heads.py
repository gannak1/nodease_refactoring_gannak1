"""Merge schedule dispatch and model routing migration heads.

Revision ID: fe2f3a4b5c67
Revises: fd1e2f3a4b56, fb8c9d0e1f23
"""

from typing import Sequence, Union

revision: str = "fe2f3a4b5c67"
down_revision: Union[str, Sequence[str], None] = (
    "fd1e2f3a4b56",
    "fb8c9d0e1f23",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Join independent additive schema branches without DDL."""


def downgrade() -> None:
    """Restore both parent revisions; guards run in the schedule branch."""
