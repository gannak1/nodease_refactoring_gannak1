import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.sql.operators import eq

from apps.gateway.services import app_service
from apps.gateway.services.app_service import AppService
from apps.shared.db.models.app import App
from apps.shared.db.models.workflow_deployment import WorkflowDeployment


class _FilteringQuery:
    def __init__(self, rows):
        self.rows = list(rows)
        self.expressions = []

    def filter(self, *expressions):
        self.expressions.extend(expressions)
        return self

    def first(self):
        return next(
            (
                row
                for row in self.rows
                if all(self._matches(row, expression) for expression in self.expressions)
            ),
            None,
        )

    @staticmethod
    def _matches(row, expression):
        left = getattr(expression, "left", None)
        if left is None or expression.operator is not eq:
            return True
        column = getattr(left, "key", None)
        if not column or not hasattr(row, column):
            return False
        right = expression.right
        expected = right.value if hasattr(right, "value") else right
        return getattr(row, column) == expected


class _ModelDb:
    def __init__(self, rows_by_model):
        self.rows_by_model = rows_by_model

    def query(self, model):
        return _FilteringQuery(self.rows_by_model.get(model, []))


def test_app_read_allows_primary_workflow_reader(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        is_market=False,
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
        is_market=False,
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(app_service, "has_organization_manager_permission", lambda *a: False)
    monkeypatch.setattr(app_service, "has_workflow_permission", lambda *a, **k: False)

    assert AppService.can_read_app(SimpleNamespace(), app, user_id) is False


def test_app_read_denial_is_403_inside_organization_scope(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        is_market=False,
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
        is_market=False,
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
        is_market=False,
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


def test_app_read_allows_marketplace_app_without_permissions(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        is_market=True,
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(app_service, "has_organization_manager_permission", lambda *a: False)
    monkeypatch.setattr(app_service, "has_workflow_permission", lambda *a, **k: False)

    assert AppService.can_read_app(SimpleNamespace(), app, user_id) is True


def test_app_operations_read_denies_marketplace_app_without_workflow_read(
    monkeypatch,
):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        is_market=True,
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(
        app_service, "has_organization_manager_permission", lambda *a: False
    )
    monkeypatch.setattr(app_service, "has_workflow_permission", lambda *a, **k: False)

    assert AppService.can_read_app(SimpleNamespace(), app, user_id) is True
    assert AppService.can_read_app_operations(SimpleNamespace(), app, user_id) is False


def test_app_operations_read_allows_primary_workflow_builder(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        is_market=True,
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(
        app_service, "has_organization_manager_permission", lambda *a: False
    )
    monkeypatch.setattr(app_service, "has_workflow_permission", lambda *a, **k: True)

    assert AppService.can_read_app_operations(SimpleNamespace(), app, user_id) is True


def test_app_operations_read_allows_organization_manager(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        is_market=False,
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(
        app_service, "has_organization_manager_permission", lambda *a: True
    )
    monkeypatch.setattr(app_service, "has_workflow_permission", lambda *a, **k: False)

    assert AppService.can_read_app_operations(SimpleNamespace(), app, user_id) is True


def test_app_operations_read_denies_execute_only_workflow_user(monkeypatch):
    app = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        is_market=False,
    )
    user_id = uuid.uuid4()

    monkeypatch.setattr(
        app_service, "has_organization_manager_permission", lambda *a: False
    )

    def has_workflow_permission(*args, **kwargs):
        return args[3] in {"read", "execute"}

    monkeypatch.setattr(app_service, "has_workflow_permission", has_workflow_permission)

    assert AppService.can_read_app(SimpleNamespace(), app, user_id) is True
    assert AppService.can_read_app_operations(SimpleNamespace(), app, user_id) is False


def test_deployment_status_ignores_cross_app_active_pointer():
    app = SimpleNamespace(id=uuid.uuid4(), active_deployment_id=uuid.uuid4())
    deployment = SimpleNamespace(
        id=app.active_deployment_id,
        app_id=uuid.uuid4(),
        is_active=True,
    )
    db = _ModelDb({WorkflowDeployment: [deployment]})

    AppService._populate_deployment_status(db, app)

    assert app.active_deployment_is_active is None


def test_deployment_status_accepts_matching_app_active_pointer():
    app = SimpleNamespace(id=uuid.uuid4(), active_deployment_id=uuid.uuid4())
    deployment = SimpleNamespace(
        id=app.active_deployment_id,
        app_id=app.id,
        is_active=True,
    )
    db = _ModelDb({WorkflowDeployment: [deployment]})

    AppService._populate_deployment_status(db, app)

    assert app.active_deployment_is_active is True


def test_clone_app_rejects_cross_app_active_deployment_pointer(monkeypatch):
    source_app = SimpleNamespace(
        id=uuid.uuid4(),
        active_deployment_id=uuid.uuid4(),
    )
    deployment = SimpleNamespace(
        id=source_app.active_deployment_id,
        app_id=uuid.uuid4(),
    )
    db = _ModelDb(
        {
            App: [source_app],
            WorkflowDeployment: [deployment],
        }
    )
    monkeypatch.setattr(AppService, "can_read_app", lambda *args, **kwargs: True)

    with pytest.raises(ValueError, match="Active deployment data not found"):
        AppService.clone_app(
            db,
            source_app.id,
            uuid.uuid4(),
            organization_id=uuid.uuid4(),
        )
