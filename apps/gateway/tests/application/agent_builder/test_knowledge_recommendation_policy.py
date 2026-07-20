import pytest
import uuid

from apps.gateway.application.agent_builder.knowledge_recommendation import (
    CandidateSemanticScore,
    EmbeddingResolution,
    RecommendationDeadline,
    aggregate_parent_relevance,
    compose_final_recommendation_score,
    KnowledgeRecommendationRetrievalRequest,
    normalize_cosine_similarity,
    semantic_state_for_embedding_failure,
    select_parent_first_relevance,
)


@pytest.mark.parametrize(
    ("cosine_similarity", "expected"),
    [
        (-0.2, 0.0),
        (0.0, 0.0),
        (0.83, 0.83),
        (1.0000001, 1.0),
    ],
)
def test_cosine_similarity_is_clamped_to_recommendation_score(
    cosine_similarity,
    expected,
):
    assert normalize_cosine_similarity(cosine_similarity) == pytest.approx(expected)


def test_parent_relevance_uses_exact_top_three_aggregation():
    result = aggregate_parent_relevance([0.2, 0.9, 0.7, 0.5, 0.1])

    assert result == pytest.approx(0.7 * 0.9 + 0.3 * ((0.9 + 0.7 + 0.5) / 3))


def test_single_parent_relevance_equals_its_normalized_cosine_score():
    assert aggregate_parent_relevance([0.62]) == pytest.approx(0.62)


def test_parent_first_uses_available_zero_instead_of_metadata_fallback():
    assert (
        select_parent_first_relevance(
            parent_relevance=0.0,
            metadata_relevance=0.95,
            semantic_available=True,
        )
        == 0.0
    )


def test_parent_first_uses_metadata_only_when_semantic_is_unavailable():
    assert select_parent_first_relevance(
        parent_relevance=None,
        metadata_relevance=0.64,
        semantic_available=False,
    ) == pytest.approx(0.64)


def test_zero_relevance_blocks_operational_signal_score():
    assert (
        compose_final_recommendation_score(
            relevance=0.0,
            source_tier=1.0,
            availability=1.0,
            freshness=1.0,
        )
        == 0.0
    )


def test_positive_relevance_uses_documented_score_weights():
    assert compose_final_recommendation_score(
        relevance=0.8,
        source_tier=0.6,
        availability=1.0,
        freshness=0.5,
    ) == pytest.approx(0.7 * 0.8 + 0.1 * 0.6 + 0.1 * 1.0 + 0.1 * 0.5)


@pytest.mark.parametrize(
    "overrides",
    [
        {"safe_query_topics": tuple("x" for _ in range(21))},
        {"safe_query_topics": ("x" * 1001,)},
        {"deadline_ms": 10_001},
        {"candidate_kb_ids": tuple(uuid.uuid4() for _ in range(5001))},
    ],
)
def test_retrieval_request_rejects_values_over_server_bounds(overrides):
    values = {
        "organization_id": uuid.uuid4(),
        "actor_id": uuid.uuid4(),
        "safe_query_topics": ("topic",),
        "candidate_kb_ids": (uuid.uuid4(),),
        "candidate_snapshot_ref": "snapshot-1",
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        KnowledgeRecommendationRetrievalRequest(**values)


def test_retrieval_request_rejects_duplicate_candidate_ids():
    candidate_id = uuid.uuid4()

    with pytest.raises(ValueError):
        KnowledgeRecommendationRetrievalRequest(
            organization_id=uuid.uuid4(),
            actor_id=uuid.uuid4(),
            safe_query_topics=("topic",),
            candidate_kb_ids=(candidate_id, candidate_id),
            candidate_snapshot_ref="snapshot-1",
        )


@pytest.mark.parametrize(
    "reason",
    [
        "model_ambiguous",
        "credential_unavailable",
        "provider_unavailable",
        "deadline_exceeded",
    ],
)
def test_embedding_failure_reason_allowlist_is_preserved(reason):
    resolution = EmbeddingResolution.unavailable(reason)

    assert resolution.vector is None
    assert resolution.failure_reason == reason
    assert semantic_state_for_embedding_failure(resolution.failure_reason) == reason


def test_unknown_embedding_failure_collapses_without_retaining_outer_detail():
    unsafe_detail = "provider timeout: upstream-secret-marker"

    resolution = EmbeddingResolution.unavailable(unsafe_detail)

    assert resolution.failure_reason == "provider_unavailable"
    assert unsafe_detail not in repr(resolution)
    assert (
        semantic_state_for_embedding_failure(unsafe_detail)
        == "provider_unavailable"
    )


def test_successful_embedding_cannot_carry_a_failure_reason():
    with pytest.raises(ValueError):
        EmbeddingResolution(
            vector=(0.1, 0.2),
            failure_reason="provider_unavailable",
        )


def test_unknown_semantic_state_and_reason_collapse_to_safe_unavailable_score():
    unsafe_detail = "database exception with protected marker"

    score = CandidateSemanticScore(
        knowledge_base_id=uuid.uuid4(),
        semantic_state=unsafe_detail,
        parent_relevance=0.91,
        safe_reason_code=unsafe_detail,
    )

    assert score.semantic_state == "retrieval_unavailable"
    assert score.parent_relevance is None
    assert score.safe_reason_code == "retrieval_unavailable"
    assert unsafe_detail not in repr(score)


def test_available_semantic_score_uses_content_match_reason_only():
    score = CandidateSemanticScore(
        knowledge_base_id=uuid.uuid4(),
        semantic_state="available",
        parent_relevance=1.2,
        safe_reason_code="metadata_fallback",
    )

    assert score.parent_relevance == 1.0
    assert score.safe_reason_code == "content_match"


def test_absolute_deadline_reports_remaining_time_and_rejects_late_results():
    deadline = RecommendationDeadline.from_timeout_ms(
        10_000,
        now_monotonic=100.0,
    )

    assert deadline.remaining_seconds(now_monotonic=106.25) == pytest.approx(3.75)
    assert deadline.accepts_result(completed_at_monotonic=110.0)
    assert not deadline.accepts_result(completed_at_monotonic=110.000_001)
    assert deadline.remaining_seconds(now_monotonic=111.0) == 0.0


@pytest.mark.parametrize("timeout_ms", [0, 10_001])
def test_absolute_deadline_rejects_values_outside_server_budget(timeout_ms):
    with pytest.raises(ValueError):
        RecommendationDeadline.from_timeout_ms(
            timeout_ms,
            now_monotonic=100.0,
        )


def test_direct_absolute_deadline_rejects_a_budget_shorter_than_one_millisecond():
    with pytest.raises(ValueError):
        RecommendationDeadline(
            started_at_monotonic=100.0,
            expires_at_monotonic=100.0001,
        )


def test_request_carries_the_precomputed_absolute_deadline():
    deadline = RecommendationDeadline.from_timeout_ms(
        4_000,
        now_monotonic=20.0,
    )

    request = KnowledgeRecommendationRetrievalRequest(
        organization_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        safe_query_topics=("topic",),
        candidate_kb_ids=(uuid.uuid4(),),
        candidate_snapshot_ref="snapshot-1",
        deadline=deadline,
    )

    assert request.deadline is deadline
    assert request.deadline_ms == 4_000
