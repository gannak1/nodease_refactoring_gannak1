"""Merge Cost Optimizer and schedule migration heads.

Revision ID: ff6d7e8f9012
Revises: fd0e1f2a3b4c, fe3f4a5b6c78
Create Date: 2026-07-11 23:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

from apps.shared.alembic.schedule_dispatch_downgrade import (
    assert_schedule_configuration_quarantine_downgrade_is_safe,
    assert_schedule_dispatch_downgrade_is_safe,
)


revision: str = "ff6d7e8f9012"
down_revision: Union[str, Sequence[str], None] = (
    "fd0e1f2a3b4c",
    "fe3f4a5b6c78",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """독립적으로 추가된 두 migration branch를 DDL 없이 합친다."""


def downgrade() -> None:
    """두 parent head로 graph를 분리하기 전에 schedule 안전성을 확인한다."""
    assert_schedule_dispatch_downgrade_is_safe(op.get_bind())
    assert_schedule_configuration_quarantine_downgrade_is_safe(op.get_bind())
