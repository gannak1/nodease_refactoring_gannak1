import uuid
from types import SimpleNamespace

from apps.gateway.services.app_lifecycle_lock import lock_app_for_lifecycle
from apps.shared.db.models.app import App


class _Query:
    def __init__(self, row):
        self.row = row
        self.filters = []
        self.locked = False

    def filter(self, *expressions):
        self.filters.extend(expressions)
        return self

    def with_for_update(self):
        self.locked = True
        return self

    def first(self):
        return self.row


class _Db:
    def __init__(self, row):
        self.query_value = _Query(row)

    def query(self, model):
        assert model is App
        return self.query_value


def test_app_lifecycle_lock_filters_scope_and_uses_for_update():
    row = SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4())
    db = _Db(row)

    result = lock_app_for_lifecycle(
        db,
        row.id,
        organization_id=row.organization_id,
    )

    assert result is row
    assert db.query_value.locked is True
    assert len(db.query_value.filters) == 2
