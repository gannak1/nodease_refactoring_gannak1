from __future__ import annotations

from datetime import datetime, timezone

import pytest

from apps.memory.application.retention import PurgeExpiredPublicSecretReplaysUseCase
from apps.shared.celery_app import celery_app


class _Repository:
    def __init__(self, deleted_count: int = 0, error: Exception | None = None) -> None:
        self.deleted_count = deleted_count
        self.error = error
        self.calls = []

    def delete_expired_secret_replays(self, *, now, limit):
        self.calls.append((now, limit))
        if self.error is not None:
            raise self.error
        return self.deleted_count


class _UnitOfWork:
    def __init__(self) -> None:
        self.events = []

    def begin(self) -> None:
        self.events.append("begin")

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


def test_secret_replay_retention_deletes_one_bounded_batch_transactionally():
    repository = _Repository(deleted_count=3)
    uow = _UnitOfWork()
    now = datetime(2026, 7, 18, tzinfo=timezone.utc)

    deleted = PurgeExpiredPublicSecretReplaysUseCase(
        repository=repository,
        uow=uow,
    ).execute(now=now, limit=500)

    assert deleted == 3
    assert repository.calls == [(now, 500)]
    assert uow.events == ["begin", "commit"]


def test_secret_replay_retention_rolls_back_and_rejects_unbounded_inputs():
    repository = _Repository(error=RuntimeError("safe synthetic failure"))
    uow = _UnitOfWork()
    use_case = PurgeExpiredPublicSecretReplaysUseCase(
        repository=repository,
        uow=uow,
    )

    with pytest.raises(RuntimeError):
        use_case.execute(now=datetime.now(timezone.utc), limit=1000)
    assert uow.events == ["begin", "rollback"]

    with pytest.raises(ValueError):
        use_case.execute(now=datetime.now(timezone.utc), limit=1001)


def test_secret_replay_retention_has_a_memory_owned_periodic_task():
    entry = celery_app.conf.beat_schedule["memory-secret-replay-retention"]

    assert entry == {
        "task": "memory.secret_replay_retention_purge",
        "schedule": 60.0,
        "options": {"queue": "log"},
    }
    assert celery_app.conf.task_routes["memory.*"] == {"queue": "log"}
