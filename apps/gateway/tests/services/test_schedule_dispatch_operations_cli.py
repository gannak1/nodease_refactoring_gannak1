from __future__ import annotations

from scripts.check_schedule_dispatch_rollback import (
    _active_schedule_task_count,
    _workflow_queue_depth,
)


class _Inspector:
    def active(self):
        return {
            "worker-1": [
                {"name": "workflow.execute_scheduled_deployment"},
                {"name": "workflow.execute_by_deployment"},
            ]
        }

    def reserved(self):
        return {
            "worker-1": [
                {
                    "request": {
                        "name": "workflow.execute_scheduled_deployment",
                        "args": ["must-not-be-read"],
                    }
                }
            ]
        }

    def scheduled(self):
        return {"worker-1": []}


class _Control:
    def inspect(self, *, timeout):
        assert timeout == 3.0
        return _Inspector()


class _Celery:
    control = _Control()


def test_rollback_preflight_counts_only_dedicated_schedule_tasks(monkeypatch):
    monkeypatch.setattr(
        "scripts.check_schedule_dispatch_rollback.celery_app",
        _Celery(),
    )

    assert _active_schedule_task_count(timeout=3.0) == 2
    assert _active_schedule_task_count(timeout=3.0, include_legacy=True) == 3


def test_rollback_preflight_fails_closed_when_worker_inspection_is_unavailable(
    monkeypatch,
):
    class _UnavailableInspector(_Inspector):
        def active(self):
            return None

    class _UnavailableControl:
        def inspect(self, *, timeout):
            return _UnavailableInspector()

    class _UnavailableCelery:
        control = _UnavailableControl()

    monkeypatch.setattr(
        "scripts.check_schedule_dispatch_rollback.celery_app",
        _UnavailableCelery(),
    )

    try:
        _active_schedule_task_count(timeout=3.0)
    except RuntimeError as exc:
        assert str(exc) == "worker task inspection is unavailable"
    else:
        raise AssertionError("worker inspection must fail closed")


def test_transition_preflight_counts_workflow_priority_queues_without_reading_payload(
    monkeypatch,
):
    class _RedisClient:
        def __init__(self):
            self.closed = False

        def scan_iter(self, *, match):
            assert match == b"workflow*"
            return iter(
                [
                    b"workflow",
                    b"workflow\x06\x163",
                    b"workflow-result",
                ]
            )

        def type(self, key):
            return b"list"

        def llen(self, key):
            return {b"workflow": 2, b"workflow\x06\x163": 1}[key]

        def close(self):
            self.closed = True

    client = _RedisClient()
    monkeypatch.setattr(
        "scripts.check_schedule_dispatch_rollback.redis.Redis.from_url",
        lambda *args, **kwargs: client,
    )
    monkeypatch.setattr(
        "scripts.check_schedule_dispatch_rollback.celery_app.conf.broker_url",
        "redis://localhost/0",
    )

    assert _workflow_queue_depth(timeout=3.0) == 3
    assert client.closed is True
