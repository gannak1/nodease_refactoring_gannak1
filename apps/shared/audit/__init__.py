"""
Moduly Audit 패키지

사용자 작업 감사(Audit) 로그를 비동기로 수집한다.
- record_audit: 감사 이벤트를 Celery 태스크로 발행 (계층 A/B 공용)
- context: 요청 단위 actor 정보를 flush 이벤트(계층 B)까지 전파하는 contextvar
"""

from apps.shared.audit.context import (
    AuditActor,
    clear_current_actor,
    get_current_actor,
    set_current_actor,
)
from apps.shared.audit.logger import record_audit

__all__ = [
    "record_audit",
    "AuditActor",
    "get_current_actor",
    "set_current_actor",
    "clear_current_actor",
]
