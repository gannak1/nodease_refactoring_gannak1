from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.shared.db.models.connection import Connection
from apps.shared.db.models.knowledge import Document
from apps.shared.services.connection_use_resolver import (
    ConnectionUseDenied,
    ConnectionUseResolver,
)


class ConnectionLifecycleError(Exception):
    """Base error for owner-scoped connection lifecycle mutations."""


class ConnectionLifecycleHidden(ConnectionLifecycleError):
    pass


class ConnectionLifecycleInUse(ConnectionLifecycleError):
    pass


class ConnectionLifecycleUnavailable(ConnectionLifecycleError):
    pass


class ConnectionLifecycleService:
    """Serialize owner connection references with reference-aware deletion."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def lock_owned_connection_for_reference(
        self,
        *,
        connection_id: UUID,
        owner_id: UUID,
    ) -> Connection:
        """Serialize a new document reference with owner-scoped deletion."""

        try:
            return ConnectionUseResolver(self.db).resolve(
                connection_id,
                execution_subject_user_id=owner_id,
                lock_for_use=True,
            )
        except ConnectionUseDenied:
            raise ConnectionLifecycleHidden() from None
        except SQLAlchemyError:
            raise ConnectionLifecycleUnavailable() from None

    def delete_unreferenced_connection(
        self,
        *,
        connection_id: UUID,
        owner_id: UUID,
    ) -> None:
        try:
            connection = self.lock_owned_connection_for_reference(
                connection_id=connection_id,
                owner_id=owner_id,
            )

            referenced_document = (
                self.db.query(Document.id)
                .filter(
                    or_(
                        Document.meta_info.contains(
                            {"connection_id": str(connection_id)}
                        ),
                        Document.meta_info.contains(
                            {
                                "db_config": {
                                    "connection_id": str(connection_id)
                                }
                            }
                        ),
                        and_(
                            func.jsonb_typeof(Document.meta_info["db_config"])
                            == "string",
                            Document.meta_info["db_config"].astext.contains(
                                str(connection_id)
                            ),
                        ),
                    )
                )
                .first()
            )
            if referenced_document is not None:
                raise ConnectionLifecycleInUse()

            self.db.delete(connection)
            self.db.commit()
        except ConnectionLifecycleError:
            self.db.rollback()
            raise
        except SQLAlchemyError:
            self.db.rollback()
            raise ConnectionLifecycleUnavailable() from None
