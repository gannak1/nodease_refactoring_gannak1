from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from apps.shared.db.models.workflow_deployment import DeploymentType
from apps.shared.domain.deployment_runtime_policy import (
    DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
)
from apps.shared.domain.schedule_dispatch import (
    REASON_BUDGET_BLOCKED,
    REASON_ORGANIZATION_SCOPE_MISMATCH,
    STATUS_ENQUEUED,
    ScheduleDispatchSettings,
)
from apps.shared.domain.workflow_budget import BudgetExecutionDecision
from apps.workflow_engine.application.schedule_dispatch import (
    ScheduleAdmissionSnapshot,
    ScheduleClaimLocator,
    ScheduledDeploymentExecutionUseCase,
)

NOW = datetime(2026, 7, 10, tzinfo=timezone.utc)


def _snapshot(**overrides):
    claim_id = uuid.uuid4()
    schedule_id = uuid.uuid4()
    deployment_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    app_id = uuid.uuid4()
    values = {
        "claim_id": claim_id,
        "schedule_id": schedule_id,
        "claim_deployment_id": deployment_id,
        "claim_organization_id": organization_id,
        "status": STATUS_ENQUEUED,
        "idempotency_key": f"schedule:{uuid.uuid4()}",
        "attempt_count": 1,
        "scheduled_for": NOW,
        "app_exists": True,
        "deployment_exists": True,
        "schedule_exists": True,
        "canonical_schedule_id": schedule_id,
        "schedule_deployment_id": deployment_id,
        "app_id": app_id,
        "app_organization_id": organization_id,
        "credential_principal_user_id": uuid.uuid4(),
        "workflow_id": uuid.uuid4(),
        "active_deployment_id": deployment_id,
        "deployment_id": deployment_id,
        "deployment_app_id": app_id,
        "deployment_active": True,
        "deployment_type": DeploymentType.SCHEDULE,
        "workflow_version": 3,
        "graph_snapshot": {"nodes": [{"id": "start", "type": "startNode"}]},
    }
    values.update(overrides)
    return ScheduleAdmissionSnapshot(**values)


class _Repository:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.running = []
        self.canceled = []
        self.deferred = []
        self.finalized = []

    def database_now(self):
        return NOW

    def read_locator(self, claim_id):
        if claim_id != self.snapshot.claim_id:
            return None
        return ScheduleClaimLocator(
            claim_id=claim_id,
            schedule_id=self.snapshot.schedule_id,
            deployment_id=self.snapshot.claim_deployment_id,
        )

    def lock_canonical_bundle(self, locator):
        return self.snapshot

    def mark_canceled(self, **kwargs):
        self.canceled.append(kwargs)

    def mark_budget_deferred(self, **kwargs):
        self.deferred.append(kwargs)

    def mark_running(self, **kwargs):
        self.running.append(kwargs)

    def finalize_succeeded(self, **kwargs):
        self.finalized.append((True, kwargs))
        return True

    def finalize_failed(self, **kwargs):
        self.finalized.append((False, kwargs))
        return True


class _Uow:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Budget:
    def __init__(self, status="allowed"):
        self.status = status

    def evaluate(self, **kwargs):
        return BudgetExecutionDecision(status=self.status)


def _use_case(*, mode="claim"):
    return ScheduledDeploymentExecutionUseCase(
        settings=ScheduleDispatchSettings(mode=mode),
        runtime_policy=DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
    )


def test_valid_claim_admits_one_system_schedule_execution():
    snapshot = _snapshot()
    repository = _Repository(snapshot)
    uow = _Uow()

    result = _use_case().admit(
        repository=repository,
        budget=_Budget(),
        uow=uow,
        claim_id=snapshot.claim_id,
        task_id=snapshot.idempotency_key,
        admission_owner="opaque-owner",
    )

    assert result.status == "admitted"
    assert result.plan is not None
    assert result.plan.execution_context["user_id"] is None
    assert "execution_subject" not in result.plan.execution_context
    assert result.plan.execution_context["organization_id"] == str(
        snapshot.app_organization_id
    )
    assert result.plan.execution_context["workflow_task_id"] == snapshot.idempotency_key
    assert repository.running[0]["admission_owner"] == "opaque-owner"
    assert uow.commits == 1


def test_disabled_mode_does_not_admit_an_already_queued_schedule_task():
    snapshot = _snapshot()
    repository = _Repository(snapshot)
    uow = _Uow()

    result = _use_case(mode="disabled").admit(
        repository=repository,
        budget=_Budget(),
        uow=uow,
        claim_id=snapshot.claim_id,
        task_id=snapshot.idempotency_key,
        admission_owner="owner",
    )

    assert result.status == "deferred"
    assert result.reason == "schedule_dispatch_disabled"
    assert repository.running == []
    assert uow.commits == 0


@pytest.mark.parametrize("status", ["running", "succeeded", "canceled", "dead_lettered"])
def test_non_admissible_existing_state_suppresses_duplicate_engine_start(status):
    snapshot = _snapshot(status=status)
    repository = _Repository(snapshot)

    result = _use_case().admit(
        repository=repository,
        budget=_Budget(),
        uow=_Uow(),
        claim_id=snapshot.claim_id,
        task_id=snapshot.idempotency_key,
        admission_owner="owner",
    )

    assert result.status == "duplicate"
    assert result.plan is None
    assert repository.running == []


def test_task_id_mismatch_is_rejected_without_claim_mutation():
    snapshot = _snapshot()
    repository = _Repository(snapshot)

    result = _use_case().admit(
        repository=repository,
        budget=_Budget(),
        uow=_Uow(),
        claim_id=snapshot.claim_id,
        task_id=f"schedule:{uuid.uuid4()}",
        admission_owner="owner",
    )

    assert result.status == "rejected"
    assert repository.running == repository.canceled == []


def test_canonical_organization_mismatch_is_canceled_before_admission():
    snapshot = _snapshot(app_organization_id=uuid.uuid4())
    repository = _Repository(snapshot)
    uow = _Uow()

    result = _use_case().admit(
        repository=repository,
        budget=_Budget(),
        uow=uow,
        claim_id=snapshot.claim_id,
        task_id=snapshot.idempotency_key,
        admission_owner="owner",
    )

    assert result.reason == REASON_ORGANIZATION_SCOPE_MISMATCH
    assert repository.canceled == [{"reason": result.reason, "now": NOW}]
    assert uow.commits == 1


def test_budget_blocked_after_enqueue_is_canceled_before_admission():
    snapshot = _snapshot()
    repository = _Repository(snapshot)

    result = _use_case().admit(
        repository=repository,
        budget=_Budget("blocked"),
        uow=_Uow(),
        claim_id=snapshot.claim_id,
        task_id=snapshot.idempotency_key,
        admission_owner="owner",
    )

    assert result.reason == REASON_BUDGET_BLOCKED
    assert repository.running == []


def test_budget_unavailable_returns_claim_to_dispatcher_without_engine_start():
    snapshot = _snapshot()
    repository = _Repository(snapshot)

    result = _use_case().admit(
        repository=repository,
        budget=_Budget("unavailable"),
        uow=_Uow(),
        claim_id=snapshot.claim_id,
        task_id=snapshot.idempotency_key,
        admission_owner="owner",
    )

    assert result.status == "deferred"
    assert repository.deferred[0]["exhausted"] is False
    assert repository.running == []


def test_schedule_plan_separates_system_actor_credential_and_rag_subject():
    snapshot = _snapshot()
    repository = _Repository(snapshot)

    result = _use_case().admit(
        repository=repository,
        budget=_Budget(),
        uow=_Uow(),
        claim_id=snapshot.claim_id,
        task_id=snapshot.idempotency_key,
        admission_owner="owner",
    )

    assert result.status == "admitted"
    assert result.plan is not None
    context = result.plan.execution_context
    assert context["user_id"] is None
    assert context["credential_principal"] == {
        "subject_type": "user",
        "subject_id": str(snapshot.credential_principal_user_id),
    }
    assert "execution_subject" not in context


def test_finalize_uses_claim_run_and_owner_compare_and_set_contract():
    snapshot = _snapshot()
    repository = _Repository(snapshot)
    admission = _use_case().admit(
        repository=repository,
        budget=_Budget(),
        uow=_Uow(),
        claim_id=snapshot.claim_id,
        task_id=snapshot.idempotency_key,
        admission_owner="owner",
    )

    assert _use_case().finalize(
        repository=repository,
        uow=_Uow(),
        plan=admission.plan,
        succeeded=True,
    )
    assert repository.finalized[0][0] is True


def test_admission_exception_rolls_back_without_plan():
    snapshot = _snapshot()

    class _BrokenRepository(_Repository):
        def mark_running(self, **kwargs):
            raise RuntimeError("db failure")

    uow = _Uow()
    with pytest.raises(RuntimeError):
        _use_case().admit(
            repository=_BrokenRepository(snapshot),
            budget=_Budget(),
            uow=uow,
            claim_id=snapshot.claim_id,
            task_id=snapshot.idempotency_key,
            admission_owner="owner",
        )

    assert uow.rollbacks == 1
