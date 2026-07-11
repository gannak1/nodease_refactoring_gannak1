from __future__ import annotations

import pytest

from apps.shared.alembic.migration_lock import migration_advisory_lock


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _Connection:
    def __init__(self, acquired=True):
        self.acquired = acquired
        self.calls = []

    def execute(self, statement, parameters):
        sql = str(statement)
        self.calls.append((sql, parameters))
        if "pg_try_advisory_lock" in sql:
            return _Result(self.acquired)
        return _Result(True)


def test_migration_lock_is_released_after_success_and_failure():
    connection = _Connection()
    with migration_advisory_lock(connection):
        pass
    assert "pg_try_advisory_lock" in connection.calls[0][0]
    assert "pg_advisory_unlock" in connection.calls[-1][0]

    failing_connection = _Connection()
    with pytest.raises(RuntimeError, match="migration body failed"):
        with migration_advisory_lock(failing_connection):
            raise RuntimeError("migration body failed")
    assert "pg_advisory_unlock" in failing_connection.calls[-1][0]


def test_migration_lock_fails_closed_when_another_owner_exists():
    connection = _Connection(acquired=False)

    with pytest.raises(RuntimeError, match="already running"):
        with migration_advisory_lock(connection):
            pass

    assert len(connection.calls) == 1
