import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.gateway.api.v1.endpoints import knowledge as knowledge_endpoint


def test_delete_knowledge_base_delegates_lifecycle_service(monkeypatch):
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    db = object()
    calls = []

    service = SimpleNamespace(
        delete_owned_knowledge_base=lambda **kwargs: calls.append(kwargs)
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "KnowledgeLifecycleService",
        lambda service_db: service if service_db is db else None,
    )

    response = knowledge_endpoint.delete_knowledge_base.__wrapped__(
        kb_id=kb_id,
        db=db,
        current_user=SimpleNamespace(id=user_id),
    )

    assert response.status_code == 204
    assert calls == [{"kb_id": kb_id, "user_id": user_id}]


def test_delete_knowledge_base_translates_lifecycle_not_found(monkeypatch):
    def raise_not_found(**_kwargs):
        raise knowledge_endpoint.KnowledgeLifecycleNotFound()

    monkeypatch.setattr(
        knowledge_endpoint,
        "KnowledgeLifecycleService",
        lambda _db: SimpleNamespace(delete_owned_knowledge_base=raise_not_found),
    )

    with pytest.raises(HTTPException) as exc_info:
        knowledge_endpoint.delete_knowledge_base.__wrapped__(
            kb_id=uuid.uuid4(),
            db=object(),
            current_user=SimpleNamespace(id=uuid.uuid4()),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Knowledge Base not found"
