import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.gateway.api.v1.endpoints import deployment as deployment_endpoint
from apps.shared.db.models.app import App
from apps.shared.db.models.workflow_deployment import WorkflowDeployment
from apps.shared.schemas.deployment import (
    DeploymentPreflightRequest,
    DeploymentPreflightResponse,
)


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.result


class FakeDb:
    def __init__(self, app):
        self.app = app

    def query(self, *args, **kwargs):
        return FakeQuery(self.app)


class FakeModelDb:
    def __init__(self, rows_by_model):
        self.rows_by_model = rows_by_model

    def query(self, model, *args, **kwargs):
        return FakeQuery(self.rows_by_model.get(model))


def test_get_deployments_authorizes_app_workflow_when_app_and_workflow_supplied(
    monkeypatch,
):
    app_workflow_id = uuid.uuid4()
    supplied_workflow_id = uuid.uuid4()
    app = SimpleNamespace(id=uuid.uuid4(), workflow_id=app_workflow_id)
    user = SimpleNamespace(id=uuid.uuid4())
    checked_workflow_ids = []

    def deny(db, current_user, checked_workflow_id, action):
        checked_workflow_ids.append(checked_workflow_id)
        raise HTTPException(status_code=403, detail="Forbidden")

    def fail_list(*args, **kwargs):
        raise AssertionError("deployments should not be listed without app permission")

    monkeypatch.setattr(deployment_endpoint, "ensure_workflow_permission", deny)
    monkeypatch.setattr(
        deployment_endpoint.DeploymentService, "list_deployments", fail_list
    )

    with pytest.raises(HTTPException) as exc_info:
        deployment_endpoint.get_deployments(
            app_id=str(app.id),
            workflow_id=str(supplied_workflow_id),
            db=FakeDb(app),
            current_user=user,
        )

    assert exc_info.value.status_code == 403
    assert checked_workflow_ids == [app_workflow_id]


def test_get_deployments_rejects_app_workflow_mismatch_after_authorization(
    monkeypatch,
):
    app_workflow_id = uuid.uuid4()
    supplied_workflow_id = uuid.uuid4()
    app = SimpleNamespace(id=uuid.uuid4(), workflow_id=app_workflow_id)
    user = SimpleNamespace(id=uuid.uuid4())

    def allow(db, current_user, checked_workflow_id, action):
        assert checked_workflow_id == app_workflow_id
        assert action == "read"

    def fail_list(*args, **kwargs):
        raise AssertionError("mismatched ids should not reach the service")

    monkeypatch.setattr(deployment_endpoint, "ensure_workflow_permission", allow)
    monkeypatch.setattr(
        deployment_endpoint.DeploymentService, "list_deployments", fail_list
    )

    with pytest.raises(HTTPException) as exc_info:
        deployment_endpoint.get_deployments(
            app_id=str(app.id),
            workflow_id=str(supplied_workflow_id),
            db=FakeDb(app),
            current_user=user,
        )

    assert exc_info.value.status_code == 400


def test_get_deployments_accepts_equivalent_workflow_uuid_text(monkeypatch):
    app_workflow_id = uuid.uuid4()
    app = SimpleNamespace(id=uuid.uuid4(), workflow_id=app_workflow_id)
    user = SimpleNamespace(id=uuid.uuid4())

    def allow(db, current_user, checked_workflow_id, action):
        assert checked_workflow_id == app_workflow_id
        assert action == "read"

    def list_deployments(*args, **kwargs):
        assert kwargs["app_id"] == str(app.id)
        assert kwargs["workflow_id"] == str(app_workflow_id).upper()
        return ["deployment"]

    monkeypatch.setattr(deployment_endpoint, "ensure_workflow_permission", allow)
    monkeypatch.setattr(
        deployment_endpoint.DeploymentService, "list_deployments", list_deployments
    )

    result = deployment_endpoint.get_deployments(
        app_id=str(app.id),
        workflow_id=str(app_workflow_id).upper(),
        db=FakeDb(app),
        current_user=user,
    )

    assert result == ["deployment"]


def test_preview_deployment_preflight_authorizes_deploy_and_returns_result(monkeypatch):
    workflow_id = uuid.uuid4()
    app = SimpleNamespace(id=uuid.uuid4(), workflow_id=workflow_id)
    current_user = SimpleNamespace(id=uuid.uuid4())
    graph = {"nodes": [], "edges": []}
    checked = []
    captured = {}

    def allow(db, user, checked_workflow_id, action):
        checked.append((user.id, checked_workflow_id, action))

    def resolve_graph(db, checked_workflow_id, graph_snapshot):
        captured["resolve"] = (checked_workflow_id, graph_snapshot)
        return graph

    def preview(db, **kwargs):
        captured["preview"] = kwargs
        return DeploymentPreflightResponse(
            status="passed",
            audience="anonymous_public",
        )

    monkeypatch.setattr(deployment_endpoint, "ensure_workflow_permission", allow)
    monkeypatch.setattr(
        deployment_endpoint.DeploymentService,
        "_resolve_graph_snapshot",
        resolve_graph,
    )
    monkeypatch.setattr(
        deployment_endpoint.DeploymentService,
        "preview_knowledge_preflight",
        preview,
    )

    result = deployment_endpoint.preview_deployment_preflight(
        DeploymentPreflightRequest(
            app_id=app.id,
            type="chatbot",
            config={},
            is_active=True,
            graph_snapshot=graph,
            audience="anonymous_public",
        ),
        db=FakeModelDb({App: app}),
        current_user=current_user,
    )

    assert result.status == "passed"
    assert checked == [(current_user.id, workflow_id, "deploy")]
    assert captured["resolve"] == (workflow_id, graph)
    assert captured["preview"]["app"] == app
    assert captured["preview"]["deployment_type"].value == "chatbot"
    assert captured["preview"]["graph_snapshot"] == graph
    assert captured["preview"]["audience_hint"] == "anonymous_public"


def test_authenticated_run_routes_are_registered_before_deployment_detail():
    paths = [getattr(route, "path", "") for route in deployment_endpoint.router.routes]

    assert paths.index("/{deployment_id}/run-info") < paths.index("/{deployment_id}")
    assert paths.index("/{deployment_id}/run") < paths.index("/{deployment_id}")


def test_run_authenticated_deployment_authorizes_execute_and_forwards_inputs(
    monkeypatch,
):
    workflow_id = uuid.uuid4()
    deployment = WorkflowDeployment(
        id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        version=1,
        graph_snapshot={"nodes": [], "edges": []},
        is_active=True,
        created_by=uuid.uuid4(),
    )
    app = App(
        id=deployment.app_id,
        workflow_id=workflow_id,
        active_deployment_id=deployment.id,
        created_by=uuid.uuid4(),
    )
    current_user = SimpleNamespace(id=uuid.uuid4())
    checked = []
    captured = {}

    def allow(db, user, checked_workflow_id, action):
        checked.append((user.id, checked_workflow_id, action))

    async def run_service(**kwargs):
        captured.update(kwargs)
        return {"status": "success", "results": {"answer": "ok"}}

    monkeypatch.setattr(deployment_endpoint, "ensure_workflow_permission", allow)
    monkeypatch.setattr(
        deployment_endpoint.DeploymentService,
        "run_authenticated_deployment",
        run_service,
    )

    result = asyncio.run(
        deployment_endpoint.run_authenticated_deployment(
            deployment_id=str(deployment.id),
            request=SimpleNamespace(headers={"x-request-id": "req-1"}),
            request_body={"inputs": {"question": "개발팀 커밋 컨벤션은?"}},
            db=FakeModelDb({WorkflowDeployment: deployment, App: app}),
            current_user=current_user,
        )
    )

    assert result["status"] == "success"
    assert checked == [(current_user.id, workflow_id, "execute")]
    assert captured["deployment_id"] == str(deployment.id)
    assert captured["user_inputs"] == {"question": "개발팀 커밋 컨벤션은?"}
    assert captured["current_user_id"] == current_user.id
    assert captured["request_id"] == "req-1"


def test_run_authenticated_deployment_forwards_middleware_request_id(
    monkeypatch,
):
    workflow_id = uuid.uuid4()
    deployment = WorkflowDeployment(
        id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        version=1,
        graph_snapshot={"nodes": [], "edges": []},
        is_active=True,
        created_by=uuid.uuid4(),
    )
    app = App(
        id=deployment.app_id,
        workflow_id=workflow_id,
        active_deployment_id=deployment.id,
        created_by=uuid.uuid4(),
    )
    current_user = SimpleNamespace(id=uuid.uuid4())
    captured = {}

    monkeypatch.setattr(
        deployment_endpoint,
        "ensure_workflow_permission",
        lambda db, user, checked_workflow_id, action: None,
    )

    async def run_service(**kwargs):
        captured.update(kwargs)
        return {"status": "success", "results": {"answer": "ok"}}

    monkeypatch.setattr(
        deployment_endpoint.DeploymentService,
        "run_authenticated_deployment",
        run_service,
    )

    asyncio.run(
        deployment_endpoint.run_authenticated_deployment(
            deployment_id=str(deployment.id),
            request=SimpleNamespace(
                headers={},
                state=SimpleNamespace(request_id="middleware-req-1"),
            ),
            request_body={"inputs": {"question": "개발팀 커밋 컨벤션은?"}},
            db=FakeModelDb({WorkflowDeployment: deployment, App: app}),
            current_user=current_user,
        )
    )

    assert captured["request_id"] == "middleware-req-1"


def test_get_authenticated_deployment_run_info_authorizes_execute(monkeypatch):
    workflow_id = uuid.uuid4()
    deployment = WorkflowDeployment(
        id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        version=1,
        graph_snapshot={"nodes": [], "edges": []},
        is_active=True,
        created_by=uuid.uuid4(),
    )
    app = App(
        id=deployment.app_id,
        workflow_id=workflow_id,
        organization_id=uuid.uuid4(),
        active_deployment_id=deployment.id,
        created_by=uuid.uuid4(),
    )
    current_user = SimpleNamespace(id=uuid.uuid4())
    checked = []

    def allow(db, user, checked_workflow_id, action):
        checked.append((user.id, checked_workflow_id, action))

    monkeypatch.setattr(deployment_endpoint, "ensure_workflow_permission", allow)
    monkeypatch.setattr(
        deployment_endpoint.DeploymentService,
        "get_deployment_run_info",
        lambda db, deployment_id: {
            "deployment_id": deployment_id,
            "name": "safe run info",
            "input_schema": {"variables": []},
        },
    )

    result = deployment_endpoint.get_authenticated_deployment_run_info(
        deployment_id=str(deployment.id),
        request=SimpleNamespace(headers={}),
        db=FakeModelDb({WorkflowDeployment: deployment, App: app}),
        current_user=current_user,
    )

    assert result["name"] == "safe run info"
    assert checked == [(current_user.id, workflow_id, "execute")]


def test_run_authenticated_deployment_rejects_non_object_inputs(monkeypatch):
    workflow_id = uuid.uuid4()
    deployment = WorkflowDeployment(
        id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        version=1,
        graph_snapshot={"nodes": [], "edges": []},
        is_active=True,
        created_by=uuid.uuid4(),
    )
    app = App(
        id=deployment.app_id,
        workflow_id=workflow_id,
        active_deployment_id=deployment.id,
        created_by=uuid.uuid4(),
    )

    monkeypatch.setattr(
        deployment_endpoint,
        "ensure_workflow_permission",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            deployment_endpoint.run_authenticated_deployment(
                deployment_id=str(deployment.id),
                request=SimpleNamespace(headers={}),
                request_body={"inputs": "not-an-object"},
                db=FakeModelDb({WorkflowDeployment: deployment, App: app}),
                current_user=SimpleNamespace(id=uuid.uuid4()),
            )
        )

    assert exc_info.value.status_code == 400


def test_run_authenticated_deployment_masks_active_organization_mismatch(
    monkeypatch,
):
    workflow_id = uuid.uuid4()
    active_organization_id = uuid.uuid4()
    app_organization_id = uuid.uuid4()
    deployment = WorkflowDeployment(
        id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        version=1,
        graph_snapshot={"nodes": [], "edges": []},
        is_active=True,
        created_by=uuid.uuid4(),
    )
    app = App(
        id=deployment.app_id,
        workflow_id=workflow_id,
        organization_id=app_organization_id,
        active_deployment_id=deployment.id,
        created_by=uuid.uuid4(),
    )

    monkeypatch.setattr(
        deployment_endpoint,
        "resolve_active_organization_id",
        lambda *args, **kwargs: active_organization_id,
    )
    monkeypatch.setattr(
        deployment_endpoint,
        "ensure_workflow_permission",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("permission check should not run after org mismatch")
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            deployment_endpoint.run_authenticated_deployment(
                deployment_id=str(deployment.id),
                request=SimpleNamespace(headers={}),
                request_body={"inputs": {}},
                x_organization_id=str(active_organization_id),
                db=FakeModelDb({WorkflowDeployment: deployment, App: app}),
                current_user=SimpleNamespace(id=uuid.uuid4()),
            )
        )

    assert exc_info.value.status_code == 404


def test_toggle_audit_action_marks_previous_activation():
    deployment_id = uuid.uuid4()
    deployment = SimpleNamespace(id=deployment_id, is_active=False)
    app = SimpleNamespace(active_deployment_id=uuid.uuid4())

    assert (
        deployment_endpoint._deployment_toggle_audit_action(deployment, app)
        == deployment_endpoint.AuditAction.DEPLOYMENT_ACTIVATE_PREVIOUS
    )


def test_toggle_audit_action_keeps_regular_toggle_for_deactivation():
    deployment_id = uuid.uuid4()
    deployment = SimpleNamespace(id=deployment_id, is_active=True)
    app = SimpleNamespace(active_deployment_id=deployment_id)

    assert (
        deployment_endpoint._deployment_toggle_audit_action(deployment, app)
        == deployment_endpoint.AuditAction.DEPLOYMENT_TOGGLE
    )
