import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.gateway.services.ingestion.service import IngestionOrchestrator
from apps.shared.db.models.knowledge import Document, DocumentVersion, KnowledgeBase
from apps.shared.services.knowledge_ingestion_finalizer import (
    KnowledgeIngestionFinalizationError,
    KnowledgeIngestionFinalizer,
)
from apps.shared.services.knowledge_ingestion_outbox import (
    OUTBOX_STATUS_DEAD_LETTERED,
    OUTBOX_STATUS_LEASED,
    OUTBOX_STATUS_RETRY_SCHEDULED,
    OUTBOX_STATUS_SUCCEEDED,
    KnowledgeIngestionOutboxService,
)
from apps.shared.services.knowledge_sync_cursor import (
    KnowledgeSyncCursorError,
    KnowledgeSyncCursorService,
)


ORG_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
KB_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
DOC_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
NEW_VERSION_ID = uuid.UUID("40000000-0000-0000-0000-000000000001")
OLD_VERSION_ID = uuid.UUID("50000000-0000-0000-0000-000000000001")


class FakeDb:
    def __init__(
        self,
        *,
        legacy_document=None,
        previous_version=None,
        kb=None,
        max_version_number=0,
    ):
        self.legacy_document = legacy_document
        self.previous_version = previous_version
        self.kb = kb
        self.max_version_number = max_version_number
        self.added = []
        self.flush_count = 0

    def get(self, model, value):
        if model is Document and value == DOC_ID:
            return self.legacy_document
        if model is DocumentVersion and value == OLD_VERSION_ID:
            return self.previous_version
        if model is KnowledgeBase and self.kb and value == self.kb.id:
            return self.kb
        return None

    def query(self, *args):
        return FakeScalarQuery(self.max_version_number)

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flush_count += 1


class FakeScalarQuery:
    def __init__(self, value):
        self.value = value

    def filter(self, *args):
        return self

    def scalar(self):
        return self.value


class FakeFinalizer(KnowledgeIngestionFinalizer):
    def __init__(
        self,
        db,
        *,
        kb,
        version,
        previous_version=None,
        chunk_count=3,
        deleted_legacy_count=0,
    ):
        super().__init__(db)
        self.kb = kb
        self.version = version
        self.previous_version = previous_version
        self.chunk_count = chunk_count
        self.deleted_legacy_count = deleted_legacy_count
        self.enqueued = []

    def _lock_document_version(self, document_version_id):
        assert document_version_id == self.version.id
        return self.version

    def _lock_knowledge_base(self, knowledge_base_id):
        assert knowledge_base_id == self.kb.id
        return self.kb

    def _previous_active_version(self, previous_version_id):
        assert previous_version_id == OLD_VERSION_ID
        return self.previous_version

    def _version_chunk_count(self, document_version_id):
        assert document_version_id == self.version.id
        return self.chunk_count

    def _delete_legacy_unversioned_chunks(self, version):
        assert version.id == self.version.id
        return self.deleted_legacy_count

    def _lock_legacy_document(self, legacy_document_id):
        return self.db.get(Document, legacy_document_id)

    def _enqueue_cleanup_event(
        self, *, version, previous_version_id, deleted_legacy_chunk_count
    ):
        event = SimpleNamespace(id=uuid.uuid4())
        self.enqueued.append(
            {
                "version_id": version.id,
                "previous_version_id": previous_version_id,
                "deleted_legacy_chunk_count": deleted_legacy_chunk_count,
            }
        )
        return event


def _version(status="indexing"):
    return SimpleNamespace(
        id=NEW_VERSION_ID,
        organization_id=ORG_ID,
        knowledge_base_id=KB_ID,
        legacy_document_id=DOC_ID,
        source_identity_id=None,
        status=status,
        content_hash="new-content-hash",
        embedding_model="text-embedding-3-small",
        safe_metadata={},
        ready_at=None,
        error_code="old-error",
        updated_at=None,
    )


def test_finalizer_swaps_active_version_and_supersedes_previous_in_one_boundary():
    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    kb = SimpleNamespace(id=KB_ID, active_document_version_id=OLD_VERSION_ID)
    previous = SimpleNamespace(
        id=OLD_VERSION_ID,
        status="ready",
        superseded_at=None,
        updated_at=None,
    )
    legacy_document = SimpleNamespace(
        id=DOC_ID,
        content_hash="old-content-hash",
        embedding_model="old-model",
        updated_at=None,
    )
    db = FakeDb(legacy_document=legacy_document, previous_version=previous, kb=kb)
    finalizer = FakeFinalizer(
        db,
        kb=kb,
        version=_version(),
        previous_version=previous,
        chunk_count=7,
        deleted_legacy_count=2,
    )

    result = finalizer.finalize_active_version(finalizer.version, now=now)

    assert kb.active_document_version_id == NEW_VERSION_ID
    assert finalizer.version.status == "ready"
    assert finalizer.version.ready_at == now
    assert finalizer.version.error_code is None
    assert previous.status == "superseded"
    assert previous.superseded_at == now
    assert legacy_document.content_hash == "new-content-hash"
    assert legacy_document.embedding_model == "text-embedding-3-small"
    assert result.previous_document_version_id == OLD_VERSION_ID
    assert result.chunk_count == 7
    assert result.deleted_legacy_chunk_count == 2
    assert finalizer.enqueued == [
        {
            "version_id": NEW_VERSION_ID,
            "previous_version_id": OLD_VERSION_ID,
            "deleted_legacy_chunk_count": 2,
        }
    ]
    assert db.flush_count == 1


def test_finalizer_refuses_empty_version_without_changing_active_pointer():
    kb = SimpleNamespace(id=KB_ID, active_document_version_id=OLD_VERSION_ID)
    version = _version()
    finalizer = FakeFinalizer(
        FakeDb(kb=kb),
        kb=kb,
        version=version,
        chunk_count=0,
    )

    with pytest.raises(KnowledgeIngestionFinalizationError):
        finalizer.finalize_active_version(version)

    assert kb.active_document_version_id == OLD_VERSION_ID
    assert version.status == "indexing"
    assert finalizer.enqueued == []


def test_finalizer_rejects_stale_worker_fencing_token():
    token_a = "worker-a-token"
    token_b = "worker-b-token"
    kb = SimpleNamespace(id=KB_ID, active_document_version_id=OLD_VERSION_ID)
    legacy_document = SimpleNamespace(
        id=DOC_ID,
        content_hash="old-content-hash",
        embedding_model="old-model",
        meta_info={},
        updated_at=None,
    )
    db = FakeDb(legacy_document=legacy_document, kb=kb)
    version = _version()
    finalizer = FakeFinalizer(db, kb=kb, version=version)
    version.safe_metadata = {
        "ingestion_fencing_token_hash": finalizer._hash_fencing_token(token_a)
    }
    legacy_document.meta_info = {
        "active_ingestion_fencing_token_hash": finalizer._hash_fencing_token(token_b)
    }

    with pytest.raises(KnowledgeIngestionFinalizationError):
        finalizer.finalize_active_version(version, expected_fencing_token=token_a)

    assert kb.active_document_version_id == OLD_VERSION_ID
    assert version.status == "indexing"
    assert finalizer.enqueued == []


def test_finalizer_clears_fencing_hash_after_successful_finalize():
    token = "worker-token"
    kb = SimpleNamespace(id=KB_ID, active_document_version_id=None)
    legacy_document = SimpleNamespace(
        id=DOC_ID,
        content_hash="old-content-hash",
        embedding_model="old-model",
        meta_info={},
        updated_at=None,
    )
    db = FakeDb(legacy_document=legacy_document, kb=kb)
    version = _version()
    finalizer = FakeFinalizer(db, kb=kb, version=version, chunk_count=1)
    token_hash = finalizer._hash_fencing_token(token)
    version.safe_metadata = {"ingestion_fencing_token_hash": token_hash}
    legacy_document.meta_info = {"active_ingestion_fencing_token_hash": token_hash}

    finalizer.finalize_active_version(version, expected_fencing_token=token)

    assert kb.active_document_version_id == NEW_VERSION_ID
    assert "active_ingestion_fencing_token_hash" not in legacy_document.meta_info


def test_failed_indexing_version_is_recorded_after_rollback_context():
    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    token = "worker-token"
    kb = SimpleNamespace(id=KB_ID, organization_id=ORG_ID)
    db = FakeDb(kb=kb, max_version_number=4)
    finalizer = KnowledgeIngestionFinalizer(db)

    version = finalizer.record_failed_indexing_version(
        organization_id=ORG_ID,
        knowledge_base_id=KB_ID,
        legacy_document_id=DOC_ID,
        source_identity_id=None,
        content_hash="hash-after-extract",
        chunking_fingerprint="fingerprint-v1",
        embedding_model="text-embedding-3-small",
        safe_reason_code="ingestion.processing_failed",
        safe_metadata={"source_type": "FILE"},
        fencing_token=token,
        now=now,
    )

    assert version.status == "failed"
    assert version.version_number == 5
    assert version.error_code == "ingestion.processing_failed"
    assert version.content_hash == "hash-after-extract"
    assert version.updated_at == now
    assert version.safe_metadata["source_type"] == "FILE"
    assert token not in str(version.safe_metadata)
    assert "ingestion_fencing_token_hash" in version.safe_metadata
    assert db.added == [version]
    assert db.flush_count == 1


def test_outbox_retry_and_dead_letter_status_are_explicit():
    service = KnowledgeIngestionOutboxService(SimpleNamespace())
    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    retry_event = SimpleNamespace(
        retryable=True,
        attempt_count=1,
        max_attempts=3,
        owner_token="worker",
        fencing_token="fence",
        lease_expires_at=now,
        safe_reason_code=None,
        status="leased",
        next_retry_at=None,
        dead_lettered_at=None,
        updated_at=None,
    )
    dead_letter_event = SimpleNamespace(
        retryable=True,
        attempt_count=3,
        max_attempts=3,
        owner_token="worker",
        fencing_token="fence",
        lease_expires_at=now,
        safe_reason_code=None,
        status="leased",
        next_retry_at=None,
        dead_lettered_at=None,
        updated_at=None,
    )

    service.mark_retry_or_dead_letter(
        retry_event,
        safe_reason_code="outbox.processing_failed",
        now=now,
    )
    service.mark_retry_or_dead_letter(
        dead_letter_event,
        safe_reason_code="outbox.processing_failed",
        now=now,
    )

    assert retry_event.status == OUTBOX_STATUS_RETRY_SCHEDULED
    assert retry_event.owner_token is None
    assert retry_event.fencing_token is None
    assert retry_event.lease_expires_at is None
    assert retry_event.next_retry_at is not None
    assert dead_letter_event.status == OUTBOX_STATUS_DEAD_LETTERED
    assert dead_letter_event.dead_lettered_at == now


class FakeOutboxQuery:
    def __init__(self, rows):
        self.rows = rows
        self.skip_locked = None
        self.limit_value = None

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def with_for_update(self, **kwargs):
        self.skip_locked = kwargs.get("skip_locked")
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        return self.rows[: self.limit_value]


class FakeOutboxDb:
    def __init__(self, rows):
        self.query_obj = FakeOutboxQuery(rows)
        self.flush_count = 0

    def query(self, *args):
        return self.query_obj

    def flush(self):
        self.flush_count += 1


def test_outbox_lease_uses_skip_locked_and_sets_owner_fields():
    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    row = SimpleNamespace(
        status="pending",
        owner_token=None,
        fencing_token=None,
        lease_expires_at=None,
        attempt_count=0,
        updated_at=None,
    )
    db = FakeOutboxDb([row])
    service = KnowledgeIngestionOutboxService(db)

    leased = service.lease_due_events(
        owner_token="worker-1",
        limit=1,
        lease_seconds=30,
        now=now,
    )

    assert leased == [row]
    assert db.query_obj.skip_locked is True
    assert db.query_obj.limit_value == 1
    assert row.status == OUTBOX_STATUS_LEASED
    assert row.owner_token == "worker-1"
    assert row.fencing_token
    assert row.lease_expires_at == now + timedelta(seconds=30)
    assert row.attempt_count == 1
    assert db.flush_count == 1


def test_outbox_recovery_moves_expired_lease_to_retry_or_dead_letter():
    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    row = SimpleNamespace(
        status=OUTBOX_STATUS_LEASED,
        owner_token="worker",
        fencing_token="fence",
        lease_expires_at=now - timedelta(seconds=1),
        retryable=True,
        attempt_count=5,
        max_attempts=5,
        next_retry_at=None,
        safe_reason_code=None,
        dead_lettered_at=None,
        updated_at=None,
    )
    db = FakeOutboxDb([row])
    service = KnowledgeIngestionOutboxService(db)

    recovered_count = service.recover_stale_leases(now=now)

    assert recovered_count == 1
    assert row.status == OUTBOX_STATUS_DEAD_LETTERED
    assert row.owner_token is None
    assert row.fencing_token is None
    assert row.lease_expires_at is None
    assert row.safe_reason_code == "outbox.lease_expired"
    assert row.dead_lettered_at == now
    assert db.flush_count == 1


@pytest.mark.parametrize("limit", [0, -1, 5001, "not-a-number", None])
def test_outbox_limit_validation_rejects_invalid_values(limit):
    with pytest.raises(ValueError):
        KnowledgeIngestionOutboxService.validate_limit(limit)


def test_cleanup_superseded_event_refuses_active_version_deletion():
    previous = SimpleNamespace(
        id=OLD_VERSION_ID,
        knowledge_base_id=KB_ID,
        status="superseded",
    )
    kb = SimpleNamespace(id=KB_ID, active_document_version_id=OLD_VERSION_ID)
    event = SimpleNamespace(
        target_ref={"previous_document_version_id": str(OLD_VERSION_ID)}
    )
    service = KnowledgeIngestionOutboxService(
        FakeDb(previous_version=previous, kb=kb)
    )

    with pytest.raises(RuntimeError):
        service.process_cleanup_superseded_event(event)


def test_cleanup_superseded_event_succeeds_when_previous_version_is_missing():
    event = SimpleNamespace(
        target_ref={"previous_document_version_id": str(OLD_VERSION_ID)},
        status="leased",
        owner_token="worker",
        fencing_token="fence",
        lease_expires_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
        next_retry_at=None,
        safe_reason_code="old",
        safe_metadata={},
        updated_at=None,
    )
    service = KnowledgeIngestionOutboxService(FakeDb())

    deleted_count = service.process_cleanup_superseded_event(event)

    assert deleted_count == 0
    assert event.status == OUTBOX_STATUS_SUCCEEDED
    assert event.safe_metadata["version_missing"] is True


def test_cleanup_superseded_event_is_noop_for_non_superseded_version():
    previous = SimpleNamespace(
        id=OLD_VERSION_ID,
        knowledge_base_id=KB_ID,
        status="ready",
    )
    kb = SimpleNamespace(id=KB_ID, active_document_version_id=NEW_VERSION_ID)
    event = SimpleNamespace(
        target_ref={"previous_document_version_id": str(OLD_VERSION_ID)},
        status="leased",
        owner_token="worker",
        fencing_token="fence",
        lease_expires_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
        next_retry_at=None,
        safe_reason_code="old",
        safe_metadata={},
        updated_at=None,
    )
    service = KnowledgeIngestionOutboxService(
        FakeDb(previous_version=previous, kb=kb)
    )

    deleted_count = service.process_cleanup_superseded_event(event)

    assert deleted_count == 0
    assert event.status == OUTBOX_STATUS_SUCCEEDED
    assert event.safe_metadata["version_status"] == "ready"


def test_content_cursor_advances_only_after_active_ready_version():
    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    kb = SimpleNamespace(id=KB_ID, active_document_version_id=NEW_VERSION_ID)
    version = SimpleNamespace(
        id=NEW_VERSION_ID,
        knowledge_base_id=KB_ID,
        status="ready",
    )
    source_identity = SimpleNamespace(safe_metadata={}, updated_at=None)
    db = FakeDb(kb=kb)
    service = KnowledgeSyncCursorService(db)

    service.advance_content_cursor_after_finalization(
        source_identity=source_identity,
        document_version=version,
        content_cursor_ref="cursor-ref-v2",
        now=now,
    )

    assert source_identity.safe_metadata["sync_refs"] == {
        "content_cursor_ref": "cursor-ref-v2",
        "content_document_version_id": str(NEW_VERSION_ID),
        "content_committed_at": now.isoformat(),
    }
    assert db.flush_count == 1


def test_content_cursor_refuses_unready_or_inactive_version():
    kb = SimpleNamespace(id=KB_ID, active_document_version_id=OLD_VERSION_ID)
    version = SimpleNamespace(
        id=NEW_VERSION_ID,
        knowledge_base_id=KB_ID,
        status="indexing",
    )
    service = KnowledgeSyncCursorService(FakeDb(kb=kb))

    with pytest.raises(KnowledgeSyncCursorError):
        service.advance_content_cursor_after_finalization(
            source_identity=SimpleNamespace(safe_metadata={}),
            document_version=version,
            content_cursor_ref="cursor-ref-v2",
        )


def test_acl_watermark_advances_independently_from_content_cursor():
    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    source_identity = SimpleNamespace(
        safe_metadata={
            "sync_refs": {
                "content_cursor_ref": "cursor-ref-v2",
                "content_document_version_id": str(NEW_VERSION_ID),
            }
        },
        updated_at=None,
    )
    service = KnowledgeSyncCursorService(FakeDb())

    service.advance_acl_watermark_after_permission_commit(
        source_identity=source_identity,
        acl_watermark_ref="acl-ref-7",
        freshness_epoch=7,
        candidate_cache_epoch=3,
        now=now,
    )

    assert source_identity.safe_metadata["sync_refs"]["content_cursor_ref"] == (
        "cursor-ref-v2"
    )
    assert source_identity.safe_metadata["sync_refs"]["acl_watermark_ref"] == (
        "acl-ref-7"
    )
    assert source_identity.safe_metadata["sync_refs"]["acl_freshness_epoch"] == 7
    assert source_identity.safe_metadata["sync_refs"]["candidate_cache_epoch"] == 3


def test_ingestion_error_message_does_not_store_raw_exception_detail():
    orchestrator = IngestionOrchestrator(db=SimpleNamespace())

    assert orchestrator._safe_ingestion_error_message(
        RuntimeError("postgres://internal-host/secret-table")
    ) == "문서 처리에 실패했습니다."
    assert orchestrator._safe_ingestion_error_message(
        KnowledgeIngestionFinalizationError("version_has_no_chunks")
    ) == "문서 색인 최종화에 실패했습니다."
