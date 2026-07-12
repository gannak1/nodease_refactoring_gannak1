"""
Audit System Celery 태스크

사용자 작업 감사(Audit) 로그를 DB(audit_logs)에 저장하는 Celery 태스크입니다.
record_audit가 발행한 `audit.record`를 소비합니다. (기존 log_system/tasks.py 컨벤션 준수)
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, NoReturn, Optional

from apps.shared.celery_app import celery_app
from apps.shared.db.models.audit_log import AuditLog
from apps.shared.db.models.security_alert import SecurityAlertReconciliationWatermark
from apps.shared.db.models.user import User  # noqa: F401
from apps.shared.db.session import SessionLocal
from apps.shared.services.security_alert_aggregation import (
    aggregate_security_alert_detection,
)
from apps.shared.services.security_alert_reconciliation import (
    SQLAlchemySecurityAlertReconciliationRepository,
    reconcile_security_alert_batch,
)
from apps.shared.services.security_alert_rule_evaluator import (
    evaluate_security_alert_rules,
)
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)
_SECURITY_ALERT_DETECTION_TASK = "security_alert.detect"
_SECURITY_ALERT_RECONCILIATION_TASK = "security_alert.reconcile"
_SECURITY_ALERT_PROCESSOR = "security-alert-v1"
_SECURITY_ALERT_MAX_WINDOW = timedelta(minutes=10)
_SECURITY_ALERT_RECONCILIATION_OVERLAP = timedelta(minutes=1)


class SecurityAlertTaskRetryError(RuntimeError):
    pass


def _to_uuid(value) -> Optional[uuid.UUID]:
    try:
        if value is None or isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _to_datetime(value):
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value


def _audit_id(data: Dict[str, Any], task_id: str | None) -> uuid.UUID:
    supplied = _to_uuid(data.get("id"))
    if supplied is not None:
        return supplied
    # 배포 중 이미 broker에 들어가 있던 legacy message도 retry마다 같은 ID를 쓴다.
    return uuid.uuid5(uuid.NAMESPACE_URL, f"nodease:audit-task:{task_id}")


def _result(*, status: str, data: Dict[str, Any], audit_id: uuid.UUID) -> Dict[str, str]:
    return {
        "status": status,
        "action": data.get("action"),
        "audit_id": str(audit_id),
    }


def _dispatch_security_alert_detection(audit_id: uuid.UUID) -> None:
    celery_app.send_task(_SECURITY_ALERT_DETECTION_TASK, args=[str(audit_id)])


def _dispatched_result(
    *,
    status: str,
    data: Dict[str, Any],
    audit_id: uuid.UUID,
) -> Dict[str, str]:
    _dispatch_security_alert_detection(audit_id)
    return _result(status=status, data=data, audit_id=audit_id)


def _retry_countdown(task: Any) -> int:
    return 2**task.request.retries


def _retry_security_alert_task(
    task: Any,
    error: Exception,
    *,
    operation: str,
) -> NoReturn:
    logger.error(
        "[Security Alert] task failed: operation=%s error_type=%s",
        operation,
        type(error).__name__,
    )
    raise task.retry(
        exc=SecurityAlertTaskRetryError("security alert task retry requested"),
        countdown=_retry_countdown(task),
    )


@celery_app.task(name="audit.record", bind=True, max_retries=3)
def record_audit_log(self, data: Dict[str, Any]):
    """감사 로그 1건 저장."""
    session = SessionLocal()
    audit_id = _audit_id(data, getattr(self.request, "id", None))
    try:
        if session.get(AuditLog, audit_id) is not None:
            return _dispatched_result(
                status="duplicate",
                data=data,
                audit_id=audit_id,
            )

        audit = AuditLog(
            id=audit_id,
            occurred_at=_to_datetime(data.get("occurred_at")),
            actor_id=_to_uuid(data.get("actor_id")),
            actor_type=data["actor_type"],
            category=data["category"],
            action=data["action"],
            target_type=data.get("target_type"),
            target_id=data.get("target_id"),
            before=data.get("before"),
            after=data.get("after"),
            status=data.get("status", "success"),
            audit_metadata=data.get("audit_metadata") or {},
        )
        session.add(audit)
        session.commit()
        return _dispatched_result(status="success", data=data, audit_id=audit_id)
    except IntegrityError as e:
        session.rollback()
        # 동시에 같은 message를 받은 경우 PK winner가 commit됐으면 성공으로 본다.
        if session.get(AuditLog, audit_id) is not None:
            return _dispatched_result(
                status="duplicate",
                data=data,
                audit_id=audit_id,
            )
        logger.error(
            "[Audit] record_audit_log integrity failure: error_type=%s",
            type(e).__name__,
        )
        raise self.retry(exc=e, countdown=_retry_countdown(self))
    except Exception as e:
        session.rollback()
        logger.error(
            "[Audit] record_audit_log failure: error_type=%s",
            type(e).__name__,
        )
        raise self.retry(exc=e, countdown=_retry_countdown(self))
    finally:
        session.close()


@celery_app.task(
    name=_SECURITY_ALERT_DETECTION_TASK,
    bind=True,
    max_retries=3,
)
def detect_security_alert(self, audit_id: str) -> Dict[str, Any]:
    session = SessionLocal()
    parsed_audit_id = _to_uuid(audit_id)
    try:
        candidate_count = _process_security_alert_audit(session, parsed_audit_id)
        if candidate_count is None:
            return {"status": "missing", "audit_id": audit_id}

        session.commit()
        return {
            "status": "processed",
            "audit_id": audit_id,
            "candidate_count": candidate_count,
        }
    except Exception as e:
        session.rollback()
        _retry_security_alert_task(self, e, operation="detect")
    finally:
        session.close()


def _process_security_alert_audit(
    db: Any,
    audit_id: uuid.UUID | None,
) -> int | None:
    context = _load_security_alert_detection_context(db, audit_id)
    if context is None:
        return None
    current_event, window_events, activation_started_at = context
    return _evaluate_and_aggregate_security_alerts(
        db,
        current_event=current_event,
        window_events=window_events,
        activation_started_at=activation_started_at,
    )


def _evaluate_and_aggregate_security_alerts(
    db: Any,
    *,
    current_event: Any,
    window_events: list[Any],
    activation_started_at: datetime,
) -> int:
    candidates = evaluate_security_alert_rules(
        current_event=current_event,
        window_events=window_events,
        activation_started_at=activation_started_at,
    )
    for candidate in candidates:
        aggregate_security_alert_detection(
            db,
            candidate=candidate,
            audit_logs=window_events,
            detected_at=current_event.occurred_at,
        )
    return len(candidates)


def _load_security_alert_detection_context(db: Any, audit_id: uuid.UUID | None):
    current_event = db.get(AuditLog, audit_id)
    if current_event is None:
        return None
    activation_started_at = _security_alert_activation_started_at(db, current_event)
    window_started_at = max(
        activation_started_at,
        current_event.occurred_at - _SECURITY_ALERT_MAX_WINDOW,
    )
    organization_id = (current_event.audit_metadata or {}).get("organization_id")
    window_events = (
        db.query(AuditLog)
        .filter(
            AuditLog.actor_id == current_event.actor_id,
            AuditLog.audit_metadata["organization_id"].astext
            == str(organization_id),
            AuditLog.occurred_at >= window_started_at,
            AuditLog.occurred_at <= current_event.occurred_at,
        )
        .order_by(AuditLog.occurred_at, AuditLog.id)
        .all()
    )
    return current_event, window_events, activation_started_at


def _security_alert_activation_started_at(db: Any, current_event: Any) -> datetime:
    watermark = db.get(
        SecurityAlertReconciliationWatermark,
        _SECURITY_ALERT_PROCESSOR,
    )
    return (
        watermark.activation_started_at
        if watermark is not None
        else current_event.occurred_at
    )


@celery_app.task(
    name=_SECURITY_ALERT_RECONCILIATION_TASK,
    bind=True,
    max_retries=3,
)
def reconcile_security_alerts(self) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        repository = SQLAlchemySecurityAlertReconciliationRepository(
            session,
            process_audit=lambda audit: _process_reconciliation_audit(
                session,
                audit,
            ),
        )
        result = reconcile_security_alert_batch(
            repository,
            processor_name=_SECURITY_ALERT_PROCESSOR,
            overlap=_SECURITY_ALERT_RECONCILIATION_OVERLAP,
        )
        return {
            "status": "processed",
            "processed_count": result.processed_count,
        }
    except Exception as e:
        session.rollback()
        _retry_security_alert_task(self, e, operation="reconcile")
    finally:
        session.close()


def _process_reconciliation_audit(db: Any, audit: AuditLog) -> None:
    _process_security_alert_audit(db, audit.id)
