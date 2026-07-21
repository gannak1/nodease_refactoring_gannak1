from __future__ import annotations

import json

from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedIntentPlanV1,
    CachedKnowledgePlacement,
    CachedKnowledgeRequirement,
    EphemeralCacheScope,
    IntentLogicalTopology,
    IntentPlanContractVersions,
    IntentPlanningContext,
    LogicalStepRef,
    PlannerRuntimeFingerprint,
)

from apps.gateway.services.agent_builder import intent_cache_knowledge


def _context():
    return IntentPlanningContext(
        full_safe_message="사내 문서를 활용한 답변 workflow를 만들어줘",
        workflow_context=IntentLogicalTopology(workflow_present=False, nodes=(), edges=()),
        planner_runtime=PlannerRuntimeFingerprint(provider_ref="openai", model_relation_fingerprint="a" * 64, credential_relation_fingerprint="b" * 64),
        generation_mode="guided_generate", knowledge_context_fingerprint="c" * 64,
        contract_versions=IntentPlanContractVersions(normalizer_version="intent-normalizer-v1", cache_schema_version=1, planner_contract_version="agent-builder-intent-v1", catalog_version=3, canonical_text_registry_version="intent-text-v1", materializer_version="agent-builder-direct-edit-v1"),
        scope=EphemeralCacheScope(actor_id=uuid4(), organization_id=uuid4(), selected_target_type=None, selected_target_id=None),
    )


def _plan(context):
    step = LogicalStepRef(capability="knowledge_backed_llm", occurrence=1)
    return CachedIntentPlanV1(
        schema_version=1,
        request_type="new_workflow",
        draft_mode="new_workflow",
        ordered_capabilities=("knowledge_backed_llm",),
        logical_steps=(step,),
        edit_placement=None,
        integration_actions=(),
        parameter_guidance_refs=(),
        knowledge_requirements=(
            CachedKnowledgeRequirement(
                requirement_ref="kr_1",
                required=True,
                evidence_kind="policy_or_reference",
                target_step_ref=step,
                topic_refs=("topic.internal_documents.v1",),
            ),
        ),
        knowledge_placements=(
            CachedKnowledgePlacement(
                requirement_ref="kr_1",
                timing="after_graph",
                effect_kind="binding_only",
                target_step_ref=step,
            ),
        ),
        risk_flags=(),
        contract_versions=context.contract_versions,
    )


def test_current_knowledge_resolver_reissues_available_handle(monkeypatch):
    context = _context()
    captured = {}

    class FakeService:
        def __init__(self, *_args, **_kwargs):
            pass

        def recommend_for_builder(self, request, **kwargs):
            captured["request"] = request
            captured["kwargs"] = kwargs
            return SimpleNamespace(status="recommended", recommendations=[SimpleNamespace(candidate_handle="issued-for-this-request", runtime_availability="available"), SimpleNamespace(candidate_handle="not-operational", runtime_availability="warning")])

    monkeypatch.setattr(intent_cache_knowledge, "KnowledgeRAGRecommendationService", FakeService)
    resolutions = intent_cache_knowledge.current_knowledge_resolutions(db=object(), user_id=context.scope._actor_id, organization_id=context.scope._organization_id, context=context, plan=_plan(context))

    assert resolutions[0].status == "ready"
    assert resolutions[0].candidate_handles == ("issued-for-this-request",)
    assert captured["kwargs"]["include_materialized_refs"] is False
    assert captured["request"].safe_query_topics == ["사내 문서"]


def test_unavailable_current_knowledge_never_reuses_cached_authorization(monkeypatch):
    context = _context()

    class FakeService:
        def __init__(self, *_args, **_kwargs):
            pass

        def recommend_for_builder(self, *_args, **_kwargs):
            return SimpleNamespace(status="unavailable", recommendations=[])

    monkeypatch.setattr(intent_cache_knowledge, "KnowledgeRAGRecommendationService", FakeService)
    with pytest.raises(ValueError, match="resolver unavailable"):
        intent_cache_knowledge.current_knowledge_resolutions(db=object(), user_id=context.scope._actor_id, organization_id=context.scope._organization_id, context=context, plan=_plan(context))


def test_knowledge_fingerprint_uses_hmac_identity_and_ignores_handle_or_order(monkeypatch):
    organization_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    collection_id = uuid4()

    def candidate(resource_id, label):
        return SimpleNamespace(
            candidate_id=resource_id,
            candidate_type="knowledge_base",
            permission=SimpleNamespace(
                effective_auth_state="member",
                freshness_epoch=1,
                reason_code="allowed",
                safe_metadata={"policy_revision": "revision-1"},
                source_acl_state="allowed",
            ),
            runtime_availability="available",
            safe_label=label,
            safe_metadata={},
        )

    first = candidate(first_id, "Internal docs")
    second = candidate(second_id, "Policy docs")
    response = SimpleNamespace(
        status="recommended",
        recommendations=[],
        _cache_fingerprint_candidates=[first, second],
        _cache_fingerprint_collections=[
            SimpleNamespace(
                collection_id=collection_id,
                safe_label="Policy collection",
                safe_metadata={},
                candidates=[first, second],
            )
        ],
        reason_code=None,
        summary={},
    )

    class FakeService:
        def __init__(self, *_args, **_kwargs):
            pass

        def recommend_for_builder(self, *_args, **kwargs):
            assert kwargs["include_cache_fingerprint_projection"] is True
            return response

    monkeypatch.setattr(intent_cache_knowledge, "KnowledgeRAGRecommendationService", FakeService)
    key = b"k" * 32
    first_digest = intent_cache_knowledge.current_knowledge_context_fingerprint(
        db=object(),
        user_id=uuid4(),
        organization_id=organization_id,
        full_safe_message="safe request",
        hmac_key=key,
    )
    response._cache_fingerprint_candidates = [second, first]
    reordered_digest = intent_cache_knowledge.current_knowledge_context_fingerprint(
        db=object(),
        user_id=uuid4(),
        organization_id=organization_id,
        full_safe_message="safe request",
        hmac_key=key,
    )

    first.safe_label = "Renamed internal docs"
    second.safe_label = "Renamed policy docs"
    response._cache_fingerprint_collections[0].safe_label = "Renamed collection"
    relabeled_digest = intent_cache_knowledge.current_knowledge_context_fingerprint(
        db=object(),
        user_id=uuid4(),
        organization_id=organization_id,
        full_safe_message="safe request",
        hmac_key=key,
    )

    assert first_digest == reordered_digest
    assert first_digest == relabeled_digest
    assert str(first_id) not in first_digest


def test_knowledge_fingerprint_changes_when_current_candidate_state_changes(monkeypatch):
    organization_id = uuid4()
    candidate_id = uuid4()
    state = {"availability": "available"}

    class FakeService:
        def __init__(self, *_args, **_kwargs):
            pass

        def recommend_for_builder(self, *_args, **kwargs):
            assert kwargs["include_cache_fingerprint_projection"] is True
            candidate = SimpleNamespace(
                candidate_id=candidate_id,
                candidate_type="knowledge_base",
                permission=SimpleNamespace(
                    effective_auth_state="member",
                    freshness_epoch=1,
                    reason_code="allowed",
                    safe_metadata={"policy_revision": "revision-1"},
                    source_acl_state="allowed",
                ),
                runtime_availability=state["availability"],
                safe_label="Internal docs",
                safe_metadata={},
            )
            return SimpleNamespace(
                status="recommended",
                recommendations=[],
                _cache_fingerprint_candidates=[candidate],
                _cache_fingerprint_collections=[],
                reason_code=None,
                summary={},
            )

    monkeypatch.setattr(intent_cache_knowledge, "KnowledgeRAGRecommendationService", FakeService)
    kwargs = {
        "db": object(),
        "user_id": uuid4(),
        "organization_id": organization_id,
        "full_safe_message": "safe request",
        "hmac_key": b"k" * 32,
    }
    before = intent_cache_knowledge.current_knowledge_context_fingerprint(**kwargs)
    state["availability"] = "unavailable"
    after = intent_cache_knowledge.current_knowledge_context_fingerprint(**kwargs)

    assert before != after

def test_knowledge_fingerprint_includes_all_current_permission_and_hierarchy_state(monkeypatch):
    organization_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    collection_id = uuid4()
    state = {"policy_revision": "revision-1", "collection_topics": ["policy"]}

    def candidate(resource_id):
        return SimpleNamespace(
            candidate_id=resource_id,
            candidate_type="knowledge_base",
            permission=SimpleNamespace(
                effective_auth_state="member",
                source_acl_state="allowed",
                freshness_epoch=1,
                reason_code="allowed",
                safe_metadata={"policy_revision": state["policy_revision"]},
            ),
            runtime_availability="available",
            safe_label="Internal docs",
            safe_metadata={"kb_safe_topics": ["policy"]},
        )

    class FakeService:
        def __init__(self, *_args, **_kwargs):
            pass

        def recommend_for_builder(self, *_args, **kwargs):
            assert kwargs["include_cache_fingerprint_projection"] is True
            first = candidate(first_id)
            second = candidate(second_id)
            return SimpleNamespace(
                status="recommended",
                recommendations=[],
                _cache_fingerprint_candidates=[first, second],
                _cache_fingerprint_collections=[
                    SimpleNamespace(
                        collection_id=collection_id,
                        safe_label="Policy collection",
                        safe_metadata={"safe_topics": state["collection_topics"]},
                        candidates=[first],
                    )
                ],
                reason_code=None,
                summary={},
            )

    monkeypatch.setattr(intent_cache_knowledge, "KnowledgeRAGRecommendationService", FakeService)
    kwargs = {
        "db": object(),
        "user_id": uuid4(),
        "organization_id": organization_id,
        "full_safe_message": "safe request",
        "hmac_key": b"k" * 32,
    }

    before = intent_cache_knowledge.current_knowledge_context_fingerprint(**kwargs)
    state["policy_revision"] = "revision-2"
    after_policy_change = intent_cache_knowledge.current_knowledge_context_fingerprint(**kwargs)
    state["collection_topics"] = ["security"]
    after_hierarchy_change = intent_cache_knowledge.current_knowledge_context_fingerprint(**kwargs)

    assert before != after_policy_change != after_hierarchy_change

def test_knowledge_fingerprint_requires_current_policy_revision(monkeypatch):
    candidate_id = uuid4()

    class FakeService:
        def __init__(self, *_args, **_kwargs):
            pass

        def recommend_for_builder(self, *_args, **_kwargs):
            candidate = SimpleNamespace(
                candidate_id=candidate_id,
                candidate_type="knowledge_base",
                permission=SimpleNamespace(
                    effective_auth_state="member",
                    freshness_epoch=1,
                    reason_code="allowed",
                    safe_metadata={},
                    source_acl_state="allowed",
                ),
                runtime_availability="available",
                safe_label="Internal docs",
                safe_metadata={},
            )
            return SimpleNamespace(
                status="recommended",
                recommendations=[],
                _cache_fingerprint_candidates=[candidate],
                _cache_fingerprint_collections=[],
                reason_code=None,
                summary={},
            )

    monkeypatch.setattr(intent_cache_knowledge, "KnowledgeRAGRecommendationService", FakeService)

    with pytest.raises(ValueError, match="policy revision unavailable"):
        intent_cache_knowledge.current_knowledge_context_fingerprint(
            db=object(),
            user_id=uuid4(),
            organization_id=uuid4(),
            full_safe_message="safe request",
            hmac_key=b"k" * 32,
        )


def test_knowledge_fingerprint_excludes_nested_identity_and_presentation_metadata(
    monkeypatch,
):
    """The outer cache projection contains semantic state, not resolver identity."""

    organization_id = uuid4()
    collection_id = uuid4()
    knowledge_id = uuid4()
    captured_context_projections = []
    original_hmac_token = intent_cache_knowledge._hmac_token

    def capture_context_projection(key, *, domain, value):
        if domain == "agent-builder-cache:knowledge-context:v1":
            captured_context_projections.append(value)
        return original_hmac_token(key, domain=domain, value=value)

    monkeypatch.setattr(
        intent_cache_knowledge,
        "_hmac_token",
        capture_context_projection,
    )

    collection = SimpleNamespace(
        collection_id=collection_id,
        safe_metadata={
            "safe_topics": [
                {
                    "topic": "policy",
                    "protected_collection_id": str(collection_id),
                    "safe_label": "Finance Knowledge",
                    "description": "A presentation-only nested description",
                }
            ],
            "collection_id": str(collection_id),
            "collection_safe_label": "Finance Knowledge",
        },
        candidates=[],
    )
    candidate = SimpleNamespace(
        candidate_id=knowledge_id,
        candidate_type="knowledge_base",
        runtime_availability="available",
        safe_metadata={
            "active_document_version_status": "ready",
            "collection_id": str(collection_id),
            "collection_safe_label": "Finance Knowledge",
            "kb_safe_description": "A presentation-only description",
            "kb_safe_topics": ["policy"],
        },
        permission=SimpleNamespace(
            effective_auth_state="allowed",
            freshness_epoch="2026-07-21T00:00:00Z",
            reason_code="allowed",
            source_acl_state="current",
            safe_metadata={
                "policy_revision": "policy-v1",
                "collection_id": str(collection_id),
                "collection_safe_label": "Finance Knowledge",
                "lifecycle_state": "active",
            },
        ),
    )
    collection.candidates = [candidate]
    response = SimpleNamespace(
        status="recommended",
        reason_code="ok",
        summary={},
        _cache_fingerprint_candidates=[candidate],
        _cache_fingerprint_collections=[collection],
    )

    class FakeService:
        def __init__(self, *_args, **_kwargs):
            pass

        def recommend_for_builder(self, *_args, **_kwargs):
            return response

    monkeypatch.setattr(intent_cache_knowledge, "KnowledgeRAGRecommendationService", FakeService)
    kwargs = {
        "db": object(),
        "user_id": uuid4(),
        "organization_id": organization_id,
        "full_safe_message": "safe request",
        "hmac_key": b"k" * 32,
    }

    before = intent_cache_knowledge.current_knowledge_context_fingerprint(**kwargs)
    collection.safe_metadata["collection_safe_label"] = "Renamed Finance Knowledge"
    candidate.safe_metadata["collection_safe_label"] = "Renamed Finance Knowledge"
    candidate.safe_metadata["kb_safe_description"] = "A renamed presentation description"
    candidate.permission.safe_metadata["collection_safe_label"] = (
        "Renamed Finance Knowledge"
    )
    collection.safe_metadata["safe_topics"][0]["protected_collection_id"] = str(
        uuid4()
    )
    collection.safe_metadata["safe_topics"][0]["safe_label"] = "Renamed nested label"
    collection.safe_metadata["safe_topics"][0]["description"] = (
        "A renamed nested description"
    )
    after = intent_cache_knowledge.current_knowledge_context_fingerprint(**kwargs)

    assert before == after
    assert captured_context_projections
    outer_projection = json.dumps(
        captured_context_projections[-1], sort_keys=True, separators=(",", ":")
    )
    assert str(collection_id) not in outer_projection
    assert str(knowledge_id) not in outer_projection
    assert "Finance Knowledge" not in outer_projection
    assert "presentation description" not in outer_projection
    assert "Renamed nested label" not in outer_projection
    assert "nested description" not in outer_projection