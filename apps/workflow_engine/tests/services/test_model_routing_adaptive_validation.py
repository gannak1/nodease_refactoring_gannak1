import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from apps.workflow_engine.services.model_routing_adaptive_validation import (
    AdaptiveValidationOutcome,
    AdaptiveValidationResultService,
)
from apps.workflow_engine.services.model_routing_adaptive_validation_service import (
    AdaptiveModelRoutingValidationService,
)
from apps.shared.db.models.model_routing_cohort import (
    LLMNodeModelRoutingModelEvidence,
)
from apps.shared.db.models.workflow_run import WorkflowRun


def _outcome(*, cost: float = 0.01, quality: float = 90.0, **overrides):
    values = {
        "execution_succeeded": True,
        "schema_passed": True,
        "downstream_passed": True,
        "quality_score": quality,
        "baseline_quality_score": 90.0,
        "quality_confidence": 0.9,
        "candidate_cost": cost,
        "baseline_cost": 0.02,
        "candidate_latency_ms": 500,
        "baseline_latency_ms": 900,
        "fallback_used": False,
    }
    values.update(overrides)
    return AdaptiveValidationOutcome(**values)


def test_candidate_is_validated_only_after_all_five_replays_pass_quality_and_contract_gates():
    result = AdaptiveValidationResultService.evaluate(
        [_outcome() for _ in range(5)],
        expected_samples=5,
    )

    assert result.status == "validated"
    assert result.quality_summary["schema_pass_rate"] == 1.0
    assert result.quality_summary["downstream_pass_rate"] == 1.0
    assert result.efficiency_summary["net_savings_per_request"] > 0


def test_candidate_replay_flattens_original_selector_input_for_synthetic_start():
    """Replay LLM도 원래 selector가 가리키던 실제 대표 문의를 받아야 한다."""
    source_graph = {
        "nodes": [
            {
                "id": "start-question",
                "type": "startNode",
                "data": {"variables": [{"id": "question", "name": "question", "label": "질문", "type": "text"}]},
            },
            {
                "id": "llm-answer",
                "type": "llmNode",
                "data": {
                    "model_id": "gpt-5.6-luna",
                    "referenced_variables": [
                        {"name": "question", "value_selector": ["start-question", "question"]}
                    ],
                },
            },
        ],
        "edges": [{"source": "start-question", "target": "llm-answer"}],
    }

    graph, replay_input = AdaptiveModelRoutingValidationService._candidate_graph(
        source_graph,
        node_id="llm-answer",
        candidate_model_id="gpt-4.1-mini",
        fallback_model_id="",
        baseline_input={"start-question": {"question": "SSO 설정 순서를 알려 주세요."}},
    )

    start = next(node for node in graph["nodes"] if node["type"] == "startNode")
    llm = next(node for node in graph["nodes"] if node["id"] == "llm-answer")
    assert replay_input == {"question": "SSO 설정 순서를 알려 주세요."}
    assert start["data"]["variables"][0]["name"] == "question"
    assert llm["data"]["referenced_variables"][0]["value_selector"] == [
        "model-routing-validation-input",
        "question",
    ]


def test_candidate_rejects_one_moderate_quality_outlier_even_when_average_is_stable():
    """대표 입력 하나의 큰 품질 하락도 입력군 전체 rule로 확대하지 않는다."""

    outcomes = [_outcome(quality=95.0) for _ in range(4)]
    outcomes.append(_outcome(quality=75.0, baseline_quality_score=90.0))

    result = AdaptiveValidationResultService.evaluate(
        outcomes,
        expected_samples=5,
    )

    assert result.status == "rejected"
    assert result.reason_code == "quality_outlier_gate_failed"
    assert result.quality_summary["quality_delta_minimum"] == -15.0
    assert result.quality_summary["quality_outlier_rate"] == 0.2


def test_candidate_is_rejected_when_one_replay_has_an_absolute_quality_failure():
    """평균이 좋아도 실제 후보 점수가 70점 미만이면 입력군 전체에 승격하지 않는다."""

    outcomes = [_outcome(quality=95.0) for _ in range(4)]
    outcomes.append(_outcome(quality=55.0, baseline_quality_score=90.0))

    result = AdaptiveValidationResultService.evaluate(
        outcomes,
        expected_samples=5,
    )

    assert result.status == "rejected"
    assert result.reason_code == "quality_outlier_gate_failed"
    assert result.quality_summary["quality_score_minimum"] == 55.0


def test_non_high_risk_candidate_can_be_promoted_when_it_preserves_low_baseline_quality():
    """정답지가 없는 RAG Judge의 낮은 절대 점수만으로 후보를 막지 않는다."""

    outcomes = [
        _outcome(quality=36.5, baseline_quality_score=31.5),
        _outcome(quality=39.0, baseline_quality_score=21.0),
        _outcome(quality=39.0, baseline_quality_score=25.0),
    ]

    result = AdaptiveValidationResultService.evaluate(
        outcomes,
        expected_samples=3,
        validation_stage="bootstrap",
    )

    assert result.status == "validated"
    assert result.reason_code == "quality_and_efficiency_gate_passed"
    assert result.quality_summary["quality_delta_minimum"] > 0


def test_non_high_risk_candidate_still_rejects_a_near_empty_answer():
    outcomes = [
        _outcome(quality=29.0, baseline_quality_score=25.0),
        _outcome(quality=38.0, baseline_quality_score=30.0),
        _outcome(quality=40.0, baseline_quality_score=31.0),
    ]

    result = AdaptiveValidationResultService.evaluate(
        outcomes,
        expected_samples=3,
        validation_stage="bootstrap",
    )

    assert result.status == "rejected"
    assert result.reason_code == "quality_relative_safety_gate_failed"


def test_safety_protected_candidate_rejects_even_one_moderate_quality_outlier():
    """보호 입력군은 품질 사고 비용이 크므로 완화된 이상치 규칙을 적용하지 않는다."""

    outcomes = [_outcome(quality=95.0) for _ in range(4)]
    outcomes.append(_outcome(quality=75.0, baseline_quality_score=90.0))

    result = AdaptiveValidationResultService.evaluate(
        outcomes,
        expected_samples=5,
        safety_protected=True,
    )

    assert result.status == "rejected"
    assert result.reason_code == "quality_outlier_gate_failed"


def test_candidate_result_summary_exposes_safe_rejection_diagnostics():
    """탈락 이유는 남기되 실제 입력과 출력은 batch summary에 복제하지 않는다."""
    cohort = SimpleNamespace(
        id=uuid.uuid4(),
        cohort_key="account-access",
    )
    result = SimpleNamespace(
        status="rejected",
        reason_code="quality_gate_failed",
        quality_summary={
            "baseline_quality_mean": 94.4,
            "candidate_quality_mean": 85.0,
            "raw_input": "저장하면 안 되는 값",
        },
        efficiency_summary={"net_savings_ratio": 0.82},
    )

    summary = AdaptiveModelRoutingValidationService._candidate_result_summary(
        cohort=cohort,
        model_id="gpt-4.1-mini",
        result=result,
        sample_count=5,
    )

    assert summary == {
        "cohort_id": str(cohort.id),
        "cohort_key": "account-access",
        "model_id": "gpt-4.1-mini",
        "status": "rejected",
        "reason_code": "quality_gate_failed",
        "sample_count": 5,
        "baseline_quality_mean": 94.4,
        "candidate_quality_mean": 85.0,
        "net_savings_ratio": 0.82,
    }


def test_validation_item_links_only_a_persisted_candidate_workflow_run():
    """비동기 run log가 아직 없으면 임시 UUID를 FK에 저장하지 않는다."""

    class _Query:
        def filter(self, *_args):
            return self

        def first(self):
            return None

    class _Db:
        def query(self, model):
            assert model is WorkflowRun
            return _Query()

    assert (
        AdaptiveModelRoutingValidationService._persisted_workflow_run_id(
            _Db(),
            uuid.uuid4(),
        )
        is None
    )


def test_rejected_evidence_does_not_block_revalidation_with_new_operational_inputs():
    """탈락 evidence는 검증 완료가 아니므로 다음 운영 window에서 다시 후보가 될 수 있다."""

    class _Query:
        def filter(self, *_args):
            return self

        def first(self):
            return None

    class _Db:
        def query(self, model):
            assert model is LLMNodeModelRoutingModelEvidence
            return _Query()

    assert (
        AdaptiveModelRoutingValidationService._model_has_validated_evidence(
            _Db(),
            cohort_id=uuid.uuid4(),
            model_id="gpt-4.1-mini",
            fingerprint="fingerprint-v1",
        )
        is False
    )


def test_bootstrap_candidate_wave_skips_any_previously_tried_model():
    """bootstrap 후속 wave는 탈락 후보 반복 대신 아직 검증하지 않은 후보로 전진한다."""
    candidates = [
        SimpleNamespace(model_id="gpt-4.1", price_score=1.0),
        SimpleNamespace(model_id="gpt-4.1-mini", price_score=0.2),
        SimpleNamespace(model_id="gpt-4o-mini", price_score=0.1),
        SimpleNamespace(model_id="gpt-5.4-mini", price_score=0.4),
    ]
    with (
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.ModelRouter.collect_candidates",
            return_value=candidates,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_model_has_any_evidence",
            side_effect=lambda *_args, model_id, **_kwargs: model_id
            in {"gpt-4.1-mini", "gpt-4o-mini"},
        ),
    ):
        planned = AdaptiveModelRoutingValidationService._candidate_models(
            MagicMock(),
            policy=SimpleNamespace(organization_id=uuid.uuid4()),
            cohort_id=uuid.uuid4(),
            fingerprint="fingerprint-v1",
            baseline_model_id="gpt-4.1",
            available_model_ids={item.model_id for item in candidates},
            exclude_prior_rejections=True,
        )

    assert planned == ["gpt-5.4-mini"]


def test_operational_revalidation_can_retry_a_rejected_model_with_new_inputs():
    """운영 observation ID가 바뀐 refresh는 과거 rejected 모델을 다시 검증할 수 있다."""
    candidates = [
        SimpleNamespace(model_id="gpt-4.1", price_score=1.0),
        SimpleNamespace(model_id="gpt-4.1-mini", price_score=0.2),
        SimpleNamespace(model_id="gpt-4o-mini", price_score=0.1),
    ]
    with (
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.ModelRouter.collect_candidates",
            return_value=candidates,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_model_has_validated_evidence",
            return_value=False,
        ),
    ):
        planned = AdaptiveModelRoutingValidationService._candidate_models(
            MagicMock(),
            policy=SimpleNamespace(organization_id=uuid.uuid4()),
            cohort_id=uuid.uuid4(),
            fingerprint="fingerprint-v1",
            baseline_model_id="gpt-4.1",
            available_model_ids={item.model_id for item in candidates},
            exclude_prior_rejections=False,
        )

    assert planned == ["gpt-4o-mini", "gpt-4.1-mini"]


def test_operational_revalidation_includes_the_current_active_model_first():
    """운영 갱신은 새 후보 탐색 전에 현재 active 모델의 품질 유지 여부를 다시 본다."""

    candidates = [
        SimpleNamespace(model_id="gpt-4.1", price_score=1.0),
        SimpleNamespace(model_id="gpt-4o-mini", price_score=0.1),
        SimpleNamespace(model_id="gpt-5.4-mini", price_score=0.4),
    ]
    with (
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.ModelRouter.collect_candidates",
            return_value=candidates,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_model_has_validated_evidence",
            side_effect=lambda *_args, model_id, **_kwargs: model_id == "gpt-5.4-mini",
        ),
    ):
        planned = AdaptiveModelRoutingValidationService._candidate_models(
            MagicMock(),
            policy=SimpleNamespace(organization_id=uuid.uuid4()),
            cohort_id=uuid.uuid4(),
            fingerprint="fingerprint-v1",
            baseline_model_id="gpt-4.1",
            available_model_ids={item.model_id for item in candidates},
            exclude_prior_rejections=False,
            active_model_id="gpt-5.4-mini",
        )

    assert planned == ["gpt-5.4-mini", "gpt-4o-mini"]


def test_operational_refresh_includes_active_cohorts_but_bootstrap_does_not():
    assert AdaptiveModelRoutingValidationService._validation_cohort_statuses(
        "auto_n_runs"
    ) == ("proposed", "validated_waiting", "active")
    assert AdaptiveModelRoutingValidationService._validation_cohort_statuses(
        "deployment_bootstrap"
    ) == ("proposed", "validated_waiting")


def test_completed_bootstrap_batch_plans_the_next_untried_candidate_wave():
    """첫 검증 탈락은 전체 탐색 종료가 아니라 다음 후보 batch 계획으로 이어진다."""
    batch = SimpleNamespace(
        id=uuid.uuid4(),
        policy_id=uuid.uuid4(),
        policy_update_id=None,
        trigger="deployment_bootstrap",
        status="completed",
        error_summary={
            "validated_route_count": 0,
            "rejected_or_waiting_cohort_count": 3,
        },
    )
    follow_up = SimpleNamespace(id=uuid.uuid4(), status="pending")
    db = MagicMock()

    with patch.object(
        AdaptiveModelRoutingValidationService,
        "plan_batch",
        return_value=follow_up,
    ) as plan_batch:
        result = (
            AdaptiveModelRoutingValidationService.plan_deployment_bootstrap_follow_up(
                db,
                batch=batch,
            )
        )

    assert result is follow_up
    plan_batch.assert_called_once_with(
        db,
        policy_id=batch.policy_id,
        trigger="deployment_bootstrap",
        policy_update_id=None,
        bootstrap_wave=2,
    )
    assert batch.error_summary["bootstrap_search_state"] == "continued"
    assert batch.error_summary["follow_up_batch_id"] == str(follow_up.id)


def test_bootstrap_search_keeps_the_default_when_no_follow_up_can_be_planned():
    """후보나 예산이 없을 때 gate를 낮추지 않고 기본 모델 유지 상태로 닫는다."""
    batch = SimpleNamespace(
        id=uuid.uuid4(),
        policy_id=uuid.uuid4(),
        policy_update_id=None,
        trigger="deployment_bootstrap",
        status="completed",
        error_summary={
            "validated_route_count": 0,
            "rejected_or_waiting_cohort_count": 2,
        },
    )
    db = MagicMock()

    with patch.object(
        AdaptiveModelRoutingValidationService,
        "plan_batch",
        return_value=None,
    ):
        result = (
            AdaptiveModelRoutingValidationService.plan_deployment_bootstrap_follow_up(
                db,
                batch=batch,
            )
        )

    assert result is None
    assert batch.error_summary["bootstrap_search_state"] == "no_follow_up_batch"
    assert batch.error_summary["follow_up_batch_id"] is None


def test_bootstrap_search_stops_after_three_candidate_waves():
    """초기 검증이 월간 예산을 끝없이 소진하지 않도록 세 번째 wave에서 닫는다."""
    batch = SimpleNamespace(
        id=uuid.uuid4(),
        policy_id=uuid.uuid4(),
        policy_update_id=None,
        trigger="deployment_bootstrap",
        status="completed",
        candidate_plan={"bootstrap_wave": 3},
        error_summary={
            "validated_route_count": 0,
            "rejected_or_waiting_cohort_count": 1,
        },
    )
    db = MagicMock()

    with patch.object(
        AdaptiveModelRoutingValidationService,
        "plan_batch",
    ) as plan_batch:
        result = (
            AdaptiveModelRoutingValidationService.plan_deployment_bootstrap_follow_up(
                db,
                batch=batch,
            )
        )

    assert result is None
    plan_batch.assert_not_called()
    assert batch.error_summary["bootstrap_search_state"] == "max_waves_reached"


def test_high_risk_candidate_never_activates_from_a_single_replay():
    result = AdaptiveValidationResultService.evaluate(
        [_outcome(quality=98.0)],
        expected_samples=1,
        safety_protected=True,
    )

    assert result.status == "rejected"
    assert result.reason_code == "high_risk_samples_insufficient"


def test_high_risk_candidate_uses_a_stricter_quality_gate():
    result = AdaptiveValidationResultService.evaluate(
        [_outcome(quality=82.0, baseline_quality_score=82.0) for _ in range(5)],
        expected_samples=5,
        safety_protected=True,
    )

    assert result.status == "rejected"
    assert result.reason_code == "high_risk_quality_floor_not_met"


def test_high_risk_candidate_can_activate_after_five_strong_replays():
    result = AdaptiveValidationResultService.evaluate(
        [
            _outcome(
                quality=95.0,
                baseline_quality_score=95.0,
                quality_confidence=0.9,
            )
            for _ in range(5)
        ],
        expected_samples=5,
        safety_protected=True,
    )

    assert result.status == "validated"
    assert result.reason_code == "quality_and_efficiency_gate_passed"


def test_schema_failure_rejects_candidate_even_when_it_is_cheaper():
    outcomes = [_outcome() for _ in range(4)] + [_outcome(schema_passed=False)]

    result = AdaptiveValidationResultService.evaluate(outcomes, expected_samples=5)

    assert result.status == "rejected"
    assert result.reason_code == "schema_gate_failed"


def test_quality_drop_or_low_confidence_rejects_candidate():
    result = AdaptiveValidationResultService.evaluate(
        [_outcome(quality=82.0, quality_confidence=0.5) for _ in range(5)],
        expected_samples=5,
    )

    assert result.status == "rejected"
    assert result.reason_code in {"quality_gate_failed", "quality_confidence_insufficient"}


def test_bootstrap_quality_gate_rejects_one_output_below_the_80_point_floor():
    """비고위험 후보도 단일 응답이 80점 미만이면 활성화하지 않는다."""
    outcomes = [
        _outcome(quality=75.0, baseline_quality_score=85.0),
        _outcome(quality=95.0, baseline_quality_score=75.0),
        _outcome(quality=92.0, baseline_quality_score=70.0),
        _outcome(quality=95.0, baseline_quality_score=85.0),
        _outcome(quality=95.0, baseline_quality_score=70.0),
    ]

    result = AdaptiveValidationResultService.evaluate(outcomes, expected_samples=5)

    assert result.status == "rejected"
    assert result.reason_code == "quality_single_score_not_met"
    assert result.quality_summary["quality_score_minimum"] == 75.0


def test_non_safety_candidate_can_activate_when_one_output_is_82_5_and_beats_baseline():
    """모든 표본이 기준보다 낫다면 단일 85점 고정선 때문에 절감 후보를 막지 않는다."""
    result = AdaptiveValidationResultService.evaluate(
        [
            _outcome(quality=95.0, baseline_quality_score=40.0),
            _outcome(quality=95.0, baseline_quality_score=57.5),
            _outcome(quality=82.5, baseline_quality_score=80.0),
            _outcome(quality=95.0, baseline_quality_score=50.0),
            _outcome(quality=95.0, baseline_quality_score=50.0),
        ],
        expected_samples=5,
        safety_protected=False,
    )

    assert result.status == "validated"
    assert result.reason_code == "quality_and_efficiency_gate_passed"


def test_safety_candidate_keeps_the_85_point_single_output_floor():
    """고위험 입력군은 상대 품질이 좋아도 단일 85점 미만 후보를 허용하지 않는다."""
    result = AdaptiveValidationResultService.evaluate(
        [
            _outcome(quality=95.0, baseline_quality_score=90.0),
            _outcome(quality=95.0, baseline_quality_score=90.0),
            _outcome(quality=82.5, baseline_quality_score=80.0),
            _outcome(quality=95.0, baseline_quality_score=90.0),
            _outcome(quality=95.0, baseline_quality_score=90.0),
        ],
        expected_samples=5,
        safety_protected=True,
    )

    assert result.status == "rejected"
    assert result.reason_code == "quality_single_score_not_met"


def test_candidate_is_rejected_when_conservative_quality_floor_is_below_76_5():
    """평균이 흔들리지 않아도 보수적 품질 하한이 76.5점 미만이면 승격하지 않는다."""
    result = AdaptiveValidationResultService.evaluate(
        [
            _outcome(quality=76.0, baseline_quality_score=76.0)
            for _ in range(5)
        ],
        expected_samples=5,
    )

    assert result.status == "rejected"
    assert result.reason_code == "quality_floor_not_met"
    assert result.quality_summary["quality_score_lower_bound"] == 76.0


def test_candidate_with_good_lower_bound_but_low_average_quality_is_rejected():
    """하한이 안정적이어도 평균 품질 85점 미만이면 운영 rule로 승격하지 않는다."""
    result = AdaptiveValidationResultService.evaluate(
        [
            _outcome(quality=84.0, baseline_quality_score=84.0)
            for _ in range(5)
        ],
        expected_samples=5,
    )

    assert result.status == "rejected"
    assert result.reason_code == "quality_average_not_met"


def test_candidate_can_activate_at_85_or_higher_when_relative_quality_is_stable():
    """절대 85점 이상이고 기준 대비 하락이 없으면 안정적인 절감 후보를 허용한다."""
    result = AdaptiveValidationResultService.evaluate(
        [
            _outcome(quality=87.0, baseline_quality_score=86.0)
            for _ in range(5)
        ],
        expected_samples=5,
    )

    assert result.status == "validated"
    assert result.reason_code == "quality_and_efficiency_gate_passed"


def test_non_safety_candidate_can_trade_five_quality_points_for_large_savings():
    """비고위험 입력군은 절대 품질과 이상치 gate 통과 시 평균 5점 절감을 허용한다."""
    result = AdaptiveValidationResultService.evaluate(
        [
            _outcome(quality=89.0, baseline_quality_score=93.6)
            for _ in range(5)
        ],
        expected_samples=5,
        safety_protected=False,
    )

    assert result.status == "validated"
    assert result.reason_code == "quality_and_efficiency_gate_passed"
    assert round(result.quality_summary["quality_delta_average"], 1) == -4.6


def test_candidate_can_activate_when_average_and_lower_bound_both_pass():
    """평균 88점과 보수적 하한 76.5점을 함께 통과하면 저비용 후보를 허용한다."""
    result = AdaptiveValidationResultService.evaluate(
        [
            _outcome(quality=89.0, baseline_quality_score=89.0)
            for _ in range(5)
        ],
        expected_samples=5,
    )

    assert result.status == "validated"
    assert result.reason_code == "quality_and_efficiency_gate_passed"


def test_candidate_with_negligible_cost_saving_is_not_promoted():
    """가격표상 더 싸도 실질 절감이 거의 없으면 검증 예산을 쓴 정책으로 승격하지 않는다."""
    result = AdaptiveValidationResultService.evaluate(
        [_outcome(cost=0.0199) for _ in range(5)],
        expected_samples=5,
    )

    assert result.status == "rejected"
    assert result.reason_code == "net_savings_insufficient"


def test_active_policy_adds_only_validated_cohort_rules_and_keeps_baseline_default():
    policy = AdaptiveValidationResultService.project_active_policy(
        current_policy={"default_model_id": "gpt-4.1", "fallback_model_id": "gpt-4.1"},
        semantic_router={"routes": [{"cohort_id": "billing"}]},
        validated_routes=[
            {
                "cohort_id": "billing",
                "model_id": "gpt-4.1-mini",
                "fallback_model_id": "gpt-4.1",
                "evidence_version": "evidence-1",
            }
        ],
    )

    assert policy["default_model_id"] == "gpt-4.1"
    assert policy["rules"] == [
        {
            "id": "adaptive-cohort-billing",
            "when": {"semantic_cohort_id": "billing"},
            "selected_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "priority": 100,
            "reason_code": "validated_adaptive_cohort",
            "evidence_version": "evidence-1",
        }
    ]


def test_route_selection_prefers_safer_validated_model_when_quality_lower_bound_gap_is_large():
    """통과 후보끼리도 품질 하한 차이가 크면 최저가보다 안전한 후보를 선택한다."""

    cohort_id = uuid.uuid4()
    selected = AdaptiveModelRoutingValidationService._select_validated_routes(
        [
            {
                "cohort_row_id": cohort_id,
                "model_id": "gpt-5.4-mini",
                "candidate_cost": 0.0010,
                "quality_score_lower_bound": 87.0,
            },
            {
                "cohort_row_id": cohort_id,
                "model_id": "gpt-5-mini",
                "candidate_cost": 0.0006,
                "quality_score_lower_bound": 81.5,
            },
        ]
    )

    assert [route["model_id"] for route in selected.values()] == ["gpt-5.4-mini"]


def test_route_selection_uses_lower_cost_when_validated_quality_is_comparable():
    """보수적 품질 하한이 허용 오차 안이면 그때 저비용 후보를 선택한다."""

    cohort_id = uuid.uuid4()
    selected = AdaptiveModelRoutingValidationService._select_validated_routes(
        [
            {
                "cohort_row_id": cohort_id,
                "model_id": "gpt-5.4-mini",
                "candidate_cost": 0.0010,
                "quality_score_lower_bound": 87.0,
            },
            {
                "cohort_row_id": cohort_id,
                "model_id": "gpt-5-mini",
                "candidate_cost": 0.0006,
                "quality_score_lower_bound": 85.0,
            },
        ]
    )

    assert selected[cohort_id]["model_id"] == "gpt-5-mini"


def test_validation_batch_reads_target_node_data_from_deployment_snapshot():
    """검증 batch는 deployment graph에서 대상 LLM node 설정을 찾아야 한다."""
    graph = {
        "nodes": [
            {"id": "start", "data": {"title": "입력"}},
            {"id": "llm-triage", "data": {"model_id": "gpt-4.1"}},
        ]
    }

    assert AdaptiveModelRoutingValidationService._node_data(graph, "llm-triage") == {
        "model_id": "gpt-4.1"
    }
    assert AdaptiveModelRoutingValidationService._node_data(graph, "missing") is None


def test_validation_available_models_exclude_node_blocked_models():
    """월간 검증 예산은 노드에서 명시적으로 제외한 모델에 사용하지 않는다."""
    node_data = {
        "model_routing_policy": {
            "excluded_model_ids": ["gpt-5.6-sol", " gpt-5.6-sol "],
        }
    }

    available = AdaptiveModelRoutingValidationService._eligible_available_model_ids(
        ["gpt-5.6-luna", "gpt-5.6-sol"],
        node_data=node_data,
    )

    assert available == {"gpt-5.6-luna"}


def test_validation_available_models_exclude_google_models_with_normalized_id():
    """제외 설정의 표기와 credential catalog 표기가 달라도 유료 Replay 후보가 되지 않는다."""
    node_data = {
        "model_routing_policy": {
            "excluded_model_ids": ["gemini-2.5-flash"],
        }
    }

    available = AdaptiveModelRoutingValidationService._eligible_available_model_ids(
        ["models/gemini-2.5-flash", "gpt-4.1-mini"],
        node_data=node_data,
    )

    assert available == {"gpt-4.1-mini"}


def test_candidate_replay_uses_a_canonical_manual_run_trigger():
    """FR-011-A52: 후보 Replay도 workflow run 계약이 허용하는 trigger mode를 사용한다."""
    context = AdaptiveModelRoutingValidationService._candidate_execution_context(
        workflow_id="workflow-1",
        organization_id="organization-1",
        deployment_id="deployment-1",
        workflow_run_id="run-1",
        execution_subject_id="user-1",
    )

    assert context["trigger_mode"] == "cost_optimizer_compare"


def test_bootstrap_validation_runs_baseline_before_paid_candidate():
    """대표 예시 검증은 기준 모델을 먼저 통과시킨 뒤 후보 모델을 호출한다."""
    policy = SimpleNamespace(
        id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        deployment_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        node_id="llm-triage",
    )
    deployment = SimpleNamespace(graph_snapshot={"nodes": [], "edges": []})
    item = SimpleNamespace(
        observation_id=None,
        cohort_example_id=uuid.uuid4(),
        baseline_model_id="gpt-4.1",
        model_id="gpt-4.1-mini",
    )
    db = MagicMock()
    calls: list[tuple[str, str]] = []

    def run_replay(*_args, replay_model_id, fallback_model_id, **_kwargs):
        calls.append((replay_model_id, fallback_model_id))
        return (
            {
                "text": '{"answer": "ok"}',
                "model": replay_model_id,
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "cost": 0.01 if replay_model_id == "gpt-4.1" else 0.005,
            },
            uuid.uuid4(),
        )

    with (
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_validation_input",
            return_value=({"message": "결제 오류를 확인해 주세요."}, None, None),
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_run_model_replay",
            side_effect=run_replay,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_schema_passed",
            return_value=True,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_downstream_passed",
            return_value=True,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_judge_quality",
            return_value={
                "candidate_score": 90.0,
                "baseline_score": 92.0,
                "confidence": 0.9,
                "judge_cost": 0.001,
            },
        ),
    ):
        result = AdaptiveModelRoutingValidationService._execute_validation_item(
            db,
            policy=policy,
            deployment=deployment,
            node_data={"output_format": {"type": "json", "schema": {}}},
            item=item,
            execution_subject_id=uuid.uuid4(),
        )

    assert calls == [("gpt-4.1", ""), ("gpt-4.1-mini", "")]
    assert result["status"] == "completed"
    assert result["execution_summary"]["baseline_validation_passed"] is True


def test_bootstrap_validation_does_not_spend_candidate_cost_when_baseline_fails():
    """기준 모델이 계약을 지키지 못한 입력은 후보 비교 자체가 성립하지 않는다."""
    item = SimpleNamespace(
        observation_id=None,
        cohort_example_id=uuid.uuid4(),
        baseline_model_id="gpt-4.1",
        model_id="gpt-4.1-mini",
    )
    run_replay = MagicMock(
        return_value=({"text": "not-json", "model": "gpt-4.1", "cost": 0.01}, uuid.uuid4())
    )

    with (
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_validation_input",
            return_value=({"message": "결제 오류"}, None, None),
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_run_model_replay",
            run_replay,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_schema_passed",
            return_value=False,
        ),
    ):
        result = AdaptiveModelRoutingValidationService._execute_validation_item(
            MagicMock(),
            policy=SimpleNamespace(
                id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                deployment_id=uuid.uuid4(),
                organization_id=uuid.uuid4(),
                node_id="llm-triage",
            ),
            deployment=SimpleNamespace(graph_snapshot={"nodes": [], "edges": []}),
            node_data={"output_format": {"type": "json", "schema": {}}},
            item=item,
            execution_subject_id=uuid.uuid4(),
        )

    run_replay.assert_called_once()
    assert result["status"] == "baseline_failed"
    assert result["execution_summary"]["reason_code"] == "baseline_schema_gate_failed"


def test_bootstrap_validation_reuses_a_passed_baseline_for_other_candidates():
    """같은 대표 입력의 후보가 여러 개여도 기준 모델은 배치에서 한 번만 호출한다."""
    item = SimpleNamespace(
        observation_id=None,
        cohort_example_id=uuid.uuid4(),
        baseline_model_id="gpt-4.1",
        model_id="gpt-4o-mini",
    )
    run_replay = MagicMock(
        return_value=(
            {
                "text": '{"answer": "candidate"}',
                "model": "gpt-4o-mini",
                "usage": {"input_tokens": 8, "output_tokens": 4},
                "cost": 0.002,
            },
            uuid.uuid4(),
        )
    )
    validated_baseline = {
        "passed": True,
        "output": {
            "text": '{"answer": "baseline"}',
            "model": "gpt-4.1",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "cost": 0.01,
        },
        "latency_ms": 900,
    }

    with (
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_validation_input",
            return_value=({"message": "결제 오류"}, None, None),
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_run_model_replay",
            run_replay,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_schema_passed",
            return_value=True,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_downstream_passed",
            return_value=True,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_judge_quality",
            return_value={
                "candidate_score": 90.0,
                "baseline_score": 92.0,
                "confidence": 0.9,
                "judge_cost": 0.001,
            },
        ),
    ):
        result = AdaptiveModelRoutingValidationService._execute_validation_item(
            MagicMock(),
            policy=SimpleNamespace(
                id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                deployment_id=uuid.uuid4(),
                organization_id=uuid.uuid4(),
                node_id="llm-triage",
            ),
            deployment=SimpleNamespace(graph_snapshot={"nodes": [], "edges": []}),
            node_data={"output_format": {"type": "json", "schema": {}}},
            item=item,
            execution_subject_id=uuid.uuid4(),
            validated_baseline=validated_baseline,
        )

    assert run_replay.call_count == 1
    assert run_replay.call_args.kwargs["replay_model_id"] == "gpt-4o-mini"
    assert run_replay.call_args.kwargs["fallback_model_id"] == ""
    assert result["actual_cost_usd"] == Decimal("0.003")
    assert result["execution_summary"]["baseline_cost"] == 0.01


def test_quality_judge_scores_against_the_llm_node_contract():
    """Judge는 계약을 보고 A/B 순서를 바꾸어 두 번 평가한 뒤 평균낸다."""
    client = MagicMock()
    client.invoke_sync.side_effect = [
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "variant_a_score": 92,
                                "variant_b_score": 80,
                                "confidence": 0.9,
                            }
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                # 두 번째는 candidate가 A, baseline이 B다.
                                "variant_a_score": 88,
                                "variant_b_score": 90,
                                "confidence": 0.8,
                            }
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 6},
        },
    ]
    policy = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        node_id="llm-triage",
    )

    with (
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.LLMService.get_runtime_available_model_ids_for_user",
            return_value=["gpt-4.1"],
        ),
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.LLMService.get_runtime_client_for_user",
            return_value=SimpleNamespace(client=client, credential_id=uuid.uuid4()),
        ),
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.LLMService.calculate_cost",
            return_value=Decimal("0.001"),
        ),
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.LLMService.log_usage",
            return_value=SimpleNamespace(id=uuid.uuid4()),
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_judge_visible",
            side_effect=lambda value: value,
        ),
    ):
        result = AdaptiveModelRoutingValidationService._judge_quality(
            MagicMock(),
            policy=policy,
            execution_subject_id=uuid.uuid4(),
            baseline_input={"message": "문의"},
            baseline_output={"text": '{"answer": "A"}'},
            candidate_output={"text": '{"answer": "B"}'},
            preferred_model_id="gpt-4.1",
            node_data={
                "system_prompt": "고객 문의에 정확히 답하세요.",
                "user_prompt": "{{message}}",
                "assistant_prompt": "",
                "output_format": {
                    "type": "json",
                    "schema": {"answer": {"type": "string", "required": True}},
                },
            },
        )

    assert client.invoke_sync.call_count == 2
    first_payload = json.loads(client.invoke_sync.call_args_list[0].args[0][1]["content"])
    second_payload = json.loads(client.invoke_sync.call_args_list[1].args[0][1]["content"])
    assert first_payload["evaluation_contract"] == {
        "system_prompt": "고객 문의에 정확히 답하세요.",
        "user_prompt": "{{message}}",
        "assistant_prompt": "",
        "output_format": {
            "type": "json",
            "schema": {"answer": {"type": "string", "required": True}},
        },
        "knowledge_enabled": False,
        "grounding_policy": {
            "unsupported_specific_claims": "penalize",
            "transparent_uncertainty": "do_not_penalize",
        },
    }
    assert first_payload["variant_a"] == {"text": '{"answer": "A"}'}
    assert first_payload["variant_b"] == {"text": '{"answer": "B"}'}
    assert second_payload["variant_a"] == {"text": '{"answer": "B"}'}
    assert second_payload["variant_b"] == {"text": '{"answer": "A"}'}
    assert result["baseline_score"] == 91.0
    assert result["candidate_score"] == 84.0
    assert result["confidence"] == 0.85
    assert result["judge_passes"] == 2


def test_quality_judge_retries_only_the_transiently_failed_pass():
    """한 방향 판정의 일시 오류가 후보 전체의 품질 증거를 없애면 안 된다."""
    client = MagicMock()
    client.invoke_sync.side_effect = [
        TimeoutError("temporary provider timeout"),
        {
            "choices": [{"message": {"content": json.dumps({
                "variant_a_score": 92,
                "variant_b_score": 90,
                "confidence": 0.9,
            })}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
        {
            "choices": [{"message": {"content": json.dumps({
                "variant_a_score": 88,
                "variant_b_score": 91,
                "confidence": 0.9,
            })}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    ]
    policy = SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        node_id="llm-triage",
    )

    with (
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.LLMService.get_runtime_available_model_ids_for_user",
            return_value=["gpt-4.1"],
        ),
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.LLMService.get_runtime_client_for_user",
            return_value=SimpleNamespace(client=client, credential_id=uuid.uuid4()),
        ),
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.LLMService.calculate_cost",
            return_value=Decimal("0.001"),
        ),
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.LLMService.log_usage",
            return_value=SimpleNamespace(id=uuid.uuid4()),
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_judge_visible",
            side_effect=lambda value: value,
        ),
    ):
        result = AdaptiveModelRoutingValidationService._judge_quality(
            MagicMock(),
            policy=policy,
            execution_subject_id=uuid.uuid4(),
            baseline_input={"message": "문의"},
            baseline_output={"text": "A"},
            candidate_output={"text": "B"},
            preferred_model_id="gpt-4.1",
            node_data={"output_format": {"type": "json"}},
        )

    assert client.invoke_sync.call_count == 3
    assert result["status"] == "completed"
    assert result["judge_passes"] == 2


def test_bootstrap_representative_query_is_written_to_the_semantic_input_path():
    """대표 문의는 빈 임의 필드가 아니라 실제 semantic router 입력 selector에 들어간다."""
    node_data = {
        "referenced_variables": [
            {"value_selector": ["webhook-ticket", "message"]},
            {"value_selector": ["webhook-ticket", "customerTier"]},
        ],
        "model_routing_context": {
            "semantic_router": {"input_paths": ["webhook-ticket.message"]}
        },
    }

    payload = AdaptiveModelRoutingValidationService._synthetic_baseline_input(
        node_data,
        "결제 오류를 확인해 주세요.",
    )

    assert payload == {
        "webhook-ticket": {
            "message": "결제 오류를 확인해 주세요.",
            "customerTier": "",
        }
    }


def test_candidate_execution_marks_requested_model_mismatch_as_fallback():
    """Replay가 요청 모델 대신 다른 모델을 썼으면 검증 통과 표본으로 쓰지 않는다."""
    actual_model_id, fallback_used = (
        AdaptiveModelRoutingValidationService._candidate_execution_model(
            {
                "model": "gpt-4.1",
                # 후보 Replay는 auto routing을 끄므로 model_routing trace가 없을 수 있다.
                "metadata": {},
            },
            requested_model_id="gpt-5-nano",
        )
    )

    assert actual_model_id == "gpt-4.1"
    assert fallback_used is True


def test_candidate_execution_uses_trace_fallback_flag_when_available():
    """자동 라우팅 trace가 있으면 provider 응답보다 그 fallback 판정을 우선한다."""
    actual_model_id, fallback_used = (
        AdaptiveModelRoutingValidationService._candidate_execution_model(
            {
                "model": "gpt-5.4-nano",
                "metadata": {"model_routing": {"fallback_used": True}},
            },
            requested_model_id="gpt-5.4-nano",
        )
    )

    assert actual_model_id == "gpt-5.4-nano"
    assert fallback_used is True


def test_quality_summary_serializes_judge_usage_log_id_for_json_storage():
    """Judge usage FK는 UUID로 유지하되 JSON summary에는 문자열만 저장한다."""
    usage_log_id = uuid.uuid4()

    summary = AdaptiveModelRoutingValidationService._json_safe_quality_summary(
        {"candidate_score": 91.0, "judge_usage_log_id": usage_log_id}
    )

    assert summary == {
        "candidate_score": 91.0,
        "judge_usage_log_id": str(usage_log_id),
    }


def test_active_policy_projection_keeps_non_adaptive_safety_rule():
    """FR-011-A51: 검증된 할인 규칙을 갱신해도 고위험 기본 모델 규칙은 남긴다."""
    policy = AdaptiveValidationResultService.project_active_policy(
        current_policy={
            "default_model_id": "gpt-4.1",
            "rules": [
                {
                    "id": "safety-high-risk",
                    "when": {"semantic_cohort_id": "high_risk"},
                    "selected_model_id": "gpt-4.1",
                    "fallback_model_id": "gpt-4.1-mini",
                    "priority": 10,
                    "reason_code": "safety_override_baseline",
                },
                {
                    "id": "old-adaptive",
                    "when": {"semantic_cohort_id": "old-cohort"},
                    "selected_model_id": "gpt-4o-mini",
                    "priority": 100,
                    "reason_code": "validated_adaptive_cohort",
                },
            ],
        },
        semantic_router={"route_catalog_version": "adaptive-test", "routes": []},
        validated_routes=[
            {
                "cohort_id": "invoice",
                "model_id": "gpt-4o-mini",
                "fallback_model_id": "gpt-4.1",
                "evidence_version": "evidence-v1",
            }
        ],
    )

    assert policy["rules"][0]["id"] == "safety-high-risk"
    assert policy["rules"][1]["when"] == {"semantic_cohort_id": "invoice"}
    assert any(rule.get("id") == "old-adaptive" for rule in policy["rules"])


def test_active_policy_projection_keeps_other_validated_cohort_when_one_cohort_is_refreshed():
    """새 cohort 검증 결과가 기존 cohort의 검증된 라우팅 규칙을 지우면 안 된다."""
    policy = AdaptiveValidationResultService.project_active_policy(
        current_policy={
            "default_model_id": "gpt-4.1",
            "rules": [
                {
                    "when": {"semantic_cohort_id": "invoice"},
                    "selected_model_id": "gpt-5.4-nano",
                    "fallback_model_id": "gpt-4.1",
                    "priority": 100,
                    "reason_code": "validated_adaptive_cohort",
                    "evidence_version": "invoice-evidence-v1",
                }
            ],
        },
        semantic_router={"route_catalog_version": "adaptive-test", "routes": []},
        validated_routes=[
            {
                "cohort_id": "slack",
                "model_id": "gpt-5-mini",
                "fallback_model_id": "gpt-4.1",
                "evidence_version": "slack-evidence-v1",
            }
        ],
    )

    mapped_models = {
        rule["when"]["semantic_cohort_id"]: rule["selected_model_id"]
        for rule in policy["rules"]
        if rule.get("reason_code") == "validated_adaptive_cohort"
    }
    assert mapped_models == {
        "invoice": "gpt-5.4-nano",
        "slack": "gpt-5-mini",
    }


def test_active_policy_projection_revokes_only_the_degraded_cohort():
    """운영 재검증 탈락은 해당 입력군만 기본 모델로 되돌린다."""

    policy = AdaptiveValidationResultService.project_active_policy(
        current_policy={
            "default_model_id": "gpt-4.1",
            "rules": [
                {
                    "when": {"semantic_cohort_id": "finance"},
                    "selected_model_id": "gpt-5.4-mini",
                    "fallback_model_id": "gpt-4.1",
                    "reason_code": "validated_adaptive_cohort",
                    "evidence_version": "finance-v1",
                },
                {
                    "when": {"semantic_cohort_id": "routine"},
                    "selected_model_id": "gpt-4.1-mini",
                    "fallback_model_id": "gpt-4.1",
                    "reason_code": "validated_adaptive_cohort",
                    "evidence_version": "routine-v1",
                },
            ],
        },
        semantic_router={"route_catalog_version": "adaptive-test", "routes": []},
        validated_routes=[],
        revoked_cohort_ids=["finance"],
    )

    mapped_models = {
        rule["when"]["semantic_cohort_id"]: rule["selected_model_id"]
        for rule in policy["rules"]
        if rule.get("reason_code") == "validated_adaptive_cohort"
    }
    assert mapped_models == {"routine": "gpt-4.1-mini"}


def test_validation_batch_restores_cohort_status_when_execution_cannot_start():
    """일시적인 실행 주체 오류 뒤에도 입력군은 다음 점검에서 다시 검증돼야 한다."""
    cohort_id = uuid.uuid4()
    cohort = SimpleNamespace(id=cohort_id, status="validating")
    batch = SimpleNamespace(
        candidate_plan={
            "cohort_status_before_validation": {
                str(cohort_id): "validated_waiting",
            }
        },
        reserved_cost=Decimal("0.10"),
        status="pending",
        error_summary=None,
        completed_at=None,
    )
    policy = SimpleNamespace(
        id=uuid.uuid4(),
        active_policy=None,
        refresh_requested_at=None,
        status="refreshing",
        last_refresh_result=None,
        last_refreshed_at=None,
    )
    cohort_query = MagicMock()
    cohort_query.filter.return_value = cohort_query
    cohort_query.all.return_value = [cohort]
    db = MagicMock()
    db.query.return_value = cohort_query

    with patch.object(
        AdaptiveModelRoutingValidationService,
        "_locked_monthly_budget",
        return_value=SimpleNamespace(reserved_usd=Decimal("0.10")),
    ):
        AdaptiveModelRoutingValidationService._fail_batch_and_release_refresh(
            db,
            batch=batch,
            policy=policy,
            reason_code="execution_subject_unavailable",
        )

    assert batch.status == "failed"
    assert cohort.status == "validated_waiting"


def test_finalize_batch_flushes_activated_cohorts_before_runtime_catalog_projection():
    """검증 통과 cohort의 active 상태가 catalog 조회 전에 DB에 반영되어야 한다."""
    from apps.workflow_engine.services.model_routing_adaptive_validation import (
        AdaptiveEvidenceResult,
    )
    from apps.workflow_engine.services.model_routing_adaptive_validation_service import (
        AdaptiveModelRoutingValidationService,
    )
    from apps.shared.db.models.model_routing_cohort import (
        LLMNodeModelRoutingCohort,
        LLMNodeModelRoutingValidationItem,
    )

    cohort_id = uuid.uuid4()
    policy = SimpleNamespace(
        id=uuid.uuid4(),
        active_policy={"default_model_id": "gpt-4.1", "rules": []},
        policy_version="bootstrap-v1",
        status="refreshing",
        last_refresh_result="pending_review",
        last_refreshed_at=None,
        refresh_requested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        eligible_runs_since_last_refresh=20,
    )
    batch = SimpleNamespace(
        id=uuid.uuid4(),
        candidate_plan={"node_config_fingerprint": "config-v1"},
        reserved_cost=0,
        spent_cost=0,
        status="running",
        completed_at=None,
        error_summary={},
    )
    item = SimpleNamespace(cohort_id=cohort_id, model_id="gpt-5.4-nano")
    cohort = SimpleNamespace(
        id=cohort_id,
        cohort_key="invoice-cohort",
        status="validating",
        safety_protected=True,
    )

    def query(model):
        result = MagicMock()
        result.filter.return_value = result
        if model is LLMNodeModelRoutingValidationItem:
            result.all.return_value = [item]
        elif model is LLMNodeModelRoutingCohort:
            result.first.return_value = cohort
        return result

    db = MagicMock()
    db.query.side_effect = query
    budget = SimpleNamespace(reserved_usd=0, spent_usd=0)

    def catalog_after_flush(*_args, **_kwargs):
        assert cohort.status == "active"
        assert db.flush.called
        return {"routes": [{"cohort_id": cohort.cohort_key}]}

    with (
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_outcome_from_item",
            return_value=SimpleNamespace(),
        ),
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.AdaptiveValidationResultService.evaluate",
            return_value=AdaptiveEvidenceResult(
                status="validated",
                reason_code="quality_and_efficiency_gate_passed",
                quality_summary={},
                efficiency_summary={},
            ),
        ) as evaluate,
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_upsert_evidence",
            return_value=SimpleNamespace(
                status="validated",
                evidence_version="evidence-v1",
                efficiency_summary={"candidate_cost_average": 0.001},
            ),
        ),
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.AdaptiveModelRoutingCohortStore.build_runtime_catalog",
            side_effect=catalog_after_flush,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_remaining_run_event_count",
            return_value=0,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_locked_monthly_budget",
            return_value=budget,
        ),
    ):
        AdaptiveModelRoutingValidationService._finalize_batch(
            db,
            batch=batch,
            policy=policy,
            node_data={"model_id": "gpt-4.1"},
        )

    assert policy.status == "active"
    assert evaluate.call_args.kwargs["safety_protected"] is True
    assert any(
        rule.get("reason_code") == "validated_adaptive_cohort"
        for rule in policy.active_policy["rules"]
    )


def test_finalize_batch_projects_required_cohort_catalog_when_all_models_are_rejected():
    """후보 모델 탈락은 입력군 매칭 catalog까지 제거하지 않는다."""
    from apps.workflow_engine.services.model_routing_adaptive_validation import (
        AdaptiveEvidenceResult,
    )
    from apps.shared.db.models.model_routing_cohort import (
        LLMNodeModelRoutingCohort,
        LLMNodeModelRoutingValidationItem,
    )

    cohort_id = uuid.uuid4()
    policy = SimpleNamespace(
        id=uuid.uuid4(),
        active_policy={"default_model_id": "gpt-4.1", "rules": []},
        policy_version="bootstrap-v1",
        status="refreshing",
        last_refresh_result="pending_review",
        last_refreshed_at=None,
        refresh_requested_at=None,
        eligible_runs_since_last_refresh=0,
    )
    batch = SimpleNamespace(
        id=uuid.uuid4(),
        candidate_plan={"node_config_fingerprint": "config-v1"},
        reserved_cost=0,
        spent_cost=0,
        status="running",
        completed_at=None,
        error_summary={},
    )
    item = SimpleNamespace(cohort_id=cohort_id, model_id="gpt-4.1-mini")
    cohort = SimpleNamespace(
        id=cohort_id,
        cohort_key="routine",
        status="validating",
        safety_protected=False,
    )

    def query(model):
        result = MagicMock()
        result.filter.return_value = result
        if model is LLMNodeModelRoutingValidationItem:
            result.all.return_value = [item]
        elif model is LLMNodeModelRoutingCohort:
            result.first.return_value = cohort
        return result

    db = MagicMock()
    db.query.side_effect = query
    budget = SimpleNamespace(reserved_usd=0, spent_usd=0)
    catalog = {
        "route_catalog_version": "adaptive-test",
        "routes": [{"cohort_id": "routine"}],
    }
    with (
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_outcome_from_item",
            return_value=SimpleNamespace(),
        ),
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.AdaptiveValidationResultService.evaluate",
            return_value=AdaptiveEvidenceResult(
                status="rejected",
                reason_code="quality_gate_failed",
                quality_summary={},
                efficiency_summary={},
            ),
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_upsert_evidence",
            return_value=SimpleNamespace(
                status="rejected",
                evidence_version="evidence-v1",
                efficiency_summary={},
            ),
        ),
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.AdaptiveModelRoutingCohortStore.build_runtime_catalog",
            return_value=catalog,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_locked_monthly_budget",
            return_value=budget,
        ),
    ):
        AdaptiveModelRoutingValidationService._finalize_batch(
            db,
            batch=batch,
            policy=policy,
            node_data={"model_id": "gpt-4.1"},
        )

    assert policy.status == "collecting"
    assert policy.last_refresh_result == "kept_current"
    assert policy.active_policy["semantic_router"] == catalog
    assert policy.active_policy["rules"] == []


def test_finalize_batch_revokes_a_degraded_active_route_after_production_revalidation():
    """활성 모델이 운영 입력 재검증에서 탈락하면 그 입력군만 기본 모델로 복귀한다."""
    from apps.workflow_engine.services.model_routing_adaptive_validation import (
        AdaptiveEvidenceResult,
    )
    from apps.shared.db.models.model_routing_cohort import (
        LLMNodeModelRoutingCohort,
        LLMNodeModelRoutingValidationItem,
    )

    cohort_id = uuid.uuid4()
    policy = SimpleNamespace(
        id=uuid.uuid4(),
        active_policy={
            "default_model_id": "gpt-4.1",
            "rules": [
                {
                    "when": {"semantic_cohort_id": "finance"},
                    "selected_model_id": "gpt-5.4-mini",
                    "reason_code": "validated_adaptive_cohort",
                },
                {
                    "when": {"semantic_cohort_id": "routine"},
                    "selected_model_id": "gpt-4.1-mini",
                    "reason_code": "validated_adaptive_cohort",
                },
            ],
        },
        policy_version="adaptive-v3",
        status="refreshing",
        last_refresh_result="pending_review",
        last_refreshed_at=None,
        refresh_requested_at=None,
        eligible_runs_since_last_refresh=0,
    )
    batch = SimpleNamespace(
        id=uuid.uuid4(),
        candidate_plan={
            "node_config_fingerprint": "config-v1",
            "validation_stage": "production",
        },
        reserved_cost=0,
        spent_cost=0,
        status="running",
        completed_at=None,
        error_summary={},
    )
    item = SimpleNamespace(cohort_id=cohort_id, model_id="gpt-5.4-mini")
    cohort = SimpleNamespace(
        id=cohort_id,
        cohort_key="finance",
        status="validating",
        safety_protected=False,
    )

    def query(model):
        result = MagicMock()
        result.filter.return_value = result
        if model is LLMNodeModelRoutingValidationItem:
            result.all.return_value = [item]
        elif model is LLMNodeModelRoutingCohort:
            result.first.return_value = cohort
        return result

    db = MagicMock()
    db.query.side_effect = query
    budget = SimpleNamespace(reserved_usd=0, spent_usd=0)
    catalog = {"route_catalog_version": "adaptive-test", "routes": []}
    with (
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_outcome_from_item",
            return_value=SimpleNamespace(),
        ),
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.AdaptiveValidationResultService.evaluate",
            return_value=AdaptiveEvidenceResult(
                status="rejected",
                reason_code="quality_outlier_gate_failed",
                quality_summary={"quality_delta_minimum": -15.0},
                efficiency_summary={},
            ),
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_upsert_evidence",
            return_value=SimpleNamespace(
                status="rejected",
                evidence_version="evidence-v2",
                efficiency_summary={},
            ),
        ),
        patch(
            "apps.workflow_engine.services.model_routing_adaptive_validation_service.AdaptiveModelRoutingCohortStore.build_runtime_catalog",
            return_value=catalog,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_locked_monthly_budget",
            return_value=budget,
        ),
    ):
        AdaptiveModelRoutingValidationService._finalize_batch(
            db,
            batch=batch,
            policy=policy,
            node_data={"model_id": "gpt-4.1"},
        )

    routed_cohorts = {
        rule["when"]["semantic_cohort_id"]
        for rule in policy.active_policy["rules"]
        if rule.get("reason_code") == "validated_adaptive_cohort"
    }
    assert routed_cohorts == {"routine"}
    assert cohort.status == "validated_waiting"
    assert policy.status == "active"
    assert policy.last_refresh_result == "applied"
    assert batch.error_summary["revoked_route_count"] == 1


def test_empty_validation_plan_releases_refresh_lease_for_the_next_observation_window():
    """아직 cohort가 없으면 refresh를 끝내 다음 운영 run이 다시 갱신을 예약할 수 있어야 한다."""
    policy = SimpleNamespace(
        id=uuid.uuid4(),
        active_policy={"default_model_id": "gpt-4.1", "rules": []},
        status="refreshing",
        last_refresh_result="pending_review",
        last_refreshed_at=None,
        refresh_requested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        eligible_runs_since_last_refresh=20,
    )
    db = MagicMock()

    with (
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_locked_policy",
            return_value=policy,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_remaining_run_event_count",
            return_value=0,
        ),
    ):
        completed = AdaptiveModelRoutingValidationService.complete_refresh_without_batch(
            db,
            policy_id=policy.id,
        )

    assert completed is policy
    assert policy.status == "collecting"
    assert policy.last_refresh_result == "kept_current"
    assert policy.refresh_requested_at is None
    assert policy.eligible_runs_since_last_refresh == 0
    db.flush.assert_called_once()


def test_completed_validation_batch_is_not_reused_for_a_new_refresh_cycle():
    """종료된 batch는 재실행하지 않고 caller가 refresh lease를 닫을 수 있어야 한다."""
    assert (
        AdaptiveModelRoutingValidationService._should_reuse_existing_batch(
            SimpleNamespace(status="completed")
        )
        is False
    )
    assert (
        AdaptiveModelRoutingValidationService._should_reuse_existing_batch(
            SimpleNamespace(status="pending")
        )
        is True
    )


def test_execute_batch_does_not_finalize_a_batch_completed_by_another_worker():
    """행 잠금 대기 뒤 완료 상태가 됐으면 비용/정책을 다시 확정하면 안 된다."""
    batch_id = uuid.uuid4()
    initial_batch = SimpleNamespace(
        id=batch_id,
        policy_id=uuid.uuid4(),
        status="running",
    )
    completed_batch = SimpleNamespace(
        id=batch_id,
        policy_id=initial_batch.policy_id,
        status="completed",
    )
    policy = SimpleNamespace(id=initial_batch.policy_id, node_id="llm-triage")

    def query_result(*, first=None, all_rows=None):
        result = MagicMock()
        result.filter.return_value = result
        result.order_by.return_value = result
        result.with_for_update.return_value = result
        result.first.return_value = first
        result.all.return_value = all_rows or []
        return result

    db = MagicMock()
    db.query.side_effect = [
        query_result(first=initial_batch),
        query_result(first=policy),
        query_result(all_rows=[]),
        query_result(first=completed_batch),
    ]

    with (
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_deployment",
            return_value=SimpleNamespace(graph_snapshot={}),
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_node_data",
            return_value={"model_id": "gpt-4.1"},
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_execution_subject",
            return_value=uuid.uuid4(),
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_locked_policy",
            return_value=policy,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_batch_has_nonterminal_items",
            return_value=False,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "_finalize_batch",
        ) as finalize_batch,
    ):
        result = AdaptiveModelRoutingValidationService.execute_batch(
            db,
            batch_id=batch_id,
        )

    assert result is completed_batch
    finalize_batch.assert_not_called()


def test_stale_running_validation_item_is_recovered_but_fresh_item_is_left_running():
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    stale = SimpleNamespace(
        execution_summary={"_lease_started_at": (now - timedelta(minutes=6)).isoformat()}
    )
    fresh = SimpleNamespace(
        execution_summary={"_lease_started_at": (now - timedelta(seconds=30)).isoformat()}
    )

    assert AdaptiveModelRoutingValidationService._is_stale_running_item(stale, now=now) is True
    assert AdaptiveModelRoutingValidationService._is_stale_running_item(fresh, now=now) is False


def test_downstream_contract_checks_condition_answer_and_slack_consumers():
    graph = {
        "nodes": [
            {"id": "llm", "type": "llmNode", "data": {}},
            {
                "id": "condition",
                "type": "conditionNode",
                "data": {"cases": [{"conditions": [{"variable_selector": ["llm", "approved"]}]}]},
            },
            {
                "id": "answer",
                "type": "answerNode",
                "data": {"outputs": [{"value_selector": ["llm", "reply"]}]},
            },
            {
                "id": "slack",
                "type": "slackPostNode",
                "data": {"referenced_variables": [{"value_selector": ["llm", "reply"]}]},
            },
        ],
        "edges": [
            {"source": "llm", "target": "condition"},
            {"source": "llm", "target": "answer"},
            {"source": "llm", "target": "slack"},
        ],
    }

    assert AdaptiveModelRoutingValidationService._downstream_passed(
        graph, "llm", {"approved": True, "reply": "done"}
    ) is True
    assert AdaptiveModelRoutingValidationService._downstream_passed(
        graph, "llm", {"approved": True}
    ) is False


def test_monthly_budget_limit_follows_the_latest_policy_setting():
    policy = SimpleNamespace(id=uuid.uuid4(), validation_budget_usd=Decimal("1.5"))
    budget = SimpleNamespace(limit_usd=Decimal("3"))
    db = MagicMock()
    db.query.return_value.filter.return_value.filter.return_value.with_for_update.return_value.first.return_value = budget

    resolved = AdaptiveModelRoutingValidationService._locked_monthly_budget(db, policy)

    assert resolved is budget
    assert budget.limit_usd == Decimal("1.5")
