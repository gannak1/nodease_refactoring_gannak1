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

    monkeypatch.setattr(app_service, "has_organization_manager_permission", lambda *a: False)
    monkeypatch.setattr(app_service, "has_workflow_permission", lambda *a, **k: True)

    assert AppService.can_read_app(SimpleNamespace(), app, user_id) is True


def test_app_read_denies_non_reader(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(app_service, "has_organization_manager_permission", lambda *a: False)
    monkeypatch.setattr(app_service, "has_workflow_permission", lambda *a, **k: False)

    assert AppService.can_read_app(SimpleNamespace(), app, user_id) is False
