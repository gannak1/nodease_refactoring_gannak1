"""Node log tasks should treat missing parent WorkflowRun as a quiet retry."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from celery.exceptions import Retry

from apps.log_system import tasks as log_tasks


class _MissingQuery:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None


class _MissingRunSession:
    def __init__(self):
        self.rollback_calls = 0
        self.closed = False

    def expire_all(self):
        pass

    def query(self, *args, **kwargs):
        return _MissingQuery()

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.closed = True


def _raise_retry(*, exc, countdown):
    raise Retry(exc=exc, when=countdown)


def _base_node_data(**overrides):
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "id": str(uuid4()),
        "log_id": str(uuid4()),
        "workflow_run_id": str(uuid4()),
        "node_id": "node-1",
        "node_type": "llm",
        "inputs": {},
        "outputs": {"answer": "ok"},
        "process_data": {},
        "error_message": "node failed",
        "started_at": now,
        "finished_at": now,
        "trace_payloads": [],
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    "task_func",
    [
        log_tasks.create_node_log,
        log_tasks.update_node_log_finish,
        log_tasks.update_node_log_error,
    ],
)
def test_missing_workflow_run_retry_is_not_logged_as_error(
    task_func, monkeypatch, caplog
):
    session = _MissingRunSession()
    monkeypatch.setattr(log_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(task_func, "retry", _raise_retry)

    with pytest.raises(Retry):
        task_func.__wrapped__(_base_node_data())

    assert session.rollback_calls == 0
    assert session.closed is True
    assert "실패" not in caplog.text
