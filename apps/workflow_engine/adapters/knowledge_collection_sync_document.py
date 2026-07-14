from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.shared.db.models.connection import Connection
from apps.shared.db.models.knowledge import (
    Document,
    KnowledgeBase,
    KnowledgeCollection,
    KnowledgeCollectionItem,
    SourceType,
)
from apps.shared.services.ingestion.processors.db_processor import DbProcessor
from apps.shared.services.ingestion.vector_store_service import (
    VectorStoreService,
    acquire_document_write_lock,
)
from apps.shared.services.permissions import has_active_organization_membership
from apps.workflow_engine.application.knowledge_collection_sync import (
    SyncTargetChanged,
    SyncTargetConfigurationInvalid,
    SyncTargetTemporarilyUnavailable,
    WorkerSyncItem,
)


class SqlAlchemyKnowledgeCollectionSyncDocument:
    """Apply one durable DB-document target without exposing its stored config."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def sync(self, item: WorkerSyncItem, *, actor_id: uuid.UUID) -> None:
        acquire_document_write_lock(self.db, item.document_id)
        collection = (
            self.db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.id == item.collection_id,
                KnowledgeCollection.organization_id == item.organization_id,
                KnowledgeCollection.lifecycle_state == "active",
                KnowledgeCollection.sync_state != "source_deleted",
                KnowledgeCollection.is_system_managed.is_(False),
                KnowledgeCollection.source_identity_id.is_(None),
                KnowledgeCollection.source_connector_ref.is_(None),
            )
            .with_for_update()
            .one_or_none()
        )
        membership = (
            self.db.query(KnowledgeCollectionItem)
            .filter(
                KnowledgeCollectionItem.organization_id == item.organization_id,
                KnowledgeCollectionItem.collection_id == item.collection_id,
                KnowledgeCollectionItem.knowledge_base_id == item.knowledge_base_id,
            )
            .with_for_update()
            .one_or_none()
        )
        knowledge_base = (
            self.db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.id == item.knowledge_base_id,
                KnowledgeBase.organization_id == item.organization_id,
                KnowledgeBase.lifecycle_state == "active",
                KnowledgeBase.sync_state != "source_deleted",
                KnowledgeBase.source_identity_id.is_(None),
            )
            .with_for_update()
            .one_or_none()
        )
        document = (
            self.db.query(Document)
            .filter(
                Document.id == item.document_id,
                Document.knowledge_base_id == item.knowledge_base_id,
                Document.source_type == SourceType.DB,
            )
            .with_for_update()
            .one_or_none()
        )
        if None in (collection, membership, knowledge_base, document):
            raise SyncTargetChanged()

        source_config = self._source_config(document.meta_info)
        connection_id = self._connection_id(source_config.get("connection_id"))
        connection = (
            self.db.query(Connection)
            .filter(Connection.id == connection_id)
            .with_for_update()
            .one_or_none()
        )
        if (
            connection is None
            or connection.type != "postgres"
            or not has_active_organization_membership(
                self.db, connection.user_id, item.organization_id
            )
        ):
            raise SyncTargetConfigurationInvalid()
        self._validate_selections(source_config.get("selections"))

        try:
            result = DbProcessor(db_session=self.db, user_id=actor_id).process(
                source_config
            )
            error_code = result.metadata.get("error_code")
            if error_code == "configuration_invalid":
                raise SyncTargetConfigurationInvalid()
            if result.metadata.get("error") is not None:
                raise SyncTargetTemporarilyUnavailable()
            VectorStoreService(db=self.db, user_id=actor_id).save_chunks(
                document_id=document.id,
                chunks=result.chunks,
                model_name=knowledge_base.embedding_model
                or "text-embedding-3-small",
                commit=False,
                allow_empty_replace=True,
            )
        except (SyncTargetConfigurationInvalid, SyncTargetTemporarilyUnavailable):
            raise
        except RuntimeError as exc:
            if str(exc) == "DB sync vector store path is flat-only for MBA-85":
                raise SyncTargetConfigurationInvalid() from None
            raise SyncTargetTemporarilyUnavailable() from None
        except Exception:
            raise SyncTargetTemporarilyUnavailable() from None

        document.status = "completed"
        document.error_message = None
        document.updated_at = datetime.now(timezone.utc)

    @staticmethod
    def _connection_id(value: object) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except (AttributeError, TypeError, ValueError):
            raise SyncTargetConfigurationInvalid() from None

    @staticmethod
    def _source_config(meta_info: object) -> dict[str, Any]:
        if not isinstance(meta_info, dict):
            raise SyncTargetConfigurationInvalid()
        source_config = dict(meta_info)
        nested = source_config.get("db_config")
        if nested is not None:
            if not isinstance(nested, dict):
                raise SyncTargetConfigurationInvalid()
            source_config.update(nested)
        limit = source_config.get("limit", 1000)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise SyncTargetConfigurationInvalid()
        source_config["limit"] = min(limit, 1000)
        return source_config

    @staticmethod
    def _validate_selections(value: object) -> None:
        if not isinstance(value, list) or not 1 <= len(value) <= 2:
            raise SyncTargetConfigurationInvalid()
        for selection in value:
            if not isinstance(selection, dict):
                raise SyncTargetConfigurationInvalid()
            table_name = selection.get("table_name")
            columns = selection.get("columns")
            if not isinstance(table_name, str) or not table_name.strip():
                raise SyncTargetConfigurationInvalid()
            if columns is not None and (
                not isinstance(columns, list)
                or not columns
                or any(not isinstance(column, str) for column in columns)
            ):
                raise SyncTargetConfigurationInvalid()
