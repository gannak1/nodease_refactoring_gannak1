"""Opt-in PostgreSQL evidence for the external action credential migration."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from runpy import run_path

import pytest
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError


ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mbased_external_action_credential"
MIGRATION_PATH = (
    ROOT_DIR
    / "apps"
    / "shared"
    / "alembic"
    / "versions"
    / "d3e9f5a1b607_add_external_action_credentials.py"
)
MIGRATION = run_path(MIGRATION_PATH)
EXTERNAL_ACTION_CREDENTIAL_REVISION = MIGRATION["revision"]
BASE_REVISION = MIGRATION["down_revision"]
TABLES = {
    "external_action_credentials",
    "team_external_action_credential_permissions",
    "user_external_action_credential_permissions",
}


def _alembic_result(
    *args: str,
    database: str,
    config: DisposablePostgresConfig,
) -> int:
    environment = config.subprocess_environment(database=database, root_dir=ROOT_DIR)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "apps/shared/alembic.ini", *args],
        cwd=ROOT_DIR,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
        check=False,
    )
    return result.returncode


def _run_alembic(
    *args: str,
    database: str,
    config: DisposablePostgresConfig,
) -> None:
    returncode = _alembic_result(*args, database=database, config=config)
    if returncode != 0:
        pytest.fail(
            "alembic command failed; stdout/stderr omitted to avoid leaking "
            "local configuration"
        )


def _enable_vector_extension(
    database: str,
    config: DisposablePostgresConfig,
) -> None:
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
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()


def _table_names(database: str, config: DisposablePostgresConfig) -> set[str]:
    engine = create_engine(config.database_url(database))
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _insert_and_read_external_action_credential_permissions(
    database: str,
    config: DisposablePostgresConfig,
) -> None:
    engine = create_engine(config.database_url(database))
    try:
        with engine.begin() as connection:
            user_id = uuid.uuid4()
            organization_id = uuid.uuid4()
            team_id = uuid.uuid4()
            credential_id = uuid.uuid4()
            now = datetime.now(timezone.utc)
            connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, email, name, social_provider, created_at, updated_at
                    ) VALUES (
                        :id, :email, :name, :social_provider, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": user_id,
                    "email": f"external-action-migration-{user_id}@example.invalid",
                    "name": "External Action Migration",
                    "social_provider": "local",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO organization (
                        id, name, created_by, is_active, created_at, updated_at
                    ) VALUES (
                        :id, :name, :created_by, true, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": organization_id,
                    "name": f"External Action Migration {organization_id}",
                    "created_by": user_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO teams (
                        id, organization_id, name, created_by, is_active,
                        is_auto_add, created_at, updated_at
                    ) VALUES (
                        :id, :organization_id, :name, :created_by, true,
                        false, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": team_id,
                    "organization_id": organization_id,
                    "name": "External Action Operators",
                    "created_by": user_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO external_action_credentials (
                        id, organization_id, credential_name, provider,
                        encrypted_secret, encryption_key_version,
                        encryption_algorithm, revision, status, created_by,
                        created_at, updated_at
                    ) VALUES (
                        :id, :organization_id, :credential_name, :provider,
                        :encrypted_secret, :encryption_key_version,
                        :encryption_algorithm, 1, 'active', :created_by,
                        :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": credential_id,
                    "organization_id": organization_id,
                    "credential_name": "Operations Slack",
                    "provider": "slack_api",
                    "encrypted_secret": "synthetic-ciphertext",
                    "encryption_key_version": "v1",
                    "encryption_algorithm": "fernet-v1",
                    "created_by": user_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO user_external_action_credential_permissions (
                        id, grantee_organization_id, user_id,
                        external_action_credential_id, auth_state, assigned_by,
                        assigned_at
                    ) VALUES (
                        :id, :organization_id, :user_id, :credential_id,
                        'operator', :assigned_by, :assigned_at
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "credential_id": credential_id,
                    "assigned_by": user_id,
                    "assigned_at": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO team_external_action_credential_permissions (
                        id, grantee_organization_id, team_id,
                        external_action_credential_id, auth_state, assigned_by,
                        assigned_at
                    ) VALUES (
                        :id, :organization_id, :team_id, :credential_id,
                        'builder', :assigned_by, :assigned_at
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "organization_id": organization_id,
                    "team_id": team_id,
                    "credential_id": credential_id,
                    "assigned_by": user_id,
                    "assigned_at": now,
                },
            )

            assert (
                connection.execute(
                    text("SELECT id FROM external_action_credentials")
                ).scalar_one()
                == credential_id
            )
            assert (
                connection.execute(
                    text(
                        "SELECT auth_state "
                        "FROM user_external_action_credential_permissions"
                    )
                ).scalar_one()
                == "operator"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT auth_state "
                        "FROM team_external_action_credential_permissions"
                    )
                ).scalar_one()
                == "builder"
            )
    finally:
        engine.dispose()


def _delete_external_action_credential_rows(
    database: str,
    config: DisposablePostgresConfig,
) -> None:
    engine = create_engine(config.database_url(database))
    try:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM team_external_action_credential_permissions")
            )
            connection.execute(
                text("DELETE FROM user_external_action_credential_permissions")
            )
            connection.execute(text("DELETE FROM external_action_credentials"))
    finally:
        engine.dispose()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=(
        "set NODEASE_RUN_DISPOSABLE_DB_TEST=1 to run disposable PostgreSQL "
        "external action credential migration smoke"
    ),
)
def test_external_action_credential_upgrade_downgrade_and_reupgrade_in_disposable_postgres():
    assert isinstance(BASE_REVISION, str)
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

        _run_alembic(
            "upgrade",
            EXTERNAL_ACTION_CREDENTIAL_REVISION,
            database=database,
            config=config,
        )
        assert _revision(database, config) == EXTERNAL_ACTION_CREDENTIAL_REVISION
        assert TABLES <= _table_names(database, config)
        _insert_and_read_external_action_credential_permissions(database, config)

        # The downgrade must not silently delete active credential records.
        assert _alembic_result(
            "downgrade", "-1", database=database, config=config
        ) != 0
        assert _revision(database, config) == EXTERNAL_ACTION_CREDENTIAL_REVISION

        _delete_external_action_credential_rows(database, config)
        _run_alembic("downgrade", "-1", database=database, config=config)
        assert _revision(database, config) == BASE_REVISION
        assert TABLES.isdisjoint(_table_names(database, config))

        _run_alembic(
            "upgrade",
            EXTERNAL_ACTION_CREDENTIAL_REVISION,
            database=database,
            config=config,
        )
        assert _revision(database, config) == EXTERNAL_ACTION_CREDENTIAL_REVISION
        assert TABLES <= _table_names(database, config)
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
                    connection.execute(
                        text(f"DROP DATABASE IF EXISTS {quoted_database}"))
            except OperationalError:
                raise pytest.fail.Exception(
                    "disposable PostgreSQL cleanup could not connect; "
                    "connection details omitted",
                    pytrace=False,
                ) from None
        admin_engine.dispose()
