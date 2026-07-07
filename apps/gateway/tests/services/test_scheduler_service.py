import uuid
import importlib
from datetime import datetime, timezone
from types import SimpleNamespace

from apps.gateway.services.scheduler_service import SchedulerService
from apps.shared.db.models.app import App
from apps.shared.db.models.schedule import Schedule
from apps.shared.db.models.workflow_budget import WorkflowBudget
from apps.shared.db.models.workflow_deployment import WorkflowDeployment


class FakeQuery:
    def __init__(self, row):
        self.row = row

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.row


class FakeSession:
    def __init__(self, *, deployment, app, schedule):
        self.deployment = deployment
        self.app = app
        self.schedule = schedule
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def query(self, model):
        if model is WorkflowDeployment:
            return FakeQuery(self.deployment)
        if model is App:
            return FakeQuery(self.app)
        if model is Schedule:
            return FakeQuery(self.schedule)
        if model is WorkflowBudget:
            # 예산 미설정 — 실행 전 예산 확인은 통과한다
            return FakeQuery(None)
        raise AssertionError(f"unexpected query model: {model}")

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class FakeCeleryApp:
    def __init__(self):
        self.calls = []

    def send_task(self, name, args=None, kwargs=None):
        self.calls.append({"name": name, "args": args or [], "kwargs": kwargs or {}})


class FakeScheduler:
    def __init__(self, next_run_time):
        self.next_run_time = next_run_time

    def get_job(self, job_id):
        return SimpleNamespace(next_run_time=self.next_run_time)


def test_scheduled_workflow_includes_app_organization_scope(monkeypatch):
    """Scheduled LLM runtime keeps the app organization scope in execution context. MBA-43"""
    deployment_id = uuid.uuid4()
    schedule_id = uuid.uuid4()
    app_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    created_by = uuid.uuid4()
    next_run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)

    deployment = SimpleNamespace(
        id=deployment_id,
        app_id=app_id,
        created_by=created_by,
        graph_snapshot={"nodes": []},
        is_active=True,
    )
    app = SimpleNamespace(
        id=app_id,
        workflow_id=workflow_id,
        organization_id=organization_id,
    )
    schedule = SimpleNamespace(
        id=schedule_id,
        last_run_at=None,
        next_run_at=None,
    )
    db = FakeSession(deployment=deployment, app=app, schedule=schedule)
    celery = FakeCeleryApp()

    celery_module = importlib.import_module("apps.shared.celery_app")
    monkeypatch.setattr("apps.shared.db.session.SessionLocal", lambda: db)
    monkeypatch.setattr(celery_module, "celery_app", celery)

    service = object.__new__(SchedulerService)
    service.scheduler = FakeScheduler(next_run_time)

    service._run_workflow(deployment_id, schedule_id)

    assert len(celery.calls) == 1
    task = celery.calls[0]
    assert task["name"] == "workflow.execute"
    assert task["kwargs"] == {"is_deployed": True}

    _, user_input, execution_context = task["args"]
    assert user_input["schedule_id"] == str(schedule_id)
    assert execution_context["trigger_mode"] == "schedule"
    assert execution_context["workflow_id"] == str(workflow_id)
    assert execution_context["organization_id"] == str(organization_id)
    assert execution_context["app_id"] == str(app_id)
    assert execution_context["deployment_id"] == str(deployment_id)
    assert execution_context["user_id"] == str(created_by)
    assert schedule.last_run_at is not None
    assert schedule.next_run_at == next_run_time
    assert db.committed is True
    assert db.rolled_back is False
    assert db.closed is True
