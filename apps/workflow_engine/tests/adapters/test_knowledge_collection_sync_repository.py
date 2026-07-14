from datetime import datetime, timedelta, timezone
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
