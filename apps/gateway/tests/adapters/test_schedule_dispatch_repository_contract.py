import uuid

import pytest

from apps.gateway.adapters.db.schedule_dispatch_repository import (
    SqlAlchemyScheduleDispatchRepository,
)


def test_due_schedule_query_excludes_missing_organization_provenance():
    statement = SqlAlchemyScheduleDispatchRepository._active_schedule_statement()
    where_sql = " ".join(str(clause) for clause in statement._where_criteria)

    assert "organization_id IS NOT NULL" in where_sql
    assert "configuration_error_code IS NULL" in where_sql


def test_visibility_gap_query_requires_admitted_claim_without_a_run_row():
    source = SqlAlchemyScheduleDispatchRepository.lock_workflow_run_visibility_gaps
    source_text = __import__("inspect").getsource(source)

    assert "workflow_run_missing_reported_at.is_(None)" in source_text
    assert "WorkflowRun.id.is_(None)" in source_text
    assert "STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_DEAD_LETTERED" in source_text


def test_configuration_quarantine_rejects_non_allowlisted_code():
    repository = SqlAlchemyScheduleDispatchRepository.__new__(
        SqlAlchemyScheduleDispatchRepository
    )

    with pytest.raises(ValueError, match="unknown schedule"):
        repository.mark_configuration_invalid(uuid.uuid4(), "raw detail")


def test_outcome_review_repository_uses_exact_claim_lock_and_db_blocker_counts():
    inspect_module = __import__("inspect")
    lock_source = inspect_module.getsource(
        SqlAlchemyScheduleDispatchRepository.lock_outcome_review_claim
    )
    blocker_source = inspect_module.getsource(
        SqlAlchemyScheduleDispatchRepository.count_rollback_blockers
    )

    assert "ScheduleDispatchClaim.id == claim_id" in lock_source
    assert ".with_for_update()" in lock_source
    assert "STATUS_DISPATCHING" in blocker_source
    assert "REASON_EXECUTION_OUTCOME_UNKNOWN" in blocker_source
    assert "outcome_reviewed_at.is_(None)" in blocker_source
