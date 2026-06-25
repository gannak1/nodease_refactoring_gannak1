"""감사 이벤트를 Celery 태스크(`audit.record`)로 비동기 발행한다."""

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from apps.shared.celery_app import celery_app

logger = logging.getLogger(__name__)

_TASK_NAME = "audit.record"


def _serialize(value: Any) -> Any:
    """Celery JSON 직렬화를 위해 UUID/datetime/Enum/dict/list를 재귀 변환한다."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # 알 수 없는 타입은 문자열로 안전 변환
    return str(value)


def record_audit(
    action: str,
    category: str,
    *,
    actor_id: Optional[Any] = None,
    actor_type: str = "user",
    target_type: Optional[str] = None,
    target_id: Optional[Any] = None,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
    status: str = "success",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """감사 이벤트 1건을 발행한다. 발행 실패는 로깅만 한다."""
    try:
        data = {
            "action": action,
            "category": category,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "target_type": target_type,
            "target_id": str(target_id) if target_id is not None else None,
            "before": before,
            "after": after,
            "status": status,
            "audit_metadata": metadata or {},
            "occurred_at": datetime.now(timezone.utc),
        }
        celery_app.send_task(_TASK_NAME, args=[_serialize(data)])
    except Exception as e:  # noqa: BLE001 - 감사 발행은 절대 본 요청을 막지 않는다
        logger.error(f"[Audit] record 발행 실패 (action={action}): {e}")
