from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from apps.shared.db.models.audit_log import AuditLog
from apps.shared.db.models.security_alert import (
    SecurityAlertReconciliationReceipt,
    SecurityAlertReconciliationWatermark,
)
from sqlalchemy import and_, exists, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased


@dataclass(frozen=True)
class SecurityAlertReconciliationResult:
    processed_count: int


class SQLAlchemySecurityAlertReconciliationRepository:
    def __init__(self, db: Any, *, process_audit: Callable[[Any], None]):
        self.db = db
        self.process_audit = process_audit
        self.watermark = None
        self.processor_name = None

    def load_security_alert_watermark(self, *, processor_name: str):
        self.processor_name = processor_name
        self.watermark = (
            self.db.query(SecurityAlertReconciliationWatermark)
            .filter(
                SecurityAlertReconciliationWatermark.processor_name
                == processor_name
            )
            .with_for_update()
            .one()
        )
        return self.watermark

    def scan_security_alert_audits(
        self,
        *,
        started_at: datetime,
        replay_horizon: timedelta,
    ):
        processed_receipt_exists = exists().where(
            SecurityAlertReconciliationReceipt.processor_name
            == self.processor_name,
            SecurityAlertReconciliationReceipt.audit_log_id == AuditLog.id,
        )
        unprocessed_audit = aliased(AuditLog)
        unprocessed_receipt = aliased(SecurityAlertReconciliationReceipt)
        unprocessed_receipt_exists = exists().where(
            unprocessed_receipt.processor_name == self.processor_name,
            unprocessed_receipt.audit_log_id == unprocessed_audit.id,
        )
        unprocessed_predecessor_exists = exists().where(
            unprocessed_audit.occurred_at >= started_at,
            ~unprocessed_receipt_exists,
            unprocessed_audit.actor_id.is_not(None),
            unprocessed_audit.actor_type == "user",
            unprocessed_audit.category == "action",
            unprocessed_audit.status == "failure",
            or_(
                and_(
                    unprocessed_audit.action == "permission.denied",
                    unprocessed_audit.target_type.is_not(None),
                    unprocessed_audit.target_id.is_not(None),
                ),
                unprocessed_audit.action == "policy.block",
            ),
            AuditLog.actor_id == unprocessed_audit.actor_id,
            AuditLog.actor_type == "user",
            AuditLog.category == "action",
            AuditLog.status == "failure",
            AuditLog.action == unprocessed_audit.action,
            AuditLog.audit_metadata["organization_id"].astext
            == unprocessed_audit.audit_metadata["organization_id"].astext,
            unprocessed_audit.occurred_at <= AuditLog.occurred_at,
            AuditLog.occurred_at
            <= unprocessed_audit.occurred_at + replay_horizon,
        )
        return (
            self.db.query(AuditLog)
            .filter(AuditLog.occurred_at >= started_at)
            .filter(
                or_(
                    ~processed_receipt_exists,
                    unprocessed_predecessor_exists,
                )
            )
            .order_by(AuditLog.occurred_at, AuditLog.id)
            .all()
        )

    def process_security_alert_audit(self, audit: Any) -> None:
        self.process_audit(audit)

    def mark_security_alert_audit_processed(self, *, audit_log_id: Any) -> None:
        self.db.execute(
            insert(SecurityAlertReconciliationReceipt)
            .values(
                processor_name=self.processor_name,
                audit_log_id=audit_log_id,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    SecurityAlertReconciliationReceipt.processor_name,
                    SecurityAlertReconciliationReceipt.audit_log_id,
                ]
            )
        )

    def advance_security_alert_watermark(
        self,
        *,
        occurred_at: datetime,
        audit_log_id: Any,
    ) -> None:
        self.watermark.cursor_occurred_at = occurred_at
        self.watermark.cursor_audit_log_id = audit_log_id

    def commit(self) -> None:
        self.db.commit()


def reconcile_security_alert_batch(
    repository,
    *,
    processor_name: str,
    replay_horizon: timedelta,
) -> SecurityAlertReconciliationResult:
    watermark = repository.load_security_alert_watermark(
        processor_name=processor_name
    )
    audits = repository.scan_security_alert_audits(
        started_at=watermark.activation_started_at,
        replay_horizon=replay_horizon,
    )
    for audit in audits:
        repository.process_security_alert_audit(audit)
        repository.mark_security_alert_audit_processed(audit_log_id=audit.id)

    latest_cursor = _latest_processed_cursor(watermark, audits)
    if latest_cursor is not None:
        repository.advance_security_alert_watermark(
            occurred_at=latest_cursor[0],
            audit_log_id=latest_cursor[1],
        )
    repository.commit()
    return SecurityAlertReconciliationResult(processed_count=len(audits))


def _latest_processed_cursor(watermark, audits):
    cursors = [(audit.occurred_at, audit.id) for audit in audits]
    if watermark.cursor_occurred_at is not None:
        cursors.append(
            (watermark.cursor_occurred_at, watermark.cursor_audit_log_id)
        )
    return max(cursors) if cursors else None
