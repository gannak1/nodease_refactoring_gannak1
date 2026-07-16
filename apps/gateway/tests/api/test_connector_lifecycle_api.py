import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.gateway.api.v1.endpoints import connectors as connector_endpoint
from apps.gateway.services.connection_lifecycle_service import (
    ConnectionLifecycleHidden,
    ConnectionLifecycleInUse,
    ConnectionLifecycleUnavailable,
)


@pytest.fixture
def connector_client(monkeypatch):
    app = FastAPI()
    app.include_router(connector_endpoint.router, prefix="/api/v1/connectors")
    db = SimpleNamespace()
    user = SimpleNamespace(id=uuid.uuid4())
    app.dependency_overrides[connector_endpoint.get_db] = lambda: db
    app.dependency_overrides[connector_endpoint.get_current_user] = lambda: user
    monkeypatch.setattr(
        "apps.gateway.utils.audit.record_audit",
        lambda **_kwargs: None,
    )
    with TestClient(app) as client:
        yield client, db, user


@pytest.mark.parametrize(
    ("error", "status_code", "reason_code"),
    [
        (ConnectionLifecycleHidden(), 404, "resource.hidden"),
        (ConnectionLifecycleInUse(), 409, "connection.in_use"),
        (
            ConnectionLifecycleUnavailable(),
            503,
            "connection.delete_unavailable",
        ),
    ],
)
def test_delete_connection_maps_safe_lifecycle_errors(
    connector_client,
    monkeypatch,
    error,
    status_code,
    reason_code,
):
    client, _db, _user = connector_client

    class _Service:
        def __init__(self, _db):
            pass

        def delete_unreferenced_connection(self, **_kwargs):
            raise error

    monkeypatch.setattr(connector_endpoint, "ConnectionLifecycleService", _Service)

    response = client.delete(f"/api/v1/connectors/{uuid.uuid4()}")

    assert response.status_code == status_code
    assert response.json()["detail"] == {"reason_code": reason_code}


def test_delete_connection_returns_no_content_after_owner_cleanup(
    connector_client,
    monkeypatch,
):
    client, dependency_db, user = connector_client
    captured = {}

    class _Service:
        def __init__(self, db):
            captured["db"] = db

        def delete_unreferenced_connection(self, **kwargs):
            captured["kwargs"] = kwargs

    monkeypatch.setattr(connector_endpoint, "ConnectionLifecycleService", _Service)
    connection_id = uuid.uuid4()

    response = client.delete(f"/api/v1/connectors/{connection_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert captured == {
        "db": dependency_db,
        "kwargs": {"connection_id": connection_id, "owner_id": user.id},
    }
