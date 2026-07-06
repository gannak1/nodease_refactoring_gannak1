import uuid
import sys
from types import SimpleNamespace

import pytest

from apps.workflow_engine import tasks


class FakeSession:
    def close(self):
        return None

    def query(self, _model):
        return FakeQuery()


class FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return SimpleNamespace(
            id=uuid.uuid4(),
            app_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            is_active=True,
            graph_data={"nodes": []},
            graph_snapshot={"nodes": []},
            version=1,
        )


class FakeColumn:
    def __eq__(self, _other):
        return True

    def is_(self, _other):
        return True


class FakeApp:
    id = FakeColumn()


class FakeWorkflowDeployment:
    id = FakeColumn()
    workflow_id = FakeColumn()
    is_active = FakeColumn()


class FakeWorkflowEngine:
    def __init__(self, *args, **kwargs):
        self.execution_context = kwargs.get("execution_context", {})

    def execute(self):
        return {"ok": True}

    def execute_stream(self):
        yield {"type": "workflow_finish", "data": {"ok": True}}

    def cleanup(self):
        return None


class FakeSyncService:
    calls = []

    def __init__(self, db, user_id, organization_id=None):
        self.db = db
        self.user_id = user_id
        self.organization_id = organization_id

    def sync_knowledge_bases(self, graph):
        self.__class__.calls.append(
            {
                "user_id": self.user_id,
                "organization_id": self.organization_id,
                "graph": graph,
            }
        )
        return {"synced_count": 1, "failed": []}


@pytest.fixture(autouse=True)
def patch_task_dependencies(monkeypatch):
    FakeSyncService.calls = []
    monkeypatch.setattr(tasks, "SessionLocal", lambda: FakeSession())
    monkeypatch.setitem(
        sys.modules,
        "apps.workflow_engine.workflow.core.workflow_engine",
        SimpleNamespace(WorkflowEngine=FakeWorkflowEngine),
    )
    monkeypatch.setitem(
        sys.modules,
        "apps.workflow_engine.services.sync_service",
        SimpleNamespace(SyncService=FakeSyncService),
    )
    monkeypatch.setitem(
        sys.modules,
        "apps.shared.db.models.app",
        SimpleNamespace(App=FakeApp),
    )
    monkeypatch.setitem(
        sys.modules,
        "apps.shared.db.models.workflow_deployment",
        SimpleNamespace(WorkflowDeployment=FakeWorkflowDeployment),
    )


def test_execute_workflow_skips_sync_without_execution_subject():
    owner_id = uuid.uuid4()
    result = tasks.execute_workflow.run(
        {"nodes": []},
        {},
        {
            "user_id": str(owner_id),
            "organization_id": str(uuid.uuid4()),
        },
        False,
    )

    assert result["status"] == "success"
    assert result["sync_status"] == {
        "synced_count": 0,
        "failed": [],
        "skipped": True,
        "reason": "anonymous_public_only",
    }
    assert FakeSyncService.calls == []


def test_execute_workflow_syncs_with_execution_subject_not_actor_user():
    actor_id = uuid.uuid4()
    subject_id = uuid.uuid4()
    organization_id = uuid.uuid4()

    result = tasks.execute_workflow.run(
        {"nodes": []},
        {},
        {
            "user_id": str(actor_id),
            "organization_id": str(organization_id),
            "execution_subject": {
                "type": "user",
                "id": str(subject_id),
            },
        },
        False,
    )

    assert result["sync_status"] == {"synced_count": 1, "failed": []}
    assert FakeSyncService.calls == [
        {
            "user_id": subject_id,
            "organization_id": str(organization_id),
            "graph": {"nodes": []},
        }
    ]


def test_execute_workflow_skips_sync_for_invalid_subject():
    result = tasks.execute_workflow.run(
        {"nodes": []},
        {},
        {
            "user_id": str(uuid.uuid4()),
            "organization_id": str(uuid.uuid4()),
            "execution_subject": {
                "type": "service_account",
                "id": str(uuid.uuid4()),
            },
        },
        False,
    )

    assert result["status"] == "success"
    assert result["sync_status"]["skipped"] is True
    assert result["sync_status"]["reason"] == "anonymous_public_only"
    assert FakeSyncService.calls == []


def test_stream_workflow_uses_execution_subject_for_sync():
    subject_id = uuid.uuid4()
    organization_id = uuid.uuid4()

    result = tasks.stream_workflow.run(
        {"nodes": []},
        {},
        {
            "user_id": str(uuid.uuid4()),
            "organization_id": str(organization_id),
            "execution_subject": {
                "subject_type": "user",
                "subject_id": str(subject_id),
            },
        },
        str(uuid.uuid4()),
    )

    assert result["status"] == "success"
    assert FakeSyncService.calls == [
        {
            "user_id": subject_id,
            "organization_id": str(organization_id),
            "graph": {"nodes": []},
        }
    ]


def test_execute_deployed_workflow_skips_sync_without_execution_subject():
    result = tasks.execute_deployed_workflow.run(
        str(uuid.uuid4()),
        {},
        {
            "user_id": str(uuid.uuid4()),
            "organization_id": str(uuid.uuid4()),
        },
    )

    assert result["status"] == "success"
    assert result["sync_status"] == {
        "synced_count": 0,
        "failed": [],
        "skipped": True,
        "reason": "anonymous_public_only",
    }
    assert FakeSyncService.calls == []


def test_execute_by_deployment_skips_sync_without_execution_subject():
    result = tasks.execute_by_deployment.run(
        str(uuid.uuid4()),
        {},
        {
            "user_id": str(uuid.uuid4()),
            "organization_id": str(uuid.uuid4()),
        },
    )

    assert result["status"] == "success"
    assert result["sync_status"] == {
        "synced_count": 0,
        "failed": [],
        "skipped": True,
        "reason": "anonymous_public_only",
    }
    assert FakeSyncService.calls == []
