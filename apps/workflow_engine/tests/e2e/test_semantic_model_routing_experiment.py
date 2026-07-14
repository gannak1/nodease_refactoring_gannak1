"""FR-011-A29/A30 실제 배포 semantic routing 실험 스크립트 계약."""

from collections import Counter
from datetime import datetime, timezone

from scripts.experiment_semantic_model_routing import (
    CALIBRATION_CASES,
    EVIDENCE_CASES,
    EVIDENCE_MODELS,
    FINAL_HOLDOUT_CASES,
    FINAL_HOLDOUT_V1_CASES,
    FINAL_HOLDOUT_V2_CASES,
    HOLDOUT_CASES,
    RoutingObservation,
    _candidate_request_from_node,
    _embed_with_retry,
    _expected_model_for_cohort,
    _latest_deployed_observation,
    build_markdown_report,
    build_runtime_inputs,
)


def test_deployed_observation_excludes_runs_started_before_current_request(
    monkeypatch,
):
    """A44: 같은 실험 ID를 재사용해도 과거 완료 행을 새 실행으로 오인하지 않는다."""
    captured = {}

    class EmptyResult:
        def mappings(self):
            return self

        def first(self):
            return None

    class FakeSession:
        def execute(self, statement, params):
            captured["statement"] = str(statement)
            captured["params"] = params
            return EmptyResult()

        def close(self):
            return None

    monkeypatch.setattr(
        "apps.shared.db.session.SessionLocal",
        lambda: FakeSession(),
    )
    requested_after = datetime(2026, 7, 14, 3, 0, tzinfo=timezone.utc)

    observation = _latest_deployed_observation(
        HOLDOUT_CASES[0],
        experiment_run_id="repeatable-experiment",
        expected_model_id="gpt-4.1",
        requested_after=requested_after,
    )

    assert observation is None
    assert "wr.started_at >= :requested_after" in captured["statement"]
    assert captured["params"]["requested_after"] == requested_after


def test_holdout_dataset_has_twenty_unique_queries_per_semantic_cohort():
    """대표 문장과 별개인 holdout 입력을 3개 cohort에 동일하게 배분한다."""
    counts = Counter(case.expected_cohort_id for case in HOLDOUT_CASES)

    assert len(HOLDOUT_CASES) == 60
    assert counts == {
        "routine_support": 20,
        "account_billing": 20,
        "high_risk": 20,
    }
    assert len({case.case_id for case in HOLDOUT_CASES}) == 60
    assert len({case.message for case in HOLDOUT_CASES}) == 60


def test_calibration_and_holdout_are_balanced_and_disjoint():
    """보정에 쓴 문장을 final holdout 정확도 계산에 다시 사용하지 않는다."""
    calibration_counts = Counter(
        case.expected_cohort_id for case in CALIBRATION_CASES
    )
    calibration_messages = {case.message for case in CALIBRATION_CASES}
    holdout_messages = {case.message for case in HOLDOUT_CASES}

    assert len(CALIBRATION_CASES) == 60
    assert calibration_counts == {
        "routine_support": 20,
        "account_billing": 20,
        "high_risk": 20,
    }
    assert calibration_messages.isdisjoint(holdout_messages)


def test_replay_evidence_dataset_is_independent_and_meets_minimum_sample_count():
    """A38: 실제 Replay 증거 입력은 보정/최종 평가와 분리하고 cohort별 5개를 둔다."""
    counts = Counter(case.expected_cohort_id for case in EVIDENCE_CASES)
    evidence_messages = {case.message for case in EVIDENCE_CASES}

    assert len(EVIDENCE_CASES) == 10
    assert counts == {"routine_support": 5, "account_billing": 5}
    assert evidence_messages.isdisjoint(case.message for case in CALIBRATION_CASES)
    assert evidence_messages.isdisjoint(case.message for case in HOLDOUT_CASES)
    assert EVIDENCE_MODELS == {
        "routine_support": "gpt-4o-mini",
        "account_billing": "gpt-4.1-mini",
    }


def test_final_holdout_is_balanced_unique_and_untouched_by_previous_datasets():
    """A39: 최종 60개는 이전 보정·검증·Replay 입력과 완전히 분리한다."""
    counts = Counter(case.expected_cohort_id for case in FINAL_HOLDOUT_CASES)
    final_messages = {case.message for case in FINAL_HOLDOUT_CASES}
    previous_messages = {
        case.message
        for dataset in (
            CALIBRATION_CASES,
            HOLDOUT_CASES,
            EVIDENCE_CASES,
            FINAL_HOLDOUT_V1_CASES,
            FINAL_HOLDOUT_V2_CASES,
        )
        for case in dataset
    }

    assert len(FINAL_HOLDOUT_CASES) == 60
    assert counts == {
        "routine_support": 20,
        "account_billing": 20,
        "high_risk": 20,
    }
    assert len({case.case_id for case in FINAL_HOLDOUT_CASES}) == 60
    assert len(final_messages) == 60
    assert final_messages.isdisjoint(previous_messages)


def test_expected_model_comes_from_frozen_active_policy_not_cohort_hardcode():
    """A40: cohort 전용 검증 rule이 없으면 policy default 모델을 예상한다."""
    active_policy = {
        "default_model_id": "gpt-4.1",
        "rules": [
            {
                "when": {"semantic_cohort_id": "account_billing"},
                "selected_model_id": "gpt-4.1-mini",
            }
        ],
    }

    assert (
        _expected_model_for_cohort(active_policy, "account_billing")
        == "gpt-4.1-mini"
    )
    assert _expected_model_for_cohort(active_policy, "routine_support") == "gpt-4.1"
    assert _expected_model_for_cohort(active_policy, "high_risk") == "gpt-4.1"


def test_replay_candidate_uses_exact_model_and_preserves_deployed_node_contract():
    """A38: B는 자동 라우팅을 끄고 배포 node 설정을 복사해 exact 모델만 검증한다."""
    request = _candidate_request_from_node(
        {
            "model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "auto_model_routing": True,
            "task_type": "customer_support_triage",
            "system_prompt": "system",
            "user_prompt": "{{ message }}",
            "assistant_prompt": "assistant",
            "referenced_variables": [{"name": "message"}],
            "parameters": {"temperature": 0.2, "max_tokens": 700},
            "output_format": {"type": "json", "schema": {"type": "object"}},
            "knowledgeBases": [{"id": "kb-1"}],
            "topK": 4,
            "scoreThreshold": 0.7,
        },
        candidate_model_id="gpt-4o-mini",
        label="routine evidence",
    )

    assert request["model_id"] == "gpt-4o-mini"
    assert request["fallback_model_id"] is None
    assert request["auto_model_routing"] is False
    assert request["system_prompt"] == "system"
    assert request["user_prompt"] == "{{ message }}"
    assert request["parameters"] == {"temperature": 0.2, "max_tokens": 700}
    assert request["output_format"] == {"type": "json", "schema": {"type": "object"}}
    assert request["knowledge"] == {
        "knowledge_base_ids": ["kb-1"],
        "top_k": 4,
        "score_threshold": 0.7,
    }


def test_embedding_preflight_retries_transient_provider_failure(monkeypatch):
    """A37: 일시적인 503은 제한적으로 재시도해 장시간 실험을 보존한다."""
    calls = []

    class Client:
        def embed_sync(self, text):
            calls.append(text)
            if len(calls) < 3:
                raise ValueError("embedding failed (status 503)")
            return [0.1, 0.2]

    monkeypatch.setattr("scripts.experiment_semantic_model_routing.time.sleep", lambda _seconds: None)

    assert _embed_with_retry(Client(), "문의 본문") == [0.1, 0.2]
    assert calls == ["문의 본문", "문의 본문", "문의 본문"]


def test_runtime_input_matches_deployed_llm_node_upstream_shape():
    """사전 평가도 실제 LLM node가 받는 upstream object와 같은 문장을 임베딩한다."""
    case = HOLDOUT_CASES[0]

    assert build_runtime_inputs(case) == {
        "webhook-ticket": {
            "message": case.message,
            "customerTier": case.customer_tier,
        }
    }


def test_report_keeps_expected_actual_model_and_human_reason():
    """최종 Obsidian 보고서에 사용자가 요구한 네 가지 판단 정보가 남는다."""
    case = HOLDOUT_CASES[0]
    report = build_markdown_report(
        [
            RoutingObservation(
                case=case,
                run_id="run-1",
                run_status="SUCCESS",
                expected_model_id="gpt-4o-mini",
                actual_model_id="gpt-4o-mini",
                actual_cohort_id="routine_support",
                match_status="matched",
                reason_code="validated_quality_floor_cost_reduction",
                similarity=0.82,
                threshold=0.55,
                margin=0.21,
                policy_version="router-policy-v2",
                route_catalog_version="ticket-routing-v1",
                candidate_cohort_id="routine_support",
                candidate_label="단순 사용·안내 문의",
            )
        ]
    )

    assert "입력" in report
    assert "예상 모델" in report
    assert "실제 모델" in report
    assert "선정 근거" in report
    assert case.message in report
    assert "gpt-4o-mini" in report
    assert "API key" not in report
    assert "auth_secret" not in report


def test_report_explains_closest_candidate_when_route_is_rejected():
    """미매칭 행은 가장 가까운 군과 탈락 기준을 보여줘 조정 근거가 된다."""
    case = HOLDOUT_CASES[0]
    report = build_markdown_report(
        [
            RoutingObservation(
                case=case,
                run_id=None,
                run_status="SEMANTIC_PREFLIGHT",
                expected_model_id="gpt-4o-mini",
                actual_model_id="gpt-4.1",
                actual_cohort_id=None,
                match_status="no_match",
                reason_code="semantic_no_match_default",
                similarity=0.43,
                threshold=0.55,
                margin=0.07,
                policy_version="router-policy-v2",
                route_catalog_version="ticket-routing-v1",
                candidate_cohort_id="account_billing",
                candidate_label="계정·결제 문의",
            )
        ]
    )

    assert "가장 가까운 유형은 계정·결제 문의" in report
    assert "유사도 43%가 선택 기준 55%에 미달" in report


def test_report_explains_policy_safety_override_without_signal_text():
    """A43: 보고서는 안전 우선 이유를 설명하되 policy signal 원문은 숨긴다."""
    case = FINAL_HOLDOUT_CASES[-1]
    report = build_markdown_report(
        [
            RoutingObservation(
                case=case,
                run_id="run-safety",
                run_status="SUCCESS",
                expected_model_id="gpt-4.1",
                actual_model_id="gpt-4.1",
                actual_cohort_id="high_risk",
                match_status="matched",
                reason_code="semantic_matched_no_rule_default",
                similarity=0.61,
                threshold=0.75,
                margin=-0.1,
                policy_version="router-policy-v7",
                route_catalog_version="ticket-routing-v7",
                candidate_cohort_id="high_risk",
                candidate_label="보안 및 SLA 고위험",
                semantic_decision_source="safety_override",
                lexical_signal_count=2,
            )
        ]
    )

    assert "정책의 안전 조건 2개와 일치" in report
    assert "credential leak" not in report
