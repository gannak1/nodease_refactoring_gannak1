from __future__ import annotations

import importlib

from apps.shared.db.models.schedule_dispatch import ScheduleDispatchClaim
from apps.shared.db.models.workflow_run import WorkflowRun

EXPECTED_CLAIM_INDEXES = {
    "ix_schedule_dispatch_claims_completed_at",
    "ix_schedule_dispatch_claims_deployment_id",
    "ix_schedule_dispatch_claims_org_status_completed",
    "ix_schedule_dispatch_claims_status_execution_deadline",
    "ix_schedule_dispatch_claims_status_lease_expiry",
    "ix_schedule_dispatch_claims_status_next_attempt",
}
EXPECTED_CLAIM_CONSTRAINTS = {
    "ck_schedule_dispatch_claims_attempt_count",
    "ck_schedule_dispatch_claims_next_attempt_status",
    "ck_schedule_dispatch_claims_outcome_review",
    "ck_schedule_dispatch_claims_safe_reason",
    "ck_schedule_dispatch_claims_status",
    "ck_schedule_dispatch_claims_status_fields",
    "ck_schedule_dispatch_claims_task_id",
    "ck_schedule_dispatch_claims_timestamp_order",
    "uq_schedule_dispatch_claims_idempotency_key",
    "uq_schedule_dispatch_claims_occurrence",
    "uq_schedule_dispatch_claims_workflow_run_id",
}


def test_claim_model_preserves_durable_references_without_foreign_keys():
    table = ScheduleDispatchClaim.__table__

    assert table.c.schedule_id.nullable is False
    assert table.c.organization_id.nullable is False
    assert table.c.deployment_id.nullable is False
    assert table.c.claimed_at.nullable is False
    assert not table.c.schedule_id.foreign_keys
    assert not table.c.organization_id.foreign_keys
    assert not table.c.deployment_id.foreign_keys
    assert not table.c.workflow_run_id.foreign_keys


def test_claim_model_declares_required_constraints_and_indexes():
    table = ScheduleDispatchClaim.__table__

    constraint_names = {
        constraint.name for constraint in table.constraints if constraint.name
    }
    index_names = {index.name for index in table.indexes}

    assert EXPECTED_CLAIM_CONSTRAINTS <= constraint_names
    assert EXPECTED_CLAIM_INDEXES == index_names


def test_workflow_run_allows_only_correlated_system_schedule_null_executor():
    table = WorkflowRun.__table__
    constraint = next(
        item
        for item in table.constraints
        if item.name == "ck_workflow_runs_system_schedule_executor"
    )

    assert table.c.user_id.nullable is True
    sql = str(constraint.sqltext)
    assert "user_id IS NOT NULL" in sql
    assert "trigger_mode = 'SCHEDULER'" in sql
    assert "workflow_task_id LIKE 'schedule:%'" in sql


def test_schedule_dispatch_migration_extends_current_single_head():
    migration = importlib.import_module(
        "apps.shared.alembic.versions.fa8b9c0d1e23_add_schedule_dispatch_claims"
    )

    assert migration.revision == "fa8b9c0d1e23"
    assert migration.down_revision == "fa7b8c9d0e12"
