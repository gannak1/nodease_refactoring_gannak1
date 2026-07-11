from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text

MIGRATION_ADVISORY_LOCK_ID = 734_187_2026


@contextmanager
def migration_advisory_lock(connection):
    """Own one bounded PostgreSQL migration session at a time."""
    acquired = bool(
        connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
        ).scalar()
    )
    if not acquired:
        raise RuntimeError("another database migration is already running")
    try:
        yield
    finally:
        connection.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
        )
