"""
요청 단위 actor 컨텍스트

flush 이벤트(계층 B)에는 요청 컨텍스트가 없어 actor를 알 수 없다.
`@audit` 데코레이터가 요청 처리 동안 현재 actor를 contextvar에 세팅하면,
ORM 리스너가 이를 읽어 data_change 로그에 actor를 채울 수 있다.

세팅되지 않은 경로(시드/배치 등)에서는 actor가 없으므로 system으로 기록된다.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AuditActor:
    """현재 행위 주체. snapshot은 audit_metadata.actor로 보존된다."""

    actor_id: Optional[str] = None
    actor_type: str = "user"  # user / admin / system
    snapshot: dict = field(default_factory=dict)  # {id, email, name}


_current_actor: ContextVar[Optional[AuditActor]] = ContextVar(
    "audit_current_actor", default=None
)


def set_current_actor(actor: AuditActor):
    """현재 요청의 actor를 세팅하고, 복원용 토큰을 반환한다."""
    return _current_actor.set(actor)


def get_current_actor() -> Optional[AuditActor]:
    return _current_actor.get()


def clear_current_actor(token=None):
    """토큰이 있으면 이전 값으로 복원, 없으면 None으로 초기화한다."""
    if token is not None:
        _current_actor.reset(token)
    else:
        _current_actor.set(None)
