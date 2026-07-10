import os
import subprocess
import sys
import uuid
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
DB_PREFIX = "mbased_disposable"


def _run_seed_command(
    args: list[str],
    *,
    database: str,
    config: DisposablePostgresConfig,
) -> None:
    env = config.subprocess_environment(
        database=database,
        root_dir=ROOT_DIR,
        extra={
            "NODEASE_DEMO_REGENERATE_KNOWLEDGE_FIXTURE": "0",
        },
    )
    result = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT_DIR,
        env=env,
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
            f"command failed with exit code {returncode}; "
            "stdout/stderr omitted to avoid leaking local configuration"
        )


def _enable_vector_extension(
    database: str,
    config: DisposablePostgresConfig,
) -> None:
    engine = create_engine(
        config.database_url(database),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    finally:
        engine.dispose()


def _snapshot_counts(
    database: str,
    config: DisposablePostgresConfig,
) -> dict[str, int]:
    engine = create_engine(config.database_url(database))
    try:
        with engine.connect() as conn:
            return {
                "knowledge_bases": conn.execute(
                    text("SELECT COUNT(*) FROM knowledge_bases")
                ).scalar_one(),
                "documents": conn.execute(
                    text("SELECT COUNT(*) FROM documents")
                ).scalar_one(),
                "document_chunks": conn.execute(
                    text("SELECT COUNT(*) FROM document_chunks")
                ).scalar_one(),
                "document_chunk_document_orphans": conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM document_chunks c
                        LEFT JOIN documents d ON d.id = c.document_id
                        WHERE d.id IS NULL
                        """
                    )
                ).scalar_one(),
                "document_chunk_kb_orphans": conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM document_chunks c
                        LEFT JOIN knowledge_bases kb ON kb.id = c.knowledge_base_id
                        WHERE kb.id IS NULL
                        """
                    )
                ).scalar_one(),
                "document_kb_orphans": conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM documents d
                        LEFT JOIN knowledge_bases kb ON kb.id = d.knowledge_base_id
                        WHERE kb.id IS NULL
                        """
                    )
                ).scalar_one(),
            }
    finally:
        engine.dispose()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL seed smoke",
)
def test_demo_seed_is_idempotent_in_disposable_postgres_database():
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
        with admin_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {quoted_database}"))
        database_created = True

        _enable_vector_extension(database, config)
        _run_seed_command(
            ["-m", "alembic", "-c", "apps/shared/alembic.ini", "upgrade", "heads"],
            database=database,
            config=config,
        )
        _run_seed_command(
            ["scripts/seed_demo.py", "--profile", "demo", "--reset"],
            database=database,
            config=config,
        )
        reset_counts = _snapshot_counts(database, config)

        _run_seed_command(
            ["scripts/seed_demo.py", "--profile", "demo"],
            database=database,
            config=config,
        )
        seeded_counts = _snapshot_counts(database, config)

        _run_seed_command(
            ["scripts/seed_demo.py", "--profile", "demo", "--reset"],
            database=database,
            config=config,
        )
        second_reset_counts = _snapshot_counts(database, config)

        assert reset_counts["knowledge_bases"] > 0
        assert reset_counts["documents"] > 0
        assert reset_counts["document_chunks"] > 0
        assert reset_counts == seeded_counts == second_reset_counts
        assert reset_counts["document_chunk_document_orphans"] == 0
        assert reset_counts["document_chunk_kb_orphans"] == 0
        assert reset_counts["document_kb_orphans"] == 0
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable or rejected the connection; "
            "connection details omitted",
            pytrace=False,
        ) from None
    finally:
        if database_created:
            try:
                with admin_engine.connect() as conn:
                    conn.execute(
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
                    conn.execute(text(f"DROP DATABASE IF EXISTS {quoted_database}"))
            except OperationalError:
                raise pytest.fail.Exception(
                    "disposable PostgreSQL cleanup could not connect; "
                    "connection details omitted",
                    pytrace=False,
                ) from None
        admin_engine.dispose()
