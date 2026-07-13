import asyncio
import uuid
from types import SimpleNamespace

from starlette.requests import Request

from apps.gateway.api.v1.endpoints import workflow as workflow_endpoint


class FakeTask:
    def get(self, timeout=None):
        return {"status": "success", "result": {}}


class FakeCeleryApp:
    def __init__(self):
        self.calls = []

    def send_task(self, name, args=None, kwargs=None, **options):
        self.calls.append(
            {
                "name": name,
                "args": args or [],
                "kwargs": kwargs or {},
                "options": options,
            }
        )
        return FakeTask()


class FakeNoBudgetDb:
    """예산 미설정 세션 — 실행 전 예산 확인이 조용히 통과한다."""

    def query(self, model, *rest):
        return SimpleNamespace(
            filter=lambda *args, **kwargs: SimpleNamespace(first=lambda: None)
        )


def test_authenticated_execute_passes_current_user_execution_subject(monkeypatch):
    workflow_id = str(uuid.uuid4())
    app_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    current_user = SimpleNamespace(id=uuid.uuid4())
    workflow = SimpleNamespace(id=workflow_id, app_id=app_id, organization_id=organization_id)
    celery = FakeCeleryApp()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/v1/workflows/{workflow_id}/execute",
            "headers": [],
        }
    )

    monkeypatch.setattr(
        workflow_endpoint,
        "ensure_workflow_permission",
        lambda *args, **kwargs: workflow,
    )
    monkeypatch.setattr(
        workflow_endpoint.WorkflowService,
        "get_draft",
        lambda *args, **kwargs: {"nodes": [], "edges": []},
    )
    monkeypatch.setattr(workflow_endpoint, "celery_app", celery)

    asyncio.run(
        workflow_endpoint.execute_workflow(
            workflow_id,
            request,
            user_input={},
            db=FakeNoBudgetDb(),
            current_user=current_user,
        )
    )

    assert len(celery.calls) == 1
    execution_context = celery.calls[0]["args"][2]
    assert execution_context["user_id"] == str(current_user.id)
    assert execution_context["execution_subject"] == {
        "type": "user",
        "id": str(current_user.id),
    }


def test_authenticated_execute_dispatches_draft_rag_selection(monkeypatch):
    workflow_id = str(uuid.uuid4())
    app_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    knowledge_base_id = str(uuid.uuid4())
    current_user = SimpleNamespace(id=uuid.uuid4())
    workflow = SimpleNamespace(id=workflow_id, app_id=app_id, organization_id=organization_id)
    celery = FakeCeleryApp()
    draft_graph = {
        "nodes": [
            {
                "id": "llm-1",
                "type": "llmNode",
                "position": {"x": 100, "y": 120},
                "data": {
                    "title": "LLM",
                    "provider": "openai",
                    "model_id": "gpt-4o",
                    "user_prompt": "query",
                    "knowledgeBases": [
                        {"id": knowledge_base_id, "name": "제품 정책"}
                    ],
                    "topK": 4,
                    "scoreThreshold": 0.6,
                },
            }
        ],
        "edges": [],
    }
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/v1/workflows/{workflow_id}/execute",
            "headers": [],
        }
    )

    monkeypatch.setattr(
        workflow_endpoint,
        "ensure_workflow_permission",
        lambda *args, **kwargs: workflow,
    )
    monkeypatch.setattr(
        workflow_endpoint.WorkflowService,
        "get_draft",
        lambda *args, **kwargs: draft_graph,
    )
    monkeypatch.setattr(workflow_endpoint, "celery_app", celery)

    asyncio.run(
        workflow_endpoint.execute_workflow(
            workflow_id,
            request,
            user_input={"message": "hello"},
            db=FakeNoBudgetDb(),
            current_user=current_user,
        )
    )

    dispatched_graph = celery.calls[0]["args"][0]
    dispatched_context = celery.calls[0]["args"][2]

    assert dispatched_graph["nodes"][0]["data"]["knowledgeBases"] == [
        {"id": knowledge_base_id, "name": "제품 정책"}
    ]
    assert dispatched_graph["nodes"][0]["data"]["topK"] == 4
    assert dispatched_graph["nodes"][0]["data"]["scoreThreshold"] == 0.6
    assert dispatched_context["execution_subject"] == {
        "type": "user",
        "id": str(current_user.id),
    }
