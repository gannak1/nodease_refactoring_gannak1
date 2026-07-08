import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from apps.gateway.api.v1.endpoints import knowledge as knowledge_endpoint
from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.main import app
from apps.gateway.services.knowledge_base_query_service import DEFAULT_EMBEDDING_MODEL
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


class FakeCreateKnowledgeDb:
    def __init__(self):
        self.added = None
        self.committed = False
        self.rolled_back = False

    def add(self, item):
        self.added = item

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, item):
        item.id = item.id or uuid.uuid4()
        item.created_at = item.created_at or datetime.now(timezone.utc)
        item.updated_at = item.updated_at or item.created_at


class FailingCreateKnowledgeDb(FakeCreateKnowledgeDb):
    def commit(self):
        raise SQLAlchemyError("simulated write failure")


class FakeDetailQuery:
    def __init__(self, *, first_value=None, all_value=None):
        self.first_value = first_value
        self.all_value = all_value or []

    def select_from(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def group_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.first_value

    def get(self, *_args, **_kwargs):
        return None

    def all(self):
        return self.all_value


class FakeDetailKnowledgeDb:
    def __init__(self, kb_row, doc_rows):
        self.kb_row = kb_row
        self.doc_rows = doc_rows
        self.query_count = 0
        self.query_entities = []

    def query(self, *entities):
        self.query_count += 1
        self.query_entities.append(entities)
        if self.query_count == 1:
            return FakeDetailQuery(first_value=self.kb_row)
        return FakeDetailQuery(all_value=self.doc_rows)


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
        request=None,
        x_organization_id=None,
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
    assert response[0].embedding_model == DEFAULT_EMBEDDING_MODEL
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
        request=None,
        x_organization_id=None,
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
            "embedding_model": DEFAULT_EMBEDDING_MODEL,
        }
    ]


def test_knowledge_list_scopes_to_active_organization_header(monkeypatch):
    kb_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    row = (
        kb_id,
        organization_id,
        "조직 KB",
        None,
        "text-embedding-3-small",
        datetime(2026, 7, 7, 1, tzinfo=timezone.utc),
        None,
        0,
        None,
        [],
    )
    captured = {}

    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        lambda _db, _required: {},
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "_table_has_column",
        lambda _db, table_name, column_name: (
            table_name == "knowledge_bases" and column_name == "organization_id"
        ),
    )

    def fake_resolve_active_organization_id(db, request, raw, current_user_id):
        captured["raw"] = raw
        captured["current_user_id"] = current_user_id
        return organization_id

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        fake_resolve_active_organization_id,
    )

    response = knowledge_endpoint.list_knowledge_bases(
        request=None,
        x_organization_id=str(organization_id),
        db=FakeKnowledgeDb([row]),
        current_user=SimpleNamespace(id=user_id),
    )

    assert captured == {
        "raw": str(organization_id),
        "current_user_id": user_id,
    }
    assert len(response) == 1
    assert response[0].organization_id == organization_id


def test_knowledge_create_uses_active_organization_header(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    fake_db = FakeCreateKnowledgeDb()
    captured = {}

    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        lambda _db, _required: {},
    )

    def fake_resolve_active_organization_id(db, request, raw, current_user_id):
        captured["raw"] = raw
        captured["current_user_id"] = current_user_id
        return organization_id

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        fake_resolve_active_organization_id,
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            "/api/v1/knowledge",
            json={
                "name": "신규 KB",
                "description": "테스트",
                "embedding_model": "text-embedding-3-small",
            },
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 201
    assert captured == {
        "raw": str(organization_id),
        "current_user_id": user_id,
    }
    assert fake_db.committed is True
    assert fake_db.added.organization_id == organization_id
    assert response.json()["organization_id"] == str(organization_id)


def test_knowledge_create_preserves_primary_organization_fallback(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    fake_db = FakeCreateKnowledgeDb()

    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        lambda _db, _required: {},
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "get_user_primary_organization_id",
        lambda _db, current_user_id: (
            organization_id if current_user_id == user_id else None
        ),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        lambda *_args, **_kwargs: pytest.fail("organization resolver not expected"),
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            "/api/v1/knowledge",
            json={
                "name": "기존 fallback KB",
                "description": "테스트",
                "embedding_model": "text-embedding-3-small",
            },
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 201
    assert fake_db.added.organization_id == organization_id
    assert response.json()["organization_id"] == str(organization_id)


def test_knowledge_create_rejects_invalid_active_organization(monkeypatch):
    user_id = uuid.uuid4()
    fake_db = FakeCreateKnowledgeDb()

    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        lambda _db, _required: {},
    )

    def fake_resolve_active_organization_id(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Organization not found")

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        fake_resolve_active_organization_id,
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            "/api/v1/knowledge",
            json={
                "name": "차단 KB",
                "description": "테스트",
                "embedding_model": "text-embedding-3-small",
            },
            headers={"X-Organization-Id": str(uuid.uuid4())},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 404
    assert fake_db.added is None
    assert fake_db.committed is False


def test_knowledge_create_returns_structured_error_on_write_failure(monkeypatch):
    fake_db = FailingCreateKnowledgeDb()
    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        lambda _db, _required: {},
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "get_user_primary_organization_id",
        lambda *_args, **_kwargs: uuid.uuid4(),
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    try:
        response = TestClient(app).post(
            "/api/v1/knowledge",
            json={
                "name": "쓰기 실패 KB",
                "description": "테스트",
                "embedding_model": "text-embedding-3-small",
            },
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "knowledge.create_failed"
    assert fake_db.rolled_back is True


def test_knowledge_create_reports_stale_schema_without_raw_500(monkeypatch):
    fake_db = FakeCreateKnowledgeDb()
    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        lambda _db, _required: {"knowledge_bases": ["sync_state"]},
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    try:
        response = TestClient(app).post(
            "/api/v1/knowledge",
            json={
                "name": "stale schema KB",
                "description": "테스트",
                "embedding_model": "text-embedding-3-small",
            },
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "knowledge.schema_not_ready"
    assert body["error"]["details"]["missing_columns"] == {
        "knowledge_bases": ["sync_state"]
    }
    assert fake_db.added is None


def test_knowledge_schema_missing_columns_raises_on_introspection_failure(monkeypatch):
    monkeypatch.setattr(
        knowledge_endpoint,
        "check_knowledge_schema_readiness",
        lambda *_args, **_kwargs: SimpleNamespace(
            missing_columns={},
            reason="schema_introspection_failed",
        ),
    )

    with pytest.raises(knowledge_endpoint.KnowledgeSchemaIntrospectionError):
        knowledge_endpoint._knowledge_schema_missing_columns(
            FakeCreateKnowledgeDb(),
            {"knowledge_bases": {"sync_state"}},
        )


def test_knowledge_create_reports_schema_introspection_failure_without_insert(
    monkeypatch,
):
    fake_db = FakeCreateKnowledgeDb()

    def raise_schema_introspection_error(*_args, **_kwargs):
        raise knowledge_endpoint.KnowledgeSchemaIntrospectionError

    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        raise_schema_introspection_error,
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    try:
        response = TestClient(app).post(
            "/api/v1/knowledge",
            json={
                "name": "schema introspection failure KB",
                "description": "테스트",
                "embedding_model": "text-embedding-3-small",
            },
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "knowledge.schema_not_ready"
    assert body["error"]["details"] == {
        "missing_columns": {},
        "reason": "schema_introspection_failed",
    }
    assert fake_db.added is None
    assert fake_db.committed is False


def test_knowledge_detail_uses_scoped_safe_column_query(monkeypatch):
    knowledge_base_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    doc_id = uuid.uuid4()
    fake_db = FakeDetailKnowledgeDb(
        (
            knowledge_base_id,
            organization_id,
            "사내 정책 KB",
            "테스트 상세",
            "text-embedding-3-small",
            now,
            None,
            None,
        ),
        [
            (
                doc_id,
                "policy.pdf",
                "completed",
                now,
                None,
                None,
                SourceType.FILE,
                {"category": "policy"},
            )
        ],
    )
    captured = {}

    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        lambda _db, _required: {},
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "_table_has_column",
        lambda _db, table_name, column_name: (
            table_name == "knowledge_bases" and column_name == "organization_id"
        ),
    )

    def fake_resolve_active_organization_id(db, request, raw, current_user_id):
        captured["raw"] = raw
        captured["current_user_id"] = current_user_id
        return organization_id

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        fake_resolve_active_organization_id,
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).get(
            f"/api/v1/knowledge/{knowledge_base_id}",
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert captured == {
        "raw": str(organization_id),
        "current_user_id": user_id,
    }
    body = response.json()
    assert body["id"] == str(knowledge_base_id)
    assert body["organization_id"] == str(organization_id)
    assert body["document_count"] == 1
    assert body["source_types"] == ["FILE"]
    assert body["documents"][0]["id"] == str(doc_id)
    assert body["documents"][0]["chunk_count"] == 0
    assert all(
        entity is not knowledge_endpoint.KnowledgeBase
        for query_entities in fake_db.query_entities
        for entity in query_entities
    )


def test_knowledge_detail_uses_legacy_safe_query_without_organization_column(
    monkeypatch,
):
    knowledge_base_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    doc_id = uuid.uuid4()
    fake_db = FakeDetailKnowledgeDb(
        (
            knowledge_base_id,
            None,
            "레거시 KB",
            None,
            None,
            now,
            None,
            None,
        ),
        [
            (
                doc_id,
                "legacy.pdf",
                "completed",
                now,
                None,
                None,
                None,
                None,
            )
        ],
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "_table_has_column",
        lambda _db, _table_name, _column_name: False,
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        lambda *_args, **_kwargs: pytest.fail("organization resolver not expected"),
    )

    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    try:
        response = TestClient(app).get(f"/api/v1/knowledge/{knowledge_base_id}")
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(knowledge_base_id)
    assert body["organization_id"] is None
    assert body["embedding_model"] == DEFAULT_EMBEDDING_MODEL
    assert body["source_types"] == []
    assert body["documents"][0]["chunk_count"] == 0
    assert body["documents"][0]["source_type"] == "FILE"
    assert all(
        entity is not knowledge_endpoint.KnowledgeBase
        for query_entities in fake_db.query_entities
        for entity in query_entities
    )
