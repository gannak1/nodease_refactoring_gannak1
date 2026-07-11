"""Opt-in PostgreSQL evidence for schedule dispatch migration safety."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mbased_schedule_claim"
HEAD_REVISION = "fd1e2f3a4b56"
PRE_CLAIM_REVISION = "fa7b8c9d0e12"


def _run_alembic(
    *args: str,
    database: str,
    config: DisposablePostgresConfig,
    expect_success: bool,
) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "apps/shared/alembic.ini", *args],
        cwd=ROOT_DIR,
        env=config.subprocess_environment(database=database, root_dir=ROOT_DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
        check=False,
    )
    if (result.returncode == 0) != expect_success:
        returncode = result.returncode
        del result
        pytest.fail(
            f"alembic command returned unexpected exit code {returncode}; "
            "stdout/stderr omitted to avoid leaking local configuration"
        )


def _enable_vector_extension(database: str, config: DisposablePostgresConfig) -> None:
    engine = create_engine(config.database_url(database), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    finally:
        engine.dispose()


def _revision(database: str, config: DisposablePostgresConfig) -> str:
    engine = create_engine(config.database_url(database))
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()


def _insert_pending_claim(database: str, config: DisposablePostgresConfig) -> None:
    engine = create_engine(config.database_url(database))
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO schedule_dispatch_claims (
                        id, schedule_id, organization_id, deployment_id,
                        scheduled_for, idempotency_key, status, attempt_count,
                        claimed_at
                    ) VALUES (
                        :id, :schedule_id, :organization_id, :deployment_id,
                        :scheduled_for, :idempotency_key, 'pending', 0,
                        :claimed_at
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "schedule_id": uuid.uuid4(),
                    "organization_id": uuid.uuid4(),
                    "deployment_id": uuid.uuid4(),
                    "scheduled_for": datetime.now(timezone.utc),
                    "idempotency_key": f"schedule:{uuid.uuid4()}",
                    "claimed_at": datetime.now(timezone.utc),
                },
            )
    finally:
        engine.dispose()


def _delete_claims(database: str, config: DisposablePostgresConfig) -> None:
    engine = create_engine(config.database_url(database))
    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM schedule_dispatch_claims"))
    finally:
        engine.dispose()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL schedule migration smoke",
)
def test_schedule_dispatch_migrations_refuse_partial_downgrade_and_reupgrade():
    try:
        config = DisposablePostgresConfig.from_environment()
    except DisposablePostgresConfigurationError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL connection settings are not safely configured",
            pytrace=False,
        ) from None

    database = f"{DB_PREFIX}_{uuid.uuid4().hex[:12]}"
    quoted_database = quote_disposable_database_name(database, prefix=DB_PREFIX)
    admin_engine = create_engine(
        config.database_url(config.maintenance_database),
        isolation_level="AUTOCOMMIT",
    )
    database_created = False

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {quoted_database}"))
        database_created = True

        _enable_vector_extension(database, config)
        _run_alembic("upgrade", "heads", database=database, config=config, expect_success=True)
        assert _revision(database, config) == HEAD_REVISION

        _insert_pending_claim(database, config)
        _run_alembic(
            "downgrade",
            PRE_CLAIM_REVISION,
            database=database,
            config=config,
            expect_success=False,
        )
        assert _revision(database, config) == HEAD_REVISION

        _delete_claims(database, config)
        _run_alembic(
            "downgrade",
            PRE_CLAIM_REVISION,
            database=database,
            config=config,
            expect_success=True,
        )
        assert _revision(database, config) == PRE_CLAIM_REVISION

        _run_alembic("upgrade", "heads", database=database, config=config, expect_success=True)
        assert _revision(database, config) == HEAD_REVISION
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable or rejected the connection; "
            "connection details omitted",
            pytrace=False,
        ) from None
    finally:
        if database_created:
            try:
                with admin_engine.connect() as connection:
                    connection.execute(
                        text(
                            """
                            SELECT pg_terminate_backend(pid)
                            FROM pg_stat_activity
                            WHERE datname = :database
                              AND pid <> pg_backend_pid()
                            """
                        ),
                        {"database": database},
                    )
                    connection.execute(text(f"DROP DATABASE IF EXISTS {quoted_database}"))
            except OperationalError:
                raise pytest.fail.Exception(
                    "disposable PostgreSQL cleanup could not connect; "
                    "connection details omitted",
                    pytrace=False,
                ) from None
        admin_engine.dispose()
