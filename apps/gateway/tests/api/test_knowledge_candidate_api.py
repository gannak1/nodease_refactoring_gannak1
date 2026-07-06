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
    KnowledgeRAGRecommendation,
    KnowledgeRAGRecommendationProvenance,
    KnowledgeRAGRecommendationResponse,
    KnowledgeRAGRecommendationSummary,
    KnowledgeRAGRecommendedOptions,
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


def test_knowledge_rag_recommendation_route_uses_server_context(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    captured = {}

    monkeypatch.setattr(
        knowledge_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, current_user_id: organization_id,
    )

    class FakeRecommendationService:
        def __init__(self, db, *, user_id, organization_id):
            captured["user_id"] = user_id
            captured["organization_id"] = organization_id

        def recommend_for_builder(self, recommendation_request):
            captured["workflow_intent"] = recommendation_request.workflow_intent
            captured["has_body_actor"] = hasattr(recommendation_request, "actor_user_id")
            return KnowledgeRAGRecommendationResponse(
                recommendations=[
                    KnowledgeRAGRecommendation(
                        recommendation_id=f"rec-{uuid.uuid4()}",
                        recommendation_mode="auto_collection",
                        candidate_id=kb_id,
                        safe_label=None,
                        confidence=0.4,
                        safe_reason_code="safe_candidate_available",
                        recommended_options=KnowledgeRAGRecommendedOptions(),
                        materialized_knowledge_bases=[
                            {"id": kb_id, "name": "Knowledge Base"}
                        ],
                        provenance=KnowledgeRAGRecommendationProvenance(
                            safe_reason_code="safe_candidate_available",
                        ),
                        runtime_availability="unknown",
                        warnings=["runtime_availability_unknown"],
                    )
                ],
                summary=KnowledgeRAGRecommendationSummary(
                    candidate_count_bucket="1",
                    recommendation_count_bucket="1",
                ),
            )

    monkeypatch.setattr(
        knowledge_endpoint,
        "KnowledgeRAGRecommendationService",
        FakeRecommendationService,
    )
    app.dependency_overrides[knowledge_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            "/api/v1/knowledge/rag-recommendations",
            json={
                "workflow_intent": "휴가\x00 규정 답변",
                "node_purpose": "HR policy",
                "mode": "auto",
                "actor_user_id": str(uuid.uuid4()),
                "organization_id": str(uuid.uuid4()),
            },
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    body = response.json()
    assert captured["user_id"] == user_id
    assert captured["organization_id"] == organization_id
    assert captured["workflow_intent"] == "휴가 규정 답변"
    assert captured["has_body_actor"] is False
    assert body["recommendations"][0]["candidate_type"] == "knowledge_base"
    assert str(kb_id) not in body["recommendations"][0]["recommendation_id"]
    assert body["recommendations"][0]["safe_label"] is None
    assert body["recommendations"][0]["materialized_knowledge_bases"][0]["name"] == (
        "Knowledge Base"
    )
    assert "raw_source_url" not in str(body)
