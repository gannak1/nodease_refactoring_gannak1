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


def test_quality_gate_accepts_a_high_quality_candidate_despite_one_judge_outlier():
    """한 번의 Judge 점수 흔들림보다 반복 실행의 보수적 품질 하한을 우선한다."""
    outcomes = [
        _outcome(quality=70.0, baseline_quality_score=85.0),
        _outcome(quality=95.0, baseline_quality_score=75.0),
        _outcome(quality=92.0, baseline_quality_score=70.0),
        _outcome(quality=95.0, baseline_quality_score=85.0),
        _outcome(quality=95.0, baseline_quality_score=70.0),
    ]

    result = AdaptiveValidationResultService.evaluate(outcomes, expected_samples=5)

    assert result.status == "validated"
    assert result.quality_summary["quality_score_lower_bound"] >= 70.0


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
            "when": {"semantic_cohort_id": "billing"},
            "selected_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "priority": 100,
            "reason_code": "validated_adaptive_cohort",
            "evidence_version": "evidence-1",
        }
    ]


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
        ),
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
    assert any(
        rule.get("reason_code") == "validated_adaptive_cohort"
        for rule in policy.active_policy["rules"]
    )


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
