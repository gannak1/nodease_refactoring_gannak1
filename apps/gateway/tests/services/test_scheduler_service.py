import uuid
import importlib
from datetime import datetime, timezone
from types import SimpleNamespace

from apps.gateway.services.scheduler_service import SchedulerService
from apps.shared.db.models.app import App
from apps.shared.db.models.schedule import Schedule
from apps.shared.db.models.workflow_budget import WorkflowBudget
from apps.shared.db.models.workflow_deployment import DeploymentType, WorkflowDeployment


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


class CaptureLoadQuery:
    def __init__(self):
        self.joins = []
        self.filters = []

    def join(self, model, on_clause):
        self.joins.append((model, on_clause))
        return self

    def filter(self, *expressions):
        self.filters.extend(expressions)
        return self

    def all(self):
        return []


class CaptureLoadDb:
    def __init__(self):
        self.captured_query = CaptureLoadQuery()

    def query(self, model):
        assert model is Schedule
        return self.captured_query


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
        type=DeploymentType.SCHEDULE,
    )
    app = SimpleNamespace(
        id=app_id,
        workflow_id=workflow_id,
        organization_id=organization_id,
        active_deployment_id=deployment_id,
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
    assert task["name"] == "workflow.execute_by_deployment"
    assert task["kwargs"] == {}

    queued_deployment_id, user_input, execution_context = task["args"]
    assert queued_deployment_id == str(deployment_id)
    assert user_input["schedule_id"] == str(schedule_id)
    assert execution_context["trigger_mode"] == "schedule"
    assert execution_context["workflow_id"] == str(workflow_id)
    assert execution_context["organization_id"] == str(organization_id)
    assert execution_context["app_id"] == str(app_id)
    assert execution_context["deployment_id"] == str(deployment_id)
    assert execution_context["user_id"] == str(created_by)
    assert deployment.graph_snapshot not in task["args"]
    assert schedule.last_run_at is not None
    assert schedule.next_run_at == next_run_time
    assert db.committed is True
    assert db.rolled_back is False
    assert db.closed is True


def test_scheduler_does_not_dispatch_non_schedule_deployment(monkeypatch):
    deployment_id = uuid.uuid4()
    schedule_id = uuid.uuid4()
    app_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    created_by = uuid.uuid4()

    deployment = SimpleNamespace(
        id=deployment_id,
        app_id=app_id,
        created_by=created_by,
        graph_snapshot={"nodes": []},
        is_active=True,
        type=DeploymentType.WORKFLOW_NODE,
    )
    app = SimpleNamespace(
        id=app_id,
        workflow_id=workflow_id,
        organization_id=organization_id,
        active_deployment_id=deployment_id,
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
    service.scheduler = FakeScheduler(None)

    service._run_workflow(deployment_id, schedule_id)

    assert celery.calls == []
    assert db.committed is False
    assert db.rolled_back is False
    assert db.closed is True


def test_scheduler_does_not_dispatch_stale_non_current_deployment(monkeypatch):
    deployment_id = uuid.uuid4()
    schedule_id = uuid.uuid4()
    app_id = uuid.uuid4()
    deployment = SimpleNamespace(
        id=deployment_id,
        app_id=app_id,
        created_by=uuid.uuid4(),
        graph_snapshot={"nodes": []},
        is_active=True,
        type=DeploymentType.SCHEDULE,
    )
    app = SimpleNamespace(
        id=app_id,
        workflow_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        active_deployment_id=uuid.uuid4(),
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
    service.scheduler = FakeScheduler(None)

    service._run_workflow(deployment_id, schedule_id)

    assert celery.calls == []
    assert schedule.last_run_at is None
    assert db.committed is False
    assert db.rolled_back is False
    assert db.closed is True


def test_scheduler_load_query_requires_current_app_active_deployment():
    db = CaptureLoadDb()
    service = object.__new__(SchedulerService)

    service.load_schedules_from_db(db)

    assert [model for model, _clause in db.captured_query.joins] == [
        WorkflowDeployment,
        App,
    ]
    join_pairs = {
        (clause.left.key, clause.right.key)
        for _model, clause in db.captured_query.joins
    }
    assert join_pairs == {
        ("deployment_id", "id"),
        ("id", "app_id"),
    }
    active_pointer_filters = [
        expression
        for expression in db.captured_query.filters
        if getattr(getattr(expression, "left", None), "key", None)
        == "active_deployment_id"
    ]
    assert len(active_pointer_filters) == 1
    assert active_pointer_filters[0].right.key == "id"
