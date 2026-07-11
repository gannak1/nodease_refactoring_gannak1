from __future__ import annotations

import uuid

from apps.gateway.adapters.audit.sqlalchemy_schedule_dispatch_audit import (
    SqlAlchemyScheduleDispatchAuditRecorder,
)
from apps.shared.db.models.audit_log import ActorType, AuditStatus


class _Session:
    def __init__(self) -> None:
        self.rows = []

    def add(self, row) -> None:
        self.rows.append(row)


def test_missing_workflow_run_audit_uses_only_safe_system_metadata():
    session = _Session()
    organization_id = uuid.uuid4()
    claim_id = uuid.uuid4()

    SqlAlchemyScheduleDispatchAuditRecorder(session).record_workflow_run_missing(
        organization_id=organization_id,
        claim_id=claim_id,
    )

    row = session.rows[0]
    assert row.action == "schedule_dispatch.workflow_run_missing"
    assert row.actor_id is None
    assert row.actor_type == ActorType.SYSTEM
    assert row.status == AuditStatus.FAILURE
    assert row.target_id == str(claim_id)
    assert row.audit_metadata == {
        "organization_id": str(organization_id),
        "reason": "workflow_run_missing",
    }


def test_outcome_review_audit_returns_its_generated_id_and_safe_metadata():
    session = _Session()
    organization_id = uuid.uuid4()
    claim_id = uuid.uuid4()

    audit_id = SqlAlchemyScheduleDispatchAuditRecorder(
        session
    ).record_outcome_reviewed(
        organization_id=organization_id,
        claim_id=claim_id,
        operation_correlation_id="github-run:42",
        outcome_resolution_code="confirmed_completed",
    )

    row = session.rows[0]
    assert row.id == audit_id
    assert row.action == "schedule_dispatch.outcome_reviewed"
    assert row.actor_id is None
    assert row.actor_type == ActorType.SYSTEM
    assert row.target_id == str(claim_id)
    assert row.audit_metadata == {
        "organization_id": str(organization_id),
        "operation_correlation_id": "github-run:42",
        "outcome_resolution_code": "confirmed_completed",
    }
