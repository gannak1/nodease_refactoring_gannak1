from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from apps.memory.domain.errors import MemoryAdapterUnavailableError
from apps.shared.audit import record_audit


class SqlAlchemyPublicConversationAudit:
    """Write a public-actor lifecycle audit event into the caller UoW outbox."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        action: str,
        organization_id: uuid.UUID,
        deployment_id: uuid.UUID,
        session_id: uuid.UUID,
        purge_job_id: uuid.UUID | None = None,
    ) -> None:
        audit_id = record_audit(
            action=action,
            category="action",
            actor_id=None,
            actor_type="public",
            target_type="conversation_session",
            target_id=session_id,
            status="success",
            metadata={
                "organization_id": str(organization_id),
                "deployment_id": str(deployment_id),
                "surface": "public_chatbot",
                "purge_job_id": str(purge_job_id) if purge_job_id else None,
            },
            db_session=self._session,
        )
        if audit_id is None:
            raise MemoryAdapterUnavailableError()


__all__ = ["SqlAlchemyPublicConversationAudit"]
