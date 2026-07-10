"""Add idempotent Cost Optimizer recommendation verification requests

Revision ID: fc9a1b2c3d4e
Revises: fb8c9d0e1f23
Create Date: 2026-07-11 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

from apps.shared.db.models.cost_optimizer import CostOptimizerRecommendationVerification


revision: str = "fc9a1b2c3d4e"
down_revision: Union[str, Sequence[str], None] = "fb8c9d0e1f23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    CostOptimizerRecommendationVerification.__table__.create(
        bind=op.get_bind(),
        checkfirst=True,
    )


def downgrade() -> None:
    CostOptimizerRecommendationVerification.__table__.drop(
        bind=op.get_bind(),
        checkfirst=True,
    )
