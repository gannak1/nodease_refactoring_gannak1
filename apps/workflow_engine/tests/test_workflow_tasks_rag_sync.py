import uuid
import sys
from types import SimpleNamespace

import pytest

from apps.workflow_engine import tasks
from apps.shared.db.models.workflow_deployment import DeploymentType
from apps.shared.domain.deployment_runtime_policy import (
    DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
    SURFACE_WEBHOOK_RUN,
)
from apps.workflow_engine.workflow.errors import NonRetryableWorkflowError


class FakeSession:
    deployment = None
    app = None

    def close(self):
        return None

    def query(self, model):
        return FakeQuery(model)


class FakeQuery:
    def __init__(self, model):
        self.model = model

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self.model is FakeWorkflowDeployment and FakeSession.deployment is not None:
            return FakeSession.deployment
        if self.model is FakeApp and FakeSession.app is not None:
            return FakeSession.app
        return SimpleNamespace(
            id=uuid.uuid4(),
            app_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            active_deployment_id=uuid.uuid4(),
            is_active=True,
            type=DeploymentType.WEBHOOK,
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


def _active_deployment_pair(
    *,
    deployment_id=None,
    deployment_type=DeploymentType.WEBHOOK,
    trigger_mode="webhook",
    graph_snapshot=None,
):
    deployment_id = deployment_id or uuid.uuid4()
    app_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    created_by = uuid.uuid4()
    FakeSession.deployment = SimpleNamespace(
        id=deployment_id,
        app_id=app_id,
        version=7,
        type=deployment_type,
        is_active=True,
        created_by=created_by,
        graph_snapshot=graph_snapshot or {"nodes": []},
    )
    FakeSession.app = SimpleNamespace(
        id=app_id,
        workflow_id=workflow_id,
        organization_id=organization_id,
        active_deployment_id=deployment_id,
        created_by=created_by,
    )
    return FakeSession.deployment, FakeSession.app, trigger_mode


class FakeWorkflowEngine:
    calls = []
    execute_error = None

    def __init__(self, *args, **kwargs):
        self.__class__.calls.append({"args": args, "kwargs": kwargs})
        self.execution_context = kwargs.get("execution_context", {})

    def execute(self):
        if self.execute_error is not None:
            raise self.execute_error
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
    FakeWorkflowEngine.calls = []
    FakeWorkflowEngine.execute_error = None
    FakeSession.deployment = None
    FakeSession.app = None
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
        SimpleNamespace(
            DeploymentType=DeploymentType,
            WorkflowDeployment=FakeWorkflowDeployment,
        ),
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
    deployment, _app, trigger_mode = _active_deployment_pair()

    result = tasks.execute_by_deployment.run(
        str(deployment.id),
        {},
        {
            "user_id": str(uuid.uuid4()),
            "organization_id": str(uuid.uuid4()),
            "trigger_mode": trigger_mode,
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


def test_execute_by_deployment_uses_snapshot_rag_selection():
    deployment_id = uuid.uuid4()
    knowledge_base_id = str(uuid.uuid4())
    graph_snapshot = {
        "nodes": [
            {
                "id": "llm-1",
                "type": "llmNode",
                "data": {
                    "title": "LLM",
                    "provider": "openai",
                    "model_id": "gpt-4o",
                    "user_prompt": "query",
                    "knowledgeBases": [{"id": knowledge_base_id, "name": "제품 정책"}],
                    "topK": 4,
                },
            }
        ],
        "edges": [],
    }
    deployment, app, trigger_mode = _active_deployment_pair(
        deployment_id=deployment_id,
        graph_snapshot=graph_snapshot,
    )

    result = tasks.execute_by_deployment.run(
        str(deployment_id),
        {"message": "hello"},
        {"trigger_mode": trigger_mode},
    )

    engine_kwargs = FakeWorkflowEngine.calls[0]["kwargs"]
    assert result["status"] == "success"
    assert engine_kwargs["graph"]["nodes"][0]["data"]["knowledgeBases"] == [
        {"id": knowledge_base_id, "name": "제품 정책"}
    ]
    assert engine_kwargs["graph"]["nodes"][0]["data"]["topK"] == 4
    assert engine_kwargs["execution_context"]["workflow_id"] == str(app.workflow_id)
    assert engine_kwargs["execution_context"]["organization_id"] == str(
        app.organization_id
    )
    assert engine_kwargs["execution_context"]["deployment_id"] == str(deployment_id)


def test_execute_by_deployment_rebuilds_tenant_context_from_database():
    deployment, app, trigger_mode = _active_deployment_pair()
    attacker_workflow_id = str(uuid.uuid4())
    attacker_organization_id = str(uuid.uuid4())
    attacker_app_id = str(uuid.uuid4())
    attacker_user_id = str(uuid.uuid4())

    result = tasks.execute_by_deployment.run(
        str(deployment.id),
        {},
        {
            "trigger_mode": trigger_mode,
            "workflow_id": attacker_workflow_id,
            "organization_id": attacker_organization_id,
            "app_id": attacker_app_id,
            "user_id": attacker_user_id,
            "deployment_id": str(uuid.uuid4()),
            "workflow_version": 999,
            "execution_subject": {
                "subject_type": "user",
                "subject_id": str(uuid.uuid4()),
            },
            "request_id": "request-1",
        },
    )

    context = FakeWorkflowEngine.calls[0]["kwargs"]["execution_context"]
    assert result["status"] == "success"
    assert context["workflow_id"] == str(app.workflow_id)
    assert context["organization_id"] == str(app.organization_id)
    assert context["app_id"] == str(deployment.app_id)
    assert context["deployment_id"] == str(deployment.id)
    assert context["workflow_version"] == deployment.version
    assert context["user_id"] == str(deployment.created_by)
    assert context["request_id"] == "request-1"
    assert "execution_subject" not in context
    assert attacker_workflow_id not in context.values()
    assert attacker_organization_id not in context.values()
    assert attacker_app_id not in context.values()
    assert attacker_user_id not in context.values()


def test_execute_by_deployment_rejects_inactive_deployment():
    deployment, _app, trigger_mode = _active_deployment_pair()
    deployment.is_active = False

    with pytest.raises(tasks.PermanentDeploymentExecutionError):
        tasks.execute_by_deployment.run(
            str(deployment.id),
            {},
            {"trigger_mode": trigger_mode},
        )

    assert FakeWorkflowEngine.calls == []


def test_execute_by_deployment_rejects_deleted_deployment_without_retry():
    FakeSession.deployment = False

    with pytest.raises(tasks.PermanentDeploymentExecutionError):
        tasks.execute_by_deployment.run(
            str(uuid.uuid4()),
            {},
            {"trigger_mode": "schedule"},
        )

    assert FakeWorkflowEngine.calls == []


def test_execute_by_deployment_rejects_missing_graph_without_retry():
    deployment, _app, trigger_mode = _active_deployment_pair(
        deployment_type=DeploymentType.SCHEDULE,
        trigger_mode="schedule",
    )
    deployment.graph_snapshot = None

    with pytest.raises(tasks.PermanentDeploymentExecutionError):
        tasks.execute_by_deployment.run(
            str(deployment.id),
            {},
            {"trigger_mode": trigger_mode},
        )

    assert FakeWorkflowEngine.calls == []


def test_execute_by_deployment_rejects_stale_active_pointer():
    deployment, app, trigger_mode = _active_deployment_pair()
    app.active_deployment_id = uuid.uuid4()

    with pytest.raises(tasks.PermanentDeploymentExecutionError):
        tasks.execute_by_deployment.run(
            str(deployment.id),
            {},
            {"trigger_mode": trigger_mode},
        )

    assert FakeWorkflowEngine.calls == []


def test_execute_by_deployment_rejects_trigger_type_mismatch():
    deployment, _app, _trigger_mode = _active_deployment_pair(
        deployment_type=DeploymentType.WEBHOOK,
    )

    with pytest.raises(tasks.PermanentDeploymentExecutionError):
        tasks.execute_by_deployment.run(
            str(deployment.id),
            {},
            {"trigger_mode": "schedule"},
        )

    assert FakeWorkflowEngine.calls == []


def test_claim_mode_rejects_legacy_generic_schedule_task(monkeypatch):
    deployment, _app, _trigger_mode = _active_deployment_pair(
        deployment_type=DeploymentType.SCHEDULE,
        trigger_mode="schedule",
    )
    monkeypatch.setattr(
        tasks,
        "get_schedule_dispatch_settings",
        lambda: SimpleNamespace(mode="claim"),
    )

    with pytest.raises(tasks.PermanentDeploymentExecutionError):
        tasks.execute_by_deployment.run(
            str(deployment.id),
            {},
            {"trigger_mode": "schedule"},
        )

    assert FakeWorkflowEngine.calls == []


def test_execute_by_deployment_uses_worker_runtime_policy_provider(monkeypatch):
    deployment, _app, trigger_mode = _active_deployment_pair()
    injected_policy = DEFAULT_DEPLOYMENT_RUNTIME_POLICY.with_surface_allowed_types(
        SURFACE_WEBHOOK_RUN,
        set(),
    )
    monkeypatch.setattr(
        tasks,
        "get_deployment_runtime_policy",
        lambda: injected_policy,
    )

    with pytest.raises(tasks.PermanentDeploymentExecutionError):
        tasks.execute_by_deployment.run(
            str(deployment.id),
            {},
            {"trigger_mode": trigger_mode},
        )

    assert FakeWorkflowEngine.calls == []


def test_execute_by_deployment_rejects_workflow_node_deployment():
    deployment, _app, trigger_mode = _active_deployment_pair(
        deployment_type=DeploymentType.WORKFLOW_NODE,
    )

    with pytest.raises(tasks.PermanentDeploymentExecutionError):
        tasks.execute_by_deployment.run(
            str(deployment.id),
            {},
            {"trigger_mode": trigger_mode},
        )

    assert FakeWorkflowEngine.calls == []


def test_execute_by_deployment_does_not_retry_non_retryable_runtime_error():
    deployment, _app, trigger_mode = _active_deployment_pair()
    FakeWorkflowEngine.execute_error = NonRetryableWorkflowError(
        "Recursive workflow-node reference detected"
    )

    with pytest.raises(NonRetryableWorkflowError):
        tasks.execute_by_deployment.run(
            str(deployment.id),
            {},
            {"trigger_mode": trigger_mode},
        )

    assert len(FakeWorkflowEngine.calls) == 1
