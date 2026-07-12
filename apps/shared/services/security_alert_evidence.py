from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from apps.shared.db.models.security_alert import SecurityAlertAuditEvent


def link_security_alert_evidence(
    db: Any,
    *,
    alert: Any,
    detected_at: datetime,
    audit_log_id: UUID | None = None,
    audit_log: Any | None = None,
) -> bool:
    if audit_log is not None:
        if not _has_matching_organization(alert, audit_log):
            return False
        audit_log_id = audit_log.id

    if audit_log_id is None:
        raise ValueError("audit_log or audit_log_id is required")

    if not _insert_evidence_once(
        db,
        alert_id=alert.id,
        audit_log_id=audit_log_id,
        linked_at=detected_at,
    ):
        return False

    alert.occurrence_count += 1
    alert.last_detected_at = detected_at
    return True


def _has_matching_organization(alert: Any, audit_log: Any) -> bool:
    audit_metadata = audit_log.audit_metadata or {}
    return str(audit_metadata.get("organization_id")) == str(alert.organization_id)


def _insert_evidence_once(
    db: Any,
    *,
    alert_id: UUID,
    audit_log_id: UUID,
    linked_at: datetime,
) -> bool:
    insert_once = getattr(db, "add_evidence_once", None)
    if callable(insert_once):
        return insert_once(alert_id=alert_id, audit_log_id=audit_log_id)

    statement = (
        insert(SecurityAlertAuditEvent)
        .values(
            security_alert_id=alert_id,
            audit_log_id=audit_log_id,
            linked_at=linked_at,
        )
        .on_conflict_do_nothing(
            constraint="uq_security_alert_audit_events_alert_audit"
        )
        .returning(SecurityAlertAuditEvent.id)
    )
    return db.execute(statement).scalar_one_or_none() is not None
