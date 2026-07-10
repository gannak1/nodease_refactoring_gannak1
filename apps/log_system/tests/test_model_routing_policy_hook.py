"""FR-011 운영 표본 집계 hook의 완료 시점 경계 테스트."""

from types import SimpleNamespace
from uuid import uuid4

from apps.log_system import tasks as log_tasks
from apps.shared.db.models.workflow_run import NodeRunStatus


def test_running_llm_node_does_not_enqueue_policy_run_record(monkeypatch):
    sent = []
    monkeypatch.setattr(
        log_tasks.celery_app,
        "send_task",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    log_tasks._schedule_model_routing_run_record(
        SimpleNamespace(
            node_type="llmNode",
            status=NodeRunStatus.RUNNING,
            workflow_run_id=uuid4(),
        )
    )

    assert sent == []


def test_successful_llm_node_enqueues_policy_run_record(monkeypatch):
    sent = []
    workflow_run_id = uuid4()
    monkeypatch.setattr(
        log_tasks.celery_app,
        "send_task",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    log_tasks._schedule_model_routing_run_record(
        SimpleNamespace(
            node_type="llmNode",
            status=NodeRunStatus.SUCCESS,
            workflow_run_id=workflow_run_id,
        )
    )

    assert sent == [
        (
            ("workflow.model_routing.record_run",),
            {"args": [str(workflow_run_id)]},
        )
    ]
