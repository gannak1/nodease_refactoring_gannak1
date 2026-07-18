"""Bounded retention commands owned by the Conversation Memory domain."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.memory.application.ports import MemoryUnitOfWorkPort


class PublicSecretReplayRetentionRepositoryPort(Protocol):
    def delete_expired_secret_replays(self, *, now: datetime, limit: int) -> int: ...


class PurgeExpiredPublicSecretReplaysUseCase:
    def __init__(
        self,
        *,
        repository: PublicSecretReplayRetentionRepositoryPort,
        uow: MemoryUnitOfWorkPort,
    ) -> None:
        self.repository = repository
        self.uow = uow

    def execute(self, *, now: datetime, limit: int = 500) -> int:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("retention time must be timezone-aware")
        if not 1 <= limit <= 1000:
            raise ValueError("retention batch limit must be between 1 and 1000")
        self.uow.begin()
        try:
            deleted_count = self.repository.delete_expired_secret_replays(
                now=now,
                limit=limit,
            )
            self.uow.commit()
            return deleted_count
        except Exception:
            self.uow.rollback()
            raise


__all__ = [
    "PublicSecretReplayRetentionRepositoryPort",
    "PurgeExpiredPublicSecretReplaysUseCase",
]
