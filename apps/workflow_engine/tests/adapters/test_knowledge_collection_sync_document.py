from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import and_
from sqlalchemy.dialects import postgresql

from apps.shared.db.models.connection import Connection
from apps.shared.db.models.knowledge import (
    Document,
    KnowledgeBase,
    KnowledgeCollection,
    KnowledgeCollectionItem,
)
from apps.workflow_engine.adapters import knowledge_collection_sync_document as adapter_module
from apps.workflow_engine.adapters.knowledge_collection_sync_document import (
    SqlAlchemyKnowledgeCollectionSyncDocument,
)
from apps.workflow_engine.application.knowledge_collection_sync import (
    SyncTargetChanged,
    SyncTargetConfigurationInvalid,
    WorkerSyncItem,
)


class Query:
    def __init__(self, row) -> None:
        self.row = row
        self.criteria = []

    def filter(self, *args):
        self.criteria.extend(args)
        return self

    def with_for_update(self):
        return self

    def one_or_none(self):
        return self.row


class Db:
    def __init__(self, rows: dict[object, object]) -> None:
        self.rows = rows
        self.queries: dict[object, list[Query]] = {}
        self.events: list[str] = []

    def query(self, model):
        self.events.append(f"query:{getattr(model, '__name__', 'unknown')}")
        query = Query(self.rows.get(model))
        self.queries.setdefault(model, []).append(query)
        return query

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))


def _item() -> WorkerSyncItem:
    return WorkerSyncItem(
        item_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        collection_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        position=0,
        status="pending",
        attempt_count=0,
        max_attempts=3,
    )


def _rows(item: WorkerSyncItem):
    owner_id = uuid.uuid4()
    document = SimpleNamespace(
        id=item.document_id,
        meta_info={
            "db_config": {
                "connection_id": str(uuid.uuid4()),
                "selections": [{"table_name": "safe_table", "columns": ["id"]}],
                "limit": 5000,
            }
        },
        status="completed",
        error_message=None,
        updated_at=None,
    )
    return {
        KnowledgeCollection: SimpleNamespace(id=item.collection_id),
        KnowledgeCollectionItem: SimpleNamespace(id=uuid.uuid4()),
        KnowledgeBase: SimpleNamespace(
            id=item.knowledge_base_id,
            embedding_model="text-embedding-3-small",
        ),
        Document: document,
        Connection: SimpleNamespace(id=uuid.uuid4(), user_id=owner_id, type="postgres"),
    }


def test_document_adapter_clamps_limit_and_keeps_vector_commit_in_unit_of_work(
    monkeypatch,
) -> None:
    item = _item()
    rows = _rows(item)
    processor = Mock()
    processor.process.return_value = SimpleNamespace(chunks=[], metadata={})
    processor_class = Mock(return_value=processor)
    vector = Mock()
    vector_class = Mock(return_value=vector)
    monkeypatch.setattr(adapter_module, "DbProcessor", processor_class)
    monkeypatch.setattr(adapter_module, "VectorStoreService", vector_class)
    db = Db(rows)
    acquire_lock = Mock(side_effect=lambda *_args: db.events.append("advisory"))
    monkeypatch.setattr(adapter_module, "acquire_document_write_lock", acquire_lock)
    monkeypatch.setattr(
        adapter_module, "has_active_organization_membership", lambda *args: True
    )

    SqlAlchemyKnowledgeCollectionSyncDocument(db).sync(item, actor_id=uuid.uuid4())

    source_config = processor.process.call_args.args[0]
    acquire_lock.assert_called_once_with(db, item.document_id)
    assert db.events[0] == "advisory"
    collection_predicate = and_(*db.queries[KnowledgeCollection][0].criteria)
    compiled = collection_predicate.compile(dialect=postgresql.dialect())
    assert "sync_state" in str(compiled)
    assert "source_deleted" in compiled.params.values()
    assert source_config["limit"] == 1000
    assert rows[Document].meta_info["db_config"]["limit"] == 5000
    vector.save_chunks.assert_called_once_with(
        document_id=item.document_id,
        chunks=[],
        model_name="text-embedding-3-small",
        commit=False,
        allow_empty_replace=True,
    )


def test_connection_owner_outside_organization_fails_before_processor(
    monkeypatch,
) -> None:
    item = _item()
    rows = _rows(item)
    processor_class = Mock()
    monkeypatch.setattr(adapter_module, "DbProcessor", processor_class)
    monkeypatch.setattr(
        adapter_module, "has_active_organization_membership", lambda *args: False
    )

    with pytest.raises(SyncTargetConfigurationInvalid):
        SqlAlchemyKnowledgeCollectionSyncDocument(Db(rows)).sync(
            item, actor_id=uuid.uuid4()
        )

    processor_class.assert_not_called()


def test_unlinked_target_is_skipped_before_connection_lookup() -> None:
    item = _item()
    rows = _rows(item)
    rows[KnowledgeCollectionItem] = None

    with pytest.raises(SyncTargetChanged):
        SqlAlchemyKnowledgeCollectionSyncDocument(Db(rows)).sync(
            item, actor_id=uuid.uuid4()
        )
