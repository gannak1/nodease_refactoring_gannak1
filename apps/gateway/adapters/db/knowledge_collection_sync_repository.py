from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.gateway.application.knowledge_collection_sync.use_cases import (
    CollectionSyncCollectionSnapshot,
    CollectionSyncCommand,
    CollectionSyncJobSnapshot,
    CollectionSyncTarget,
    CollectionSyncTargetScan,
)
from apps.shared.db.models.knowledge import (
    Document,
    KnowledgeBase,
    KnowledgeCollection,
    KnowledgeCollectionItem,
    KnowledgeCollectionSyncJob,
    KnowledgeCollectionSyncJobItem,
    SourceType,
)
from apps.shared.domain.knowledge_collection_sync import (
    max_job_attempts_for_targets,
    sync_target_revision,
)
from apps.shared.services.knowledge_permission_service import KnowledgePermissionHelper
from apps.shared.services.permissions import (
    get_effective_knowledge_domain_actions,
    has_active_organization_membership,
    has_organization_manager_permission,
)


class SqlAlchemyCollectionSyncAuthorization:
    def __init__(self, db: Session) -> None:
        self.db = db

    def is_allowed(
        self,
        *,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        collection_id: uuid.UUID,
    ) -> bool:
        if not has_active_organization_membership(
            self.db, actor_id, organization_id
        ):
            return False
        if has_organization_manager_permission(self.db, actor_id, organization_id):
            return True
        if "sync_manage" in get_effective_knowledge_domain_actions(
            self.db, actor_id, organization_id
        ):
            return True
        collection = (
            self.db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.id == collection_id,
                KnowledgeCollection.organization_id == organization_id,
            )
            .first()
        )
        if collection is None:
            return False
        return KnowledgePermissionHelper(
            self.db,
            user_id=actor_id,
            organization_id=organization_id,
        ).evaluate_collection_action(
            collection, "sync", include_archived=True
        ).allowed


class SqlAlchemyCollectionSyncRepository:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._locked_collection: KnowledgeCollection | None = None

    def database_now(self) -> datetime:
        value = self.db.query(func.now()).scalar()
        return value or datetime.now(timezone.utc)

    def lock_collection(
        self, organization_id: uuid.UUID, collection_id: uuid.UUID
    ) -> CollectionSyncCollectionSnapshot | None:
        collection = (
            self.db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.id == collection_id,
                KnowledgeCollection.organization_id == organization_id,
            )
            .with_for_update()
            .first()
        )
        self._locked_collection = collection
        return self._collection_snapshot(collection)

    def get_collection(
        self, organization_id: uuid.UUID, collection_id: uuid.UUID
    ) -> CollectionSyncCollectionSnapshot | None:
        return self._collection_snapshot(
            self.db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.id == collection_id,
                KnowledgeCollection.organization_id == organization_id,
            )
            .first()
        )

    def find_by_request_hash(
        self,
        organization_id: uuid.UUID,
        collection_id: uuid.UUID,
        request_key_hash: str,
    ) -> CollectionSyncJobSnapshot | None:
        row = (
            self.db.query(KnowledgeCollectionSyncJob)
            .filter(
                KnowledgeCollectionSyncJob.organization_id == organization_id,
                KnowledgeCollectionSyncJob.collection_id == collection_id,
                KnowledgeCollectionSyncJob.request_key_hash == request_key_hash,
            )
            .with_for_update()
            .one_or_none()
        )
        return self._job_snapshot(row)

    def find_active(
        self, organization_id: uuid.UUID, collection_id: uuid.UUID
    ) -> CollectionSyncJobSnapshot | None:
        row = (
            self.db.query(KnowledgeCollectionSyncJob)
            .filter(
                KnowledgeCollectionSyncJob.organization_id == organization_id,
                KnowledgeCollectionSyncJob.collection_id == collection_id,
                KnowledgeCollectionSyncJob.status.in_(["queued", "running"]),
            )
            .with_for_update()
            .one_or_none()
        )
        return self._job_snapshot(row)

    def scan_targets(
        self,
        organization_id: uuid.UUID,
        collection_id: uuid.UUID,
        *,
        limit: int,
    ) -> CollectionSyncTargetScan:
        base_filters = (
            KnowledgeCollectionItem.organization_id == organization_id,
            KnowledgeCollectionItem.collection_id == collection_id,
            KnowledgeBase.organization_id == organization_id,
            KnowledgeBase.lifecycle_state == "active",
            KnowledgeBase.sync_state != "source_deleted",
        )
        has_source_managed = (
            self.db.query(KnowledgeCollectionItem.id)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeCollectionItem.knowledge_base_id)
            .filter(*base_filters, KnowledgeBase.source_identity_id.is_not(None))
            .first()
            is not None
        )
        has_api = (
            self.db.query(Document.id)
            .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
            .join(
                KnowledgeCollectionItem,
                KnowledgeCollectionItem.knowledge_base_id == KnowledgeBase.id,
            )
            .filter(
                *base_filters,
                KnowledgeBase.source_identity_id.is_(None),
                Document.source_type == SourceType.API,
            )
            .first()
            is not None
        )
        rows = (
            self.db.query(KnowledgeCollectionItem, KnowledgeBase, Document)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeCollectionItem.knowledge_base_id)
            .join(Document, Document.knowledge_base_id == KnowledgeBase.id)
            .filter(
                *base_filters,
                KnowledgeBase.source_identity_id.is_(None),
                Document.source_type == SourceType.DB,
            )
            .order_by(
                KnowledgeCollectionItem.rank.asc(),
                KnowledgeCollectionItem.created_at.asc(),
                KnowledgeBase.id.asc(),
                Document.id.asc(),
            )
            .limit(limit)
            .all()
        )
        targets = tuple(
            CollectionSyncTarget(
                collection_item_id=item.id,
                knowledge_base_id=kb.id,
                document_id=document.id,
                item_rank=item.rank,
                item_created_at=item.created_at,
                document_updated_at=document.updated_at,
            )
            for item, kb, document in rows
        )
        return CollectionSyncTargetScan(
            targets=targets,
            has_source_managed_child=has_source_managed,
            has_api_document=has_api,
            exceeds_limit=len(rows) >= limit,
        )

    def create_job(
        self,
        *,
        command: CollectionSyncCommand,
        request_key_hash: str,
        target_snapshot_revision: str,
        previous_sync_state: str,
        targets: tuple[CollectionSyncTarget, ...] | list[CollectionSyncTarget],
        now: datetime,
        execution_deadline_at: datetime,
    ) -> CollectionSyncJobSnapshot:
        job = KnowledgeCollectionSyncJob(
            id=uuid.uuid4(),
            organization_id=command.organization_id,
            collection_id=command.collection_id,
            requested_by=command.actor_id,
            request_key_hash=request_key_hash,
            target_snapshot_revision=target_snapshot_revision,
            previous_sync_state=previous_sync_state,
            status="queued",
            total_count=len(targets),
            max_attempts=max_job_attempts_for_targets(len(targets)),
            next_retry_at=now,
            execution_deadline_at=execution_deadline_at,
            requested_at=now,
            updated_at=now,
        )
        self.db.add(job)
        self.db.flush()
        for position, target in enumerate(targets):
            self.db.add(
                KnowledgeCollectionSyncJobItem(
                    id=uuid.uuid4(),
                    organization_id=command.organization_id,
                    job_id=job.id,
                    collection_id=command.collection_id,
                    knowledge_base_id=target.knowledge_base_id,
                    document_id=target.document_id,
                    position=position,
                    target_revision=sync_target_revision(
                        collection_id=command.collection_id,
                        collection_item_id=target.collection_item_id,
                        knowledge_base_id=target.knowledge_base_id,
                        document_id=target.document_id,
                        item_rank=target.item_rank,
                        item_created_at=target.item_created_at,
                        document_updated_at=target.document_updated_at,
                    ),
                    status="pending",
                    created_at=now,
                    updated_at=now,
                )
            )
        self.db.flush()
        return self._job_snapshot(job)  # type: ignore[return-value]

    def set_collection_sync_state(
        self,
        organization_id: uuid.UUID,
        collection_id: uuid.UUID,
        sync_state: str,
        *,
        now: datetime,
    ) -> None:
        collection = self._locked_collection
        if (
            collection is None
            or collection.id != collection_id
            or collection.organization_id != organization_id
        ):
            raise RuntimeError("collection must be locked before sync mutation")
        collection.sync_state = sync_state
        collection.updated_at = now

    def latest_job(
        self, organization_id: uuid.UUID, collection_id: uuid.UUID
    ) -> CollectionSyncJobSnapshot | None:
        row = (
            self.db.query(KnowledgeCollectionSyncJob)
            .filter(
                KnowledgeCollectionSyncJob.organization_id == organization_id,
                KnowledgeCollectionSyncJob.collection_id == collection_id,
            )
            .order_by(
                KnowledgeCollectionSyncJob.requested_at.desc(),
                KnowledgeCollectionSyncJob.id.desc(),
            )
            .first()
        )
        return self._job_snapshot(row)

    def get_job(
        self,
        organization_id: uuid.UUID,
        collection_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> CollectionSyncJobSnapshot | None:
        return self._job_snapshot(
            self.db.query(KnowledgeCollectionSyncJob)
            .filter(
                KnowledgeCollectionSyncJob.id == job_id,
                KnowledgeCollectionSyncJob.organization_id == organization_id,
                KnowledgeCollectionSyncJob.collection_id == collection_id,
            )
            .first()
        )

    @staticmethod
    def _collection_snapshot(
        row: KnowledgeCollection | None,
    ) -> CollectionSyncCollectionSnapshot | None:
        if row is None:
            return None
        return CollectionSyncCollectionSnapshot(
            collection_id=row.id,
            lifecycle_state=row.lifecycle_state,
            sync_state=row.sync_state,
            is_system_managed=row.is_system_managed,
            is_source_managed=(
                row.source_identity_id is not None or bool(row.source_connector_ref)
            ),
        )

    @staticmethod
    def _job_snapshot(
        row: KnowledgeCollectionSyncJob | None,
    ) -> CollectionSyncJobSnapshot | None:
        if row is None:
            return None
        return CollectionSyncJobSnapshot(
            job_id=row.id,
            collection_id=row.collection_id,
            status=row.status,
            total_count=row.total_count,
            completed_count=row.completed_count,
            failed_count=row.failed_count,
            skipped_count=row.skipped_count,
            retryable=row.retryable,
            safe_reason_code=row.safe_reason_code,
            requested_at=row.requested_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )
