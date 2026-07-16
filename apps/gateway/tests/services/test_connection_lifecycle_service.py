import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

from apps.gateway.services.connection_lifecycle_service import (
    ConnectionLifecycleHidden,
    ConnectionLifecycleInUse,
    ConnectionLifecycleService,
    ConnectionLifecycleUnavailable,
)
from apps.shared.db.models.connection import Connection


class _Query:
    def __init__(self, db, entity):
        self.db = db
        self.entity = entity

    def filter(self, *_args):
        return self

    def populate_existing(self):
        return self

    def with_for_update(self):
        self.db.connection_locked = True
        return self

    def first(self):
        if self.db.query_error is not None:
            raise self.db.query_error
        if self.entity is Connection:
            return self.db.connection
        return self.db.reference

    def one_or_none(self):
        return self.first()


class _Db:
    def __init__(self, *, connection=None, reference=None, query_error=None):
        self.connection = connection
        self.reference = reference
        self.query_error = query_error
        self.connection_locked = False
        self.deleted = None
        self.committed = False
        self.rolled_back = False

    def query(self, entity):
        return _Query(self, entity)

    def delete(self, entity):
        self.deleted = entity

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_delete_unreferenced_connection_locks_owner_row_and_commits():
    connection = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4())
    db = _Db(connection=connection)

    ConnectionLifecycleService(db).delete_unreferenced_connection(
        connection_id=connection.id,
        owner_id=connection.user_id,
    )

    assert db.connection_locked is True
    assert db.deleted is connection
    assert db.committed is True
    assert db.rolled_back is False


def test_reference_target_lock_uses_owner_row_without_committing():
    connection = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4())
    db = _Db(connection=connection)

    locked = ConnectionLifecycleService(db).lock_owned_connection_for_reference(
        connection_id=connection.id,
        owner_id=connection.user_id,
    )

    assert locked is connection
    assert db.connection_locked is True
    assert db.committed is False
    assert db.rolled_back is False


def test_delete_connection_hides_missing_or_other_owner_resource():
    db = _Db(connection=None)

    with pytest.raises(ConnectionLifecycleHidden):
        ConnectionLifecycleService(db).delete_unreferenced_connection(
            connection_id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
        )

    assert db.deleted is None
    assert db.rolled_back is True


def test_delete_connection_rejects_document_reference_without_mutation():
    connection = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4())
    db = _Db(connection=connection, reference=(uuid.uuid4(),))

    with pytest.raises(ConnectionLifecycleInUse):
        ConnectionLifecycleService(db).delete_unreferenced_connection(
            connection_id=connection.id,
            owner_id=connection.user_id,
        )

    assert db.deleted is None
    assert db.committed is False
    assert db.rolled_back is True


def test_delete_connection_redacts_database_failure():
    db = _Db(query_error=SQLAlchemyError("raw database detail"))

    with pytest.raises(ConnectionLifecycleUnavailable) as exc_info:
        ConnectionLifecycleService(db).delete_unreferenced_connection(
            connection_id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
        )

    assert "raw database detail" not in str(exc_info.value)
    assert db.rolled_back is True
