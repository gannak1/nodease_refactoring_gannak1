import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.gateway.api.v1.endpoints import knowledge as knowledge_endpoint
from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.main import app
from apps.shared.schemas.knowledge import (
    KnowledgeCandidate,
    KnowledgeCandidateResolution,
    KnowledgePermissionDecision,
)


def test_knowledge_candidate_resolve_route_returns_safe_response(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    intended_subject_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    captured = {}

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, current_user_id: organization_id,
    )

    class FakeResolver:
        def __init__(
            self,
            db,
            *,
            user_id,
            organization_id,
            runtime_permission_helper=None,
        ):
            captured["user_id"] = user_id
            captured["organization_id"] = organization_id
            captured["runtime_helper_present"] = runtime_permission_helper is not None

        def resolve_explicit_kbs(self, knowledge_base_ids):
            captured["knowledge_base_ids"] = knowledge_base_ids
            return KnowledgeCandidateResolution(
                candidates=[
                    KnowledgeCandidate(
                        candidate_id=kb_id,
                        candidate_type="knowledge_base",
                        permission=KnowledgePermissionDecision(
                            allowed=True,
                            reason_code="allowed",
                            external_reason_code="allowed",
                        ),
                        runtime_availability="unavailable",
                        safe_label=None,
                        safe_metadata={"runtime_reason_code": "permission.denied"},
                    )
                ],
                hidden_candidate_count_bucket="2-10",
                unavailable_candidate_count_bucket="1",
            )

    monkeypatch.setattr(knowledge_endpoint, "KnowledgeCandidateResolver", FakeResolver)
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            "/api/v1/knowledge/candidates/resolve",
            json={
                "mode": "explicit_kb",
                "knowledge_base_ids": [str(kb_id)],
                "intended_execution_subject_id": str(intended_subject_id),
            },
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    body = response.json()
    assert captured["user_id"] == user_id
    assert captured["organization_id"] == organization_id
    assert captured["runtime_helper_present"] is True
    assert body["candidates"][0]["candidate_id"] == str(kb_id)
    assert body["candidates"][0]["runtime_availability"] == "unavailable"
    assert body["hidden_candidate_count_bucket"] == "2-10"
    assert "raw_source_url" not in str(body)
    assert "exact_denied_count" not in str(body)


def test_knowledge_candidate_resolve_rejects_over_cap_request():
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    try:
        response = TestClient(app).post(
            "/api/v1/knowledge/candidates/resolve",
            json={
                "mode": "auto_collection",
                "max_candidate_kbs": 5001,
            },
            headers={"X-Organization-Id": str(uuid.uuid4())},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation.failed"
