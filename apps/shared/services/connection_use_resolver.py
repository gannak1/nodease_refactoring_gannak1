from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from apps.shared.db.models.connection import Connection


class ConnectionUseDenied(Exception):
    """Hide whether a Connection exists when the subject cannot use it."""

    code = "resource.hidden"

    def __init__(self) -> None:
        super().__init__("Resource is unavailable.")


class ConnectionUseResolver:
    """Resolve the current user-owned Connection at its use boundary."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve(
        self,
        connection_id: Any,
        *,
        execution_subject_user_id: Any,
        lock_for_use: bool = False,
    ) -> Connection:
        normalized_connection_id = self._uuid_or_hidden(connection_id)
        normalized_subject_id = self._uuid_or_hidden(execution_subject_user_id)
        if self.db is None:
            raise ConnectionUseDenied()

        query = self.db.query(Connection).filter(
            Connection.id == normalized_connection_id,
            Connection.user_id == normalized_subject_id,
        )
        if lock_for_use:
            query = query.with_for_update()
        connection = query.one_or_none()
        if connection is None:
            raise ConnectionUseDenied()
        return connection

    @staticmethod
    def _uuid_or_hidden(value: Any) -> uuid.UUID:
        try:
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        except (AttributeError, TypeError, ValueError):
            raise ConnectionUseDenied() from None

