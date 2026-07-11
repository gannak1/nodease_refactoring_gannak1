from __future__ import annotations

import uuid

import pytest

from apps.workflow_engine import tasks
from apps.workflow_engine.application import schedule_dispatch as application
from apps.workflow_engine.workflow.errors import NonRetryableWorkflowError


class _Session:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _Engine:
    calls = []
    error = None
    cleanup_error = None

    def __init__(self, **kwargs):
        self.__class__.calls.append(kwargs)

    def execute(self):
        if self.error:
            raise self.error
        return {"ok": True}

    def cleanup(self):
        if self.cleanup_error:
            raise self.cleanup_error


def _plan(claim_id, task_id):
    return application.ScheduledExecutionPlan(
        claim_id=claim_id,
        workflow_run_id=uuid.uuid4(),
        admission_owner="owner",
        graph_snapshot={"nodes": []},
        user_input={"schedule_id": str(uuid.uuid4())},
        execution_context={
            "user_id": None,
            "workflow_id": str(uuid.uuid4()),
            "organization_id": str(uuid.uuid4()),
            "workflow_task_id": task_id,
        },
    )


def test_scheduled_task_runs_engine_only_after_admission_and_finalizes(monkeypatch):
    claim_id = uuid.uuid4()
    task_id = f"schedule:{uuid.uuid4()}"
    sessions = [_Session(), _Session(), _Session()]
    calls = []

    class _UseCase:
        def __init__(self, **kwargs):
            pass

        def admit(self, **kwargs):
            calls.append("admit")
            return application.ScheduleAdmissionResult(
                "admitted", plan=_plan(claim_id, task_id)
            )

        def finalize(self, **kwargs):
            calls.append(("finalize", kwargs["succeeded"]))
            return True

    monkeypatch.setattr(tasks, "SessionLocal", lambda: sessions.pop(0))
    monkeypatch.setattr(application, "ScheduledDeploymentExecutionUseCase", _UseCase)
    monkeypatch.setattr(
        "apps.workflow_engine.workflow.core.workflow_engine.WorkflowEngine",
        _Engine,
    )
    monkeypatch.setattr(
        tasks,
        "_sync_knowledge_bases_for_execution_subject",
        lambda *a, **k: {"skipped": True},
    )
    _Engine.calls = []

    result = tasks._execute_scheduled_deployment_claim(
        str(claim_id),
        task_id=task_id,
    )

    assert result["status"] == "success"
    assert calls == ["admit", ("finalize", True)]
    assert len(_Engine.calls) == 1


def test_scheduled_task_cleanup_failure_keeps_successful_claim_finalization(
    monkeypatch,
):
    claim_id = uuid.uuid4()
    task_id = f"schedule:{uuid.uuid4()}"
    finalized = []

    class _UseCase:
        def __init__(self, **kwargs):
            pass

        def admit(self, **kwargs):
            return application.ScheduleAdmissionResult(
                "admitted", plan=_plan(claim_id, task_id)
            )

        def finalize(self, **kwargs):
            finalized.append(kwargs["succeeded"])
            return True

    monkeypatch.setattr(tasks, "SessionLocal", _Session)
    monkeypatch.setattr(application, "ScheduledDeploymentExecutionUseCase", _UseCase)
    monkeypatch.setattr(
        "apps.workflow_engine.workflow.core.workflow_engine.WorkflowEngine",
        _Engine,
    )
    monkeypatch.setattr(
        tasks,
        "_sync_knowledge_bases_for_execution_subject",
        lambda *a, **k: {"skipped": True},
    )
    _Engine.cleanup_error = RuntimeError("cleanup detail must not escape")
    try:
        result = tasks._execute_scheduled_deployment_claim(
            str(claim_id),
            task_id=task_id,
        )
    finally:
        _Engine.cleanup_error = None

    assert result["status"] == "success"
    assert finalized == [True]


def test_scheduled_task_retries_only_finalization_with_fresh_sessions(monkeypatch):
    claim_id = uuid.uuid4()
    task_id = f"schedule:{uuid.uuid4()}"
    finalization_attempts = []
    sessions = []

    class _UseCase:
        def __init__(self, **kwargs):
            pass

        def admit(self, **kwargs):
            return application.ScheduleAdmissionResult(
                "admitted", plan=_plan(claim_id, task_id)
            )

        def finalize(self, **kwargs):
            finalization_attempts.append(kwargs["succeeded"])
            if len(finalization_attempts) == 1:
                raise RuntimeError("database endpoint must not escape")
            return True

    def session_factory():
        session = _Session()
        sessions.append(session)
        return session

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(application, "ScheduledDeploymentExecutionUseCase", _UseCase)
    monkeypatch.setattr(
        "apps.workflow_engine.workflow.core.workflow_engine.WorkflowEngine",
        _Engine,
    )
    monkeypatch.setattr(
        tasks,
        "_sync_knowledge_bases_for_execution_subject",
        lambda *a, **k: {"skipped": True},
    )
    _Engine.calls = []

    result = tasks._execute_scheduled_deployment_claim(
        str(claim_id),
        task_id=task_id,
    )

    assert result["status"] == "success"
    assert len(_Engine.calls) == 1
    assert finalization_attempts == [True, True]
    assert len(sessions) == 4
    assert all(session.closed for session in sessions)


def test_scheduled_task_duplicate_does_not_construct_engine(monkeypatch):
    claim_id = uuid.uuid4()
    task_id = f"schedule:{uuid.uuid4()}"

    class _UseCase:
        def __init__(self, **kwargs):
            pass

        def admit(self, **kwargs):
            return application.ScheduleAdmissionResult("duplicate", "running")

    monkeypatch.setattr(tasks, "SessionLocal", _Session)
    monkeypatch.setattr(application, "ScheduledDeploymentExecutionUseCase", _UseCase)
    _Engine.calls = []

    result = tasks._execute_scheduled_deployment_claim(
        str(claim_id),
        task_id=task_id,
    )

    assert result["status"] == "duplicate"
    assert _Engine.calls == []


def test_scheduled_task_engine_failure_is_finalized_without_celery_retry(monkeypatch):
    claim_id = uuid.uuid4()
    task_id = f"schedule:{uuid.uuid4()}"
    finalized = []

    class _UseCase:
        def __init__(self, **kwargs):
            pass

        def admit(self, **kwargs):
            return application.ScheduleAdmissionResult(
                "admitted", plan=_plan(claim_id, task_id)
            )

        def finalize(self, **kwargs):
            finalized.append(kwargs["succeeded"])
            return True

    monkeypatch.setattr(tasks, "SessionLocal", _Session)
    monkeypatch.setattr(application, "ScheduledDeploymentExecutionUseCase", _UseCase)
    monkeypatch.setattr(
        "apps.workflow_engine.workflow.core.workflow_engine.WorkflowEngine",
        _Engine,
    )
    monkeypatch.setattr(
        tasks,
        "_sync_knowledge_bases_for_execution_subject",
        lambda *a, **k: {"skipped": True},
    )
    _Engine.error = RuntimeError("provider raw detail")
    try:
        with pytest.raises(NonRetryableWorkflowError):
            tasks._execute_scheduled_deployment_claim(
                str(claim_id),
                task_id=task_id,
            )
    finally:
        _Engine.error = None

    assert finalized == [False]


@pytest.mark.parametrize(
    ("claim_id", "task_id"),
    [("not-a-uuid", "schedule:value"), (str(uuid.uuid4()), "wrong-task")],
)
def test_scheduled_task_rejects_invalid_locator_or_task_identity(claim_id, task_id):
    with pytest.raises(tasks.PermanentDeploymentExecutionError):
        tasks._execute_scheduled_deployment_claim(claim_id, task_id=task_id)


def test_claim_task_registration_has_no_automatic_retry():
    assert tasks.execute_scheduled_deployment.max_retries == 0


def test_missing_claim_schema_is_safe_permanent_rejection(monkeypatch):
    class _UnavailableUseCase:
        def __init__(self, **kwargs):
            pass

        def admit(self, **kwargs):
            raise RuntimeError("relation details must not escape")

    monkeypatch.setattr(tasks, "SessionLocal", _Session)
    monkeypatch.setattr(
        application,
        "ScheduledDeploymentExecutionUseCase",
        _UnavailableUseCase,
    )

    with pytest.raises(tasks.PermanentDeploymentExecutionError) as exc_info:
        tasks._execute_scheduled_deployment_claim(
            str(uuid.uuid4()),
            task_id=f"schedule:{uuid.uuid4()}",
        )

    assert str(exc_info.value) == "schedule admission is unavailable"


def test_invalid_schedule_dispatch_settings_are_safe_permanent_rejection(
    monkeypatch,
):
    monkeypatch.setattr(
        tasks,
        "get_schedule_dispatch_settings",
        lambda: (_ for _ in ()).throw(ValueError("invalid environment detail")),
    )

    with pytest.raises(tasks.PermanentDeploymentExecutionError) as exc_info:
        tasks._execute_scheduled_deployment_claim(
            str(uuid.uuid4()),
            task_id=f"schedule:{uuid.uuid4()}",
        )

    assert str(exc_info.value) == "schedule dispatch configuration is invalid"
