"""Add adaptive model routing cohorts, evidence, and validation budgets.

Revision ID: f1c2d3e4f5a6
Revises: 0f4a5b6c7d89
Create Date: 2026-07-14 12:00:00.000000

The new rows intentionally retain only input hashes and embedding vectors.  Raw
operational prompts and payloads remain in the trace boundary and are never
copied into the model-routing learning store.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from apps.shared.db.models.model_routing_cohort import (
    LLMNodeModelRoutingCohort,
    LLMNodeModelRoutingCohortExample,
    LLMNodeModelRoutingModelEvidence,
    LLMNodeModelRoutingObservation,
    LLMNodeModelRoutingValidationBatch,
    LLMNodeModelRoutingValidationBudgetMonth,
    LLMNodeModelRoutingValidationCostEvent,
    LLMNodeModelRoutingValidationItem,
)


revision: str = "f1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "0f4a5b6c7d89"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()

    # `checkfirst` keeps existing developer databases usable when the prior
    # manual model-routing experiments created a subset of these tables.
    LLMNodeModelRoutingCohort.__table__.create(bind=bind, checkfirst=True)
    LLMNodeModelRoutingCohortExample.__table__.create(bind=bind, checkfirst=True)
    LLMNodeModelRoutingObservation.__table__.create(bind=bind, checkfirst=True)
    LLMNodeModelRoutingModelEvidence.__table__.create(bind=bind, checkfirst=True)
    LLMNodeModelRoutingValidationBatch.__table__.create(bind=bind, checkfirst=True)
    LLMNodeModelRoutingValidationBudgetMonth.__table__.create(bind=bind, checkfirst=True)
    LLMNodeModelRoutingValidationItem.__table__.create(bind=bind, checkfirst=True)
    LLMNodeModelRoutingValidationCostEvent.__table__.create(bind=bind, checkfirst=True)

    observation_columns = _column_names("llm_node_model_routing_observations")
    if "review_window_key" not in observation_columns:
        op.add_column(
            "llm_node_model_routing_observations",
            sa.Column(
                "review_window_key",
                sa.String(length=128),
                nullable=False,
                server_default=sa.text("'legacy'"),
            ),
        )

    policy_columns = _column_names("llm_node_model_routing_policies")
    if "execution_subject_user_id" not in policy_columns:
        op.add_column(
            "llm_node_model_routing_policies",
            sa.Column("execution_subject_user_id", sa.UUID(), nullable=True),
        )
        op.create_foreign_key(
            "fk_model_routing_policy_execution_subject_user",
            "llm_node_model_routing_policies",
            "users",
            ["execution_subject_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "validation_budget_usd" not in policy_columns:
        op.add_column(
            "llm_node_model_routing_policies",
            sa.Column(
                "validation_budget_usd",
                sa.Numeric(12, 6),
                nullable=False,
                server_default=sa.text("3"),
            ),
        )
    if "max_cohorts" not in policy_columns:
        op.add_column(
            "llm_node_model_routing_policies",
            sa.Column(
                "max_cohorts",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("6"),
            ),
        )

    cohort_columns = _column_names("llm_node_model_routing_cohorts")
    if "source" not in cohort_columns:
        op.add_column(
            "llm_node_model_routing_cohorts",
            sa.Column(
                "source",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'auto'"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    policy_columns = _column_names("llm_node_model_routing_policies")
    cohort_columns = _column_names("llm_node_model_routing_cohorts")
    if "source" in cohort_columns:
        op.drop_column("llm_node_model_routing_cohorts", "source")
    if "max_cohorts" in policy_columns:
        op.drop_column("llm_node_model_routing_policies", "max_cohorts")
    if "validation_budget_usd" in policy_columns:
        op.drop_column("llm_node_model_routing_policies", "validation_budget_usd")
    if "execution_subject_user_id" in policy_columns:
        op.drop_constraint(
            "fk_model_routing_policy_execution_subject_user",
            "llm_node_model_routing_policies",
            type_="foreignkey",
        )
        op.drop_column("llm_node_model_routing_policies", "execution_subject_user_id")

    LLMNodeModelRoutingValidationCostEvent.__table__.drop(bind=bind, checkfirst=True)
    LLMNodeModelRoutingValidationItem.__table__.drop(bind=bind, checkfirst=True)
    LLMNodeModelRoutingValidationBudgetMonth.__table__.drop(bind=bind, checkfirst=True)
    LLMNodeModelRoutingValidationBatch.__table__.drop(bind=bind, checkfirst=True)
    LLMNodeModelRoutingModelEvidence.__table__.drop(bind=bind, checkfirst=True)
    LLMNodeModelRoutingObservation.__table__.drop(bind=bind, checkfirst=True)
    LLMNodeModelRoutingCohortExample.__table__.drop(bind=bind, checkfirst=True)
    LLMNodeModelRoutingCohort.__table__.drop(bind=bind, checkfirst=True)
