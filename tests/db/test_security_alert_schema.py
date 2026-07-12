from __future__ import annotations

import importlib
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from apps.shared.db import models as shared_models


EXPECTED_ALERT_CHECKS = {
    "ck_security_alerts_occurrence_count_nonnegative",
    "ck_security_alerts_lifecycle_version_positive",
    "ck_security_alerts_severity",
    "ck_security_alerts_status",
    "ck_security_alerts_resolution_type",
    "ck_security_alerts_timestamp_order",
    "ck_security_alerts_status_fields",
}


def _security_alert_models():
    module = importlib.import_module("apps.shared.db.models.security_alert")
    return module.SecurityAlert, module.SecurityAlertAuditEvent


def _constraint_names(table, constraint_type):
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, constraint_type) and constraint.name
    }


def test_security_alert_models_are_registered_with_expected_table_names():
    alert_model, evidence_model = _security_alert_models()

    assert shared_models.SecurityAlert is alert_model
    assert shared_models.SecurityAlertAuditEvent is evidence_model
    assert alert_model.__tablename__ == "security_alerts"
    assert evidence_model.__tablename__ == "security_alert_audit_events"


def test_security_alert_model_declares_required_columns_and_defaults():
    alert_model, _ = _security_alert_models()
    table = alert_model.__table__

    required_columns = {
        "id",
        "organization_id",
        "subject_actor_id",
        "rule_id",
        "rule_version",
        "severity",
        "status",
        "policy_reason",
        "detection_key",
        "occurrence_count",
        "first_detected_at",
        "last_detected_at",
        "lifecycle_version",
        "acknowledged_by",
        "acknowledged_at",
        "resolution_type",
        "resolution_reason",
        "resolved_by",
        "resolved_at",
        "created_at",
        "updated_at",
    }
    assert required_columns == set(table.columns.keys())

    assert table.c.organization_id.nullable is False
    assert table.c.subject_actor_id.nullable is False
    assert not table.c.subject_actor_id.foreign_keys
    assert table.c.policy_reason.nullable is True
    assert table.c.occurrence_count.nullable is False
    assert table.c.occurrence_count.server_default is not None
    assert str(table.c.occurrence_count.server_default.arg) == "0"
    assert table.c.lifecycle_version.nullable is False
    assert table.c.lifecycle_version.server_default is not None
    assert str(table.c.lifecycle_version.server_default.arg) == "1"

    for name in (
        "first_detected_at",
        "last_detected_at",
        "created_at",
        "updated_at",
    ):
        assert table.c[name].type.timezone is True, name


def test_security_alert_tables_declare_required_constraints_and_indexes():
    alert_model, evidence_model = _security_alert_models()
    alert_table = alert_model.__table__
    evidence_table = evidence_model.__table__

    assert EXPECTED_ALERT_CHECKS <= _constraint_names(
        alert_table,
        CheckConstraint,
    )
    assert "uq_security_alert_audit_events_alert_audit" in _constraint_names(
        evidence_table,
        UniqueConstraint,
    )

    active_unique = next(
        index
        for index in alert_table.indexes
        if index.name == "uq_security_alerts_active_detection_key"
    )
    assert active_unique.unique is True
    where = str(active_unique.dialect_options["postgresql"]["where"])
    assert "status" in where
    assert "open" in where
    assert "acknowledged" in where

    organization_fk = next(
        constraint
        for constraint in alert_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and [column.name for column in constraint.columns] == ["organization_id"]
    )
    assert organization_fk.ondelete in {None, "NO ACTION", "RESTRICT"}


def test_security_alert_handler_deletion_is_compatible_with_status_constraint():
    alert_model, _ = _security_alert_models()
    table = alert_model.__table__

    for column_name in ("acknowledged_by", "resolved_by"):
        foreign_key = next(iter(table.c[column_name].foreign_keys))
        assert foreign_key.ondelete == "SET NULL"

    status_fields_constraint = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_security_alerts_status_fields"
    )
    status_fields_sql = str(status_fields_constraint.sqltext)

    assert "acknowledged_by IS NOT NULL" not in status_fields_sql
    assert "resolved_by IS NOT NULL" not in status_fields_sql


def test_security_alert_evidence_rejects_orphans_and_cascades_with_parents():
    _, evidence_model = _security_alert_models()
    table = evidence_model.__table__

    expected_foreign_keys = {
        "security_alert_id": "security_alerts.id",
        "audit_log_id": "audit_logs.id",
    }
    for column_name, expected_target in expected_foreign_keys.items():
        column = table.c[column_name]
        foreign_key = next(iter(column.foreign_keys))

        assert column.nullable is False
        assert foreign_key.target_fullname == expected_target
        assert foreign_key.ondelete == "CASCADE"


def test_security_alert_migration_defines_upgrade_and_downgrade_for_both_tables():
    versions = Path("apps/shared/alembic/versions")
    candidates = [
        path
        for path in versions.glob("*.py")
        if "security_alerts" in path.read_text(encoding="utf-8")
        and "security_alert_audit_events" in path.read_text(encoding="utf-8")
    ]

    assert len(candidates) == 1
    source = candidates[0].read_text(encoding="utf-8")
    assert "def upgrade" in source
    assert "def downgrade" in source
    assert source.index("drop_table(\"security_alert_audit_events\")") < source.index(
        "drop_table(\"security_alerts\")"
    )
