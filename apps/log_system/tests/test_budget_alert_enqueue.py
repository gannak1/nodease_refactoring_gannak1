"""Red-phase tests for the log_system budget alert enqueue hook (BGA-REQ-004).

run 완료(update_run_log_finish) 후 예산 알림 평가 task를 이름 기반 send_task로
enqueue한다(gateway import 없음, 앱 경계 유지). 실패나 재시도는 run 로그 저장 task와
분리된다.

대응 문서: docs/features/budget-alerts/test_cases.md > AC-1
"""

from uuid import uuid4

from apps.log_system import tasks
from apps.shared.services.budget_alerts import BUDGET_ALERT_EVALUATION_TASK


def test_enqueue_sends_named_task_with_workflow_id(monkeypatch):
    calls = []
    monkeypatch.setattr(
        tasks.celery_app,
        "send_task",
        lambda name, args=None, **kwargs: calls.append((name, args)),
    )

    workflow_id = uuid4()
    tasks._enqueue_budget_alert(workflow_id)

    assert calls == [(BUDGET_ALERT_EVALUATION_TASK, [str(workflow_id)])]


def test_enqueue_noop_when_workflow_id_none(monkeypatch):
    calls = []
    monkeypatch.setattr(
        tasks.celery_app, "send_task", lambda *args, **kwargs: calls.append(args)
    )

    tasks._enqueue_budget_alert(None)

    assert calls == []


def test_enqueue_swallows_send_task_errors(monkeypatch):
    # enqueue 실패가 run 로그 저장 task(update_run_finish)로 전파되어 재시도를
    # 유발하면 안 된다 (BGA-REQ-004: 발송 경로와 저장 경로 분리).
    def _boom(*args, **kwargs):
        raise RuntimeError("broker down")

    monkeypatch.setattr(tasks.celery_app, "send_task", _boom)

    # 예외가 전파되지 않아야 한다.
    tasks._enqueue_budget_alert(uuid4())
