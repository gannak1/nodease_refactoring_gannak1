"""DELETE /api/v1/apps/{app_id} response and resource-hiding contract."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.gateway.api.v1.endpoints import app as app_endpoint
from apps.gateway.main import app
from apps.gateway.services.app_service import AppService


class _AppQuery:
    def __init__(self, db: "_AppSession") -> None:
        self.db = db

    def filter(self, *_conditions):
        return self

    def first(self):
        return self.db.app_record


class _AppSession:
    def __init__(self, app_record) -> None:
        self.app_record = app_record

    def query(self, _model):
        return _AppQuery(self)


@pytest.fixture(autouse=True)
def _reset_app_overrides(monkeypatch):
    monkeypatch.setattr("apps.gateway.utils.audit.record_audit", Mock())
    monkeypatch.setattr("apps.gateway.main.record_audit", Mock())
    yield
    app.dependency_overrides = {}


def _client_for(db: _AppSession, actor_id, *, raise_server_exceptions=True):
    app.dependency_overrides[app_endpoint.get_db] = lambda: db
    app.dependency_overrides[app_endpoint.get_current_user] = lambda: SimpleNamespace(
        id=actor_id
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_delete_app_returns_200_and_repeat_delete_returns_404(monkeypatch):
    app_id = uuid4()
    actor_id = uuid4()
    db = _AppSession(SimpleNamespace(id=app_id, organization_id=uuid4()))
    delete = Mock()

    def delete_once(_db, requested_app_id, user_id, request_id=None):
        delete(_db, requested_app_id, user_id, request_id=request_id)
        db.app_record = None
        return True

    monkeypatch.setattr(AppService, "access_denial_status", Mock(return_value=None))
    monkeypatch.setattr(AppService, "delete_app", delete_once)
    client = _client_for(db, actor_id)

    first_response = client.delete(
        f"/api/v1/apps/{app_id}",
        headers={"X-Request-ID": "req-app-delete-success"},
    )
    second_response = client.delete(f"/api/v1/apps/{app_id}")

    assert first_response.status_code == 200
    assert first_response.json() == {"message": "App deleted successfully"}
    assert second_response.status_code == 404
    assert second_response.json() == {"detail": "App not found"}
    delete.assert_called_once_with(
        db,
        str(app_id),
        actor_id,
        request_id="req-app-delete-success",
    )


def test_delete_app_does_not_publish_success_audit_outside_delete_transaction(
    monkeypatch,
):
    app_id = uuid4()
    actor_id = uuid4()
    db = _AppSession(SimpleNamespace(id=app_id, organization_id=uuid4()))
    audit_recorder = Mock()
    monkeypatch.setattr("apps.gateway.utils.audit.record_audit", audit_recorder)
    monkeypatch.setattr(AppService, "access_denial_status", Mock(return_value=None))
    monkeypatch.setattr(AppService, "delete_app", Mock(return_value=True))

    response = _client_for(db, actor_id).delete(f"/api/v1/apps/{app_id}")

    assert response.status_code == 200
    audit_recorder.assert_not_called()


def test_delete_app_returns_403_for_same_organization_member_without_manage(
    monkeypatch,
):
    app_id = uuid4()
    actor_id = uuid4()
    db = _AppSession(SimpleNamespace(id=app_id, organization_id=uuid4()))
    delete = Mock()
    monkeypatch.setattr(AppService, "access_denial_status", Mock(return_value=403))
    monkeypatch.setattr(AppService, "delete_app", delete)

    response = _client_for(db, actor_id).delete(f"/api/v1/apps/{app_id}")

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}
    delete.assert_not_called()


def test_delete_app_returns_hidden_404_for_cross_organization_actor(monkeypatch):
    app_id = uuid4()
    actor_id = uuid4()
    workflow_id = uuid4()
    db = _AppSession(
        SimpleNamespace(
            id=app_id,
            organization_id=uuid4(),
            name="must-not-leak-app-name",
            workflow_id=workflow_id,
        )
    )
    delete = Mock()
    monkeypatch.setattr(AppService, "access_denial_status", Mock(return_value=404))
    monkeypatch.setattr(AppService, "delete_app", delete)

    response = _client_for(db, actor_id).delete(f"/api/v1/apps/{app_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "App not found"}
    assert "must-not-leak-app-name" not in response.text
    assert str(workflow_id) not in response.text
    delete.assert_not_called()


def test_delete_app_internal_error_returns_safe_json_without_database_details(
    monkeypatch,
):
    app_id = uuid4()
    actor_id = uuid4()
    db = _AppSession(SimpleNamespace(id=app_id, organization_id=uuid4()))
    sql_sentinel = "DELETE FROM workflows WHERE auth_secret='sql-secret-sentinel'"
    constraint_sentinel = "fk_private_constraint_sentinel"
    secret_sentinel = "sk-private-secret-sentinel"
    monkeypatch.setattr(AppService, "access_denial_status", Mock(return_value=None))
    monkeypatch.setattr(
        AppService,
        "delete_app",
        Mock(
            side_effect=RuntimeError(
                f"{sql_sentinel} {constraint_sentinel} {secret_sentinel}"
            )
        ),
    )

    response = _client_for(
        db,
        actor_id,
        raise_server_exceptions=False,
    ).delete(
        f"/api/v1/apps/{app_id}",
        headers={"X-Request-ID": "req-app-delete-contract"},
    )

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "error": {
            "code": "app.delete_failed",
            "message": "App deletion failed.",
            "request_id": "req-app-delete-contract",
            "details": {},
        }
    }
    response_projection = f"{response.text} {dict(response.headers)}"
    assert sql_sentinel not in response_projection
    assert constraint_sentinel not in response_projection
    assert secret_sentinel not in response_projection
