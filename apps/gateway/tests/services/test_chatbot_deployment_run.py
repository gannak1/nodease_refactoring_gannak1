"""챗봇 배포 공개 실행 경로의 conversation_id 관통 + 기억모드 강제 계약 테스트.

docs/features/chatbot-deployment/test_cases.md:
- 챗봇 배포(DeploymentType.CHATBOT)는 클라이언트 값과 무관하게 memory_mode를 강제 ON.
- inputs 안의 conversation_id / memory_mode는 dispatch 전에 pop되어 워크플로우
  입력을 오염시키지 않고, execution_context로만 전달된다.
- conversation_id는 방문자별 대화 격리 키로 execution_context에 실린다.
"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.sql.operators import eq

from apps.shared.db.models.app import App
from apps.shared.db.models.workflow_deployment import DeploymentType, WorkflowDeployment


# --- 실행 헬퍼 ---------------------------------------------------------------


def _run_public(db, url_slug, user_inputs, monkeypatch, trigger_mode="app"):
    from apps.gateway.services import deployment_service as deployment_module

    celery = _CaptureCelery()
    monkeypatch.setattr(deployment_module, "celery_app", celery)
    # run_deployment 내부의 `from celery.result import AsyncResult`가 가짜를 집도록 패치
    monkeypatch.setattr("celery.result.AsyncResult", _FakeAsyncResult)

    result = asyncio.run(
        deployment_module.DeploymentService.run_deployment(
            db=db,
            url_slug=url_slug,
            user_inputs=user_inputs,
            trigger_mode=trigger_mode,
            auth_token=None,
            require_auth=False,
        )
    )
    return celery, result


def _captured_context(celery):
    # send_task(name, args=[graph, user_inputs, execution_context], kwargs=...)
    return celery.captured.args[2]


def _captured_inputs(celery):
    return celery.captured.args[1]


# --- 테스트 ------------------------------------------------------------------


def test_chatbot_forces_memory_mode_and_threads_conversation_id(monkeypatch):
    app_row, deployment_row = _deployed_app(DeploymentType.CHATBOT)
    db = _Db(rows=[app_row, deployment_row])

    # 클라이언트는 memory_mode를 보내지 않았지만 챗봇은 서버가 강제 ON 한다.
    celery, result = _run_public(
        db,
        app_row.url_slug,
        {"question": "안녕", "conversation_id": "conv-A"},
        monkeypatch,
    )

    ctx = _captured_context(celery)
    sent_inputs = _captured_inputs(celery)

    assert ctx["memory_mode"] is True
    assert ctx["conversation_id"] == "conv-A"
    # conversation_id / memory_mode는 워크플로우 입력에서 제거된다.
    assert sent_inputs == {"question": "안녕"}
    assert result["status"] == "success"


def test_chatbot_overrides_client_memory_false(monkeypatch):
    app_row, deployment_row = _deployed_app(DeploymentType.CHATBOT)
    db = _Db(rows=[app_row, deployment_row])

    celery, _ = _run_public(
        db,
        app_row.url_slug,
        {"question": "x", "memory_mode": False, "conversation_id": "conv-B"},
        monkeypatch,
    )

    # 클라이언트가 false를 보내도 챗봇은 무조건 켠다.
    assert _captured_context(celery)["memory_mode"] is True


def test_non_chatbot_does_not_force_memory_but_threads_conversation_id(monkeypatch):
    app_row, deployment_row = _deployed_app(DeploymentType.WEBAPP)
    db = _Db(rows=[app_row, deployment_row])

    celery, _ = _run_public(
        db,
        app_row.url_slug,
        {"question": "x", "conversation_id": "conv-C"},
        monkeypatch,
    )

    ctx = _captured_context(celery)
    # webapp 등 비챗봇 배포는 기억모드를 강제하지 않는다 (기본 False).
    assert ctx["memory_mode"] is False
    # conversation_id는 배포 타입과 무관하게 그대로 전달된다.
    assert ctx["conversation_id"] == "conv-C"


def test_missing_conversation_id_is_none(monkeypatch):
    app_row, deployment_row = _deployed_app(DeploymentType.CHATBOT)
    db = _Db(rows=[app_row, deployment_row])

    celery, _ = _run_public(db, app_row.url_slug, {"question": "x"}, monkeypatch)

    assert _captured_context(celery)["conversation_id"] is None


# --- fakes -------------------------------------------------------------------


def _deployed_app(deployment_type):
    workflow_id = uuid4()
    organization_id = uuid4()
    deployment_id = uuid4()
    app_row = App(
        id=uuid4(),
        name="챗봇 앱",
        url_slug=f"chatbot-{uuid4().hex[:8]}",
        auth_secret="deploy-secret",
        workflow_id=workflow_id,
        organization_id=organization_id,
        active_deployment_id=deployment_id,
        created_by=uuid4(),
    )
    deployment_row = WorkflowDeployment(
        id=deployment_id,
        app_id=app_row.id,
        version=1,
        type=deployment_type,
        graph_snapshot={"nodes": [], "edges": []},
        is_active=True,
        created_by=uuid4(),
    )
    return app_row, deployment_row


class _CaptureCelery:
    """send_task 인자를 캡처하고 즉시 완료되는 가짜 task를 반환한다."""

    def __init__(self):
        self.captured = None

    def send_task(self, name, args=None, kwargs=None):
        self.captured = SimpleNamespace(name=name, args=args, kwargs=kwargs)
        return SimpleNamespace(id="fake-task-id")


class _FakeAsyncResult:
    def __init__(self, task_id, app=None):
        self._task_id = task_id

    def ready(self):
        return True

    def failed(self):
        return False

    @property
    def result(self):
        return {"status": "success", "result": {"answer": "ok"}}


class _Query:
    def __init__(self, items):
        self.items = list(items)
        self.filters = []

    def filter(self, *expressions):
        self.filters.extend(expressions)
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return next(
            (
                item
                for item in self.items
                if all(_matches(item, e) for e in self.filters)
            ),
            None,
        )


def _matches(item, expression):
    if not hasattr(expression, "left"):
        return True
    column = str(expression.left).split(".")[-1]
    if not hasattr(item, column):
        return True
    if expression.operator is not eq:
        return True
    right = expression.right
    right_value = right.value if hasattr(right, "value") else right
    return getattr(item, column) == right_value


class _Db:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def query(self, model, *rest):
        return _Query([row for row in self.rows if isinstance(row, model)])

    def add(self, obj):
        self.rows.append(obj)

    def flush(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass
