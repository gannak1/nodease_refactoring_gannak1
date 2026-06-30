import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from apps.gateway.api.v1.endpoints import rag
from apps.shared.db.models.knowledge import KnowledgeBase
from apps.shared.schemas.rag import RAGResponse, SearchQuery


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.result


class FakeDb:
    def __init__(self, query_result):
        self.query_result = query_result

    def query(self, model):
        return FakeQuery(self.query_result)


def _request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.request_id = "test-request-id"
    return request


def test_search_requires_knowledge_base_id():
    with pytest.raises(HTTPException) as exc:
        rag._require_search_knowledge_base_id(_request(), SearchQuery(query="policy"))

    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "validation.failed"


def test_authorize_rag_use_hides_scope_mismatch(monkeypatch):
    organization_id = uuid.uuid4()
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name="KB",
        user_id=uuid.uuid4(),
    )
    monkeypatch.setattr(rag, "has_organization_scope_access", lambda *args: True)

    with pytest.raises(HTTPException) as exc:
        rag._authorize_rag_use(
            _request(),
            FakeDb(kb),
            SimpleNamespace(id=uuid.uuid4()),
            organization_id,
            kb.id,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["error"]["code"] == "resource.not_found"


def test_authorize_rag_use_requires_use_permission(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        organization_id=organization_id,
        name="KB",
        user_id=uuid.uuid4(),
    )
    audit_calls = []
    monkeypatch.setattr(rag, "has_organization_scope_access", lambda *args: True)
    monkeypatch.setattr(
        rag,
        "get_effective_knowledge_base_auth_state",
        lambda *args, **kwargs: "viewer",
    )
    monkeypatch.setattr(
        rag,
        "record_resource_permission_denied",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    with pytest.raises(HTTPException) as exc:
        rag._authorize_rag_use(
            _request(),
            FakeDb(kb),
            SimpleNamespace(id=user_id),
            organization_id,
            kb.id,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["code"] == "permission.denied"
    assert getattr(exc.value, "audit_recorded") is True
    assert audit_calls == [
        {
            "user_id": user_id,
            "resource_type": "knowledge_base",
            "resource_id": kb.id,
            "action": "use",
            "effective_auth_state": "viewer",
            "organization_id": organization_id,
            "metadata": {
                "request_id": "test-request-id",
                "path": "/",
            },
        }
    ]


def test_search_test_chat_passes_top_k_and_organization_id(monkeypatch):
    captured = {}
    organization_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()

    class FakeRetrievalService:
        def __init__(self, db, user_id, organization_id=None):
            captured["init"] = {
                "db": db,
                "user_id": user_id,
                "organization_id": organization_id,
            }

        async def generate_answer_for_test(self, *args, **kwargs):
            captured.update(kwargs)
            return RAGResponse(answer="ok", references=[])

    monkeypatch.setattr(rag, "RetrievalService", FakeRetrievalService)
    monkeypatch.setattr(rag, "_authorize_rag_use", lambda *args, **kwargs: None)
    monkeypatch.setattr(rag, "_record_rag_retrieve_audit", lambda *args, **kwargs: None)

    asyncio.run(
        rag.search_test_chat(
            SearchQuery(
                query="policy",
                top_k=7,
                knowledge_base_id=knowledge_base_id,
            ),
            _request(),
            str(organization_id),
            db=object(),
            current_user=SimpleNamespace(id=uuid.uuid4()),
        ),
    )

    assert captured["top_k"] == 7
    assert captured["init"]["organization_id"] == organization_id
