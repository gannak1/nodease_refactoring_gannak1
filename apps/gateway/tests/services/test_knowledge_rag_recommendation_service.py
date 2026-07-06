import uuid

from apps.gateway.services.knowledge_rag_recommendation_service import (
    GENERIC_KB_LABEL,
    KnowledgeRAGRecommendationService,
)
from apps.shared.schemas.knowledge import (
    KnowledgeCandidate,
    KnowledgeCandidateResolution,
    KnowledgePermissionDecision,
    KnowledgeRAGRecommendationRequest,
)


def _candidate(
    *,
    candidate_id: uuid.UUID | None = None,
    safe_label: str | None = "휴가 규정",
    runtime_availability: str = "unknown",
    safe_metadata: dict | None = None,
) -> KnowledgeCandidate:
    return KnowledgeCandidate(
        candidate_id=candidate_id or uuid.uuid4(),
        candidate_type="knowledge_base",
        permission=KnowledgePermissionDecision(
            allowed=True,
            reason_code="allowed",
            external_reason_code="allowed",
            safe_metadata=safe_metadata or {},
        ),
        runtime_availability=runtime_availability,
        safe_label=safe_label,
        safe_metadata=safe_metadata or {},
    )


class FakeResolver:
    def __init__(self, resolution: KnowledgeCandidateResolution):
        self.resolution = resolution
        self.explicit_calls = []
        self.auto_calls = []

    def resolve_explicit_kbs(self, knowledge_base_ids):
        self.explicit_calls.append(list(knowledge_base_ids))
        return self.resolution

    def resolve_auto_collection_candidates(
        self,
        *,
        collection_ids=None,
        max_collections=20,
        max_candidate_kbs=5000,
    ):
        self.auto_calls.append(
            {
                "collection_ids": collection_ids,
                "max_collections": max_collections,
                "max_candidate_kbs": max_candidate_kbs,
            }
        )
        return self.resolution


def _service(resolver: FakeResolver) -> KnowledgeRAGRecommendationService:
    return KnowledgeRAGRecommendationService(
        None,
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        resolver=resolver,
    )


def test_recommendation_returns_kb_item_and_collection_summary_only():
    kb_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    resolver = FakeResolver(
        KnowledgeCandidateResolution(
            candidates=[
                _candidate(
                    candidate_id=kb_id,
                    safe_metadata={
                        "collection_id": str(collection_id),
                        "collection_safe_label": "HR 정책",
                        "route_scope_type": "auto_collection",
                        "linked_kb_count_bucket": "2-10",
                        "source_tier": "company_policy",
                        "sync_state": "synced",
                    },
                )
            ],
            hidden_candidate_count_bucket="2-10",
            unavailable_candidate_count_bucket="1",
        )
    )

    result = _service(resolver).recommend_for_builder(
        KnowledgeRAGRecommendationRequest(
            workflow_intent="신입 직원 휴가 규정 답변",
            node_purpose="HR policy answer",
            mode="auto",
            collection_ids=[collection_id],
        )
    )

    assert resolver.auto_calls
    recommendation = result.recommendations[0]
    assert recommendation.candidate_type == "knowledge_base"
    assert recommendation.candidate_id == kb_id
    assert recommendation.recommendation_id.startswith("rec-")
    assert str(kb_id) not in recommendation.recommendation_id
    assert recommendation.materialized_knowledge_bases[0].id == kb_id
    assert recommendation.materialized_knowledge_bases[0].name == "휴가 규정"
    assert recommendation.source_collection_summary is not None
    assert recommendation.source_collection_summary.safe_label == "HR 정책"
    assert recommendation.source_collection_summary.linked_kb_count_bucket == "2-10"
    assert "raw_source_url" not in result.model_dump_json()
    assert "exact_denied_count" not in result.model_dump_json()


def test_recommendation_uses_generic_label_without_raw_kb_name():
    kb_id = uuid.uuid4()
    resolver = FakeResolver(
        KnowledgeCandidateResolution(
            candidates=[_candidate(candidate_id=kb_id, safe_label=None)],
        )
    )

    result = _service(resolver).recommend_for_builder(
        KnowledgeRAGRecommendationRequest(
            workflow_intent="계약 검토",
            mode="explicit_kb",
            knowledge_base_ids=[kb_id],
        )
    )

    recommendation = result.recommendations[0]
    assert recommendation.safe_label is None
    assert recommendation.materialized_knowledge_bases[0].name == GENERIC_KB_LABEL
    assert "safe_label_unavailable" in recommendation.warnings


def test_high_risk_domain_only_changes_recommended_options():
    resolver = FakeResolver(
        KnowledgeCandidateResolution(candidates=[_candidate(runtime_availability="available")])
    )

    result = _service(resolver).recommend_for_builder(
        KnowledgeRAGRecommendationRequest(
            workflow_intent="계약 위반 기준 확인",
            high_risk_domain="legal",
        )
    )

    recommendation = result.recommendations[0]
    assert recommendation.recommended_options.evidenceSufficiencyPolicy == "strict_citation"
    assert recommendation.recommended_options.queryRewriteMode == "template"
    assert recommendation.safe_reason_code == "high_risk_domain_requires_citation"
    assert recommendation.runtime_availability == "available"


def test_intended_subject_absence_keeps_runtime_availability_unknown_warning():
    resolver = FakeResolver(KnowledgeCandidateResolution(candidates=[_candidate()]))

    result = _service(resolver).recommend_for_builder(
        KnowledgeRAGRecommendationRequest(workflow_intent="복지 안내")
    )

    recommendation = result.recommendations[0]
    assert recommendation.runtime_availability == "unknown"
    assert "runtime_availability_unknown" in recommendation.warnings


def test_request_normalizes_control_characters_and_rejects_blank_text():
    request = KnowledgeRAGRecommendationRequest(
        workflow_intent="휴가\x00\x01 규정\n답변",
        node_purpose=" HR\tpolicy ",
    )

    assert request.workflow_intent == "휴가 규정 답변"
    assert request.node_purpose == "HR policy"

    try:
        KnowledgeRAGRecommendationRequest(workflow_intent="\x00\n\t")
    except ValueError as exc:
        assert "text must not be empty" in str(exc)
    else:  # pragma: no cover - pydantic must reject blank raw input
        raise AssertionError("blank workflow intent was accepted")


def test_recommendation_cap_and_stable_ranking():
    lower = _candidate(
        candidate_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        safe_label="복지 안내",
        runtime_availability="unknown",
    )
    higher = _candidate(
        candidate_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        safe_label="휴가 정책",
        runtime_availability="available",
        safe_metadata={"source_tier": "company_policy"},
    )
    resolver = FakeResolver(KnowledgeCandidateResolution(candidates=[lower, higher]))

    result = _service(resolver).recommend_for_builder(
        KnowledgeRAGRecommendationRequest(
            workflow_intent="휴가 정책",
            max_recommendations=1,
        )
    )

    assert len(result.recommendations) == 1
    assert result.recommendations[0].candidate_id == higher.candidate_id
    assert result.summary.recommendation_count_bucket == "1"
