"""Opt-in PostgreSQL compatibility test for the App deletion migration."""

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
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError


ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mbased_app_deletion"
BASE_REVISION = "c1e5f4a3c2d4"
HEAD_REVISION = "d5e6f7a8b9c0"


def _run_alembic(
    *args: str,
    database: str,
    config: DisposablePostgresConfig,
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


def _seed_legacy_records(engine) -> dict[str, uuid.UUID]:
    ids = {
        name: uuid.uuid4()
        for name in (
            "user",
            "organization",
            "app",
            "workflow",
            "run",
            "provider",
            "model",
            "credential",
            "usage",
        )
    }
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (
                    id, email, name, social_provider, created_at, updated_at
                ) VALUES (
                    :id, :email, 'Migration User', 'local', :now, :now
                )
                """
            ),
            {
                "id": ids["user"],
                "email": f"app-deletion-{ids['user']}@example.invalid",
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO organization (
                    id, name, options, flags, created_by, is_active,
                    created_at, updated_at
                ) VALUES (
                    :id, 'Migration Organization', '{}'::jsonb, 0, :user_id,
                    true, :now, :now
                )
                """
            ),
            {"id": ids["organization"], "user_id": ids["user"], "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO apps (
                    id, organization_id, name, url_slug, auth_secret,
                    is_api_enabled, api_req_per_minute, api_req_per_hour,
                    is_market, created_by, created_at, updated_at
                ) VALUES (
                    :id, :organization_id, 'Migration App', :url_slug,
                    'synthetic-auth-secret', true, 60, 3600, false,
                    :user_id, :now, :now
                )
                """
            ),
            {
                "id": ids["app"],
                "organization_id": ids["organization"],
                "url_slug": f"migration-{ids['app']}",
                "user_id": ids["user"],
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO workflows (
                    id, organization_id, app_id, graph, features,
                    env_variables, runtime_variables, created_by,
                    created_at, updated_at
                ) VALUES (
                    :id, :organization_id, :app_id, '{}'::jsonb, '{}'::jsonb,
                    '{}'::jsonb, '{}'::jsonb, :user_id, :now, :now
                )
                """
            ),
            {
                "id": ids["workflow"],
                "organization_id": ids["organization"],
                "app_id": ids["app"],
                "user_id": ids["user"],
                "now": now,
            },
        )
        connection.execute(
            text("UPDATE apps SET workflow_id = :workflow_id WHERE id = :app_id"),
            {"workflow_id": ids["workflow"], "app_id": ids["app"]},
        )
        connection.execute(
            text(
                """
                INSERT INTO workflow_runs (
                    id, workflow_id, user_id, app_id, status, trigger_mode,
                    inputs, started_at, redaction_applied, pii_detected,
                    payload_storage_mode, total_tokens, total_cost
                ) VALUES (
                    :id, :workflow_id, :user_id, :app_id, 'RUNNING', 'MANUAL',
                    '{}'::jsonb, :now, false, false, 'redacted_only', 0, 0
                )
                """
            ),
            {
                "id": ids["run"],
                "workflow_id": ids["workflow"],
                "user_id": ids["user"],
                "app_id": ids["app"],
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO llm_providers (
                    id, name, type, auth_type, doc_url, created_at, updated_at
                ) VALUES (
                    :id, 'migration-provider', 'custom', 'api_key',
                    'https://example.invalid', :now, :now
                )
                """
            ),
            {"id": ids["provider"], "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO llm_models (
                    id, provider_id, model_id_for_api_call, name, type,
                    context_window, is_active, created_at, updated_at
                ) VALUES (
                    :id, :provider_id, 'migration-model', 'Migration Model',
                    'chat', 1024, true, :now, :now
                )
                """
            ),
            {"id": ids["model"], "provider_id": ids["provider"], "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO llm_credentials (
                    id, provider_id, user_id, organization_id, credential_name,
                    encrypted_config, is_valid, quota_type, quota_limit,
                    quota_used, created_at, updated_at
                ) VALUES (
                    :id, :provider_id, :user_id, :organization_id,
                    'Migration Credential', 'synthetic-ciphertext', true,
                    'none', -1, 0, :now, :now
                )
                """
            ),
            {
                "id": ids["credential"],
                "provider_id": ids["provider"],
                "user_id": ids["user"],
                "organization_id": ids["organization"],
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO llm_usage_logs (
                    id, user_id, organization_id, credential_id, model_id,
                    workflow_id, workflow_run_id, prompt_tokens,
                    completion_tokens, total_cost, latency_ms, status, created_at
                ) VALUES (
                    :id, :user_id, :organization_id, :credential_id, :model_id,
                    :workflow_id, :run_id, 1, 1, 0.001, 10, 'success', :now
                )
                """
            ),
            {
                "id": ids["usage"],
                "user_id": ids["user"],
                "organization_id": ids["organization"],
                "credential_id": ids["credential"],
                "model_id": ids["model"],
                "workflow_id": ids["workflow"],
                "run_id": ids["run"],
                "now": now,
            },
        )
    return ids


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL migration integration",
)
def test_app_deletion_migration_preserves_existing_run_and_usage_records() -> None:
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
    test_engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {quoted_database}"))
        database_created = True
        _enable_vector_extension(database, config)
        _run_alembic(
            "upgrade",
            BASE_REVISION,
            database=database,
            config=config,
        )

        test_engine = create_engine(config.database_url(database))
        ids = _seed_legacy_records(test_engine)
        assert "organization_id" not in {
            column["name"] for column in inspect(test_engine).get_columns("workflow_runs")
        }

        _run_alembic("upgrade", "heads", database=database, config=config)
        assert _revision(test_engine) == HEAD_REVISION
        with test_engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT organization_id FROM workflow_runs WHERE id = :run_id"
                ),
                {"run_id": ids["run"]},
            ).scalar_one() == ids["organization"]

        _run_alembic(
            "downgrade",
            BASE_REVISION,
            database=database,
            config=config,
        )
        assert _revision(test_engine) == BASE_REVISION
        assert "organization_id" not in {
            column["name"] for column in inspect(test_engine).get_columns("workflow_runs")
        }

        _run_alembic("upgrade", "heads", database=database, config=config)
        with test_engine.begin() as connection:
            connection.execute(
                text("UPDATE apps SET workflow_id = NULL WHERE id = :app_id"),
                {"app_id": ids["app"]},
            )
            connection.execute(
                text("DELETE FROM workflows WHERE id = :workflow_id"),
                {"workflow_id": ids["workflow"]},
            )
            retained_run = connection.execute(
                text(
                    """
                    SELECT organization_id, workflow_id
                    FROM workflow_runs
                    WHERE id = :run_id
                    """
                ),
                {"run_id": ids["run"]},
            ).one()
            retained_usage = connection.execute(
                text(
                    """
                    SELECT organization_id, workflow_id
                    FROM llm_usage_logs
                    WHERE id = :usage_id
                    """
                ),
                {"usage_id": ids["usage"]},
            ).one()

        assert retained_run == (ids["organization"], None)
        assert retained_usage == (ids["organization"], None)
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable or rejected the connection; "
            "connection details omitted",
            pytrace=False,
        ) from None
    finally:
        if test_engine is not None:
            test_engine.dispose()
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
