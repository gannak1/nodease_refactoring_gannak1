"""Celery execution adapters for Memory-owned retention work."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apps.memory.adapters.persistence.readiness import (
    REQUIRED_MEMORY_SCHEMA,
    check_memory_schema_readiness,
)
from apps.memory.adapters.persistence.repository import (
    SqlAlchemyConversationMemoryRepository,
    SqlAlchemyMemoryUnitOfWork,
)
from apps.memory.application.retention import PurgeExpiredPublicSecretReplaysUseCase
from apps.shared.celery_app import celery_app
from apps.shared.db.session import SessionLocal

logger = logging.getLogger(__name__)
_RETENTION_BATCH_LIMIT = 500
_REPLAY_SCHEMA = {
    "conversation_secret_replays": REQUIRED_MEMORY_SCHEMA[
        "conversation_secret_replays"
    ]
}


def _build_retention_use_case(session):
    return PurgeExpiredPublicSecretReplaysUseCase(
        repository=SqlAlchemyConversationMemoryRepository(session),
        uow=SqlAlchemyMemoryUnitOfWork(session),
    )


@celery_app.task(
    name="memory.secret_replay_retention_purge",
    bind=True,
    max_retries=3,
    ignore_result=True,
)
def purge_expired_public_secret_replays(self):
    session = SessionLocal()
    try:
        readiness = check_memory_schema_readiness(
            session,
            required_schema=_REPLAY_SCHEMA,
        )
        if not readiness.ready:
            return {"status": "not_ready", "deleted_count": 0}
        deleted_count = _build_retention_use_case(session).execute(
            now=datetime.now(timezone.utc),
            limit=_RETENTION_BATCH_LIMIT,
        )
        return {"status": "success", "deleted_count": deleted_count}
    except Exception as error:
        session.rollback()
        logger.error(
            "Public secret replay retention failed: error_type=%s",
            type(error).__name__,
        )
        raise self.retry(exc=error, countdown=2**self.request.retries)
    finally:
        session.close()


__all__ = ["purge_expired_public_secret_replays"]
