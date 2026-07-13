from types import SimpleNamespace
from uuid import uuid4

from apps.shared.services import notification_pubsub as module


class _ManagerQuery:
    def __init__(self, rows):
        self.rows = rows
        self.joined = False
        self.filtered = False

    def join(self, *args):
        self.joined = True
        return self

    def filter(self, *args):
        self.filtered = True
        return self

    def all(self):
        return self.rows


def test_manager_notification_publishes_only_resolved_recipient_rows(monkeypatch):
    first_user_id = uuid4()
    second_user_id = uuid4()
    query = _ManagerQuery(
        [SimpleNamespace(user_id=first_user_id), (second_user_id,)]
    )

    class Db:
        def query(self, *args):
            return query

    published = []
    monkeypatch.setattr(
        module,
        "publish_notifications_changed",
        published.append,
    )

    module.publish_notifications_changed_to_organization_managers(
        Db(),
        uuid4(),
    )

    assert query.joined is True
    assert query.filtered is True
    assert published == [first_user_id, second_user_id]


def test_manager_recipient_lookup_failure_is_isolated(monkeypatch):
    class Db:
        def query(self, *args):
            raise RuntimeError("database unavailable")

    published = []
    monkeypatch.setattr(
        module,
        "publish_notifications_changed",
        published.append,
    )

    module.publish_notifications_changed_to_organization_managers(
        Db(),
        uuid4(),
    )

    assert published == []
