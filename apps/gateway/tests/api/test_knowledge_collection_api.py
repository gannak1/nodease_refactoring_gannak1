import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.gateway.api.v1.endpoints import knowledge as knowledge_endpoint
from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.main import app
from apps.gateway.services.knowledge_collection_service import (
    KnowledgeCollectionServiceError,
)
from apps.shared.schemas.knowledge import KnowledgeCollectionLLMSelectableResponse
from apps.shared.schemas.knowledge import (
    KnowledgeCollectionResponse,
    KnowledgeCollectionVisibilityResponse,
)


def _collection_response(collection_id=None, organization_id=None):
    return KnowledgeCollectionResponse(
        id=collection_id or uuid.uuid4(),
        organization_id=organization_id or uuid.uuid4(),
        name="HR Policies",
        description="Safe collection",
        visibility="private",
        linked_kb_count_bucket="1",
        active_kb_count_bucket="1",
        can_read=True,
        can_route=True,
        can_manage=True,
        can_sync=False,
        safe_metadata={"category": "hr"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def test_collection_create_route_uses_active_organization(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    captured = {}

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, current_user_id: organization_id,
    )

    class FakeService:
        def __init__(self, db, *, user_id, organization_id):
            captured["user_id"] = user_id
            captured["organization_id"] = organization_id

        def create_collection(self, request):
            captured["name"] = request.name
            return _collection_response(organization_id=organization_id)

    monkeypatch.setattr(knowledge_endpoint, "KnowledgeCollectionService", FakeService)
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            "/api/v1/knowledge/collections",
            json={"name": "HR Policies", "safe_metadata": {"category": "hr"}},
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 201
    body = response.json()
    assert captured == {
        "user_id": user_id,
        "organization_id": organization_id,
        "name": "HR Policies",
    }
    assert body["organization_id"] == str(organization_id)
    assert "raw_source_url" not in str(body)


def test_collection_list_route_returns_management_capabilities(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    collection = _collection_response(organization_id=organization_id)

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, current_user_id: organization_id,
    )

    class FakeService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def list_collections(self, **kwargs):
            return [collection]

        def management_capabilities(self):
            return {
                "can_create_collection": True,
                "can_change_public_visibility": True,
            }

    monkeypatch.setattr(knowledge_endpoint, "KnowledgeCollectionService", FakeService)
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).get(
            "/api/v1/knowledge/collections",
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    body = response.json()
    assert body["collections"][0]["id"] == str(collection.id)
    assert body["can_create_collection"] is True
    assert body["can_change_public_visibility"] is True


def test_collection_picker_uses_active_organization_and_minimal_projection(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    captured = {}

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, current_user_id: organization_id,
    )

    class FakePicker:
        def __init__(self, db, *, user_id, organization_id):
            captured["user_id"] = user_id
            captured["organization_id"] = organization_id

        def list_llm_selectable(self):
            return KnowledgeCollectionLLMSelectableResponse(
                collections=[
                    {"id": collection_id, "safe_label": "사내 문서"}
                ]
            )

    monkeypatch.setattr(
        knowledge_endpoint,
        "KnowledgeCollectionPickerQueryService",
        FakePicker,
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).get(
            "/api/v1/knowledge/llm-selectable-collections",
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert response.json() == {
        "collections": [
            {"id": str(collection_id), "safe_label": "사내 문서"}
        ]
    }
    assert captured == {
        "user_id": user_id,
        "organization_id": organization_id,
    }


def test_collection_visibility_error_uses_safe_envelope(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    collection_id = uuid.uuid4()

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, current_user_id: organization_id,
    )

    class FakeService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def update_visibility(self, collection_id, request):
            raise KnowledgeCollectionServiceError(
                400,
                "validation.failed",
                "Public visibility acknowledgement is required.",
                {"field": "acknowledged_public_runtime_exposure"},
            )

    monkeypatch.setattr(knowledge_endpoint, "KnowledgeCollectionService", FakeService)
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            f"/api/v1/knowledge/collections/{collection_id}/visibility",
            json={
                "visibility": "public",
                "acknowledged_public_runtime_exposure": False,
            },
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation.failed"
    assert "raw_source_url" not in str(body)


def test_collection_visibility_route_returns_safe_summary(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    collection = _collection_response(organization_id=organization_id)

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, current_user_id: organization_id,
    )

    class FakeService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def update_visibility(self, collection_id, request):
            public_collection = collection.model_copy(update={"visibility": "public"})
            return KnowledgeCollectionVisibilityResponse(
                collection=public_collection,
                linked_kb_count_bucket="1",
                active_kb_count_bucket="1",
                sensitive_content_warning="unknown_or_present",
            )

    monkeypatch.setattr(knowledge_endpoint, "KnowledgeCollectionService", FakeService)
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            f"/api/v1/knowledge/collections/{collection.id}/visibility",
            json={
                "visibility": "public",
                "acknowledged_public_runtime_exposure": True,
            },
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    body = response.json()
    assert body["collection"]["visibility"] == "public"
    assert body["public_runtime_effect"] == "anonymous_public_only_candidate"
    assert "exact_denied_count" not in str(body)
