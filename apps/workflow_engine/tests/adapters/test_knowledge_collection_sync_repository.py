from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy import and_
from sqlalchemy.dialects import postgresql

from apps.workflow_engine.adapters.knowledge_collection_sync_repository import (
    SqlAlchemyWorkerSyncRepository,
)
from apps.workflow_engine.application.knowledge_collection_sync import WorkerSyncJob


def test_supported_collection_query_excludes_source_deleted_state() -> None:
    db = Mock()
    query = Mock()
    db.query.return_value = query
    query.filter.return_value = query
    query.first.return_value = (uuid4(),)
    now = datetime.now(timezone.utc)
    job = WorkerSyncJob(
        job_id=uuid4(),
        organization_id=uuid4(),
        collection_id=uuid4(),
        requested_by=uuid4(),
        total_count=1,
        status="queued",
        previous_sync_state="manual",
        attempt_count=0,
        max_attempts=8,
        lease_owner=None,
        lease_expires_at=None,
        next_retry_at=now,
        execution_deadline_at=now + timedelta(minutes=30),
        started_at=None,
    )

    assert SqlAlchemyWorkerSyncRepository(db).collection_is_supported(job) is True

    predicate = and_(*query.filter.call_args.args)
    compiled = predicate.compile(dialect=postgresql.dialect())
    assert "organization_id" in str(compiled)
    assert "sync_state" in str(compiled)
    assert "source_deleted" in compiled.params.values()


def test_collection_state_projection_does_not_overwrite_source_deleted() -> None:
    collection = SimpleNamespace(sync_state="source_deleted", updated_at=None)
    query = Mock()
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.one_or_none.return_value = collection
    db = Mock()
    db.query.return_value = query
    job_row = SimpleNamespace(
        collection_id=uuid4(),
        organization_id=uuid4(),
    )
    now = datetime.now(timezone.utc)

    SqlAlchemyWorkerSyncRepository(db)._set_collection_state(  # noqa: SLF001
        job_row,
        "synced",
        now=now,
    )

    assert collection.sync_state == "source_deleted"
    assert collection.updated_at is None


def test_finalize_job_persists_reconciled_snapshot_counts() -> None:
    now = datetime.now(timezone.utc)
    job = WorkerSyncJob(
        job_id=uuid4(),
        organization_id=uuid4(),
        collection_id=uuid4(),
        requested_by=uuid4(),
        total_count=1,
        status="running",
        previous_sync_state="manual",
        attempt_count=1,
        max_attempts=8,
        lease_owner="owner",
        lease_expires_at=now + timedelta(minutes=1),
        next_retry_at=None,
        execution_deadline_at=now + timedelta(minutes=30),
        started_at=now,
    )
    row = SimpleNamespace(
        id=job.job_id,
        total_count=1,
        status="running",
        retryable=True,
        safe_reason_code=None,
        lease_owner="owner",
        lease_expires_at=job.lease_expires_at,
        next_retry_at=None,
        completed_at=None,
        updated_at=now,
        completed_count=0,
        failed_count=0,
        skipped_count=0,
    )
    db = Mock()
    db.get.return_value = row
    repository = SqlAlchemyWorkerSyncRepository(db)
    repository._set_collection_state = Mock()  # type: ignore[method-assign]  # noqa: SLF001

    repository.finalize_job(
        job,
        status="failed",
        now=now,
        reason_code="sync.targets_changed",
        completed_count=0,
        failed_count=0,
        skipped_count=1,
    )

    assert row.status == "failed"
    assert row.completed_count == 0
    assert row.failed_count == 0
    assert row.skipped_count == 1
    repository._set_collection_state.assert_called_once()  # type: ignore[attr-defined]  # noqa: SLF001
