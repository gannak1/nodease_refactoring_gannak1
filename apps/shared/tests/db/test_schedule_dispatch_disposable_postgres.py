"""Opt-in PostgreSQL evidence for schedule dispatch migration safety."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event

import pytest
from apps.gateway.adapters.audit.sqlalchemy_schedule_dispatch_audit import (
    SqlAlchemyScheduleDispatchAuditRecorder,
)
from apps.gateway.adapters.db.schedule_dispatch_repository import (
    SqlAlchemyScheduleDispatchRepository,
)
from apps.gateway.adapters.db.sqlalchemy_unit_of_work import SqlAlchemyUnitOfWork
from apps.gateway.adapters.schedule.apscheduler_next_fire import (
    ApschedulerNextFireCalculator,
)
from apps.gateway.application.deployment.schedule_occurrence import (
    ScheduleOccurrenceUseCase,
)
from apps.gateway.services.workflow_budget_service import (
    WorkflowBudgetDecisionAdapter,
)
from apps.shared.alembic.migration_lock import migration_advisory_lock
from apps.shared.db.models.app import App
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.schedule import Schedule
from apps.shared.db.models.schedule_dispatch import ScheduleDispatchClaim
from apps.shared.db.models.user import User
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_deployment import DeploymentType, WorkflowDeployment
from apps.shared.domain.deployment_runtime_policy import (
    DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
)
from apps.shared.domain.schedule_dispatch import ScheduleDispatchSettings
from apps.shared.services.schedule_dispatch_schema_readiness import (
    require_schedule_dispatch_migration_ready,
)
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)
from apps.workflow_engine.adapters.schedule_dispatch_repository import (
    SharedWorkflowBudgetDecisionAdapter,
    SqlAlchemyScheduleAdmissionRepository,
    SqlAlchemyScheduleAdmissionUnitOfWork,
)
from apps.workflow_engine.application.schedule_dispatch import (
    ScheduledDeploymentExecutionUseCase,
)
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mbased_schedule_claim"
HEAD_REVISION = "ff3a4b5c6d78"
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


def _seed_active_schedule(database: str, config: DisposablePostgresConfig):
    engine = create_engine(config.database_url(database))
    now = datetime.now(timezone.utc)
    ids = {
        "user": uuid.uuid4(),
        "organization": uuid.uuid4(),
        "app": uuid.uuid4(),
        "workflow": uuid.uuid4(),
        "deployment": uuid.uuid4(),
        "schedule": uuid.uuid4(),
    }
    try:
        with Session(engine) as session:
            session.add(
                User(
                    id=ids["user"],
                    email=f"schedule-{ids['user']}@example.invalid",
                    name="Schedule Test",
                    social_provider="local",
                )
            )
            session.flush()
            session.add(
                Organization(
                    id=ids["organization"],
                    name="Schedule Test Organization",
                    created_by=ids["user"],
                    is_active=True,
                )
            )
            session.flush()
            app = App(
                id=ids["app"],
                organization_id=ids["organization"],
                name="Schedule Test App",
                url_slug=f"schedule-{ids['app']}",
                auth_secret="non-secret-test-value",
                created_by=ids["user"],
            )
            session.add(app)
            session.flush()
            session.add(
                Workflow(
                    id=ids["workflow"],
                    organization_id=ids["organization"],
                    app_id=ids["app"],
                    graph={"nodes": [], "edges": []},
                    created_by=ids["user"],
                )
            )
            session.flush()
            app.workflow_id = ids["workflow"]
            session.flush()
            deployment = WorkflowDeployment(
                id=ids["deployment"],
                app_id=ids["app"],
                version=1,
                type=DeploymentType.SCHEDULE,
                graph_snapshot={"nodes": [], "edges": []},
                created_by=ids["user"],
                is_active=True,
            )
            session.add(deployment)
            session.flush()
            app.active_deployment_id = deployment.id
            session.add(
                Schedule(
                    id=ids["schedule"],
                    deployment_id=deployment.id,
                    node_id="schedule-trigger",
                    cron_expression="*/5 * * * *",
                    timezone="UTC",
                    next_run_at=now,
                )
            )
            session.commit()
    finally:
        engine.dispose()
    return ids


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


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL schedule race evidence",
)
def test_schedule_occurrence_and_worker_admission_have_single_database_winner():
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
        readiness_engine = create_engine(config.database_url(database))
        try:
            require_schedule_dispatch_migration_ready(
                readiness_engine,
                settings=ScheduleDispatchSettings(mode="claim"),
            )
        finally:
            readiness_engine.dispose()
        ids = _seed_active_schedule(database, config)

        invariant_engine = create_engine(config.database_url(database))
        try:
            with invariant_engine.connect() as connection:
                transaction = connection.begin()
                try:
                    with pytest.raises(IntegrityError):
                        connection.execute(
                            text(
                                """
                                INSERT INTO schedule_dispatch_claims (
                                    id, schedule_id, organization_id, deployment_id,
                                    scheduled_for, idempotency_key, status,
                                    attempt_count, workflow_run_id, claimed_at
                                ) VALUES (
                                    :id, :schedule_id, :organization_id, :deployment_id,
                                    :scheduled_for, :idempotency_key, 'pending',
                                    0, :workflow_run_id, :claimed_at
                                )
                                """
                            ),
                            {
                                "id": uuid.uuid4(),
                                "schedule_id": ids["schedule"],
                                "organization_id": ids["organization"],
                                "deployment_id": ids["deployment"],
                                "scheduled_for": datetime.now(timezone.utc),
                                "idempotency_key": f"schedule:{uuid.uuid4()}",
                                "workflow_run_id": uuid.uuid4(),
                                "claimed_at": datetime.now(timezone.utc),
                            },
                        )
                finally:
                    transaction.rollback()
        finally:
            invariant_engine.dispose()

        claim_barrier = Barrier(2)

        def claim_once() -> int:
            engine = create_engine(config.database_url(database))
            try:
                with Session(engine) as session:
                    claim_barrier.wait(timeout=10)
                    return ScheduleOccurrenceUseCase(
                        settings=ScheduleDispatchSettings(mode="claim"),
                        runtime_policy=DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
                        next_fire=ApschedulerNextFireCalculator(),
                    ).claim_due_occurrences(
                        repository=SqlAlchemyScheduleDispatchRepository(session),
                        budget=WorkflowBudgetDecisionAdapter(session),
                        audit=SqlAlchemyScheduleDispatchAuditRecorder(session),
                        uow=SqlAlchemyUnitOfWork(session),
                    )
            finally:
                engine.dispose()

        with ThreadPoolExecutor(max_workers=2) as executor:
            claim_results = list(executor.map(lambda _item: claim_once(), range(2)))

        assert sorted(claim_results) == [0, 1]
        engine = create_engine(config.database_url(database))
        try:
            with Session(engine) as session:
                claims = session.execute(select(ScheduleDispatchClaim)).scalars().all()
                assert len(claims) == 1
                claim = claims[0]
                now = datetime.now(timezone.utc)
                claim.status = "enqueued"
                claim.attempt_count = 1
                claim.celery_task_id = claim.idempotency_key
                claim.enqueued_at = now
                claim.lease_expires_at = now + timedelta(minutes=2)
                session.commit()
                claim_id = claim.id
                task_id = claim.idempotency_key
        finally:
            engine.dispose()

        admission_barrier = Barrier(2)

        def admit_once() -> str:
            worker_engine = create_engine(config.database_url(database))
            try:
                with Session(worker_engine) as session:
                    admission_barrier.wait(timeout=10)
                    result = ScheduledDeploymentExecutionUseCase(
                        settings=ScheduleDispatchSettings(mode="claim"),
                        runtime_policy=DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
                    ).admit(
                        repository=SqlAlchemyScheduleAdmissionRepository(session),
                        budget=SharedWorkflowBudgetDecisionAdapter(session),
                        uow=SqlAlchemyScheduleAdmissionUnitOfWork(session),
                        claim_id=claim_id,
                        task_id=task_id,
                        admission_owner=str(uuid.uuid4()),
                    )
                    return result.status
            finally:
                worker_engine.dispose()

        with ThreadPoolExecutor(max_workers=2) as executor:
            admission_results = list(
                executor.map(lambda _item: admit_once(), range(2))
            )

        assert sorted(admission_results) == ["admitted", "duplicate"]
        engine = create_engine(config.database_url(database))
        try:
            with Session(engine) as session:
                claim = session.get(ScheduleDispatchClaim, claim_id)
                assert claim.status == "running"
                assert claim.workflow_run_id is not None
                assert claim.schedule_id == ids["schedule"]
        finally:
            engine.dispose()
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


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL migration lock evidence",
)
def test_migration_advisory_lock_has_one_database_session_owner():
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
    acquired = Event()
    release = Event()

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {quoted_database}"))
        database_created = True
        engine = create_engine(config.database_url(database))

        def hold_lock() -> None:
            with engine.connect() as connection:
                with migration_advisory_lock(connection):
                    acquired.set()
                    if not release.wait(timeout=10):
                        raise RuntimeError("migration lock test release timed out")

        with ThreadPoolExecutor(max_workers=2) as executor:
            owner = executor.submit(hold_lock)
            assert acquired.wait(timeout=10)
            with engine.connect() as contender:
                with pytest.raises(RuntimeError, match="already running"):
                    with migration_advisory_lock(contender):
                        pass
            release.set()
            owner.result(timeout=10)
        engine.dispose()
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable or rejected the connection; "
            "connection details omitted",
            pytrace=False,
        ) from None
    finally:
        release.set()
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
