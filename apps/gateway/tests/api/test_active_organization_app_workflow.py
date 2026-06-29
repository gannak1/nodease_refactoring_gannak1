import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.sql.operators import eq

from apps.gateway.api.v1.endpoints import app as app_endpoint
from apps.gateway.api.v1.endpoints import workflow as workflow_endpoint
from apps.gateway.services import app_service
from apps.gateway.services import workflow_service
from apps.gateway.services.app_service import AppService
from apps.gateway.services.workflow_service import WorkflowService


def test_create_app_uses_active_organization_header(monkeypatch):
    organization_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4())
    payload = object()
    captured = {}

    monkeypatch.setattr(
        app_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, user_id: organization_id,
    )
    monkeypatch.setattr(
        app_endpoint.AppService,
        "create_app",
        lambda db, request, user_id, organization_id=None: captured.update(
            {
                "request": request,
                "user_id": user_id,
                "organization_id": organization_id,
            }
        )
        or "created",
    )

    result = app_endpoint.create_app(
        request=object(),
        payload=payload,
        x_organization_id=str(organization_id),
        db=object(),
        current_user=user,
    )

    assert result == "created"
    assert captured == {
        "request": payload,
        "user_id": user.id,
        "organization_id": organization_id,
    }


def test_clone_app_uses_active_organization_header(monkeypatch):
    organization_id = uuid.uuid4()
    source_app_id = str(uuid.uuid4())
    user = SimpleNamespace(id=uuid.uuid4())
    captured = {}

    monkeypatch.setattr(
        app_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, user_id: organization_id,
    )
    monkeypatch.setattr(
        app_endpoint,
        "_get_app_or_404",
        lambda db, app_id: SimpleNamespace(id=app_id),
    )
    monkeypatch.setattr(
        app_endpoint.AppService,
        "access_denial_status",
        lambda db, app, user_id, action: None,
    )
    monkeypatch.setattr(
        app_endpoint.AppService,
        "clone_app",
        lambda db, user_id, source_app_id, organization_id=None: captured.update(
            {
                "user_id": user_id,
                "source_app_id": source_app_id,
                "organization_id": organization_id,
            }
        )
        or "cloned",
    )

    result = app_endpoint.clone_app(
        app_id=source_app_id,
        request=object(),
        x_organization_id=str(organization_id),
        db=object(),
        current_user=user,
    )

    assert result == "cloned"
    assert captured == {
        "user_id": user.id,
        "source_app_id": source_app_id,
        "organization_id": organization_id,
    }


def test_list_apps_uses_active_organization_header(monkeypatch):
    organization_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4())
    captured = {}

    monkeypatch.setattr(
        app_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, user_id: organization_id,
    )
    monkeypatch.setattr(
        app_endpoint.AppService,
        "get_user_apps",
        lambda db, user_id, organization_id=None: captured.update(
            {
                "user_id": user_id,
                "organization_id": organization_id,
            }
        )
        or ["app"],
    )

    result = app_endpoint.list_apps(
        request=object(),
        x_organization_id=str(organization_id),
        db=object(),
        current_user=user,
    )

    assert result == ["app"]
    assert captured == {
        "user_id": user.id,
        "organization_id": organization_id,
    }


def test_create_workflow_uses_active_organization_header(monkeypatch):
    organization_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4())
    payload = object()
    captured = {}

    workflow = SimpleNamespace(
        id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        created_at=SimpleNamespace(isoformat=lambda: "created"),
        updated_at=SimpleNamespace(isoformat=lambda: "updated"),
    )
    monkeypatch.setattr(
        workflow_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, user_id: organization_id,
    )
    monkeypatch.setattr(
        workflow_endpoint.WorkflowService,
        "create_workflow",
        lambda db, request, user_id, organization_id=None: captured.update(
            {
                "request": request,
                "user_id": user_id,
                "organization_id": organization_id,
            }
        )
        or workflow,
    )

    result = workflow_endpoint.create_workflow(
        request=object(),
        payload=payload,
        x_organization_id=str(organization_id),
        db=object(),
        current_user=user,
    )

    assert result["id"] == str(workflow.id)
    assert captured == {
        "request": payload,
        "user_id": user.id,
        "organization_id": organization_id,
    }


class _FakeQuery:
    def __init__(self, value):
        self.value = value
        self.filters = []

    def filter(self, *args, **kwargs):
        self.filters.extend(args)
        return self

    def options(self, *args, **kwargs):
        return self

    def first(self):
        return self.value

    def all(self):
        return self.value


class _FakeDb:
    def __init__(self, value):
        self.value = value
        self.query_obj = _FakeQuery(value)

    def query(self, *args, **kwargs):
        return self.query_obj


def test_get_user_apps_filters_by_active_organization_before_permission_filter(monkeypatch):
    organization_id = uuid.uuid4()
    app = SimpleNamespace(
        organization_id=organization_id,
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        active_deployment_id=None,
    )
    db = _FakeDb([app])

    monkeypatch.setattr(app_service, "has_organization_manager_permission", lambda *a: True)
    monkeypatch.setattr(AppService, "_populate_owner_name", lambda *a: None)
    monkeypatch.setattr(AppService, "_populate_deployment_status", lambda *a: None)

    apps = AppService.get_user_apps(db, uuid.uuid4(), organization_id=organization_id)

    assert apps == [app]
    assert any(
        str(getattr(expression, "left", "")) == "apps.organization_id"
        and expression.operator is eq
        and expression.right.value == organization_id
        for expression in db.query_obj.filters
    )


def test_create_workflow_rejects_active_organization_mismatch(monkeypatch):
    app_organization_id = uuid.uuid4()
    active_organization_id = uuid.uuid4()
    app = SimpleNamespace(id=uuid.uuid4(), organization_id=app_organization_id)

    monkeypatch.setattr(
        workflow_service.AppService,
        "can_manage_app",
        lambda db, app, user_id: True,
    )

    with pytest.raises(HTTPException) as exc_info:
        WorkflowService.create_workflow(
            _FakeDb(app),
            SimpleNamespace(app_id=app.id),
            user_id=uuid.uuid4(),
            organization_id=active_organization_id,
        )

    assert exc_info.value.status_code == 404
