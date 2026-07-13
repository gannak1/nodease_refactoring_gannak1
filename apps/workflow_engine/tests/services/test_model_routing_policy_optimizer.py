from apps.shared.services.model_routing_policy_optimizer import (
    ModelRoutingGateProfile,
    ModelRoutingOptimizationRequest,
    ModelRoutingPolicyOptimizer,
    wilson_lower_bound,
)
from apps.workflow_engine.services.model_routing_evidence import RoutingEvidenceSample


def _samples(
    *,
    count: int,
    cohort_id: str = "routine_support",
    candidate_model: str = "gpt-4o-mini",
    baseline_model: str = "gpt-4.1",
    candidate_quality: float = 89.0,
    baseline_quality: float = 90.0,
    candidate_cost: float = 0.001,
    baseline_cost: float = 0.01,
    candidate_latency_ms: float = 400,
    baseline_latency_ms: float = 1200,
    failed_indexes: set[int] | None = None,
    schema_failed_indexes: set[int] | None = None,
    downstream_failed_indexes: set[int] | None = None,
    evaluation_cost: float = 0.00002,
) -> tuple[RoutingEvidenceSample, ...]:
    failed_indexes = failed_indexes or set()
    schema_failed_indexes = schema_failed_indexes or set()
    downstream_failed_indexes = downstream_failed_indexes or set()
    return tuple(
        RoutingEvidenceSample(
            source="replay",
            model_id=candidate_model,
            semantic_cohort_id=cohort_id,
            baseline_model_id=baseline_model,
            execution_succeeded=index not in failed_indexes,
            schema_passed=index not in schema_failed_indexes,
            downstream_passed=index not in downstream_failed_indexes,
            quality_score=(
                candidate_quality
                if index not in failed_indexes | schema_failed_indexes
                else None
            ),
            baseline_quality_score=baseline_quality,
            quality_confidence=0.9,
            execution_cost=candidate_cost,
            baseline_execution_cost=baseline_cost,
            evaluation_cost=evaluation_cost,
            latency_ms=candidate_latency_ms,
            baseline_latency_ms=baseline_latency_ms,
            candidate_id=f"candidate-{index}",
            route_catalog_version="ticket-routing-v1",
        )
        for index in range(count)
    )


def _request(
    samples: tuple[RoutingEvidenceSample, ...],
    *,
    embedding_cost_per_request: float = 0.00001,
    gate_profile: ModelRoutingGateProfile | None = None,
) -> ModelRoutingOptimizationRequest:
    return ModelRoutingOptimizationRequest(
        default_model_id="gpt-4.1",
        evidence_samples=samples,
        objective="cost",
        expected_request_count=100,
        embedding_cost_per_request=embedding_cost_per_request,
        evidence_version="evidence-v1",
        gate_profile=gate_profile or ModelRoutingGateProfile(),
    )


def test_wilson_lower_bound_penalizes_small_perfect_samples():
    assert wilson_lower_bound(2, 2) < 0.7
    assert wilson_lower_bound(20, 20) > wilson_lower_bound(2, 2)
    assert wilson_lower_bound(20, 20) < 1.0


def test_optimizer_keeps_current_model_when_candidate_samples_are_too_few():
    result = ModelRoutingPolicyOptimizer.optimize(_request(_samples(count=2)))

    assert result.status == "kept_current"
    assert result.rules == ()
    assert result.cohort_decisions[0].reason_code == "candidate_samples_insufficient"


def test_optimizer_selects_cheaper_candidate_after_quality_and_net_savings_gates():
    result = ModelRoutingPolicyOptimizer.optimize(_request(_samples(count=20)))

    assert result.status == "applied"
    assert len(result.rules) == 1
    rule = result.rules[0]
    assert rule["when"] == {"semantic_cohort_id": "routine_support"}
    assert rule["selected_model_id"] == "gpt-4o-mini"
    assert rule["fallback_model_id"] == "gpt-4.1"
    assert rule["evidence_version"] == "evidence-v1"
    assert rule["gate_profile_version"] == "workflow-aware-gate-v1"
    assert result.cohort_decisions[0].expected_net_savings > 0


def test_optimizer_rejects_cheaper_candidate_below_baseline_quality_floor():
    result = ModelRoutingPolicyOptimizer.optimize(
        _request(_samples(count=20, candidate_quality=82, baseline_quality=90))
    )

    assert result.status == "kept_current"
    assert result.rules == ()
    assert result.cohort_decisions[0].reason_code == "quality_floor_failed"
    assert result.cohort_decisions[0].candidate_quality_lower_bound is not None
    assert result.cohort_decisions[0].baseline_quality_lower_bound is not None
    assert (
        result.cohort_decisions[0].candidate_quality_lower_bound
        < result.cohort_decisions[0].baseline_quality_lower_bound
    )


def test_optimizer_rejects_candidate_when_routing_overhead_removes_savings():
    result = ModelRoutingPolicyOptimizer.optimize(
        _request(
            _samples(
                count=20,
                candidate_cost=0.0099,
                baseline_cost=0.01,
                evaluation_cost=0.0005,
            ),
            embedding_cost_per_request=0.0002,
        )
    )

    assert result.status == "kept_current"
    assert result.rules == ()
    assert result.cohort_decisions[0].reason_code == "net_savings_not_positive"


def test_optimizer_changes_only_cohort_with_validated_candidate():
    routine = _samples(count=20, cohort_id="routine_support")
    high_risk = _samples(
        count=20,
        cohort_id="high_risk",
        candidate_quality=75,
        baseline_quality=92,
    )

    result = ModelRoutingPolicyOptimizer.optimize(_request(routine + high_risk))

    assert result.status == "applied"
    assert [rule["when"]["semantic_cohort_id"] for rule in result.rules] == [
        "routine_support"
    ]
    decisions = {item.cohort_id: item for item in result.cohort_decisions}
    assert decisions["routine_support"].selected_model_id == "gpt-4o-mini"
    assert decisions["high_risk"].selected_model_id == "gpt-4.1"
