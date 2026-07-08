import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_NAME_RE = re.compile(r"^mbased_disposable_[a-f0-9]{12}$")


def _db_url(database: str) -> URL:
    port = os.getenv("DB_PORT", "5432")
    return URL.create(
        "postgresql",
        username=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASSWORD", "admin123"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(port) if port.isdigit() else None,
        database=database,
    )


def _quote_disposable_db_name(database: str) -> str:
    if not DB_NAME_RE.fullmatch(database):
        raise ValueError("unsafe disposable database name")
    return f'"{database}"'


def _run_seed_command(args: list[str], *, database: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "DB_NAME": database,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(ROOT_DIR),
            "NODEASE_DEMO_REGENERATE_KNOWLEDGE_FIXTURE": "0",
        }
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


def _enable_vector_extension(database: str) -> None:
    engine = create_engine(_db_url(database), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    finally:
        engine.dispose()


def _snapshot_counts(database: str) -> dict[str, int]:
    engine = create_engine(_db_url(database))
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
    database = f"mbased_disposable_{uuid.uuid4().hex[:12]}"
    quoted_database = _quote_disposable_db_name(database)
    maintenance_database = os.getenv("NODEASE_DISPOSABLE_DB_MAINTENANCE_DB", "postgres")
    admin_engine = create_engine(
        _db_url(maintenance_database),
        isolation_level="AUTOCOMMIT",
    )

    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {quoted_database}"))

        _enable_vector_extension(database)
        _run_seed_command(
            ["-m", "alembic", "-c", "apps/shared/alembic.ini", "upgrade", "heads"],
            database=database,
        )
        _run_seed_command(
            ["scripts/seed_demo.py", "--profile", "demo", "--reset"],
            database=database,
        )
        reset_counts = _snapshot_counts(database)

        _run_seed_command(["scripts/seed_demo.py", "--profile", "demo"], database=database)
        seeded_counts = _snapshot_counts(database)

        _run_seed_command(
            ["scripts/seed_demo.py", "--profile", "demo", "--reset"],
            database=database,
        )
        second_reset_counts = _snapshot_counts(database)

        assert reset_counts["knowledge_bases"] > 0
        assert reset_counts["documents"] > 0
        assert reset_counts["document_chunks"] > 0
        assert reset_counts == seeded_counts == second_reset_counts
        assert reset_counts["document_chunk_document_orphans"] == 0
        assert reset_counts["document_chunk_kb_orphans"] == 0
        assert reset_counts["document_kb_orphans"] == 0
    finally:
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
        admin_engine.dispose()
