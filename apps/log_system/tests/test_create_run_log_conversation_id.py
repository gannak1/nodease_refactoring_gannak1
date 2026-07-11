"""create_run_log가 conversation_id를 WorkflowRun에 저장하는지 검증.

docs/features/chatbot-deployment/test_cases.md:
- 챗봇 배포의 방문자별 대화 격리를 위해, execution_context에서 넘어온
  conversation_id가 WorkflowRun.conversation_id 컬럼에 저장되어야 한다.
"""

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from apps.log_system import tasks as log_tasks
from apps.shared.db.models.workflow_run import RunStatus, RunTriggerMode, WorkflowRun


def _base_data(**overrides):
    data = {
        "run_id": str(uuid4()),
        "workflow_id": str(uuid4()),
        "user_id": str(uuid4()),
        "app_id": str(uuid4()),
        "deployment_id": str(uuid4()),
        "workflow_version": 1,
        "trigger_mode": "app",
        "is_deployed": True,
        "user_input": {"question": "안녕"},
        "started_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": None,
        "request_id": None,
        "workflow_task_id": None,
        "trace_metadata": {},
        "redaction_applied": False,
        "pii_detected": False,
        "redaction_policy_id": None,
        "retention_policy_id": None,
        "visibility_policy_id": None,
        "payload_storage_mode": "redacted_only",
        "trace_payloads": [],
    }
    data.update(overrides)
    return data


class _CaptureSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class _RetryRequested(Exception):
    pass


class _RetryTask:
    def __init__(self):
        self.request = SimpleNamespace(retries=2)
        self.error = None
        self.countdown = None

    def retry(self, *, exc, countdown):
        self.error = exc
        self.countdown = countdown
        raise _RetryRequested()


def _run_create_run_log(data, monkeypatch):
    session = _CaptureSession()
    monkeypatch.setattr(log_tasks, "SessionLocal", lambda: session)
    # trace payload 삽입은 별도 경로이므로 격리한다.
    monkeypatch.setattr(log_tasks, "_insert_trace_payloads", lambda *a, **k: None)

    # 바운드 celery task이므로 __wrapped__는 self가 이미 바인딩되어 data만 받는다.
    result = log_tasks.create_run_log.__wrapped__(data)
    assert result["status"] == "success"
    runs = [obj for obj in session.added if isinstance(obj, WorkflowRun)]
    assert len(runs) == 1
    return runs[0]


def test_conversation_id_is_persisted(monkeypatch):
    run = _run_create_run_log(_base_data(conversation_id="conv-A"), monkeypatch)
    assert run.conversation_id == "conv-A"


def test_missing_conversation_id_is_none(monkeypatch):
    run = _run_create_run_log(_base_data(), monkeypatch)
    assert run.conversation_id is None


def test_system_schedule_run_allows_null_executor_with_correlation(monkeypatch):
    run = _run_create_run_log(
        _base_data(
            user_id=None,
            trigger_mode="schedule",
            workflow_task_id=f"schedule:{uuid4()}",
        ),
        monkeypatch,
    )

    assert run.user_id is None
    assert run.trigger_mode == RunTriggerMode.SCHEDULER


def test_null_executor_without_schedule_correlation_is_rejected(monkeypatch):
    import pytest

    with pytest.raises(ValueError):
        _run_create_run_log(
            _base_data(user_id=None, trigger_mode="manual"),
            monkeypatch,
        )


def test_workflow_run_log_retry_redacts_raw_exception(caplog):
    import pytest

    task = _RetryTask()
    raw_detail = "credential=do-not-log"

    with caplog.at_level(logging.ERROR):
        with pytest.raises(_RetryRequested):
            log_tasks._retry_workflow_run_log_task(
                task,
                operation="create",
                error=RuntimeError(raw_detail),
            )

    assert raw_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert str(task.error) == "workflow run log storage retry requested"
    assert task.countdown == 4


class _QuerySession:
    def __init__(self, run):
        self.run = run
        self.committed = False

    def query(self, *entities):
        return _Query(entities[0] if entities else None, self.run)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


class _Query:
    def __init__(self, entity, run):
        self.entity = entity
        self.run = run

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self.entity is WorkflowRun:
            return self.run
        return None

    def all(self):
        return []


def test_update_run_finish_clears_previous_error_message(monkeypatch):
    run = WorkflowRun(
        id=uuid4(),
        workflow_id=uuid4(),
        user_id=uuid4(),
        trigger_mode=RunTriggerMode.MANUAL,
        status=RunStatus.FAILED,
        outputs={},
        error_message="이전 retry 실패 메시지",
        started_at=datetime.now(timezone.utc),
    )
    session = _QuerySession(run)
    monkeypatch.setattr(log_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(log_tasks, "_insert_trace_payloads", lambda *a, **k: None)
    monkeypatch.setattr(log_tasks, "_record_workflow_execute_audit", lambda *a, **k: None)

    result = log_tasks.update_run_log_finish.__wrapped__(
        {
            "run_id": str(run.id),
            "outputs": {"ok": True},
            "redaction_applied": False,
            "pii_detected": False,
            "payload_storage_mode": "redacted_only",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "trace_payloads": [],
        }
    )

    assert result["status"] == "success"
    assert session.committed is True
    assert run.status == RunStatus.SUCCESS
    assert run.error_message is None
