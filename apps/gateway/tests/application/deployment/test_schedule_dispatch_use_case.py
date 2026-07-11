from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from apps.gateway.application.deployment.schedule_dispatch import (
    ScheduleDispatchUseCase,
)
from apps.gateway.application.deployment.schedule_models import (
    DispatchCanonicalContext,
    DispatchClaimSnapshot,
    WorkflowRunVisibilityGap,
)
from apps.shared.domain.workflow_budget import BudgetExecutionDecision
from apps.shared.db.models.workflow_deployment import DeploymentType
from apps.shared.domain.deployment_runtime_policy import (
    DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
)
from apps.shared.domain.schedule_dispatch import (
    MODE_CLAIM,
    REASON_ORGANIZATION_SCOPE_MISMATCH,
    ScheduleDispatchSettings,
)

NOW = datetime(2026, 7, 10, tzinfo=timezone.utc)


def _claim():
    return DispatchClaimSnapshot(
        claim_id=uuid.uuid4(),
        schedule_id=uuid.uuid4(),
        deployment_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        idempotency_key=f"schedule:{uuid.uuid4()}",
        attempt_count=0,
        status="pending",
    )


def _context(claim, **overrides):
    values = {
        "app_exists": True,
        "schedule_id": claim.schedule_id,
        "deployment_id": claim.deployment_id,
        "organization_id": claim.organization_id,
        "workflow_id": uuid.uuid4(),
        "deployment_type": DeploymentType.SCHEDULE,
        "deployment_active": True,
        "deployment_current": True,
    }
    values.update(overrides)
    return DispatchCanonicalContext(**values)


class _Uow:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def flush(self):
        pass

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Repository:
    def __init__(self, claim, context):
        self.claim = claim
        self.context = context
        self.dispatching = []
        self.terminal = []
        self.budget_unavailable = []
        self.publish = []
        self.visibility_gaps = []
        self.reported_visibility_gaps = []

    def database_now(self):
        return NOW

    def lock_dispatch_candidates(self, *, now, limit):
        return (self.claim,)

    def load_canonical_context(self, claim):
        return self.context

    def mark_dispatching(self, claim, **kwargs):
        self.dispatching.append((claim, kwargs))

    def mark_pre_dispatch_terminal(self, claim, **kwargs):
        self.terminal.append((claim, kwargs))

    def mark_budget_unavailable(self, claim, **kwargs):
        self.budget_unavailable.append((claim, kwargs))

    def get_claim_for_publish_result(self, claim_id):
        return replace(self.claim, attempt_count=1)

    def record_publish_accepted(self, **kwargs):
        self.publish.append((True, kwargs))
        return True

    def record_publish_failed(self, **kwargs):
        self.publish.append((False, kwargs))
        return True

    def recover_expired_claims(self, **kwargs):
        return 1

    def quarantine_expired_running(self, **kwargs):
        return 2

    def lock_workflow_run_visibility_gaps(self, **kwargs):
        return tuple(self.visibility_gaps)

    def mark_workflow_run_missing_reported(self, claim_id, **kwargs):
        self.reported_visibility_gaps.append((claim_id, kwargs))

    def cleanup_terminal_claims(self, **kwargs):
        return 3


class _Budget:
    def __init__(self, status="allowed"):
        self.status = status

    def evaluate(self, **kwargs):
        return BudgetExecutionDecision(status=self.status)


class _Audit:
    def __init__(self):
        self.events = []

    def record_policy_result(self, **kwargs):
        self.events.append(kwargs)

    def record_schedule_configuration_invalid(self, **kwargs):
        raise AssertionError("not used")

    def record_workflow_run_missing(self, **kwargs):
        self.events.append(kwargs)


def _use_case():
    return ScheduleDispatchUseCase(
        settings=ScheduleDispatchSettings(mode=MODE_CLAIM),
        runtime_policy=DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
    )


def test_valid_claim_is_leased_and_prepared_for_deterministic_publish():
    claim = _claim()
    repository = _Repository(claim, _context(claim))

    requests = _use_case().prepare_publish_batch(
        repository=repository,
        budget=_Budget(),
        audit=_Audit(),
        uow=_Uow(),
        owner="opaque-owner",
    )

    assert requests[0].claim_id == claim.claim_id
    assert requests[0].task_id == claim.idempotency_key
    assert requests[0].lease_owner == "opaque-owner"
    assert len(repository.dispatching) == 1


def test_canonical_organization_mismatch_cancels_before_publish():
    claim = _claim()
    repository = _Repository(
        claim,
        _context(claim, organization_id=uuid.uuid4()),
    )
    audit = _Audit()

    requests = _use_case().prepare_publish_batch(
        repository=repository,
        budget=_Budget(),
        audit=audit,
        uow=_Uow(),
        owner="opaque-owner",
    )

    assert requests == ()
    assert repository.terminal[0][1]["reason"] == REASON_ORGANIZATION_SCOPE_MISMATCH
    assert audit.events[0]["reason"] == REASON_ORGANIZATION_SCOPE_MISMATCH


def test_budget_unavailable_is_not_published():
    claim = _claim()
    repository = _Repository(claim, _context(claim))

    requests = _use_case().prepare_publish_batch(
        repository=repository,
        budget=_Budget("unavailable"),
        audit=_Audit(),
        uow=_Uow(),
        owner="opaque-owner",
    )

    assert requests == ()
    assert len(repository.budget_unavailable) == 1


def test_publish_result_is_recorded_in_separate_transaction():
    claim = _claim()
    repository = _Repository(claim, _context(claim))
    request = _use_case().prepare_publish_batch(
        repository=repository,
        budget=_Budget(),
        audit=_Audit(),
        uow=_Uow(),
        owner="opaque-owner",
    )[0]
    result_uow = _Uow()

    changed = _use_case().record_publish_result(
        repository=repository,
        uow=result_uow,
        request=request,
        accepted=True,
    )

    assert changed is True
    assert repository.publish[0][0] is True
    assert result_uow.commits == 1


def test_recovery_scans_delivery_execution_and_retention_boundaries():
    claim = _claim()
    repository = _Repository(claim, _context(claim))

    assert _use_case().recover(
        repository=repository,
        audit=_Audit(),
        uow=_Uow(),
    ) == (1, 2, 0, 3)


def test_recovery_reports_each_missing_workflow_run_once_without_replay():
    claim = _claim()
    repository = _Repository(claim, _context(claim))
    repository.visibility_gaps = [
        WorkflowRunVisibilityGap(
            claim_id=claim.claim_id,
            organization_id=claim.organization_id,
            workflow_run_id=uuid.uuid4(),
        )
    ]
    audit = _Audit()

    result = _use_case().recover(
        repository=repository,
        audit=audit,
        uow=_Uow(),
    )

    assert result == (1, 2, 1, 3)
    assert audit.events[-1] == {
        "organization_id": claim.organization_id,
        "claim_id": claim.claim_id,
    }
    assert repository.reported_visibility_gaps[0][0] == claim.claim_id
