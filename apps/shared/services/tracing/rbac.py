from typing import Any, Protocol

from sqlalchemy.orm import Session

TRACE_SYSTEM_ADMIN_PERMISSION = "tracing.system_admin"


class TraceRbacProvider(Protocol):
    """추적 전용 권한 확인을 위한 RBAC 어댑터 경계."""

    def is_system_admin(self, db: Session, user: Any) -> bool:
        """현재 사용자가 추적 정책을 관리할 수 있는지 반환."""


class DenyAllTraceRbacProvider:
    """공용 사용자/RBAC 모델이 연결되기 전까지 사용하는 기본 제공자."""

    def is_system_admin(self, db: Session, user: Any) -> bool:
        return False


class TraceRbacService:
    """향후 사용자/RBAC 구현을 붙이기 위한 작은 통합 지점."""

    _provider: TraceRbacProvider = DenyAllTraceRbacProvider()

    @classmethod
    def configure_provider(cls, provider: TraceRbacProvider) -> None:
        cls._provider = provider

    @classmethod
    def reset_provider(cls) -> None:
        cls._provider = DenyAllTraceRbacProvider()

    @classmethod
    def is_system_admin(cls, db: Session, user: Any) -> bool:
        if user is None:
            return False
        try:
            return bool(cls._provider.is_system_admin(db, user))
        except Exception:
            return False
