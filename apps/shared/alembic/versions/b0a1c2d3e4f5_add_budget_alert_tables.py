"""Add budget alert tables (states ledger + per-recipient items)

두 head(c4d5e6f7a8b9, fa2b3c4d5e6f)를 병합하면서
budget_alert_states / budget_alerts 테이블을 생성한다.
docs/features/budget-alerts.

Revision ID: b0a1c2d3e4f5
Revises: c4d5e6f7a8b9, fa2b3c4d5e6f
Create Date: 2026-07-07 21:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "b0a1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = ("c4d5e6f7a8b9", "fa2b3c4d5e6f")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE budget_alert_states (
            id UUID PRIMARY KEY,
            workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            period_month VARCHAR(7) NOT NULL,
            last_notified_status VARCHAR(16) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_budget_alert_states_workflow_month
                UNIQUE (workflow_id, period_month)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_budget_alert_states_workflow_id "
        "ON budget_alert_states (workflow_id)"
    )

    op.execute(
        """
        CREATE TABLE budget_alerts (
            id UUID PRIMARY KEY,
            workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organization(id),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            period_month VARCHAR(7) NOT NULL,
            status VARCHAR(16) NOT NULL,
            usage_ratio NUMERIC(16, 6) NOT NULL,
            monthly_budget_usd NUMERIC(12, 2) NOT NULL,
            current_month_cost NUMERIC(16, 6) NOT NULL,
            read_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_budget_alerts_workflow_month_status_user
                UNIQUE (workflow_id, period_month, status, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_budget_alerts_workflow_id ON budget_alerts (workflow_id)"
    )
    op.execute(
        "CREATE INDEX ix_budget_alerts_organization_id "
        "ON budget_alerts (organization_id)"
    )
    op.execute("CREATE INDEX ix_budget_alerts_user_id ON budget_alerts (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS budget_alerts")
    op.execute("DROP TABLE IF EXISTS budget_alert_states")
