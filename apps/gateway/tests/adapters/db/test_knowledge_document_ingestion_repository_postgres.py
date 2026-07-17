"""Opt-in PostgreSQL evidence for durable Knowledge ingestion jobs."""

import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from apps.gateway.adapters.db.knowledge_document_ingestion_repository import (
    SqlAlchemyDocumentIngestionRepository,
)
from apps.gateway.adapters.db.sqlalchemy_unit_of_work import SqlAlchemyUnitOfWork
from apps.gateway.application.knowledge_document_ingestion.worker import (
    ExecuteDocumentIngestionJob,
)
from apps.shared.db.models.knowledge import (
    Document,
    KnowledgeBase,
    KnowledgeDocumentIngestionJob,
    SourceType,
)
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.user import User
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)


ROOT_DIR = Path(__file__).resolve().parents[5]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mba288_ingestion"

pytestmark = pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable Knowledge ingestion tests",
)


def _run_migrations(database: str, config: DisposablePostgresConfig) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "apps/shared/alembic.ini",
            "upgrade",
            "heads",
        ],
        cwd=ROOT_DIR,
        env=config.subprocess_environment(database=database, root_dir=ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            "disposable PostgreSQL migration failed; output omitted to avoid "
            "leaking local configuration"
        )


@pytest.fixture(scope="module")
def postgres_engine():
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
    created = False
    engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {quoted_database}"))
        created = True
        extension_engine = create_engine(
            config.database_url(database),
            isolation_level="AUTOCOMMIT",
        )
        try:
            with extension_engine.connect() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        finally:
            extension_engine.dispose()
        _run_migrations(database, config)
        engine = create_engine(config.database_url(database), pool_pre_ping=True)
        yield engine
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable or rejected the connection; "
            "connection details omitted",
            pytrace=False,
        ) from None
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            try:
                with admin_engine.connect() as connection:
                    connection.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = :database AND pid <> pg_backend_pid()"
                        ),
                        {"database": database},
                    )
                    connection.execute(text(f"DROP DATABASE IF EXISTS {quoted_database}"))
            except OperationalError:
                raise pytest.fail.Exception(
                    "disposable PostgreSQL cleanup failed; connection details omitted",
                    pytrace=False,
                ) from None
        admin_engine.dispose()


def _seed_scope(engine):
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    document_id = uuid.uuid4()
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        session.add(
            User(
                id=user_id,
                email=f"mba288-{user_id}@example.invalid",
                name="MBA-288 worker",
                social_provider="local",
            )
        )
        session.flush()
        session.add(
            Organization(
                id=organization_id,
                name="MBA-288 organization",
                created_by=user_id,
                managed_by=user_id,
                options={},
                flags=0,
            )
        )
        session.flush()
        session.add(
            KnowledgeBase(
                id=knowledge_base_id,
                organization_id=organization_id,
                user_id=user_id,
                name="MBA-288 KB",
                embedding_model="text-embedding-3-small",
                sync_state="manual",
                lifecycle_state="active",
            )
        )
        session.flush()
        session.add(
            Document(
                id=document_id,
                knowledge_base_id=knowledge_base_id,
                filename="fixture.txt",
                source_type=SourceType.FILE,
                status="indexing",
                chunk_size=500,
                chunk_overlap=50,
                meta_info={},
            )
        )
        session.commit()
    finally:
        session.close()
    return user_id, organization_id, knowledge_base_id, document_id


def _job(scope, *, status="pending", expired=False):
    user_id, organization_id, knowledge_base_id, document_id = scope
    now = datetime.now(timezone.utc)
    running = status == "running"
    return KnowledgeDocumentIngestionJob(
        id=uuid.uuid4(),
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        requested_by_user_id=user_id,
        operation_kind="process",
        generation=1,
        input_revision=uuid.uuid4().hex + uuid.uuid4().hex,
        idempotency_key=uuid.uuid4().hex + uuid.uuid4().hex,
        status=status,
        attempt_count=1 if running else 0,
        max_attempts=3,
        retryable=True,
        owner_token="owner" if running else None,
        fencing_token="fence" if running else None,
        heartbeat_at=now - timedelta(minutes=20) if running else None,
        lease_expires_at=(now - timedelta(seconds=1))
        if running and expired
        else (now + timedelta(minutes=10) if running else None),
        next_retry_at=now if status in {"pending", "retry_scheduled"} else None,
        requested_at=now,
        updated_at=now,
        safe_metadata={},
    )


def test_postgres_enforces_one_active_job_per_document(postgres_engine) -> None:
    scope = _seed_scope(postgres_engine)
    session_factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    first = session_factory()
    second = session_factory()
    try:
        first.add(_job(scope))
        first.commit()
        second.add(_job(scope, status="retry_scheduled"))
        with pytest.raises(IntegrityError):
            second.commit()
        second.rollback()
    finally:
        first.close()
        second.close()


def test_postgres_concurrent_claim_enters_runner_once(postgres_engine) -> None:
    scope = _seed_scope(postgres_engine)
    session_factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    seed = session_factory()
    job = _job(scope)
    seed.add(job)
    seed.commit()
    job_id = job.id
    seed.close()

    runner_started = threading.Event()
    release_runner = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    class Authorization:
        def is_allowed(self, _job_value):
            return True

    class Runner:
        def run(self, _job_value):
            nonlocal calls
            with calls_lock:
                calls += 1
            runner_started.set()
            assert release_runner.wait(timeout=5)
            return None

    runner = Runner()

    def execute():
        db = session_factory()
        try:
            return ExecuteDocumentIngestionJob(
                repository=SqlAlchemyDocumentIngestionRepository(db),
                authorization=Authorization(),
                runner=runner,
                unit_of_work=SqlAlchemyUnitOfWork(db),
            ).execute(job_id, owner_token=str(uuid.uuid4()))
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(execute)
        assert runner_started.wait(timeout=5)
        second = executor.submit(execute)
        second_result = second.result(timeout=5)
        release_runner.set()
        first_result = first.result(timeout=5)

    assert {first_result.status, second_result.status} == {"succeeded", "duplicate"}
    assert calls == 1


def test_postgres_heartbeat_requires_current_owner_and_fence(postgres_engine) -> None:
    scope = _seed_scope(postgres_engine)
    session_factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    seed = session_factory()
    job = _job(scope, status="running")
    seed.add(job)
    seed.commit()
    job_id = job.id
    seed.close()

    db = session_factory()
    try:
        repository = SqlAlchemyDocumentIngestionRepository(db)
        now = repository.database_now()
        assert repository.heartbeat(
            job_id,
            owner_token="wrong",
            fencing_token="fence",
            now=now,
            lease_expires_at=now + timedelta(minutes=15),
        ) is False
        db.rollback()
        assert repository.heartbeat(
            job_id,
            owner_token="owner",
            fencing_token="fence",
            now=now,
            lease_expires_at=now + timedelta(minutes=15),
        ) is True
        db.commit()
    finally:
        db.close()


def test_postgres_recovery_requeues_expired_lease(postgres_engine) -> None:
    scope = _seed_scope(postgres_engine)
    session_factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    seed = session_factory()
    job = _job(scope, status="running", expired=True)
    seed.add(job)
    seed.commit()
    job_id = job.id
    seed.close()

    db = session_factory()
    try:
        repository = SqlAlchemyDocumentIngestionRepository(db)
        recovered = repository.recover_due(now=repository.database_now(), limit=10)
        db.commit()
        row = db.get(KnowledgeDocumentIngestionJob, job_id)
        assert job_id in [recovery.job_id for recovery in recovered]
        assert row is not None
        assert row.status == "retry_scheduled"
        assert row.owner_token is None
        assert row.fencing_token is None
        assert row.dispatch_lease_expires_at is not None

        immediate = repository.recover_due(
            now=repository.database_now(),
            limit=10,
        )
        assert immediate == []
    finally:
        db.close()


def test_postgres_expired_lease_cannot_heartbeat_or_finalize(
    postgres_engine,
) -> None:
    scope = _seed_scope(postgres_engine)
    session_factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    seed = session_factory()
    job = _job(scope, status="running", expired=True)
    seed.add(job)
    seed.commit()
    job_id = job.id
    seed.close()

    db = session_factory()
    try:
        repository = SqlAlchemyDocumentIngestionRepository(db)
        now = repository.database_now()
        assert repository.heartbeat(
            job_id,
            owner_token="owner",
            fencing_token="fence",
            now=now,
            lease_expires_at=now + timedelta(minutes=15),
        ) is False
        db.rollback()
        assert repository.mark_succeeded(
            job_id,
            owner_token="owner",
            fencing_token="fence",
            result_document_version_id=None,
            now=repository.database_now(),
        ) is False
        db.rollback()
        assert repository.lock_owned_worker_job(
            job_id,
            owner_token="owner",
            fencing_token="fence",
        ) is None
        db.rollback()
    finally:
        db.close()


def test_postgres_recovery_uses_document_before_job_lock_order(
    postgres_engine,
) -> None:
    scope = _seed_scope(postgres_engine)
    _, _, knowledge_base_id, document_id = scope
    session_factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    seed = session_factory()
    job = _job(scope, status="running", expired=True)
    seed.add(job)
    seed.commit()
    job_id = job.id
    seed.close()

    document_locked = threading.Event()
    release_finalizer = threading.Event()

    def finalize_expired_owner() -> bool:
        db = session_factory()
        try:
            db.query(KnowledgeBase).filter(
                KnowledgeBase.id == knowledge_base_id
            ).with_for_update().one()
            db.query(Document).filter(Document.id == document_id).with_for_update().one()
            document_locked.set()
            assert release_finalizer.wait(timeout=5)
            repository = SqlAlchemyDocumentIngestionRepository(db)
            result = repository.mark_succeeded(
                job_id,
                owner_token="owner",
                fencing_token="fence",
                result_document_version_id=None,
                now=repository.database_now(),
            )
            db.commit()
            return result
        finally:
            db.close()

    def recover_expired_owner():
        assert document_locked.wait(timeout=5)
        db = session_factory()
        try:
            repository = SqlAlchemyDocumentIngestionRepository(db)
            recovered = repository.recover_due(
                now=repository.database_now(),
                limit=10,
            )
            db.commit()
            return recovered
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        finalizer = executor.submit(finalize_expired_owner)
        assert document_locked.wait(timeout=5)
        recovery = executor.submit(recover_expired_owner)
        threading.Event().wait(0.2)
        release_finalizer.set()
        assert finalizer.result(timeout=5) is False
        recovered = recovery.result(timeout=5)

    assert job_id in [item.job_id for item in recovered]
