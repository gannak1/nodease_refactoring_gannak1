import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.gateway.api.v1.endpoints import deployment as deployment_endpoint


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
