import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.gateway.api.v1.endpoints import knowledge as knowledge_endpoint
from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.main import app
from apps.shared.db.models.knowledge import SourceType


class FakeKnowledgeQuery:
    def __init__(self, rows):
        self.rows = rows

    def select_from(self, *_args, **_kwargs):
        return self

    def outerjoin(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def group_by(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows


class FakeKnowledgeDb:
    def __init__(self, rows):
        self.rows = rows
        self.query_entities = None

    def query(self, *entities):
        self.query_entities = entities
        return FakeKnowledgeQuery(self.rows)


def test_knowledge_list_handles_documentless_legacy_kb_without_500(monkeypatch):
    kb_id = uuid.uuid4()
    row = (
        kb_id,
        None,
        "문서 없는 KB",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    fake_db = FakeKnowledgeDb([row])
    monkeypatch.setattr(
        knowledge_endpoint,
        "_table_has_column",
        lambda _db, _table_name, _column_name: False,
    )

    response = knowledge_endpoint.list_knowledge_bases(
        db=fake_db,
        current_user=SimpleNamespace(id=uuid.uuid4()),
    )

    assert all(
        entity is not knowledge_endpoint.KnowledgeBase
        for entity in fake_db.query_entities
    )
    assert len(response) == 1
    assert response[0].id == kb_id
    assert response[0].organization_id is None
    assert response[0].document_count == 0
    assert response[0].source_types == []
    assert response[0].embedding_model == knowledge_endpoint.DEFAULT_EMBEDDING_MODEL
    assert response[0].created_at is not None
    assert response[0].updated_at is not None


def test_knowledge_list_normalizes_source_type_values(monkeypatch):
    kb_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    created_at = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    kb_updated_at = datetime(2026, 7, 7, 2, tzinfo=timezone.utc)
    doc_updated_at = datetime(2026, 7, 7, 3, tzinfo=timezone.utc)
    row = (
        kb_id,
        organization_id,
        "휴가 정책 KB",
        "휴가 정책",
        "custom-embedding",
        created_at,
        kb_updated_at,
        2,
        doc_updated_at,
        [SourceType.FILE, "API", None, SourceType.FILE],
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "_table_has_column",
        lambda _db, _table_name, _column_name: True,
    )

    response = knowledge_endpoint.list_knowledge_bases(
        db=FakeKnowledgeDb([row]),
        current_user=SimpleNamespace(id=uuid.uuid4()),
    )

    assert len(response) == 1
    assert response[0].organization_id == organization_id
    assert response[0].document_count == 2
    assert response[0].created_at == created_at
    assert response[0].updated_at == doc_updated_at
    assert response[0].source_types == ["FILE", "API"]
    assert response[0].embedding_model == "custom-embedding"


def test_knowledge_list_route_returns_legacy_safe_response(monkeypatch):
    kb_id = uuid.uuid4()
    row = (
        kb_id,
        None,
        "문서 없는 KB",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    fake_db = FakeKnowledgeDb([row])
    monkeypatch.setattr(
        knowledge_endpoint,
        "_table_has_column",
        lambda _db, _table_name, _column_name: False,
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    try:
        response = TestClient(app).get("/api/v1/knowledge")
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    body = response.json()
    assert body == [
        {
            "id": str(kb_id),
            "organization_id": None,
            "name": "문서 없는 KB",
            "description": None,
            "document_count": 0,
            "created_at": body[0]["created_at"],
            "updated_at": body[0]["updated_at"],
            "source_types": [],
            "embedding_model": knowledge_endpoint.DEFAULT_EMBEDDING_MODEL,
        }
    ]
