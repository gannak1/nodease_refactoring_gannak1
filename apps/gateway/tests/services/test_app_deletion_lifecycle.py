import uuid
from types import SimpleNamespace

import pytest

from apps.gateway.services.app_service import AppService
from apps.shared.db.models.app import App
from apps.shared.db.models.team import TeamWorkflowPermission, UserWorkflowPermission
from apps.shared.db.models.workflow import Workflow


class _SimulatedWorkflowForeignKeyViolation(RuntimeError):
    pass


class _DeleteQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model
        self.filters = []

    def filter(self, *_expressions):
        self.filters.extend(_expressions)
        self.db.filter_count_by_model[self.model] = (
            self.db.filter_count_by_model.get(self.model, 0) + len(_expressions)
        )
        return self

    def populate_existing(self):
        return self

    def with_for_update(self):
        self.db.app_lock_acquired = True
        return self

    def first(self):
        rows = self.db.rows_by_model.get(self.model, [])
        return rows[0] if rows else None

    def all(self):
        return list(self.db.rows_by_model.get(self.model, []))

    def delete(self, *_args, **_kwargs):
        if self.model is Workflow:
            remaining_permissions = (
                self.db.rows_by_model.get(TeamWorkflowPermission, [])
                + self.db.rows_by_model.get(UserWorkflowPermission, [])
            )
            if remaining_permissions:
                raise _SimulatedWorkflowForeignKeyViolation(
                    "workflow permissions still reference the workflow"
                )

        rows = self.db.rows_by_model.get(self.model, [])
        matched_rows = [row for row in rows if self._matches(row)]
        self.db.events.append(("delete", self.model))
        self.db.rows_by_model[self.model] = [
            row for row in rows if row not in matched_rows
        ]
        return len(matched_rows)

    def _matches(self, row):
        for expression in self.filters:
            column_name = getattr(getattr(expression, "left", None), "name", None)
            expected = getattr(getattr(expression, "right", None), "value", None)
            if column_name is None:
                continue
            if isinstance(expected, (list, tuple, set, frozenset)):
                if str(getattr(row, column_name, None)) not in {
                    str(value) for value in expected
                }:
                    return False
                continue
            if str(getattr(row, column_name, None)) != str(expected):
                return False
        return True


class _DeleteDb:
    def __init__(self, rows_by_model, *, fail_on_flush_number=None):
        self.rows_by_model = rows_by_model
        self.events = []
        self.filter_count_by_model = {}
        self.app_lock_acquired = False
        self.committed = False
        self.rolled_back = False
        self.flush_count = 0
        self.fail_on_flush_number = fail_on_flush_number

    def query(self, model):
        return _DeleteQuery(self, model)

    def flush(self):
        self.flush_count += 1
        self.events.append(("flush", None))
        if self.flush_count == self.fail_on_flush_number:
            raise RuntimeError("injected lifecycle flush failure")

    def delete(self, row):
        for model, rows in self.rows_by_model.items():
            if row in rows:
                rows.remove(row)
                self.events.append(("delete", model))
                return

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, _row):
        return None


def _deletion_fixture():
    organization_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    app_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    app = SimpleNamespace(
        id=app_id,
        organization_id=organization_id,
        workflow_id=workflow_id,
        created_by=actor_id,
    )
    workflow = SimpleNamespace(
        id=workflow_id,
        organization_id=organization_id,
        app_id=app_id,
    )
    team_permission = SimpleNamespace(workflow_id=workflow_id)
    user_permission = SimpleNamespace(workflow_id=workflow_id)
    db = _DeleteDb(
        {
            App: [app],
            Workflow: [workflow],
            TeamWorkflowPermission: [team_permission],
            UserWorkflowPermission: [user_permission],
        }
    )
    return db, app, actor_id


def test_delete_app_rechecks_manage_permission_after_lifecycle_lock(monkeypatch):
    db, app, actor_id = _deletion_fixture()

    def require_locked_permission_check(_db, _app, _user_id):
        assert db.app_lock_acquired, "manage permission must be rechecked after the app lock"
        return True

    monkeypatch.setattr(AppService, "can_manage_app", require_locked_permission_check)

    AppService.delete_app(db, str(app.id), user_id=str(actor_id))


def test_delete_app_removes_workflow_permissions_before_workflow(monkeypatch):
    db, app, actor_id = _deletion_fixture()
    monkeypatch.setattr(AppService, "can_manage_app", lambda *_args: True)

    AppService.delete_app(db, str(app.id), user_id=str(actor_id))

    assert db.rows_by_model[TeamWorkflowPermission] == []
    assert db.rows_by_model[UserWorkflowPermission] == []
    assert db.rows_by_model[Workflow] == []
    assert db.committed is True


def test_delete_app_bounds_legacy_workflow_lookup_by_organization(monkeypatch):
    db, app, actor_id = _deletion_fixture()
    foreign_workflow = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        app_id=app.id,
    )
    db.rows_by_model[Workflow].append(foreign_workflow)
    db.rows_by_model[TeamWorkflowPermission] = []
    db.rows_by_model[UserWorkflowPermission] = []
    monkeypatch.setattr(AppService, "can_manage_app", lambda *_args: True)

    AppService.delete_app(db, str(app.id), user_id=str(actor_id))

    assert db.rows_by_model[Workflow] == [foreign_workflow]


def test_delete_app_rolls_back_when_lifecycle_flush_fails(monkeypatch):
    db, app, actor_id = _deletion_fixture()
    db.rows_by_model[TeamWorkflowPermission] = []
    db.rows_by_model[UserWorkflowPermission] = []
    db.fail_on_flush_number = 2
    monkeypatch.setattr(AppService, "can_manage_app", lambda *_args: True)

    with pytest.raises(RuntimeError, match="injected lifecycle flush failure"):
        AppService.delete_app(db, str(app.id), user_id=str(actor_id))

    assert db.rolled_back is True
    assert db.committed is False
