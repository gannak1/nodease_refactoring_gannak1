"""현재 DB 세션에 동기 audit row를 남기는 헬퍼.

비동기 발행(`apps.shared.audit.logger.record_audit`)과 달리, 권한 부여/회수처럼
본 작업과 같은 트랜잭션에서 audit이 함께 커밋되어야 하는 경로에서 사용한다
(ADR-0016). commit은 호출자가 수행한다.
"""

from typing import Any

from sqlalchemy.orm import Session

from apps.shared.db.models.audit_log import AuditLog


def add_action_audit(
    db: Session,
    action: str,
    actor_id: Any,
    target_type: str,
    target_id: Any,
) -> None:
    db.add(
        AuditLog(
            action=action,
            category="action",
            actor_id=actor_id,
            actor_type="user",
            target_type=target_type,
            target_id=str(target_id),
            status="success",
            audit_metadata={},
        )
    )
