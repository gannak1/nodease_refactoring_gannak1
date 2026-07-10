"""FR-011 운영 표본 집계 hook의 완료 시점 경계 테스트."""

from types import SimpleNamespace
from uuid import uuid4

from apps.log_system import tasks as log_tasks
from apps.shared.db.models.workflow_run import RunStatus


def test_running_or_completed_node_does_not_enqueue_policy_run_record(monkeypatch):
    sent = []
    monkeypatch.setattr(
        log_tasks.celery_app,
        "send_task",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    log_tasks._schedule_model_routing_run_record(
        SimpleNamespace(
            status=RunStatus.RUNNING,
            id=uuid4(),
        )
    )

    assert sent == []


def test_terminal_workflow_run_enqueues_policy_run_record(monkeypatch):
    sent = []
    workflow_run_id = uuid4()
    monkeypatch.setattr(
        log_tasks.celery_app,
        "send_task",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    log_tasks._schedule_model_routing_run_record(
        SimpleNamespace(
            status=RunStatus.SUCCESS,
            id=workflow_run_id,
        )
    )

    assert sent == [
        (
            ("workflow.model_routing.record_run",),
            {"args": [str(workflow_run_id)]},
        )
    ]


def test_terminal_workflow_status_is_written_into_successful_llm_trace():
    """정책 refresh 전에 terminal workflow 결과를 LLM trace의 downstream summary로 확정한다."""

    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return [node_run]

    class _Session:
        def query(self, *args, **kwargs):
            return _Query()

    node_run = SimpleNamespace(
        node_type="llmNode",
        trace_metadata={"llm": {"selected_model": "gpt-4.1-mini"}},
    )

    log_tasks._finalize_llm_downstream_status(
        _Session(),
        workflow_run_id=uuid4(),
        downstream_status="failed",
    )

    assert node_run.trace_metadata["llm"]["selected_model"] == "gpt-4.1-mini"
    assert node_run.trace_metadata["llm"]["downstream_status"] == "failed"
