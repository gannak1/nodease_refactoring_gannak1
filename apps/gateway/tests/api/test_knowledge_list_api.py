import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from apps.gateway.api.v1.endpoints import knowledge as knowledge_endpoint
from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.main import app
from apps.gateway.services.knowledge_base_query_service import DEFAULT_EMBEDDING_MODEL


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
        self.info = {}

    def add(self, item):
        if isinstance(item, knowledge_endpoint.KnowledgeBase):
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


def test_knowledge_list_uses_active_org_authorized_service(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    captured = {}

    class FakeAuthorizedService:
        def list_authorized(self, *, user_id, organization_id, schema_ready):
            captured["service"] = (user_id, organization_id, schema_ready)
            return []

    monkeypatch.setattr(
        knowledge_endpoint,
        "_ensure_knowledge_schema_columns",
        lambda *_args, **_kwargs: captured.setdefault("schema_checked", True),
    )
    def fake_resolve(_db, _request, raw, caller_id):
        captured["resolver"] = (raw, caller_id)
        return organization_id

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        fake_resolve,
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_base_query_service",
        lambda _db: FakeAuthorizedService(),
    )

    response = knowledge_endpoint.list_knowledge_bases(
        request=SimpleNamespace(),
        x_organization_id=str(organization_id),
        db=object(),
        current_user=SimpleNamespace(id=user_id),
    )

    assert response == []
    assert captured["schema_checked"] is True
    assert captured["resolver"] == (str(organization_id), user_id)
    assert captured["service"] == (user_id, organization_id, True)


def test_knowledge_list_returns_authorized_service_projection(monkeypatch):
    kb_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    expected = SimpleNamespace(
        id=kb_id,
        organization_id=organization_id,
        name="휴가 정책 KB",
        description="휴가 정책",
        safe_metadata={},
        document_count=2,
        created_at=now,
        updated_at=now,
        source_types=["FILE", "API"],
        embedding_model="custom-embedding",
    )

    class FakeAuthorizedService:
        def list_authorized(self, **_kwargs):
            return [expected]

    monkeypatch.setattr(
        knowledge_endpoint,
        "_ensure_knowledge_schema_columns",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        lambda *_args, **_kwargs: organization_id,
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_base_query_service",
        lambda _db: FakeAuthorizedService(),
    )

    response = knowledge_endpoint.list_knowledge_bases(
        request=SimpleNamespace(),
        x_organization_id=None,
        db=object(),
        current_user=SimpleNamespace(id=uuid.uuid4()),
    )

    assert response == [expected]


def test_knowledge_list_route_returns_authorized_safe_response(monkeypatch):
    kb_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)

    class FakeAuthorizedService:
        def list_authorized(self, **_kwargs):
            return [
                {
                    "id": kb_id,
                    "organization_id": organization_id,
                    "name": "문서 없는 KB",
                    "description": None,
                    "safe_metadata": {},
                    "document_count": 0,
                    "created_at": now,
                    "updated_at": now,
                    "source_types": [],
                    "embedding_model": DEFAULT_EMBEDDING_MODEL,
                }
            ]

    monkeypatch.setattr(
        knowledge_endpoint,
        "_ensure_knowledge_schema_columns",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        lambda *_args, **_kwargs: organization_id,
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_base_query_service",
        lambda _db: FakeAuthorizedService(),
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
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
            "organization_id": str(organization_id),
            "name": "문서 없는 KB",
            "description": None,
            "safe_metadata": {},
            "document_count": 0,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "updated_at": now.isoformat().replace("+00:00", "Z"),
            "source_types": [],
            "embedding_model": DEFAULT_EMBEDDING_MODEL,
        }
    ]


def test_knowledge_list_scopes_to_active_organization_header(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    captured = {}

    monkeypatch.setattr(
        knowledge_endpoint,
        "_ensure_knowledge_schema_columns",
        lambda *_args, **_kwargs: None,
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

    class FakeAuthorizedService:
        def list_authorized(self, *, user_id, organization_id, schema_ready):
            captured["service"] = (user_id, organization_id, schema_ready)
            return []

    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_base_query_service",
        lambda _db: FakeAuthorizedService(),
    )

    response = knowledge_endpoint.list_knowledge_bases(
        request=SimpleNamespace(),
        x_organization_id=str(organization_id),
        db=object(),
        current_user=SimpleNamespace(id=user_id),
    )

    assert captured == {
        "raw": str(organization_id),
        "current_user_id": user_id,
        "service": (user_id, organization_id, True),
    }
    assert response == []


def test_llm_selectable_knowledge_route_uses_active_org_and_service(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    captured = {}

    class FakeLLMSelectableService:
        def list_llm_selectable(self, *, user_id, organization_id, schema_ready):
            captured["user_id"] = user_id
            captured["organization_id"] = organization_id
            captured["schema_ready"] = schema_ready
            return [
                {
                    "id": kb_id,
                    "organization_id": organization_id,
                    "name": "권한 있는 조직 KB",
                    "description": None,
                    "document_count": 1,
                    "created_at": now,
                    "updated_at": now,
                    "source_types": ["FILE"],
                    "embedding_model": "text-embedding-3-small",
                    "documents": [
                        {
                            "id": doc_id,
                            "filename": "ready.md",
                            "status": "completed",
                            "created_at": now,
                            "updated_at": now,
                            "error_message": None,
                            "chunk_count": 2,
                            "token_count": 32,
                            "source_type": "FILE",
                            "meta_info": {},
                        }
                    ],
                }
            ]

    def fake_resolve_active_organization_id(db, request, raw, current_user_id):
        captured["raw"] = raw
        captured["current_user_id"] = current_user_id
        return organization_id

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        fake_resolve_active_organization_id,
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        lambda _db, _required: {},
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_base_query_service",
        lambda _db: FakeLLMSelectableService(),
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).get(
            "/api/v1/knowledge/llm-selectable",
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert captured == {
        "raw": str(organization_id),
        "current_user_id": user_id,
        "user_id": user_id,
        "organization_id": organization_id,
        "schema_ready": True,
    }
    assert response.json()[0]["id"] == str(kb_id)
    assert response.json()[0]["documents"][0]["chunk_count"] == 2


def test_llm_selectable_knowledge_route_reports_stale_schema(monkeypatch):
    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        lambda _db, _required: {"knowledge_bases": ["lifecycle_state"]},
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    try:
        response = TestClient(app).get(
            "/api/v1/knowledge/llm-selectable",
            headers={"X-Organization-Id": str(uuid.uuid4())},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "knowledge.schema_not_ready"
    assert body["error"]["details"]["missing_columns"] == {
        "knowledge_bases": ["lifecycle_state"]
    }


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


def test_knowledge_create_validation_error_does_not_echo_raw_input(monkeypatch):
    fake_db = FakeCreateKnowledgeDb()
    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        lambda _db, _required: {},
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "get_user_primary_organization_id",
        lambda _db, _user_id: uuid.uuid4(),
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    try:
        response = TestClient(app).post(
            "/api/v1/knowledge",
            json={
                "name": "민감 모델 KB",
                "description": "테스트",
                "embedding_model": "sk-secret-like-model-value",
            },
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "knowledge.validation_failed"
    assert body["error"]["details"] == {"reason": "embedding_model_invalid"}
    assert "sk-secret-like-model-value" not in response.text
    assert fake_db.added is None
    assert fake_db.committed is False


def test_knowledge_create_rejects_empty_embedding_model(monkeypatch):
    fake_db = FakeCreateKnowledgeDb()
    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        lambda _db, _required: {},
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "get_user_primary_organization_id",
        lambda _db, _user_id: uuid.uuid4(),
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    try:
        response = TestClient(app).post(
            "/api/v1/knowledge",
            json={
                "name": "빈 임베딩 모델 KB",
                "description": "테스트",
                "embedding_model": "   ",
            },
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "knowledge.validation_failed"
    assert body["error"]["details"] == {"reason": "embedding_model_invalid"}
    assert fake_db.added is None
    assert fake_db.committed is False


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


def test_knowledge_detail_uses_read_gate_and_returns_capabilities(monkeypatch):
    knowledge_base_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    doc_id = uuid.uuid4()
    captured = {}

    monkeypatch.setattr(
        knowledge_endpoint,
        "_ensure_knowledge_schema_columns",
        lambda *_args, **_kwargs: None,
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

    kb = SimpleNamespace(
        id=knowledge_base_id,
        lifecycle_state="active",
        source_identity_id=None,
        sync_state="manual",
    )

    class FakeAuthorizationService:
        def load_kb(self, kb_id, action):
            captured["authorization"] = (kb_id, action)
            return kb

        def capabilities(self, loaded_kb):
            assert loaded_kb is kb
            return SimpleNamespace(
                can_read=True,
                can_use=True,
                can_write=True,
                can_read_content=True,
                can_manage=False,
            )

    class FakeDetailService:
        def get_detail(self, kb_id, **kwargs):
            captured["detail"] = (kb_id, kwargs)
            return {
                "id": knowledge_base_id,
                "organization_id": organization_id,
                "name": "사내 정책 KB",
                "description": "테스트 상세",
                "safe_metadata": {},
                "document_count": 1,
                "created_at": now,
                "updated_at": now,
                "source_types": ["FILE"],
                "embedding_model": "text-embedding-3-small",
                "documents": [
                    {
                        "id": doc_id,
                        "filename": "policy.pdf",
                        "status": "completed",
                        "created_at": now,
                        "updated_at": now,
                        "error_message": None,
                        "chunk_count": 0,
                        "token_count": 0,
                        "source_type": "FILE",
                        "meta_info": {},
                    }
                ],
                "can_edit_settings": True,
                "can_manage_safe_metadata": False,
                "can_register_initial_document": False,
                "can_read": True,
                "can_use": True,
                "can_write": True,
                "can_read_content": True,
                "can_manage": False,
            }

    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_authorization_service",
        lambda *_args, **_kwargs: FakeAuthorizationService(),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_base_query_service",
        lambda _db: FakeDetailService(),
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
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
        "authorization": (knowledge_base_id, "read"),
        "detail": (
            knowledge_base_id,
            {
                "organization_scope": organization_id,
                "has_organization_id": True,
                "can_edit_settings": True,
                "can_manage_safe_metadata": False,
                "can_register_initial_document": True,
                "can_read": True,
                "can_use": True,
                "can_write": True,
                "can_read_content": True,
                "can_manage": False,
            },
        ),
    }
    body = response.json()
    assert body["id"] == str(knowledge_base_id)
    assert body["organization_id"] == str(organization_id)
    assert body["document_count"] == 1
    assert body["source_types"] == ["FILE"]
    assert body["documents"][0]["id"] == str(doc_id)
    assert body["documents"][0]["chunk_count"] == 0
    assert body["can_write"] is True
    assert body["can_manage"] is False
    assert body["can_register_initial_document"] is False


def test_direct_document_detail_projects_internal_metadata(monkeypatch):
    knowledge_base_id = uuid.uuid4()
    document_id = uuid.uuid4()
    now = datetime(2026, 7, 13, 9, tzinfo=timezone.utc)
    document = SimpleNamespace(
        id=document_id,
        filename="safe-document.pdf",
        status="processing",
        created_at=now,
        updated_at=now,
        error_message=None,
        chunks=[],
        source_type="API",
        meta_info={
            "progress": 20,
            "processing_current_step": "Processing queued.",
            "api_config": {"headers_encrypted": None},
            "connection_id": None,
            "source_connector_ref": None,
        },
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "_authorized_knowledge_document",
        lambda *args, **kwargs: (SimpleNamespace(id=knowledge_base_id), document),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "finalize_stale_processing_start",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "recover_timed_out_document_with_artifacts",
        lambda *args, **kwargs: False,
    )

    response = knowledge_endpoint.get_document(
        kb_id=knowledge_base_id,
        document_id=document_id,
        request=SimpleNamespace(),
        x_organization_id=str(uuid.uuid4()),
        db=object(),
        current_user=SimpleNamespace(id=uuid.uuid4()),
    )

    assert response.meta_info == {"progress": 20}


def test_direct_document_detail_replaces_persisted_failure_detail(monkeypatch):
    knowledge_base_id = uuid.uuid4()
    document_id = uuid.uuid4()
    now = datetime(2026, 7, 13, 9, tzinfo=timezone.utc)
    document = SimpleNamespace(
        id=document_id,
        filename="safe-document.pdf",
        status="failed",
        created_at=now,
        updated_at=now,
        error_message="legacy-internal-exception-marker",
        chunks=[],
        source_type="FILE",
        meta_info={"processing_current_step": "legacy-step-marker"},
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "_authorized_knowledge_document",
        lambda *args, **kwargs: (SimpleNamespace(id=knowledge_base_id), document),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "finalize_stale_processing_start",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "recover_timed_out_document_with_artifacts",
        lambda *args, **kwargs: False,
    )

    response = knowledge_endpoint.get_document(
        kb_id=knowledge_base_id,
        document_id=document_id,
        request=SimpleNamespace(),
        x_organization_id=str(uuid.uuid4()),
        db=object(),
        current_user=SimpleNamespace(id=uuid.uuid4()),
    )

    assert response.status == "failed"
    assert response.error_message == (
        "Document processing failed. You can retry the document."
    )
    assert response.meta_info == {}
    serialized = repr(response.model_dump(mode="json"))
    assert "legacy-internal-exception-marker" not in serialized
    assert "legacy-step-marker" not in serialized


def test_document_edit_config_requires_write_and_returns_bounded_projection(
    monkeypatch,
):
    knowledge_base_id = uuid.uuid4()
    document_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    captured = {}
    document = SimpleNamespace(
        id=document_id,
        source_type="API",
        chunk_size=800,
        chunk_overlap=80,
        meta_info={
            "api_config": {
                "url_encrypted": "opaque-url-ciphertext",
                "method": "GET",
                "headers_encrypted": None,
                "body_encrypted": "opaque-body-ciphertext",
                "safe_label": "API source",
            }
        },
    )

    def authorize(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(id=knowledge_base_id), document

    monkeypatch.setattr(
        knowledge_endpoint,
        "_authorized_knowledge_document",
        authorize,
    )

    response_headers = Response()
    response = knowledge_endpoint.get_document_edit_config(
        kb_id=knowledge_base_id,
        document_id=document_id,
        request=SimpleNamespace(),
        response=response_headers,
        x_organization_id=str(organization_id),
        db=object(),
        current_user=SimpleNamespace(id=user_id),
    )

    assert captured["args"][0:3] == (
        knowledge_base_id,
        document_id,
        "write",
    )
    body = response.model_dump(mode="json")
    assert body["editable"] is True
    assert body["api_config"] == {
        "configured": True,
        "method": "GET",
        "safe_label": "API source",
        "has_headers": False,
        "has_body": True,
    }
    serialized = repr(body)
    assert "opaque-url-ciphertext" not in serialized
    assert "opaque-body-ciphertext" not in serialized
    assert response_headers.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_api_process_preserves_server_side_encrypted_source_config(monkeypatch):
    knowledge_base_id = uuid.uuid4()
    document_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    encrypted_config = {
        "url_encrypted": "opaque-url-ciphertext",
        "method": "POST",
        "headers_encrypted": "opaque-header-ciphertext",
        "body_encrypted": None,
        "safe_label": "API source",
    }
    document = SimpleNamespace(
        id=document_id,
        source_type="API",
        chunk_size=800,
        chunk_overlap=80,
        meta_info={"api_config": encrypted_config},
    )

    class FakeDb:
        committed = False

        def commit(self):
            self.committed = True

    class FakeIngestionService:
        def __init__(self, *_args, **_kwargs):
            self.organization_id = _kwargs.get("organization_id")

        async def process_document(self, _document_id):
            pass

    db = FakeDb()
    created_services = []

    def create_ingestion_service(*args, **kwargs):
        service = FakeIngestionService(*args, **kwargs)
        created_services.append(service)
        return service

    monkeypatch.setattr(
        knowledge_endpoint,
        "_authorized_knowledge_document",
        lambda *args, **kwargs: (
            SimpleNamespace(
                id=knowledge_base_id,
                organization_id=organization_id,
                embedding_model="embedding-model",
            ),
            document,
        ),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "mark_document_processing_queued",
        lambda doc: setattr(doc, "status", "indexing"),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "IngestionService",
        create_ingestion_service,
    )

    response = await knowledge_endpoint.process_document.__wrapped__(
        kb_id=knowledge_base_id,
        document_id=document_id,
        preview_request=knowledge_endpoint.DocumentPreviewRequest(
            chunk_size=700,
            chunk_overlap=70,
            source_type="API",
            db_config=None,
        ),
        request=SimpleNamespace(),
        background_tasks=BackgroundTasks(),
        x_organization_id=str(uuid.uuid4()),
        db=db,
        current_user=SimpleNamespace(id=uuid.uuid4()),
    )

    assert response == {
        "status": "processing",
        "message": "Document processing started",
    }
    assert db.committed is True
    assert [service.organization_id for service in created_services] == [organization_id]
    assert document.meta_info["api_config"] is encrypted_config
    assert document.meta_info["db_config"] is None


def test_knowledge_detail_fails_closed_when_required_schema_is_missing(monkeypatch):
    knowledge_base_id = uuid.uuid4()
    monkeypatch.setattr(
        knowledge_endpoint,
        "_knowledge_schema_missing_columns",
        lambda *_args, **_kwargs: {"knowledge_bases": ["organization_id"]},
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        lambda *_args, **_kwargs: pytest.fail("organization resolver not expected"),
    )

    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    try:
        response = TestClient(app).get(f"/api/v1/knowledge/{knowledge_base_id}")
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "knowledge.schema_not_ready"
    assert body["error"]["details"]["missing_columns"] == {
        "knowledge_bases": ["organization_id"]
    }
