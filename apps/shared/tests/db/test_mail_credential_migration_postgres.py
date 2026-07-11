"""Opt-in PostgreSQL evidence for the Mail credential migration."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from apps.shared.db.models.mail_credential import MailCredential
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.team import (
    Team,
    TeamMailCredentialPermission,
    UserMailCredentialPermission,
)
from apps.shared.db.models.user import User
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mbased_mail_credential"
HEAD_REVISION = "fc1d2e3f4a5b"
BASE_REVISION = "ff5c6d7e8f90"
TABLES = {
    "mail_credentials",
    "team_mail_credential_permissions",
    "user_mail_credential_permissions",
}


def _run_alembic(
    *args: str,
    database: str,
    config: DisposablePostgresConfig,
) -> None:
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
    if result.returncode != 0:
        returncode = result.returncode
        del result
        pytest.fail(
            f"alembic command failed with exit code {returncode}; "
            "stdout/stderr omitted to avoid leaking local configuration"
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


def _insert_and_read_mail_permissions(
    database: str,
    config: DisposablePostgresConfig,
) -> None:
    engine = create_engine(config.database_url(database))
    try:
        with Session(engine) as session:
            user_id = uuid.uuid4()
            organization_id = uuid.uuid4()
            team_id = uuid.uuid4()
            credential_id = uuid.uuid4()
            session.add(
                User(
                    id=user_id,
                    email=f"mail-migration-{user_id}@example.invalid",
                    name="Mail Migration",
                    social_provider="local",
                )
            )
            session.flush()
            session.add(
                Organization(
                    id=organization_id,
                    name=f"Mail Migration {organization_id}",
                    created_by=user_id,
                    is_active=True,
                )
            )
            session.flush()
            session.add(
                Team(
                    id=team_id,
                    organization_id=organization_id,
                    name="Mail Operators",
                    created_by=user_id,
                    is_active=True,
                )
            )
            session.add(
                MailCredential(
                    id=credential_id,
                    organization_id=organization_id,
                    credential_name="Operations Mail",
                    provider="custom",
                    email_address="mailbox@example.invalid",
                    auth_type="app_password",
                    imap_host="imap.example.invalid",
                    imap_port=993,
                    use_ssl=True,
                    encrypted_secret="synthetic-ciphertext",
                    encryption_key_version="v1",
                    encryption_algorithm="fernet-v1",
                    status="active",
                    created_by=user_id,
                )
            )
            session.flush()
            session.add_all(
                [
                    UserMailCredentialPermission(
                        grantee_organization_id=organization_id,
                        user_id=user_id,
                        mail_credential_id=credential_id,
                        auth_state="operator",
                        assigned_by=user_id,
                    ),
                    TeamMailCredentialPermission(
                        grantee_organization_id=organization_id,
                        team_id=team_id,
                        mail_credential_id=credential_id,
                        auth_state="builder",
                        assigned_by=user_id,
                    ),
                ]
            )
            session.commit()

            assert session.scalar(select(MailCredential.id)) == credential_id
            assert session.scalar(select(UserMailCredentialPermission.auth_state)) == (
                "operator"
            )
            assert session.scalar(select(TeamMailCredentialPermission.auth_state)) == (
                "builder"
            )
    finally:
        engine.dispose()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL Mail migration smoke",
)
def test_mail_credential_upgrade_downgrade_and_reupgrade_in_disposable_postgres():
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

        _run_alembic("upgrade", "heads", database=database, config=config)
        assert _revision(database, config) == HEAD_REVISION
        assert TABLES <= _table_names(database, config)
        _insert_and_read_mail_permissions(database, config)

        _run_alembic("downgrade", "-1", database=database, config=config)
        assert _revision(database, config) == BASE_REVISION
        assert TABLES.isdisjoint(_table_names(database, config))

        _run_alembic("upgrade", "heads", database=database, config=config)
        assert _revision(database, config) == HEAD_REVISION
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
                        text(f"DROP DATABASE IF EXISTS {quoted_database}")
                    )
            except OperationalError:
                raise pytest.fail.Exception(
                    "disposable PostgreSQL cleanup could not connect; "
                    "connection details omitted",
                    pytrace=False,
                ) from None
        admin_engine.dispose()
