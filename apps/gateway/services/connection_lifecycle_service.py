from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.shared.db.models.connection import Connection
from apps.shared.db.models.knowledge import Document


class ConnectionLifecycleError(Exception):
    """Base error for owner-scoped connection lifecycle mutations."""


class ConnectionLifecycleHidden(ConnectionLifecycleError):
    pass


class ConnectionLifecycleInUse(ConnectionLifecycleError):
    pass


class ConnectionLifecycleUnavailable(ConnectionLifecycleError):
    pass


class ConnectionLifecycleService:
    """Delete an owner connection only when no Knowledge document references it."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def delete_unreferenced_connection(
        self,
        *,
        connection_id: UUID,
        owner_id: UUID,
    ) -> None:
        try:
            connection = (
                self.db.query(Connection)
                .filter(
                    Connection.id == connection_id,
                    Connection.user_id == owner_id,
                )
                .with_for_update()
                .first()
            )
            if connection is None:
                raise ConnectionLifecycleHidden()

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
