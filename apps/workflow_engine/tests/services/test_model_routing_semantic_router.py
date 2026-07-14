"""FR-011-A21~A26: semantic cohort matcher와 policy 연결 계약 테스트."""

from types import SimpleNamespace

from apps.workflow_engine.services.model_router import ModelRouter
from apps.workflow_engine.services.model_routing_semantic_router import (
    SemanticLexicalSignal,
    SemanticRouteCatalog,
    SemanticRouteDefinition,
    SemanticRouteMatcher,
)


def _catalog(
    *,
    routine_threshold: float = 0.75,
    high_risk_threshold: float = 0.75,
    min_margin: float = 0.05,
) -> SemanticRouteCatalog:
    return SemanticRouteCatalog(
        version="ticket-routing-v1",
        encoder_model_id="text-embedding-test",
        top_k=4,
        aggregation="mean",
        min_margin=min_margin,
        routes=(
            SemanticRouteDefinition(
                cohort_id="routine_support",
                label="단순 사용·안내 문의",
                threshold=routine_threshold,
                representative_vectors=(
                    (1.0, 0.0, 0.0),
                    (0.98, 0.02, 0.0),
                    (0.96, 0.04, 0.0),
                ),
            ),
            SemanticRouteDefinition(
                cohort_id="high_risk_support",
                label="보안·보상·장애 문의",
                threshold=high_risk_threshold,
                representative_vectors=(
                    (0.0, 1.0, 0.0),
                    (0.02, 0.98, 0.0),
                    (0.04, 0.96, 0.0),
                ),
            ),
        ),
    )


def _policy() -> dict:
    return {
        "active_policy": {
            "default_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "semantic_router": {
                "route_catalog_version": "ticket-routing-v1",
                "encoder_model_id": "text-embedding-test",
                "top_k": 4,
                "aggregation": "mean",
                "min_margin": 0.1,
                "routes": [
                    {
                        "cohort_id": "routine_support",
                        "label": "단순 사용·안내 문의",
                        "threshold": 0.6,
                        "representatives": [
                            {"embedding": [1.0, 0.0, 0.0]},
                            {"embedding": [0.98, 0.02, 0.0]},
                        ],
                    },
                    {
                        "cohort_id": "high_risk_support",
                        "label": "보안·보상·장애 문의",
                        "threshold": 0.6,
                        "representatives": [
                            {"embedding": [0.0, 1.0, 0.0]},
                            {"embedding": [0.02, 0.98, 0.0]},
                        ],
                    },
                ],
            },
            "rules": [
                {
                    "id": "routine-low-cost",
                    "priority": 10,
                    "when": {"semantic_cohort_id": "routine_support"},
                    "selected_model_id": "gpt-4o-mini",
                    "fallback_model_id": "gpt-4.1-mini",
                    "reason_code": "semantic_routine_validated_low_cost",
                },
                {
                    "id": "high-risk-strong",
                    "priority": 10,
                    "when": {"semantic_cohort_id": "high_risk_support"},
                    "selected_model_id": "gpt-4.1",
                    "reason_code": "semantic_high_risk_quality_floor",
                },
            ],
        }
    }


def _node_data() -> SimpleNamespace:
    return SimpleNamespace(
        model_id="gpt-4.1-mini",
        fallback_model_id="gpt-4.1",
        knowledgeBases=[],
        output_format={"type": "json", "schema": {"type": "object"}},
        system_prompt="",
        user_prompt="",
        assistant_prompt="",
    )


def test_semantic_matcher_groups_top_k_scores_by_route_and_uses_mean():
    """Aurelio식 top-k 결과를 Route별로 묶어 평균 점수가 가장 높은 군을 고른다."""
    match = SemanticRouteMatcher.match(
        _catalog(),
        query_vector=(1.0, 0.0, 0.0),
    )

    assert match.status == "matched"
    assert match.cohort_id == "routine_support"
    assert match.label == "단순 사용·안내 문의"
    assert match.similarity is not None and match.similarity > 0.99
    assert match.threshold == 0.75
    assert match.runner_up_score is not None
    assert match.margin is not None and match.margin > 0.05


def test_semantic_matcher_centroid_ignores_one_accidental_nearest_example():
    """A36: 대표 문장 하나의 우연한 최고점보다 Route 전체 중심을 사용한다."""
    catalog = SemanticRouteCatalog(
        version="ticket-routing-centroid-v1",
        encoder_model_id="text-embedding-test",
        aggregation="centroid",
        min_margin=0,
        routes=(
            SemanticRouteDefinition(
                cohort_id="routine_support",
                label="일반 안내",
                threshold=0,
                representative_vectors=((0.9, 0.1), (0.8, 0.2)),
                centroid_vector=(0.85, 0.15),
            ),
            SemanticRouteDefinition(
                cohort_id="high_risk",
                label="고위험",
                threshold=0,
                representative_vectors=((1.0, 0.0), (-0.9, 0.2)),
                centroid_vector=(0.05, 0.1),
            ),
        ),
    )

    match = SemanticRouteMatcher.match(catalog, query_vector=(1.0, 0.0))

    assert match.status == "matched"
    assert match.cohort_id == "routine_support"
    assert match.similarity is not None and match.similarity > 0.98


def test_semantic_matcher_rejects_top_route_below_its_threshold():
    """최고 점수가 있어도 Route threshold를 넘지 못하면 기본 모델로 닫을 수 있다."""
    match = SemanticRouteMatcher.match(
        _catalog(routine_threshold=1.01),
        query_vector=(1.0, 0.0, 0.0),
    )

    assert match.status == "no_match"
    assert match.cohort_id is None
    assert match.label is None
    assert match.candidate_cohort_id == "routine_support"
    assert match.candidate_label == "단순 사용·안내 문의"
    assert match.similarity is not None
    assert match.threshold == 1.01


def test_semantic_matcher_rejects_ambiguous_routes_below_min_margin():
    """1위와 2위가 너무 비슷하면 저비용 Route를 임의로 고르지 않는다."""
    match = SemanticRouteMatcher.match(
        _catalog(
            routine_threshold=0.6,
            high_risk_threshold=0.6,
            min_margin=0.1,
        ),
        query_vector=(1.0, 1.0, 0.0),
    )

    assert match.status == "ambiguous"
    assert match.cohort_id is None
    assert match.label is None
    assert match.candidate_cohort_id == "high_risk_support"
    assert match.candidate_label == "보안·보상·장애 문의"
    assert match.margin is not None and match.margin < 0.1


def test_semantic_matcher_returns_safe_trace_metadata_without_vectors():
    """Trace에는 판정 근거만 남고 query/대표 embedding vector는 남지 않는다."""
    metadata = SemanticRouteMatcher.match(
        _catalog(),
        query_vector=(1.0, 0.0, 0.0),
    ).as_metadata()

    assert metadata["cohort_matcher"] == "semantic"
    assert metadata["semantic_match_status"] == "matched"
    assert metadata["semantic_route_label"] == "단순 사용·안내 문의"
    assert metadata["semantic_candidate_cohort_id"] == "routine_support"
    assert metadata["semantic_candidate_label"] == "단순 사용·안내 문의"
    assert metadata["route_catalog_version"] == "ticket-routing-v1"
    assert metadata["semantic_encoder_model"] == "text-embedding-test"
    assert "query_vector" not in metadata
    assert "representative_vectors" not in metadata


def test_semantic_matcher_trace_includes_all_cohort_scores_and_margin_gate():
    """상세 화면은 모든 입력군의 safe 점수와 최소 점수 차이를 표시한다."""
    metadata = SemanticRouteMatcher.match(
        _catalog(),
        query_vector=(1.0, 0.0, 0.0),
    ).as_metadata()

    scores = metadata["semantic_cohort_scores"]
    assert [score["cohort_id"] for score in scores] == [
        "routine_support",
        "high_risk_support",
    ]
    assert scores[0]["label"] == "단순 사용·안내 문의"
    assert scores[0]["similarity"] > scores[1]["similarity"]
    assert scores[0]["threshold"] == 0.75
    assert metadata["semantic_min_margin"] == 0.05
    assert "embedding" not in str(scores)


def test_semantic_catalog_requires_supported_aggregation():
    """지원하지 않는 집계 방식은 조용히 다른 의미로 계산하지 않는다."""
    try:
        SemanticRouteCatalog(
            version="ticket-routing-v1",
            encoder_model_id="text-embedding-test",
            aggregation="median",
            routes=_catalog().routes,
        )
    except ValueError as exc:
        assert "aggregation" in str(exc)
    else:
        raise AssertionError("unsupported aggregation must be rejected")


def test_policy_evaluator_routes_different_semantic_cohorts_to_different_models():
    """A25: semantic cohort는 검증된 active policy 모델 mapping에만 사용된다."""
    routine = ModelRouter.resolve_policy(
        _policy(),
        inputs={"message": "다운로드 위치를 알려 주세요."},
        node_data=_node_data(),
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"],
        semantic_query_vector=(1.0, 0.0, 0.0),
    )
    high_risk = ModelRouter.resolve_policy(
        _policy(),
        inputs={"message": "보안 사고 보상 여부를 검토해 주세요."},
        node_data=_node_data(),
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"],
        semantic_query_vector=(0.0, 1.0, 0.0),
    )

    assert routine.selected_model_id == "gpt-4o-mini"
    assert routine.matched_rule_id == "routine-low-cost"
    assert routine.semantic_match is not None
    assert routine.semantic_match.cohort_id == "routine_support"
    assert high_risk.selected_model_id == "gpt-4.1"
    assert high_risk.matched_rule_id == "high-risk-strong"
    assert high_risk.semantic_match is not None
    assert high_risk.semantic_match.cohort_id == "high_risk_support"


def test_policy_evaluator_keeps_default_model_for_ambiguous_semantic_input():
    """A24: semantic 점수가 애매하면 싼 모델 대신 policy default를 유지한다."""
    decision = ModelRouter.resolve_policy(
        _policy(),
        inputs={"message": "서로 다른 의미가 섞인 문의"},
        node_data=_node_data(),
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"],
        semantic_query_vector=(1.0, 1.0, 0.0),
    )

    assert decision.selected_model_id == "gpt-4.1-mini"
    assert decision.matched_rule_id is None
    assert decision.reason_code == "semantic_ambiguous_default"
    assert decision.semantic_match is not None
    assert decision.semantic_match.status == "ambiguous"


def test_policy_evaluator_does_not_select_unavailable_semantic_rule_model():
    """A25: cohort가 맞아도 실행 주체가 사용할 수 없는 모델은 선택하지 않는다."""
    decision = ModelRouter.resolve_policy(
        _policy(),
        inputs={"message": "다운로드 위치를 알려 주세요."},
        node_data=_node_data(),
        available_model_ids=["gpt-4.1-mini", "gpt-4.1"],
        semantic_query_vector=(1.0, 0.0, 0.0),
    )

    assert decision.selected_model_id == "gpt-4.1-mini"
    assert decision.matched_rule_id is None
    assert decision.semantic_match is not None
    assert decision.semantic_match.cohort_id == "routine_support"


def test_policy_explains_matched_cohort_without_validated_model_rule():
    """FR-011: Route 판정 성공과 모델 rule 부재를 unavailable로 혼동하지 않는다."""
    policy = _policy()
    policy["active_policy"]["rules"] = []

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "보안 사고 보상 여부를 검토해 주세요."},
        node_data=_node_data(),
        available_model_ids=["gpt-4.1-mini", "gpt-4.1"],
        semantic_query_vector=(0.0, 1.0, 0.0),
    )

    assert decision.semantic_match is not None
    assert decision.semantic_match.cohort_id == "high_risk_support"
    assert decision.selected_model_id == "gpt-4.1-mini"
    assert decision.reason_code == "semantic_matched_no_rule_default"


def _hybrid_catalog(*, include_policy_signals: bool = True) -> SemanticRouteCatalog:
    """A43: 주제 Route와 안전 Route가 겹치는 최소 policy catalog다."""
    return SemanticRouteCatalog(
        version="ticket-routing-hybrid-v1",
        encoder_model_id="text-embedding-test",
        aggregation="centroid",
        min_margin=0,
        routes=(
            SemanticRouteDefinition(
                cohort_id="account_billing",
                label="계정 및 결제 문제",
                threshold=0,
                representative_vectors=((1.0, 0.0),),
                centroid_vector=(1.0, 0.0),
            ),
            SemanticRouteDefinition(
                cohort_id="high_risk",
                label="보안 및 고위험",
                threshold=0,
                representative_vectors=((0.0, 1.0),),
                centroid_vector=(0.0, 1.0),
                safety_override=True,
                lexical_override_threshold=1.0,
                lexical_signals=(
                    (SemanticLexicalSignal(term="credential leak", weight=1.0),)
                    if include_policy_signals
                    else ()
                ),
            ),
        ),
    )


def test_hybrid_matcher_prioritizes_policy_safety_signal_over_dense_topic():
    """A43: 결제 Route가 더 가까워도 policy 안전 신호가 있으면 고위험으로 닫는다."""
    match = SemanticRouteMatcher.match(
        _hybrid_catalog(),
        query_vector=(1.0, 0.0),
        query_text="Billing records indicate a credential leak in the admin account.",
    )

    assert match.status == "matched"
    assert match.cohort_id == "high_risk"
    assert match.decision_source == "safety_override"
    assert match.lexical_score == 1.0
    assert match.lexical_signal_count == 1
    assert match.safety_override is True


def test_hybrid_matcher_has_no_domain_keyword_without_policy_signal():
    """A43: runtime은 같은 단어가 와도 catalog에 신호가 없으면 dense 결과를 유지한다."""
    match = SemanticRouteMatcher.match(
        _hybrid_catalog(include_policy_signals=False),
        query_vector=(1.0, 0.0),
        query_text="Billing records indicate a credential leak in the admin account.",
    )

    assert match.status == "matched"
    assert match.cohort_id == "account_billing"
    assert match.decision_source == "dense"
    assert match.safety_override is False


def test_hybrid_matcher_keeps_normal_billing_query_on_dense_route():
    """A43: 일반 결제 표현만 있는 입력은 안전 override로 과잉 승격하지 않는다."""
    match = SemanticRouteMatcher.match(
        _hybrid_catalog(),
        query_vector=(1.0, 0.0),
        query_text="Please resend the invoice and explain the refund schedule.",
    )

    assert match.status == "matched"
    assert match.cohort_id == "account_billing"
    assert match.decision_source == "dense"
    assert match.lexical_score == 0
    assert match.lexical_signal_count == 0


def test_hybrid_matcher_trace_metadata_does_not_expose_text_or_signal_terms():
    """A43: trace에는 안전 판정 수치만 남고 query/signal 원문은 남지 않는다."""
    metadata = SemanticRouteMatcher.match(
        _hybrid_catalog(),
        query_vector=(1.0, 0.0),
        query_text="A CREDENTIAL   LEAK was confirmed in a billing account.",
    ).as_metadata()

    assert metadata["cohort_matcher"] == "hybrid"
    assert metadata["semantic_decision_source"] == "safety_override"
    assert metadata["semantic_lexical_score"] == 1.0
    assert metadata["semantic_lexical_signal_count"] == 1
    assert metadata["semantic_safety_override"] is True
    assert "query_text" not in metadata
    assert "credential leak" not in str(metadata).lower()


def test_policy_evaluator_uses_hybrid_safety_route_before_dense_rule():
    """A43: ModelRouter도 policy text 신호를 전달해 안전 모델 rule을 선택한다."""
    policy = _policy()
    high_risk_route = policy["active_policy"]["semantic_router"]["routes"][1]
    high_risk_route.update(
        {
            "safety_override": True,
            "lexical_override_threshold": 1.0,
            "lexical_signals": [
                {"term": "credential leak", "weight": 1.0},
            ],
        }
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "A credential leak changed the billing account."},
        node_data=_node_data(),
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"],
        semantic_query_vector=(1.0, 0.0, 0.0),
    )

    assert decision.selected_model_id == "gpt-4.1"
    assert decision.matched_rule_id == "high-risk-strong"
    assert decision.semantic_match is not None
    assert decision.semantic_match.cohort_id == "high_risk_support"
    assert decision.semantic_match.decision_source == "safety_override"
