"""
Audit System Celery 태스크

사용자 작업 감사(Audit) 로그를 DB(audit_logs)에 저장하는 Celery 태스크입니다.
record_audit가 발행한 `audit.record`를 소비합니다. (기존 log_system/tasks.py 컨벤션 준수)
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from apps.shared.celery_app import celery_app

# SQLAlchemy 모델 relationship 초기화를 위해 User를 먼저 import (FK 대상)
from apps.shared.db.models.user import User  # noqa: F401
from apps.shared.db.models.audit_log import AuditLog
from apps.shared.db.session import SessionLocal

logger = logging.getLogger(__name__)


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


@celery_app.task(name="audit.record", bind=True, max_retries=3)
def record_audit_log(self, data: Dict[str, Any]):
    """감사 로그 1건 저장."""
    session = SessionLocal()
    try:
        audit = AuditLog(
            id=uuid.uuid4(),
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
        return {"status": "success", "action": data.get("action")}
    except Exception as e:
        session.rollback()
        logger.error(f"[Audit] record_audit_log 실패: {e}")
        raise self.retry(exc=e, countdown=2**self.request.retries)
    finally:
        session.close()
