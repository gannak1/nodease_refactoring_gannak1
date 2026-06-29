import uuid
from types import SimpleNamespace

from apps.gateway.services import app_service
from apps.gateway.services.app_service import AppService


def test_app_read_allows_primary_workflow_reader(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(
        app_service, "has_organization_manager_permission", lambda *a: False
    )
    monkeypatch.setattr(app_service, "has_organization_scope_access", lambda *a: True)
    monkeypatch.setattr(app_service, "has_workflow_permission", lambda *a, **k: True)

    assert AppService.can_read_app(SimpleNamespace(), app, user_id) is True


def test_app_read_denies_stale_workflow_permission_outside_scope(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(
        app_service, "has_organization_scope_access", lambda *a: False
    )
    monkeypatch.setattr(app_service, "has_workflow_permission", lambda *a, **k: True)

    assert AppService.can_read_app(SimpleNamespace(), app, user_id) is False
    assert (
        AppService.access_denial_status(SimpleNamespace(), app, user_id, "read")
        == 404
    )


def test_app_read_denies_non_reader(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(
        app_service, "has_organization_manager_permission", lambda *a: False
    )
    monkeypatch.setattr(app_service, "has_organization_scope_access", lambda *a: True)
    monkeypatch.setattr(app_service, "has_workflow_permission", lambda *a, **k: False)

    assert AppService.can_read_app(SimpleNamespace(), app, user_id) is False


def test_app_read_denial_is_403_inside_organization_scope(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(
        app_service, "has_organization_manager_permission", lambda *a: False
    )
    monkeypatch.setattr(app_service, "has_workflow_permission", lambda *a, **k: False)
    monkeypatch.setattr(app_service, "has_organization_scope_access", lambda *a: True)

    assert (
        AppService.access_denial_status(SimpleNamespace(), app, user_id, "read")
        == 403
    )


def test_app_read_denial_is_404_outside_organization_scope(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(
        app_service, "has_organization_manager_permission", lambda *a: False
    )
    monkeypatch.setattr(app_service, "has_workflow_permission", lambda *a, **k: False)
    monkeypatch.setattr(app_service, "has_organization_scope_access", lambda *a: False)

    assert (
        AppService.access_denial_status(SimpleNamespace(), app, user_id, "read")
        == 404
    )


def test_app_manage_denial_is_403_when_readable(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(
        app_service, "has_organization_manager_permission", lambda *a: False
    )

    def has_workflow_permission(*args, **kwargs):
        return args[3] == "read"

    monkeypatch.setattr(app_service, "has_workflow_permission", has_workflow_permission)
    monkeypatch.setattr(app_service, "has_organization_scope_access", lambda *a: True)

    assert (
        AppService.access_denial_status(SimpleNamespace(), app, user_id, "manage")
        == 403
    )
