from types import SimpleNamespace

import pytest

from apps.gateway.services.ingestion.service import (
    DurableIngestionLeaseLost,
    DurableIngestionSourceFailure,
    IngestionOrchestrator,
)
from apps.shared.db.models.knowledge import Document, KnowledgeBase
from apps.shared.services.ingestion.processors.base import ProcessingResult
from apps.shared.services.knowledge_ingestion_fencing import (
    ACTIVE_FENCING_TOKEN_HASH_KEY,
)


class FakeQuery:
    def __init__(self, document) -> None:
        self.document = document

    def get(self, _document_id):
        return self.document


class FakeDb:
    def __init__(self, document) -> None:
        self.document = document
        self.flushes = 0

    def query(self, _model):
        return FakeQuery(self.document)

    def flush(self):
        self.flushes += 1


class LockOrderQuery:
    def __init__(self, db, target) -> None:
        self.db = db
        self.target = target

    def filter(self, *_criteria):
        return self

    def scalar(self):
        return self.db.knowledge_base.id

    def with_for_update(self):
        self.db.locked_models.append(self.target)
        return self

    def one_or_none(self):
        if self.target is KnowledgeBase:
            return self.db.knowledge_base
        if self.target is Document:
            return self.db.document
        raise AssertionError(f"unexpected lock target: {self.target}")


class LockOrderDb:
    def __init__(self) -> None:
        self.knowledge_base = SimpleNamespace(id="knowledge-base-id")
        self.document = SimpleNamespace(id="document-id")
        self.locked_models = []

    def query(self, target):
        return LockOrderQuery(self, target)


def test_mark_indexing_persists_fencing_before_progress(monkeypatch) -> None:
    service = IngestionOrchestrator(SimpleNamespace())
    events: list[str] = []
    monkeypatch.setattr(
        service,
        "_update_status",
        lambda *_args, **_kwargs: events.append("status"),
    )
    monkeypatch.setattr(
        service,
        "_update_progress_redis",
        lambda *_args, **_kwargs: events.append("progress"),
    )

    service._mark_document_indexing("document-id", "fencing-token", commit=False)

    assert events == ["status", "progress"]


def test_durable_processing_locks_knowledge_base_before_document() -> None:
    db = LockOrderDb()
    service = IngestionOrchestrator(db, organization_id="organization-id")

    document = service._lock_durable_document_scope("document-id")

    assert document is db.document
    assert db.locked_models == [KnowledgeBase, Document]


def test_stale_attempt_is_rejected_before_redis_progress_write(monkeypatch) -> None:
    document = SimpleNamespace(
        status="indexing",
        meta_info={ACTIVE_FENCING_TOKEN_HASH_KEY: "different-owner"},
    )
    service = IngestionOrchestrator(FakeDb(document))
    service._durable_job_mode = True
    service._active_progress_fencing_token = "current-attempt"
    redis_requested = False

    def get_redis_client():
        nonlocal redis_requested
        redis_requested = True
        return SimpleNamespace()

    monkeypatch.setattr("apps.shared.pubsub.get_redis_client", get_redis_client)

    with pytest.raises(DurableIngestionLeaseLost):
        service._update_progress_redis("document-id", 80)

    assert redis_requested is False


def test_post_commit_completion_only_publishes_advisory_redis_progress(
    monkeypatch,
) -> None:
    service = IngestionOrchestrator(SimpleNamespace())
    service._durable_job_mode = True
    service._active_progress_fencing_token = "already-finalized-attempt"
    redis_calls: list[tuple[str, str, int]] = []

    monkeypatch.setattr(
        service,
        "_update_progress_metadata",
        lambda *_args, **_kwargs: pytest.fail(
            "post-commit notification must not open a second DB progress transaction"
        ),
    )
    monkeypatch.setattr(
        "apps.shared.pubsub.get_redis_client",
        lambda: SimpleNamespace(
            set=lambda key, value, ex: redis_calls.append((key, value, ex))
        ),
    )

    service._update_progress_redis(
        "document-id",
        100,
        expire=True,
        persist_metadata=False,
    )

    assert redis_calls == [("knowledge_progress:document-id", "100", 30)]


def test_processor_reason_is_normalized_to_typed_durable_source_failure(
    monkeypatch,
) -> None:
    processor = SimpleNamespace(
        process=lambda _config: ProcessingResult(
            chunks=[],
            metadata={
                "error": "safe processor error",
                "reason_code": "source.temporarily_unavailable",
            },
        )
    )
    monkeypatch.setattr(
        "apps.gateway.services.ingestion.service.IngestionFactory.get_processor",
        lambda *_args, **_kwargs: processor,
    )
    service = IngestionOrchestrator(SimpleNamespace())
    monkeypatch.setattr(service, "_build_config", lambda _document: {})

    with pytest.raises(DurableIngestionSourceFailure) as raised:
        service._extract_raw_blocks(SimpleNamespace(source_type="DB"))

    assert raised.value.reason_code == "source.temporarily_unavailable"


def test_unknown_processor_reason_fails_closed() -> None:
    error = DurableIngestionSourceFailure("raw.provider.detail")

    assert error.reason_code == "processing.failed"
    assert str(error) == "Source processing failed."
