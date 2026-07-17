"""FR-011: 전역 모델 profile과 노드별 운영 성적을 함께 점수화한다."""

from apps.workflow_engine.services.model_router import (
    ModelCandidate,
    ModelPerformance,
    NodeRunProfile,
)
from apps.workflow_engine.services.model_routing_bootstrap import (
    PersistedModelRoutingBootstrapStore,
)
from apps.workflow_engine.services.model_routing_constraint_difficulty import (
    ConstraintModelCandidate,
)
from apps.workflow_engine.services.model_routing_global_profiles import (
    GlobalModelProfile,
    ModelRoutingComplexityEstimate,
    ModelRoutingDifficultyDistribution,
    ModelRoutingGlobalProfileScorer,
)


def _candidate(
    model_id: str,
    *,
    input_price: float,
    output_price: float,
) -> ConstraintModelCandidate:
    return ConstraintModelCandidate(
        model_id=model_id,
        context_window=128_000,
        input_price_1k=input_price,
        output_price_1k=output_price,
        capability_tier="balanced",
        supports_strict_structured_output=True,
    )


def _profile(
    model_id: str,
    *,
    economy: float,
    balanced: float,
    advanced: float,
    latency_ms: int,
    prior_strength: float = 6.0,
) -> GlobalModelProfile:
    return GlobalModelProfile(
        model_id=model_id,
        quality_by_difficulty={
            "economy": economy,
            "balanced": balanced,
            "advanced": advanced,
        },
        uncertainty_by_difficulty={
            "economy": 0.03,
            "balanced": 0.04,
            "advanced": 0.05,
        },
        expected_latency_ms_by_input_profile={
            "short": latency_ms,
            "medium": latency_ms,
            "long": latency_ms * 2,
        },
        fallback_rate=0.02,
        prior_strength=prior_strength,
        source="test_catalog",
        profile_version="test-v1",
    )


def test_global_profiles_score_every_available_model_not_only_three_representatives():
    """난이도 결과는 사용 가능한 모든 후보를 순위화해야 한다."""
    candidates = (
        _candidate("gpt-4o-mini", input_price=0.00015, output_price=0.0006),
        _candidate("gpt-5-mini", input_price=0.00025, output_price=0.002),
        _candidate("gpt-5.4", input_price=0.0025, output_price=0.015),
        _candidate("gpt-5.6", input_price=0.005, output_price=0.03),
    )
    profiles = {
        "gpt-4o-mini": _profile(
            "gpt-4o-mini", economy=0.95, balanced=0.82, advanced=0.60, latency_ms=400
        ),
        "gpt-5-mini": _profile(
            "gpt-5-mini", economy=0.97, balanced=0.91, advanced=0.83, latency_ms=650
        ),
        "gpt-5.4": _profile(
            "gpt-5.4", economy=0.99, balanced=0.97, advanced=0.96, latency_ms=1_200
        ),
        "gpt-5.6": _profile(
            "gpt-5.6", economy=0.995, balanced=0.98, advanced=0.98, latency_ms=1_600
        ),
    }

    result = ModelRoutingGlobalProfileScorer.rank(
        candidates=candidates,
        global_profiles=profiles,
        difficulty=ModelRoutingDifficultyDistribution(advanced=1.0),
        input_profile="medium",
        estimated_input_tokens=800,
        estimated_output_tokens=300,
        default_model_id="gpt-5.4",
    )

    assert {score.model_id for score in result.ranked_candidates} == {
        "gpt-4o-mini",
        "gpt-5-mini",
        "gpt-5.4",
        "gpt-5.6",
    }
    assert result.selected_model_id == "gpt-5.4"
    assert result.by_model["gpt-5.4"].selection_eligible is True
    assert result.by_model["gpt-4o-mini"].selection_eligible is False


def test_global_profiles_choose_the_closest_sufficient_model_for_a_continuous_score():
    candidates = (
        _candidate("gpt-4o-mini", input_price=0.00015, output_price=0.0006),
        _candidate("gpt-5-mini", input_price=0.00025, output_price=0.002),
        _candidate("gpt-5.4", input_price=0.0025, output_price=0.015),
    )
    profiles = {
        "gpt-4o-mini": _profile(
            "gpt-4o-mini", economy=0.95, balanced=0.70, advanced=0.35, latency_ms=400
        ),
        "gpt-5-mini": _profile(
            "gpt-5-mini", economy=0.97, balanced=0.91, advanced=0.80, latency_ms=650
        ),
        "gpt-5.4": _profile(
            "gpt-5.4", economy=0.99, balanced=0.97, advanced=0.96, latency_ms=1_200
        ),
    }

    result = ModelRoutingGlobalProfileScorer.rank(
        candidates=candidates,
        global_profiles=profiles,
        difficulty=ModelRoutingDifficultyDistribution(balanced=1.0),
        complexity=ModelRoutingComplexityEstimate(score=64.0, uncertainty=4.0),
        input_profile="medium",
        estimated_input_tokens=800,
        estimated_output_tokens=300,
        default_model_id="gpt-5.4",
    )

    assert result.selected_model_id == "gpt-5-mini"
    assert result.complexity_score == 64.0
    assert result.quality_floor > 0.78


def test_node_specific_operational_score_can_override_global_profile_when_evidence_is_strong():
    """같은 노드에서 쌓인 충분한 성공 성적은 전역 기본 추정보다 우선한다."""
    candidates = (
        _candidate("gpt-5-mini", input_price=0.00025, output_price=0.002),
        _candidate("gpt-5.4", input_price=0.0025, output_price=0.015),
    )
    profiles = {
        "gpt-5-mini": _profile(
            "gpt-5-mini", economy=0.92, balanced=0.75, advanced=0.58, latency_ms=550,
            prior_strength=4.0,
        ),
        "gpt-5.4": _profile(
            "gpt-5.4", economy=0.99, balanced=0.97, advanced=0.96, latency_ms=1_300,
            prior_strength=4.0,
        ),
    }
    mini_evidence = ModelPerformance(
        model_id="gpt-5-mini",
        run_count=30,
        success_count=30,
        schema_pass_count=30,
        schema_eval_count=30,
        downstream_success_count=30,
        downstream_eval_count=30,
        total_cost=0.03,
        total_latency_ms=12_000,
    )
    node_profile = NodeRunProfile(
        operational_usable_runs=30,
        model_performance={"gpt-5-mini": mini_evidence},
        segment_performance={
            "medium": {
                "conditions": {"input_length_bucket": "medium"},
                "model_performance": {"gpt-5-mini": mini_evidence},
            }
        },
    )

    result = ModelRoutingGlobalProfileScorer.rank(
        candidates=candidates,
        global_profiles=profiles,
        difficulty=ModelRoutingDifficultyDistribution(balanced=1.0),
        input_profile="medium",
        estimated_input_tokens=900,
        estimated_output_tokens=250,
        default_model_id="gpt-5.4",
        node_profile=node_profile,
    )

    mini = result.by_model["gpt-5-mini"]
    assert mini.effective_operational_samples == 30
    assert mini.profile_source == "test_catalog+node_operational"
    assert mini.posterior_quality_mean > 0.95
    assert result.selected_model_id == "gpt-5-mini"


def test_missing_node_evidence_keeps_global_profile_and_configured_default_is_safe_fallback():
    """운영 성적이 없다고 모델을 제외하지 않고 전역 profile로 점수화한다."""
    candidates = (
        _candidate("gpt-5-mini", input_price=0.00025, output_price=0.002),
        _candidate("gpt-5.4", input_price=0.0025, output_price=0.015),
    )
    profiles = {
        "gpt-5-mini": _profile(
            "gpt-5-mini", economy=0.96, balanced=0.90, advanced=0.72, latency_ms=650
        ),
        "gpt-5.4": _profile(
            "gpt-5.4", economy=0.99, balanced=0.97, advanced=0.96, latency_ms=1_100
        ),
    }

    result = ModelRoutingGlobalProfileScorer.rank(
        candidates=candidates,
        global_profiles=profiles,
        difficulty=ModelRoutingDifficultyDistribution(economy=1.0),
        input_profile="short",
        estimated_input_tokens=100,
        estimated_output_tokens=80,
        default_model_id="gpt-5.4",
    )

    assert result.selected_model_id == "gpt-5-mini"
    assert result.fallback_model_id == "gpt-5.4"
    assert result.by_model["gpt-5-mini"].effective_operational_samples == 0
    assert result.by_model["gpt-5-mini"].profile_source == "test_catalog"


def test_bootstrap_policy_uses_global_profile_scores_instead_of_price_rank(monkeypatch):
    """초기 정책도 가격순 첫·중간·마지막 모델만 고르지 않는다."""
    profiles = {
        "gpt-4o-mini": _profile(
            "gpt-4o-mini", economy=0.95, balanced=0.72, advanced=0.45, latency_ms=350
        ),
        "gpt-5-mini": _profile(
            "gpt-5-mini", economy=0.91, balanced=0.91, advanced=0.75, latency_ms=600
        ),
        "gpt-5.4": _profile(
            "gpt-5.4", economy=0.99, balanced=0.97, advanced=0.96, latency_ms=1_200
        ),
        "gpt-5.6": _profile(
            "gpt-5.6", economy=0.995, balanced=0.98, advanced=0.98, latency_ms=1_700
        ),
    }
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_routing_bootstrap.ModelRoutingGlobalProfileStore.resolve_available_profiles",
        classmethod(lambda cls, db, **kwargs: profiles),
    )
    candidates = [
        ModelCandidate("gpt-4o-mini", "GPT-4o mini", 0.00015, 0.0006),
        ModelCandidate("gpt-5-mini", "GPT-5 mini", 0.00025, 0.002),
        ModelCandidate("gpt-5.4", "GPT-5.4", 0.0025, 0.015),
        ModelCandidate("gpt-5.6", "GPT-5.6", 0.005, 0.03),
    ]

    selected, matches, catalog = PersistedModelRoutingBootstrapStore._difficulty_model_selection(
        object(),
        candidates,
        default_model_id="gpt-5.4",
        node_data={"parameters": {"max_tokens": 512}},
    )

    assert selected == {
        "economy": "gpt-4o-mini",
        "balanced": "gpt-5-mini",
        "advanced": "gpt-5.4",
    }
    assert matches["advanced"]["compared_model_count"] == 4
    assert matches["advanced"]["profile_source"] == "test_catalog"
    assert len(catalog["candidates"]) == 4
    assert set(catalog["profiles"]) == {
        "gpt-4o-mini",
        "gpt-5-mini",
        "gpt-5.4",
        "gpt-5.6",
    }
