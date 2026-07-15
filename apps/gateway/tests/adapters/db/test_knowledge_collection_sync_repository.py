from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from apps.gateway.adapters.db.knowledge_collection_sync_repository import (
    SqlAlchemyCollectionSyncRepository,
)
from apps.gateway.application.knowledge_collection_sync.use_cases import (
    CollectionSyncCommand,
    CollectionSyncTarget,
)
from apps.shared.db.models.knowledge import KnowledgeCollectionSyncJobItem
from apps.shared.domain.knowledge_collection_sync import sync_target_revision


class FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        return None


class CapturingRepository(SqlAlchemyCollectionSyncRepository):
    @staticmethod
    def _job_snapshot(row):
        return row


def test_create_job_persists_each_target_revision() -> None:
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    command = CollectionSyncCommand(
        actor_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        collection_id=uuid.uuid4(),
        idempotency_key=uuid.uuid4(),
    )
    target = CollectionSyncTarget(
        collection_item_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        item_rank=3,
        item_created_at=now - timedelta(days=1),
        document_updated_at=now - timedelta(minutes=1),
    )
    db = FakeDb()

    CapturingRepository(db).create_job(
        command=command,
        request_key_hash="a" * 64,
        target_snapshot_revision="b" * 64,
        previous_sync_state="manual",
        targets=(target,),
        now=now,
        execution_deadline_at=now + timedelta(minutes=30),
    )

    item = next(
        value
        for value in db.added
        if isinstance(value, KnowledgeCollectionSyncJobItem)
    )
    assert item.target_revision == sync_target_revision(
        collection_id=command.collection_id,
        collection_item_id=target.collection_item_id,
        knowledge_base_id=target.knowledge_base_id,
        document_id=target.document_id,
        item_rank=target.item_rank,
        item_created_at=target.item_created_at,
        document_updated_at=target.document_updated_at,
    )
