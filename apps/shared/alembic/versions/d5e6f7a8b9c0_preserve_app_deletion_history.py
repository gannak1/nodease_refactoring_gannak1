"""Preserve workflow history when an App is deleted.

Revision ID: d5e6f7a8b9c0
Revises: c1e5f4a3c2d4
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c1e5f4a3c2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RETAINED_WORKFLOW_TABLES = (
    "workflow_runs",
    "llm_usage_logs",
    "cost_optimizer_experiments",
    "cost_optimizer_recommendation_verifications",
    "llm_node_model_routing_policies",
    "mail_message_processings",
)

_WORKFLOW_FK_NAMES = {
    "workflow_runs": "fk_workflow_runs_workflow",
    "llm_usage_logs": "fk_llm_usage_logs_workflow",
    "cost_optimizer_experiments": "fk_cost_optimizer_experiments_workflow",
    "cost_optimizer_recommendation_verifications": "fk_cost_opt_verifications_workflow",
    "llm_node_model_routing_policies": "fk_llm_routing_policies_workflow",
    "mail_message_processings": "fk_mail_message_processings_workflow",
}

_ORGANIZATION_PROVENANCE_TABLES = (
    "workflow_runs",
    "cost_optimizer_experiments",
    "cost_optimizer_recommendation_verifications",
    "llm_node_model_routing_policies",
)

_DOWNGRADE_REQUIRED_WORKFLOW_TABLES = tuple(
    table_name
    for table_name in _RETAINED_WORKFLOW_TABLES
    if table_name != "llm_usage_logs"
)


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _has_index(table_name: str, index_name: str) -> bool:
    return index_name in {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def _has_foreign_key(
    table_name: str,
    column_name: str,
    referred_table: str,
) -> bool:
    return any(
        foreign_key.get("constrained_columns") == [column_name]
        and foreign_key.get("referred_table") == referred_table
        for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(table_name)
    )


def _drop_foreign_key(
    table_name: str,
    column_name: str,
    referred_table: str,
) -> None:
    for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(table_name):
        if (
            foreign_key.get("constrained_columns") == [column_name]
            and foreign_key.get("referred_table") == referred_table
        ):
            op.drop_constraint(foreign_key["name"], table_name, type_="foreignkey")


def _replace_foreign_key(
    table_name: str,
    column_name: str,
    referred_table: str,
    *,
    constraint_name: str,
    ondelete: str | None,
) -> None:
    _drop_foreign_key(table_name, column_name, referred_table)
    op.create_foreign_key(
        constraint_name,
        table_name,
        referred_table,
        [column_name],
        ["id"],
        ondelete=ondelete,
    )


def _require_complete_organization_provenance() -> None:
    bind = op.get_bind()
    for table_name in _ORGANIZATION_PROVENANCE_TABLES:
        missing = bind.execute(
            sa.text(
                f"SELECT count(*) FROM {table_name} WHERE organization_id IS NULL"
            )
        ).scalar_one()
        if missing:
            raise RuntimeError(
                f"cannot assign safe organization provenance for {table_name}"
            )


def _require_workflow_references_for_downgrade() -> None:
    bind = op.get_bind()
    for table_name in _DOWNGRADE_REQUIRED_WORKFLOW_TABLES:
        missing = bind.execute(
            sa.text(f"SELECT count(*) FROM {table_name} WHERE workflow_id IS NULL")
        ).scalar_one()
        if missing:
            raise RuntimeError(
                f"cannot restore required workflow references for {table_name}"
            )


def _require_routing_policy_deployment_references_for_downgrade() -> None:
    missing = op.get_bind().execute(
        sa.text(
            """
            SELECT count(*)
            FROM llm_node_model_routing_policies
            WHERE deployment_id IS NULL
            """
        )
    ).scalar_one()
    if missing:
        raise RuntimeError(
            "cannot restore required routing policy deployment references"
        )


def upgrade() -> None:
    if not _has_column("workflow_runs", "organization_id"):
        op.add_column(
            "workflow_runs",
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if not _has_column(
        "cost_optimizer_recommendation_verifications", "organization_id"
    ):
        op.add_column(
            "cost_optimizer_recommendation_verifications",
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        )

    for table_name in _ORGANIZATION_PROVENANCE_TABLES:
        op.execute(
            sa.text(
                f"""
                UPDATE {table_name} AS retained
                SET organization_id = workflows.organization_id
                FROM workflows
                WHERE retained.workflow_id = workflows.id
                  AND retained.organization_id IS NULL
                """
            )
        )
    op.execute(
        sa.text(
            """
            UPDATE workflow_runs AS retained
            SET organization_id = apps.organization_id
            FROM apps
            WHERE retained.app_id = apps.id
              AND retained.organization_id IS NULL
            """
        )
    )
    _require_complete_organization_provenance()

    if not _has_foreign_key("workflow_runs", "organization_id", "organization"):
        op.create_foreign_key(
            "fk_workflow_runs_organization_id_organization",
            "workflow_runs",
            "organization",
            ["organization_id"],
            ["id"],
        )
    if not _has_foreign_key(
        "cost_optimizer_recommendation_verifications",
        "organization_id",
        "organization",
    ):
        op.create_foreign_key(
            "fk_cost_optimizer_recommendation_verifications_organization_id",
            "cost_optimizer_recommendation_verifications",
            "organization",
            ["organization_id"],
            ["id"],
        )
    if not _has_index("workflow_runs", "ix_workflow_runs_organization_id"):
        op.create_index(
            "ix_workflow_runs_organization_id",
            "workflow_runs",
            ["organization_id"],
            unique=False,
        )
    if not _has_index(
        "cost_optimizer_recommendation_verifications",
        "ix_cost_optimizer_recommendation_verifications_organization_id",
    ):
        op.create_index(
            "ix_cost_optimizer_recommendation_verifications_organization_id",
            "cost_optimizer_recommendation_verifications",
            ["organization_id"],
            unique=False,
        )

    for table_name in _ORGANIZATION_PROVENANCE_TABLES:
        op.alter_column(
            table_name,
            "organization_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )

    for table_name in _RETAINED_WORKFLOW_TABLES:
        op.alter_column(
            table_name,
            "workflow_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=True,
        )
        _replace_foreign_key(
            table_name,
            "workflow_id",
            "workflows",
            constraint_name=_WORKFLOW_FK_NAMES[table_name],
            ondelete="SET NULL",
        )

    _replace_foreign_key(
        "llm_node_model_routing_policies",
        "organization_id",
        "organization",
        constraint_name="fk_llm_node_model_routing_policies_organization_id",
        ondelete=None,
    )
    op.alter_column(
        "llm_node_model_routing_policies",
        "deployment_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    _replace_foreign_key(
        "llm_node_model_routing_policies",
        "deployment_id",
        "workflow_deployments",
        constraint_name="fk_llm_routing_policies_deployment",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    _require_workflow_references_for_downgrade()
    _require_routing_policy_deployment_references_for_downgrade()

    original_workflow_delete = {
        "workflow_runs": "CASCADE",
        "llm_usage_logs": None,
        "cost_optimizer_experiments": "CASCADE",
        "cost_optimizer_recommendation_verifications": "CASCADE",
        "llm_node_model_routing_policies": "CASCADE",
        "mail_message_processings": "CASCADE",
    }
    for table_name, ondelete in original_workflow_delete.items():
        _replace_foreign_key(
            table_name,
            "workflow_id",
            "workflows",
            constraint_name=_WORKFLOW_FK_NAMES[table_name],
            ondelete=ondelete,
        )
        op.alter_column(
            table_name,
            "workflow_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=table_name == "llm_usage_logs",
        )

    _replace_foreign_key(
        "llm_node_model_routing_policies",
        "organization_id",
        "organization",
        constraint_name="fk_llm_node_model_routing_policies_organization_id",
        ondelete="CASCADE",
    )
    _replace_foreign_key(
        "llm_node_model_routing_policies",
        "deployment_id",
        "workflow_deployments",
        constraint_name="fk_llm_routing_policies_deployment",
        ondelete="CASCADE",
    )
    op.alter_column(
        "llm_node_model_routing_policies",
        "deployment_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "cost_optimizer_experiments",
        "organization_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.alter_column(
        "llm_node_model_routing_policies",
        "organization_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    op.drop_index(
        "ix_cost_optimizer_recommendation_verifications_organization_id",
        table_name="cost_optimizer_recommendation_verifications",
    )
    op.drop_index("ix_workflow_runs_organization_id", table_name="workflow_runs")
    _drop_foreign_key(
        "cost_optimizer_recommendation_verifications",
        "organization_id",
        "organization",
    )
    op.drop_constraint(
        "fk_workflow_runs_organization_id_organization",
        "workflow_runs",
        type_="foreignkey",
    )
    op.drop_column(
        "cost_optimizer_recommendation_verifications", "organization_id"
    )
    op.drop_column("workflow_runs", "organization_id")
