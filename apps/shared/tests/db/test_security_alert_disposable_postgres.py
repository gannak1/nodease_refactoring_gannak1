"""Opt-in PostgreSQL integration tests for Security Alert persistence."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from apps.shared.db.models.audit_log import AuditLog
from apps.shared.db.models.security_alert import SecurityAlert
from apps.shared.services.security_alert_lifecycle import (
    SecurityAlertStaleStateError,
    acknowledge_security_alert,
    reopen_security_alert,
    resolve_security_alert,
)
from apps.shared.services.security_alert_evidence import link_security_alert_evidence

from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)

ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_SECURITY_ALERT_DB_TEST"
DB_PREFIX = "mbased_security_alert"


def _run_alembic(database: str, config: DisposablePostgresConfig) -> None:
    _run_alembic_command(database, config, "upgrade", "heads")


def _run_alembic_command(
    database: str,
    config: DisposablePostgresConfig,
    *args: str,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "apps/shared/alembic.ini",
            *args,
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
        pytest.fail("Security Alert migration command failed; output omitted")


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


def _assert_integrity_error(engine, statement: str, parameters: dict) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with pytest.raises(IntegrityError):
                connection.execute(text(statement), parameters)
        finally:
            transaction.rollback()


@contextmanager
def _disposable_database():
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
        _run_alembic(database, config)
        yield database, config
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable; connection details omitted",
            pytrace=False,
        ) from None
    finally:
        if database_created:
            with admin_engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database AND pid <> pg_backend_pid()"
                    ),
                    {"database": database},
                )
                connection.execute(text(f"DROP DATABASE IF EXISTS {quoted_database}"))
        admin_engine.dispose()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL integration tests",
)
def test_security_alert_migration_creates_real_postgres_schema():
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
        _run_alembic(database, config)

        engine = create_engine(config.database_url(database))
        try:
            schema = inspect(engine)
            assert {"security_alerts", "security_alert_audit_events"} <= set(
                schema.get_table_names()
            )

            evidence_foreign_keys = {
                tuple(foreign_key["constrained_columns"]): foreign_key
                for foreign_key in schema.get_foreign_keys(
                    "security_alert_audit_events"
                )
            }
            assert evidence_foreign_keys[("security_alert_id",)][
                "referred_table"
            ] == "security_alerts"
            assert evidence_foreign_keys[("security_alert_id",)]["options"].get(
                "ondelete"
            ) == "CASCADE"
            assert evidence_foreign_keys[("audit_log_id",)]["referred_table"] == (
                "audit_logs"
            )
            assert evidence_foreign_keys[("audit_log_id",)]["options"].get(
                "ondelete"
            ) == "CASCADE"

            alert_checks = {
                check["name"] for check in schema.get_check_constraints("security_alerts")
            }
            assert "ck_security_alerts_status_fields" in alert_checks
            assert "ck_security_alerts_timestamp_order" in alert_checks

            active_index = next(
                index
                for index in schema.get_indexes("security_alerts")
                if index["name"] == "uq_security_alerts_active_detection_key"
            )
            assert active_index["unique"] is True
        finally:
            engine.dispose()
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable; connection details omitted",
            pytrace=False,
        ) from None
    finally:
        if database_created:
            with admin_engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database AND pid <> pg_backend_pid()"
                    ),
                    {"database": database},
                )
                connection.execute(text(f"DROP DATABASE IF EXISTS {quoted_database}"))
        admin_engine.dispose()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL integration tests",
)
def test_security_alert_downgrade_removes_only_feature_schema_and_keeps_data():
    with _disposable_database() as (database, config):
        engine = create_engine(config.database_url(database))
        user_id = uuid.uuid4()
        organization_id = uuid.uuid4()
        audit_log_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        try:
            with engine.begin() as connection:
                tables_before = set(inspect(connection).get_table_names())
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, email, name, social_provider, created_at, updated_at) "
                        "VALUES (:id, :email, 'Manager', 'local', :now, :now)"
                    ),
                    {
                        "id": user_id,
                        "email": f"security-alert-downgrade-{user_id}@example.invalid",
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO organization "
                        "(id, name, options, flags, created_by, is_active, "
                        "created_at, updated_at) VALUES "
                        "(:id, 'Security Alert Downgrade', '{}'::jsonb, 0, "
                        ":created_by, true, :now, :now)"
                    ),
                    {
                        "id": organization_id,
                        "created_by": user_id,
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO audit_logs "
                        "(id, occurred_at, actor_id, actor_type, category, action, "
                        "status, audit_metadata) VALUES "
                        "(:id, :occurred_at, :actor_id, 'user', 'action', "
                        "'permission.denied', 'failure', "
                        "jsonb_build_object('organization_id', :organization_id))"
                    ),
                    {
                        "id": audit_log_id,
                        "occurred_at": now,
                        "actor_id": user_id,
                        "organization_id": str(organization_id),
                    },
                )

            _run_alembic_command(database, config, "downgrade", "-1")

            with engine.connect() as connection:
                tables_after = set(inspect(connection).get_table_names())
                user_count = connection.execute(
                    text("SELECT count(*) FROM users WHERE id = :id"),
                    {"id": user_id},
                ).scalar_one()
                organization_count = connection.execute(
                    text("SELECT count(*) FROM organization WHERE id = :id"),
                    {"id": organization_id},
                ).scalar_one()
                audit_count = connection.execute(
                    text("SELECT count(*) FROM audit_logs WHERE id = :id"),
                    {"id": audit_log_id},
                ).scalar_one()

            assert tables_after == tables_before - {
                "security_alerts",
                "security_alert_audit_events",
            }
            assert user_count == 1
            assert organization_count == 1
            assert audit_count == 1
        finally:
            engine.dispose()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL integration tests",
)
def test_concurrent_acknowledge_has_one_database_winner_and_one_audit():
    with _disposable_database() as (database, config):
        engine = create_engine(config.database_url(database))
        user_ids = (uuid.uuid4(), uuid.uuid4())
        organization_id = uuid.uuid4()
        alert_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        try:
            with engine.begin() as connection:
                for index, user_id in enumerate(user_ids):
                    connection.execute(
                        text(
                            "INSERT INTO users "
                            "(id, email, name, social_provider, created_at, updated_at) "
                            "VALUES (:id, :email, :name, 'local', :now, :now)"
                        ),
                        {
                            "id": user_id,
                            "email": f"security-alert-{index}-{user_id}@example.invalid",
                            "name": f"Manager {index}",
                            "now": now,
                        },
                    )
                connection.execute(
                    text(
                        "INSERT INTO organization "
                        "(id, name, options, flags, created_by, is_active, "
                        "created_at, updated_at) "
                        "VALUES (:id, 'Security Alert Test', '{}'::jsonb, 0, "
                        ":created_by, true, :now, :now)"
                    ),
                    {
                        "id": organization_id,
                        "created_by": user_ids[0],
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO security_alerts "
                        "(id, organization_id, subject_actor_id, rule_id, "
                        "rule_version, severity, status, detection_key, "
                        "occurrence_count, first_detected_at, last_detected_at, "
                        "lifecycle_version) VALUES "
                        "(:id, :organization_id, :subject_actor_id, "
                        "'repeated_permission_denied', 'v1', 'medium', 'open', "
                        ":detection_key, 1, :now, :now, 1)"
                    ),
                    {
                        "id": alert_id,
                        "organization_id": organization_id,
                        "subject_actor_id": uuid.uuid4(),
                        "detection_key": f"test:{alert_id}",
                        "now": now,
                    },
                )

            ready = Barrier(2)

            def acknowledge(manager_id):
                with Session(engine) as session:
                    alert = session.get(SecurityAlert, alert_id)
                    ready.wait(timeout=5)
                    try:
                        acknowledge_security_alert(
                            session,
                            alert=alert,
                            manager_id=manager_id,
                            acknowledged_at=now,
                            expected_version=1,
                        )
                        session.commit()
                        return "success"
                    except SecurityAlertStaleStateError:
                        session.rollback()
                        return "stale"

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(acknowledge, user_ids))

            with engine.connect() as connection:
                stored = connection.execute(
                    text(
                        "SELECT status, lifecycle_version FROM security_alerts "
                        "WHERE id = :alert_id"
                    ),
                    {"alert_id": alert_id},
                ).one()
                audit_count = connection.execute(
                    text(
                        "SELECT count(*) FROM audit_logs "
                        "WHERE action = 'security_alert.acknowledged' "
                        "AND target_id = :target_id"
                    ),
                    {"target_id": str(alert_id)},
                ).scalar_one()

            assert sorted(results) == ["stale", "success"]
            assert stored.status == "acknowledged"
            assert stored.lifecycle_version == 2
            assert audit_count == 1
        finally:
            engine.dispose()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL integration tests",
)
def test_occurrence_and_acknowledge_race_preserves_both_database_updates():
    with _disposable_database() as (database, config):
        engine = create_engine(config.database_url(database))
        manager_id = uuid.uuid4()
        organization_id = uuid.uuid4()
        alert_id = uuid.uuid4()
        audit_log_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        detected_at = now + timedelta(seconds=1)

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, email, name, social_provider, created_at, updated_at) "
                        "VALUES (:id, :email, 'Manager', 'local', :now, :now)"
                    ),
                    {
                        "id": manager_id,
                        "email": f"security-alert-race-{manager_id}@example.invalid",
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO organization "
                        "(id, name, options, flags, created_by, is_active, "
                        "created_at, updated_at) VALUES "
                        "(:id, 'Security Alert Race', '{}'::jsonb, 0, "
                        ":created_by, true, :now, :now)"
                    ),
                    {
                        "id": organization_id,
                        "created_by": manager_id,
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO security_alerts "
                        "(id, organization_id, subject_actor_id, rule_id, "
                        "rule_version, severity, status, detection_key, "
                        "occurrence_count, first_detected_at, last_detected_at, "
                        "lifecycle_version) VALUES "
                        "(:id, :organization_id, :subject_actor_id, "
                        "'repeated_permission_denied', 'v1', 'medium', 'open', "
                        ":detection_key, 4, :now, :now, 1)"
                    ),
                    {
                        "id": alert_id,
                        "organization_id": organization_id,
                        "subject_actor_id": uuid.uuid4(),
                        "detection_key": f"race:{alert_id}",
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO audit_logs "
                        "(id, occurred_at, actor_id, actor_type, category, action, "
                        "status, audit_metadata) VALUES "
                        "(:id, :occurred_at, :actor_id, 'user', 'action', "
                        "'permission.denied', 'failure', "
                        "jsonb_build_object('organization_id', :organization_id))"
                    ),
                    {
                        "id": audit_log_id,
                        "occurred_at": detected_at,
                        "actor_id": manager_id,
                        "organization_id": str(organization_id),
                    },
                )

            ready = Barrier(2)

            def link_occurrence():
                with Session(engine) as session:
                    alert = session.get(SecurityAlert, alert_id)
                    ready.wait(timeout=5)
                    linked = link_security_alert_evidence(
                        session,
                        alert=alert,
                        audit_log_id=audit_log_id,
                        detected_at=detected_at,
                    )
                    session.commit()
                    return linked

            def acknowledge():
                with Session(engine) as session:
                    alert = session.get(SecurityAlert, alert_id)
                    ready.wait(timeout=5)
                    acknowledge_security_alert(
                        session,
                        alert=alert,
                        manager_id=manager_id,
                        acknowledged_at=detected_at,
                        expected_version=1,
                    )
                    session.commit()
                    return True

            with ThreadPoolExecutor(max_workers=2) as executor:
                occurrence_future = executor.submit(link_occurrence)
                acknowledge_future = executor.submit(acknowledge)
                assert occurrence_future.result(timeout=10) is True
                assert acknowledge_future.result(timeout=10) is True

            with engine.connect() as connection:
                stored = connection.execute(
                    text(
                        "SELECT status, lifecycle_version, occurrence_count, "
                        "last_detected_at FROM security_alerts WHERE id = :alert_id"
                    ),
                    {"alert_id": alert_id},
                ).one()
                evidence_count = connection.execute(
                    text(
                        "SELECT count(*) FROM security_alert_audit_events "
                        "WHERE security_alert_id = :alert_id "
                        "AND audit_log_id = :audit_log_id"
                    ),
                    {"alert_id": alert_id, "audit_log_id": audit_log_id},
                ).scalar_one()
                lifecycle_audit_count = connection.execute(
                    text(
                        "SELECT count(*) FROM audit_logs "
                        "WHERE action = 'security_alert.acknowledged' "
                        "AND target_id = :target_id"
                    ),
                    {"target_id": str(alert_id)},
                ).scalar_one()

            assert stored.status == "acknowledged"
            assert stored.lifecycle_version == 2
            assert stored.occurrence_count == 5
            assert stored.last_detected_at == detected_at
            assert evidence_count == 1
            assert lifecycle_audit_count == 1
        finally:
            engine.dispose()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL integration tests",
)
def test_evidence_is_idempotent_under_race_and_rejects_cross_organization():
    with _disposable_database() as (database, config):
        engine = create_engine(config.database_url(database))
        user_id = uuid.uuid4()
        organization_ids = (uuid.uuid4(), uuid.uuid4())
        alert_id = uuid.uuid4()
        audit_ids = (uuid.uuid4(), uuid.uuid4())
        now = datetime.now(timezone.utc)

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, email, name, social_provider, created_at, updated_at) "
                        "VALUES (:id, :email, 'Manager', 'local', :now, :now)"
                    ),
                    {
                        "id": user_id,
                        "email": f"security-alert-evidence-{user_id}@example.invalid",
                        "now": now,
                    },
                )
                for index, organization_id in enumerate(organization_ids):
                    connection.execute(
                        text(
                            "INSERT INTO organization "
                            "(id, name, options, flags, created_by, is_active, "
                            "created_at, updated_at) VALUES "
                            "(:id, :name, '{}'::jsonb, 0, :created_by, true, "
                            ":now, :now)"
                        ),
                        {
                            "id": organization_id,
                            "name": f"Evidence Organization {index}",
                            "created_by": user_id,
                            "now": now,
                        },
                    )
                connection.execute(
                    text(
                        "INSERT INTO security_alerts "
                        "(id, organization_id, subject_actor_id, rule_id, "
                        "rule_version, severity, status, detection_key, "
                        "occurrence_count, first_detected_at, last_detected_at, "
                        "lifecycle_version) VALUES "
                        "(:id, :organization_id, :subject_actor_id, "
                        "'repeated_permission_denied', 'v1', 'medium', 'open', "
                        ":detection_key, 0, :now, :now, 1)"
                    ),
                    {
                        "id": alert_id,
                        "organization_id": organization_ids[0],
                        "subject_actor_id": uuid.uuid4(),
                        "detection_key": f"evidence:{alert_id}",
                        "now": now,
                    },
                )
                for audit_id, organization_id in zip(audit_ids, organization_ids):
                    connection.execute(
                        text(
                            "INSERT INTO audit_logs "
                            "(id, occurred_at, actor_id, actor_type, category, "
                            "action, status, audit_metadata) VALUES "
                            "(:id, :occurred_at, :actor_id, 'user', 'action', "
                            "'permission.denied', 'failure', "
                            "jsonb_build_object('organization_id', "
                            ":organization_id))"
                        ),
                        {
                            "id": audit_id,
                            "occurred_at": now,
                            "actor_id": user_id,
                            "organization_id": str(organization_id),
                        },
                    )

            ready = Barrier(2)

            def link_same_audit():
                with Session(engine) as session:
                    alert = session.get(SecurityAlert, alert_id)
                    ready.wait(timeout=5)
                    linked = link_security_alert_evidence(
                        session,
                        alert=alert,
                        audit_log_id=audit_ids[0],
                        detected_at=now,
                    )
                    session.commit()
                    return linked

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: link_same_audit(), range(2)))

            with Session(engine) as session:
                alert = session.get(SecurityAlert, alert_id)
                cross_organization_audit = session.get(AuditLog, audit_ids[1])
                cross_organization_linked = link_security_alert_evidence(
                    session,
                    alert=alert,
                    audit_log=cross_organization_audit,
                    detected_at=now,
                )
                session.commit()

            with engine.connect() as connection:
                occurrence_count = connection.execute(
                    text(
                        "SELECT occurrence_count FROM security_alerts "
                        "WHERE id = :alert_id"
                    ),
                    {"alert_id": alert_id},
                ).scalar_one()
                evidence_count = connection.execute(
                    text(
                        "SELECT count(*) FROM security_alert_audit_events "
                        "WHERE security_alert_id = :alert_id"
                    ),
                    {"alert_id": alert_id},
                ).scalar_one()

            assert sorted(results) == [False, True]
            assert cross_organization_linked is False
            assert occurrence_count == 1
            assert evidence_count == 1
        finally:
            engine.dispose()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL integration tests",
)
def test_alert_constraints_defaults_and_delete_policies_in_postgres():
    with _disposable_database() as (database, config):
        engine = create_engine(config.database_url(database))
        creator_id = uuid.uuid4()
        handler_id = uuid.uuid4()
        resolved_handler_id = uuid.uuid4()
        organization_id = uuid.uuid4()
        alert_id = uuid.uuid4()
        acknowledged_alert_id = uuid.uuid4()
        resolved_alert_id = uuid.uuid4()
        audit_log_id = uuid.uuid4()
        parent_delete_audit_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        base_insert = (
            "INSERT INTO security_alerts "
            "(id, organization_id, subject_actor_id, rule_id, rule_version, "
            "severity, detection_key, first_detected_at, last_detected_at) "
            "VALUES (:id, :organization_id, :subject_actor_id, "
            "'repeated_permission_denied', 'v1', :severity, :detection_key, "
            ":first_detected_at, :last_detected_at)"
        )

        try:
            with engine.begin() as connection:
                for index, user_id in enumerate(
                    (creator_id, handler_id, resolved_handler_id)
                ):
                    connection.execute(
                        text(
                            "INSERT INTO users "
                            "(id, email, name, social_provider, created_at, updated_at) "
                            "VALUES (:id, :email, :name, 'local', :now, :now)"
                        ),
                        {
                            "id": user_id,
                            "email": f"security-alert-policy-{user_id}@example.invalid",
                            "name": f"User {index}",
                            "now": now,
                        },
                    )
                connection.execute(
                    text(
                        "INSERT INTO organization "
                        "(id, name, options, flags, created_by, is_active, "
                        "created_at, updated_at) VALUES "
                        "(:id, 'Security Alert Policies', '{}'::jsonb, 0, "
                        ":created_by, true, :now, :now)"
                    ),
                    {
                        "id": organization_id,
                        "created_by": creator_id,
                        "now": now,
                    },
                )
                connection.execute(
                    text(base_insert),
                    {
                        "id": alert_id,
                        "organization_id": organization_id,
                        "subject_actor_id": uuid.uuid4(),
                        "severity": "medium",
                        "detection_key": "policy:shared-key",
                        "first_detected_at": now,
                        "last_detected_at": now,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO security_alerts "
                        "(id, organization_id, subject_actor_id, rule_id, "
                        "rule_version, severity, status, detection_key, "
                        "occurrence_count, first_detected_at, last_detected_at, "
                        "lifecycle_version, acknowledged_by, acknowledged_at) "
                        "VALUES (:id, :organization_id, :subject_actor_id, "
                        "'repeated_permission_denied', 'v1', 'medium', "
                        "'acknowledged', :detection_key, 1, :now, :now, 1, "
                        ":acknowledged_by, :now)"
                    ),
                    {
                        "id": acknowledged_alert_id,
                        "organization_id": organization_id,
                        "subject_actor_id": uuid.uuid4(),
                        "detection_key": f"ack:{acknowledged_alert_id}",
                        "acknowledged_by": handler_id,
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO audit_logs "
                        "(id, occurred_at, actor_id, actor_type, category, action, "
                        "status, audit_metadata) VALUES "
                        "(:id, :now, :actor_id, 'user', 'action', "
                        "'permission.denied', 'failure', '{}'::jsonb)"
                    ),
                    {"id": audit_log_id, "now": now, "actor_id": creator_id},
                )
                connection.execute(
                    text(
                        "INSERT INTO security_alerts "
                        "(id, organization_id, subject_actor_id, rule_id, "
                        "rule_version, severity, status, detection_key, "
                        "occurrence_count, first_detected_at, last_detected_at, "
                        "lifecycle_version, resolution_type, resolution_reason, "
                        "resolved_by, resolved_at) VALUES "
                        "(:id, :organization_id, :subject_actor_id, "
                        "'repeated_permission_denied', 'v1', 'medium', "
                        "'resolved', :detection_key, 1, :now, :now, 2, "
                        "'mitigated', 'sanitized reason', :resolved_by, :now)"
                    ),
                    {
                        "id": resolved_alert_id,
                        "organization_id": organization_id,
                        "subject_actor_id": uuid.uuid4(),
                        "detection_key": f"resolved:{resolved_alert_id}",
                        "resolved_by": resolved_handler_id,
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO audit_logs "
                        "(id, occurred_at, actor_id, actor_type, category, action, "
                        "status, audit_metadata) VALUES "
                        "(:id, :now, :actor_id, 'user', 'action', "
                        "'permission.denied', 'failure', '{}'::jsonb)"
                    ),
                    {
                        "id": parent_delete_audit_id,
                        "now": now,
                        "actor_id": creator_id,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO security_alert_audit_events "
                        "(id, security_alert_id, audit_log_id) "
                        "VALUES (:id, :alert_id, :audit_log_id)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "alert_id": alert_id,
                        "audit_log_id": audit_log_id,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO security_alert_audit_events "
                        "(id, security_alert_id, audit_log_id) "
                        "VALUES (:id, :alert_id, :audit_log_id)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "alert_id": acknowledged_alert_id,
                        "audit_log_id": parent_delete_audit_id,
                    },
                )

            with engine.connect() as connection:
                defaults = connection.execute(
                    text(
                        "SELECT status, occurrence_count, lifecycle_version, "
                        "created_at, updated_at FROM security_alerts WHERE id = :id"
                    ),
                    {"id": alert_id},
                ).one()
            assert defaults.status == "open"
            assert defaults.occurrence_count == 0
            assert defaults.lifecycle_version == 1
            assert defaults.created_at.tzinfo is not None
            assert defaults.updated_at.tzinfo is not None

            invalid_cases = (
                {"severity": "critical", "first": now, "last": now},
                {"severity": "medium", "first": now, "last": now - timedelta(1)},
            )
            for invalid in invalid_cases:
                _assert_integrity_error(
                    engine,
                    base_insert,
                    {
                        "id": uuid.uuid4(),
                        "organization_id": organization_id,
                        "subject_actor_id": uuid.uuid4(),
                        "severity": invalid["severity"],
                        "detection_key": f"invalid:{uuid.uuid4()}",
                        "first_detected_at": invalid["first"],
                        "last_detected_at": invalid["last"],
                    },
                )

            for invalid_update in (
                "occurrence_count = -1",
                "lifecycle_version = 0",
                "status = 'unknown'",
                "resolution_type = 'unknown'",
                "status = 'acknowledged', acknowledged_at = NULL",
            ):
                _assert_integrity_error(
                    engine,
                    f"UPDATE security_alerts SET {invalid_update} WHERE id = :id",
                    {"id": alert_id},
                )

            _assert_integrity_error(
                engine,
                base_insert,
                {
                    "id": uuid.uuid4(),
                    "organization_id": organization_id,
                    "subject_actor_id": uuid.uuid4(),
                    "severity": "medium",
                    "detection_key": "policy:shared-key",
                    "first_detected_at": now,
                    "last_detected_at": now,
                },
            )

            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE security_alerts SET status = 'resolved', "
                        "resolution_type = 'mitigated', "
                        "resolution_reason = 'done', resolved_at = :now "
                        "WHERE id = :id"
                    ),
                    {"id": alert_id, "now": now},
                )
                connection.execute(
                    text(base_insert),
                    {
                        "id": uuid.uuid4(),
                        "organization_id": organization_id,
                        "subject_actor_id": uuid.uuid4(),
                        "severity": "medium",
                        "detection_key": "policy:shared-key",
                        "first_detected_at": now,
                        "last_detected_at": now,
                    },
                )
                connection.execute(
                    text("DELETE FROM users WHERE id = :id"),
                    {"id": handler_id},
                )
                connection.execute(
                    text("DELETE FROM users WHERE id = :id"),
                    {"id": resolved_handler_id},
                )
                connection.execute(
                    text("DELETE FROM audit_logs WHERE id = :id"),
                    {"id": audit_log_id},
                )
                connection.execute(
                    text("DELETE FROM security_alerts WHERE id = :id"),
                    {"id": acknowledged_alert_id},
                )

            _assert_integrity_error(
                engine,
                "DELETE FROM organization WHERE id = :id",
                {"id": organization_id},
            )

            with engine.connect() as connection:
                resolved_history = connection.execute(
                    text(
                        "SELECT resolved_by, resolved_at, resolution_type, "
                        "resolution_reason FROM security_alerts WHERE id = :id"
                    ),
                    {"id": resolved_alert_id},
                ).one()
                evidence_count = connection.execute(
                    text(
                        "SELECT count(*) FROM security_alert_audit_events "
                        "WHERE audit_log_id = :audit_log_id"
                    ),
                    {"audit_log_id": audit_log_id},
                ).scalar_one()
                parent_evidence_count = connection.execute(
                    text(
                        "SELECT count(*) FROM security_alert_audit_events "
                        "WHERE audit_log_id = :audit_log_id"
                    ),
                    {"audit_log_id": parent_delete_audit_id},
                ).scalar_one()
                parent_audit_count = connection.execute(
                    text("SELECT count(*) FROM audit_logs WHERE id = :id"),
                    {"id": parent_delete_audit_id},
                ).scalar_one()

            assert resolved_history.resolved_by is None
            assert resolved_history.resolved_at == now
            assert resolved_history.resolution_type == "mitigated"
            assert resolved_history.resolution_reason == "sanitized reason"
            assert evidence_count == 0
            assert parent_evidence_count == 0
            assert parent_audit_count == 1
        finally:
            engine.dispose()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL integration tests",
)
def test_concurrent_resolve_and_reopen_each_have_one_database_winner():
    with _disposable_database() as (database, config):
        engine = create_engine(config.database_url(database))
        manager_ids = (uuid.uuid4(), uuid.uuid4())
        organization_id = uuid.uuid4()
        resolve_alert_id = uuid.uuid4()
        reopen_alert_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        try:
            with engine.begin() as connection:
                for index, manager_id in enumerate(manager_ids):
                    connection.execute(
                        text(
                            "INSERT INTO users "
                            "(id, email, name, social_provider, created_at, updated_at) "
                            "VALUES (:id, :email, :name, 'local', :now, :now)"
                        ),
                        {
                            "id": manager_id,
                            "email": f"security-alert-lifecycle-{manager_id}@example.invalid",
                            "name": f"Manager {index}",
                            "now": now,
                        },
                    )
                connection.execute(
                    text(
                        "INSERT INTO organization "
                        "(id, name, options, flags, created_by, is_active, "
                        "created_at, updated_at) VALUES "
                        "(:id, 'Lifecycle Race', '{}'::jsonb, 0, :created_by, "
                        "true, :now, :now)"
                    ),
                    {
                        "id": organization_id,
                        "created_by": manager_ids[0],
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO security_alerts "
                        "(id, organization_id, subject_actor_id, rule_id, "
                        "rule_version, severity, status, detection_key, "
                        "occurrence_count, first_detected_at, last_detected_at, "
                        "lifecycle_version) VALUES "
                        "(:id, :organization_id, :subject_actor_id, "
                        "'repeated_permission_denied', 'v1', 'medium', 'open', "
                        ":detection_key, 1, :now, :now, 1)"
                    ),
                    {
                        "id": resolve_alert_id,
                        "organization_id": organization_id,
                        "subject_actor_id": uuid.uuid4(),
                        "detection_key": f"resolve-race:{resolve_alert_id}",
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO security_alerts "
                        "(id, organization_id, subject_actor_id, rule_id, "
                        "rule_version, severity, status, detection_key, "
                        "occurrence_count, first_detected_at, last_detected_at, "
                        "lifecycle_version, acknowledged_by, acknowledged_at) "
                        "VALUES (:id, :organization_id, :subject_actor_id, "
                        "'repeated_permission_denied', 'v1', 'medium', "
                        "'acknowledged', :detection_key, 1, :now, :now, 2, "
                        ":acknowledged_by, :now)"
                    ),
                    {
                        "id": reopen_alert_id,
                        "organization_id": organization_id,
                        "subject_actor_id": uuid.uuid4(),
                        "detection_key": f"reopen-race:{reopen_alert_id}",
                        "acknowledged_by": manager_ids[0],
                        "now": now,
                    },
                )

            resolve_ready = Barrier(2)

            def resolve(manager_id):
                with Session(engine) as session:
                    alert = session.get(SecurityAlert, resolve_alert_id)
                    resolve_ready.wait(timeout=5)
                    try:
                        resolve_security_alert(
                            session,
                            alert=alert,
                            manager_id=manager_id,
                            resolved_at=now,
                            expected_version=1,
                            resolution_type="mitigated",
                            reason="대응 완료",
                            reason_sanitizer=_IdentityReasonSanitizer(),
                        )
                        session.commit()
                        return "success"
                    except SecurityAlertStaleStateError:
                        session.rollback()
                        return "stale"

            with ThreadPoolExecutor(max_workers=2) as executor:
                resolve_results = list(executor.map(resolve, manager_ids))

            reopen_ready = Barrier(2)

            def reopen(manager_id):
                with Session(engine) as session:
                    alert = session.get(SecurityAlert, reopen_alert_id)
                    reopen_ready.wait(timeout=5)
                    try:
                        reopen_security_alert(
                            session,
                            alert=alert,
                            manager_id=manager_id,
                            reopened_at=now,
                            expected_version=2,
                        )
                        session.commit()
                        return "success"
                    except SecurityAlertStaleStateError:
                        session.rollback()
                        return "stale"

            with ThreadPoolExecutor(max_workers=2) as executor:
                reopen_results = list(executor.map(reopen, manager_ids))

            with engine.connect() as connection:
                resolve_audit_count = connection.execute(
                    text(
                        "SELECT count(*) FROM audit_logs "
                        "WHERE action = 'security_alert.resolved' "
                        "AND target_id = :target_id"
                    ),
                    {"target_id": str(resolve_alert_id)},
                ).scalar_one()
                reopen_audit_count = connection.execute(
                    text(
                        "SELECT count(*) FROM audit_logs "
                        "WHERE action = 'security_alert.reopened' "
                        "AND target_id = :target_id"
                    ),
                    {"target_id": str(reopen_alert_id)},
                ).scalar_one()

            assert sorted(resolve_results) == ["stale", "success"]
            assert sorted(reopen_results) == ["stale", "success"]
            assert resolve_audit_count == 1
            assert reopen_audit_count == 1
        finally:
            engine.dispose()


class _IdentityReasonSanitizer:
    def sanitize(self, reason):
        return reason
