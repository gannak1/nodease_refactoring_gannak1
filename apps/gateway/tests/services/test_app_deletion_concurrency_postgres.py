"""Actual PostgreSQL concurrency contracts for App deletion."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from apps.gateway.services.app_lifecycle_lock import lock_app_for_lifecycle
from apps.gateway.services.app_service import AppService
from apps.gateway.services.deployment_service import DeploymentService
from apps.shared.db.models import (
    App,
    Organization,
    OrganizationMembership,
    Schedule,
    ScheduleDispatchClaim,
    User,
    UserWorkflowPermission,
    Workflow,
    WorkflowDeployment,
    WorkflowRun,
)
from apps.shared.db.models.organization_membership import (
    ORGANIZATION_AUTH_MEMBER,
    ORGANIZATION_MEMBERSHIP_ACTIVE,
)
from apps.shared.db.models.workflow_deployment import DeploymentType
from apps.shared.domain.deployment_runtime_policy import (
    DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
)
from apps.shared.domain.schedule_dispatch import ScheduleDispatchSettings
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)
from apps.workflow_engine.composition.schedule_dispatch import (
    build_schedule_admission_dependencies,
    build_scheduled_execution_use_case,
)


ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mbased_app_delete_concurrency"

pytestmark = pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run App deletion concurrency integration",
)


def _run_alembic(database: str, config: DisposablePostgresConfig) -> None:
    result = subprocess.run(
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
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"alembic failed with exit code {result.returncode}; "
            "stdout/stderr omitted to avoid leaking local configuration"
        )


@pytest.fixture(scope="module")
def postgres_sessions():
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
    engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {quoted_database}"))
        database_created = True
        engine = create_engine(config.database_url(database))
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        engine.dispose()
        engine = None

        _run_alembic(database, config)
        engine = create_engine(config.database_url(database), pool_size=10)
        yield sessionmaker(bind=engine, expire_on_commit=False), engine
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable or rejected the connection; "
            "connection details omitted",
            pytrace=False,
        ) from None
    finally:
        if engine is not None:
            engine.dispose()
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


def _seed_lifecycle_bundle(session_factory) -> dict[str, uuid.UUID | str]:
    db = session_factory()
    ids = {
        name: uuid.uuid4()
        for name in (
            "owner",
            "actor",
            "organization",
            "membership",
            "app",
            "workflow",
            "permission",
            "deployment",
            "schedule",
            "claim",
        )
    }
    task_id = f"schedule:{ids['claim']}"
    now = datetime.now(timezone.utc)
    try:
        db.add_all(
            [
                User(
                    id=ids["owner"],
                    email=f"owner-{ids['owner']}@example.invalid",
                    name="Concurrency owner",
                    social_provider="local",
                ),
                User(
                    id=ids["actor"],
                    email=f"actor-{ids['actor']}@example.invalid",
                    name="Concurrency actor",
                    social_provider="local",
                ),
            ]
        )
        db.flush()
        db.add(
            Organization(
                id=ids["organization"],
                name=f"Concurrency organization {ids['organization']}",
                created_by=ids["owner"],
            )
        )
        db.flush()
        db.add(
            OrganizationMembership(
                id=ids["membership"],
                organization_id=ids["organization"],
                user_id=ids["actor"],
                membership_state=ORGANIZATION_MEMBERSHIP_ACTIVE,
                organization_auth_state=ORGANIZATION_AUTH_MEMBER,
                invited_by=ids["owner"],
                accepted_at=now,
            )
        )
        db.add(
            App(
                id=ids["app"],
                organization_id=ids["organization"],
                name="Concurrency App",
                url_slug=f"concurrency-{ids['app']}",
                auth_secret="synthetic-auth-secret",
                created_by=ids["owner"],
            )
        )
        db.flush()
        db.add(
            Workflow(
                id=ids["workflow"],
                organization_id=ids["organization"],
                app_id=ids["app"],
                graph={},
                features={},
                env_variables={},
                runtime_variables={},
                created_by=ids["owner"],
            )
        )
        db.flush()
        app = db.get(App, ids["app"])
        assert app is not None
        app.workflow_id = ids["workflow"]
        db.add(
            UserWorkflowPermission(
                id=ids["permission"],
                grantee_organization_id=ids["organization"],
                user_id=ids["actor"],
                workflow_id=ids["workflow"],
                auth_state="manager",
                assigned_by=ids["owner"],
            )
        )
        db.add(
            WorkflowDeployment(
                id=ids["deployment"],
                app_id=ids["app"],
                version=1,
                type=DeploymentType.SCHEDULE,
                graph_snapshot={"nodes": [{"id": "start", "type": "startNode"}]},
                created_by=ids["owner"],
                is_active=True,
            )
        )
        db.flush()
        app.active_deployment_id = ids["deployment"]
        db.add(
            Schedule(
                id=ids["schedule"],
                deployment_id=ids["deployment"],
                node_id="schedule-node",
                cron_expression="0 9 * * *",
                timezone="UTC",
            )
        )
        db.add(
            ScheduleDispatchClaim(
                id=ids["claim"],
                schedule_id=ids["schedule"],
                organization_id=ids["organization"],
                deployment_id=ids["deployment"],
                scheduled_for=now,
                idempotency_key=task_id,
                status="enqueued",
                lease_expires_at=now + timedelta(minutes=1),
                attempt_count=1,
                celery_task_id=task_id,
                claimed_at=now,
                enqueued_at=now,
            )
        )
        db.commit()
    finally:
        db.close()
    ids["task_id"] = task_id
    return ids


def _set_connection_label(db, label: str) -> None:
    db.execute(
        text("SELECT set_config('application_name', :label, true)"),
        {"label": label},
    )


def _wait_for_database_lock(engine, label: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            waiting = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM pg_stat_activity
                    WHERE application_name = :label
                      AND wait_event_type = 'Lock'
                    """
                ),
                {"label": label},
            ).scalar_one()
        if waiting:
            return
        time.sleep(0.02)
    pytest.fail(f"worker {label} did not wait on the lifecycle database lock")


def _lock_app(session_factory, app_id):
    db = session_factory()
    locked = lock_app_for_lifecycle(db, app_id)
    assert locked is not None
    return db


def test_delete_vs_delete_has_one_winner_and_one_not_found(postgres_sessions):
    session_factory, engine = postgres_sessions
    ids = _seed_lifecycle_bundle(session_factory)
    winner_db = _lock_app(session_factory, ids["app"])
    label = f"delete-loser-{uuid.uuid4()}"

    def losing_delete():
        db = session_factory()
        try:
            _set_connection_label(db, label)
            return AppService.delete_app(db, str(ids["app"]), str(ids["actor"]))
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(losing_delete)
        _wait_for_database_lock(engine, label)
        assert AppService.delete_app(
            winner_db, str(ids["app"]), str(ids["actor"])
        ) is True
        assert future.result(timeout=5) is None
    winner_db.close()


def test_delete_vs_deployment_change_leaves_no_orphan(postgres_sessions):
    session_factory, engine = postgres_sessions
    ids = _seed_lifecycle_bundle(session_factory)
    delete_db = _lock_app(session_factory, ids["app"])
    label = f"deployment-change-{uuid.uuid4()}"

    def toggle_deployment():
        db = session_factory()
        try:
            _set_connection_label(db, label)
            return DeploymentService.toggle_deployment(
                db,
                ids["deployment"],
                runtime_policy=DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
                user_id=ids["actor"],
            )
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(toggle_deployment)
        _wait_for_database_lock(engine, label)
        assert AppService.delete_app(
            delete_db, str(ids["app"]), str(ids["actor"])
        ) is True
        with pytest.raises(HTTPException) as exc_info:
            future.result(timeout=5)
        assert exc_info.value.status_code == 404

    verify = session_factory()
    try:
        assert verify.get(WorkflowDeployment, ids["deployment"]) is None
        assert verify.get(App, ids["app"]) is None
    finally:
        verify.close()
        delete_db.close()


def test_delete_vs_run_admission_blocks_dispatch_after_delete(
    postgres_sessions,
    monkeypatch,
):
    session_factory, _engine = postgres_sessions
    ids = _seed_lifecycle_bundle(session_factory)
    delete_db = _lock_app(session_factory, ids["app"])
    dispatched = Event()

    async def capture_dispatch(**_kwargs):
        dispatched.set()
        return {"status": "dispatched"}

    monkeypatch.setattr(
        DeploymentService,
        "_execute_deployment_snapshot",
        capture_dispatch,
    )

    def admit_run():
        db = session_factory()
        try:
            try:
                return asyncio.run(
                    DeploymentService.run_authenticated_deployment(
                        db,
                        ids["deployment"],
                        {},
                        None,
                        ids["actor"],
                        DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
                    )
                )
            except HTTPException as exc:
                return exc
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(admit_run)
        dispatched_before_delete_commit = dispatched.wait(timeout=1)
        assert AppService.delete_app(
            delete_db, str(ids["app"]), str(ids["actor"])
        ) is True
        result = future.result(timeout=5)

    delete_db.close()
    assert dispatched_before_delete_commit is False
    assert isinstance(result, HTTPException)
    assert result.status_code == 404


def test_delete_vs_schedule_admission_cancels_retained_claim(postgres_sessions):
    session_factory, engine = postgres_sessions
    ids = _seed_lifecycle_bundle(session_factory)
    delete_db = _lock_app(session_factory, ids["app"])
    label = f"schedule-admission-{uuid.uuid4()}"

    def admit_schedule():
        db = session_factory()
        try:
            _set_connection_label(db, label)
            dependencies = build_schedule_admission_dependencies(db)
            use_case = build_scheduled_execution_use_case(
                settings=ScheduleDispatchSettings(mode="claim"),
                runtime_policy=DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
            )
            return use_case.admit(
                repository=dependencies.repository,
                budget=dependencies.budget,
                audit=dependencies.audit,
                uow=dependencies.uow,
                claim_id=ids["claim"],
                task_id=ids["task_id"],
                admission_owner="concurrency-test",
            )
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(admit_schedule)
        _wait_for_database_lock(engine, label)
        assert AppService.delete_app(
            delete_db, str(ids["app"]), str(ids["actor"])
        ) is True
        result = future.result(timeout=5)

    verify = session_factory()
    try:
        claim = verify.get(ScheduleDispatchClaim, ids["claim"])
        assert result.status == "rejected"
        assert result.plan is None
        assert claim is not None
        assert claim.status == "canceled"
        assert claim.workflow_run_id is None
        assert verify.query(WorkflowRun).count() == 0
    finally:
        verify.close()
        delete_db.close()


def test_permission_revoked_while_delete_waits_prevents_delete(postgres_sessions):
    session_factory, engine = postgres_sessions
    ids = _seed_lifecycle_bundle(session_factory)
    permission_db = _lock_app(session_factory, ids["app"])
    label = f"permission-recheck-{uuid.uuid4()}"

    def waiting_delete():
        db = session_factory()
        try:
            _set_connection_label(db, label)
            return AppService.delete_app(db, str(ids["app"]), str(ids["actor"]))
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(waiting_delete)
        _wait_for_database_lock(engine, label)
        permission = permission_db.get(UserWorkflowPermission, ids["permission"])
        assert permission is not None
        permission_db.delete(permission)
        permission_db.commit()
        assert future.result(timeout=5) is None

    verify = session_factory()
    try:
        assert verify.get(App, ids["app"]) is not None
        assert verify.get(Workflow, ids["workflow"]) is not None
    finally:
        verify.close()
        permission_db.close()
