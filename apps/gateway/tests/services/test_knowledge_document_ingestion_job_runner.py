from types import SimpleNamespace
from uuid import uuid4

import pytest
from billiard.exceptions import SoftTimeLimitExceeded

from apps.gateway.application.knowledge_document_ingestion.worker import (
    DocumentIngestionRetryableFailure,
    WorkerDocumentIngestionJob,
)
from apps.gateway.services.ingestion import job_runner
from apps.gateway.services.ingestion.job_runner import (
    KnowledgeDocumentIngestionJobRunner,
)
from apps.gateway.services.ingestion.service import DurableIngestionSourceFailure
from apps.shared.db.models.knowledge import Document, KnowledgeBase


class FakeSession:
    def __init__(self, document, knowledge_base) -> None:
        self.document = document
        self.knowledge_base = knowledge_base
        self.closed = False

    def get(self, model, _identifier):
        if model is Document:
            return self.document
        if model is KnowledgeBase:
            return self.knowledge_base
        raise AssertionError(f"unexpected model: {model}")

    def close(self):
        self.closed = True


def test_soft_time_limit_is_retryable_timeout(monkeypatch) -> None:
    organization_id = uuid4()
    knowledge_base_id = uuid4()
    document_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        knowledge_base_id=knowledge_base_id,
        chunk_size=800,
        chunk_overlap=80,
    )
    knowledge_base = SimpleNamespace(
        id=knowledge_base_id,
        organization_id=organization_id,
        lifecycle_state="active",
        sync_state="active",
        embedding_model="text-embedding-3-small",
    )
    sessions: list[FakeSession] = []

    def session_factory():
        session = FakeSession(document, knowledge_base)
        sessions.append(session)
        return session

    monkeypatch.setattr(
        job_runner.IngestionOrchestrator,
        "process_document_for_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SoftTimeLimitExceeded()),
    )
    job = WorkerDocumentIngestionJob(
        job_id=uuid4(),
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        requested_by_user_id=uuid4(),
        operation="process",
        generation=1,
        status="running",
        attempt_count=1,
        max_attempts=3,
        retryable=True,
        owner_token="owner-token",
        fencing_token="fencing-token",
        lease_expires_at=None,
        next_retry_at=None,
    )

    with pytest.raises(DocumentIngestionRetryableFailure) as exc_info:
        KnowledgeDocumentIngestionJobRunner(
            session_factory,
            heartbeat_seconds=60,
        ).run(job)

    assert exc_info.value.reason_code == "ingestion.timeout"
    assert sessions[-1].closed is True


def test_temporary_source_failure_is_retryable(monkeypatch) -> None:
    organization_id = uuid4()
    knowledge_base_id = uuid4()
    document_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        knowledge_base_id=knowledge_base_id,
        chunk_size=800,
        chunk_overlap=80,
    )
    knowledge_base = SimpleNamespace(
        id=knowledge_base_id,
        organization_id=organization_id,
        lifecycle_state="active",
        sync_state="active",
        embedding_model="text-embedding-3-small",
    )

    def session_factory():
        return FakeSession(document, knowledge_base)

    monkeypatch.setattr(
        job_runner.IngestionOrchestrator,
        "process_document_for_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DurableIngestionSourceFailure("source.temporarily_unavailable")
        ),
    )
    job = WorkerDocumentIngestionJob(
        job_id=uuid4(),
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        requested_by_user_id=uuid4(),
        operation="process",
        generation=1,
        status="running",
        attempt_count=1,
        max_attempts=3,
        retryable=True,
        owner_token="owner-token",
        fencing_token="fencing-token",
        lease_expires_at=None,
        next_retry_at=None,
    )

    with pytest.raises(DocumentIngestionRetryableFailure) as raised:
        KnowledgeDocumentIngestionJobRunner(
            session_factory,
            heartbeat_seconds=60,
        ).run(job)

    assert raised.value.reason_code == "ingestion.source_temporarily_unavailable"
