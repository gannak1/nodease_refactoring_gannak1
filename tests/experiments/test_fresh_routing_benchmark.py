from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

import pytest

from scripts.experiment_fresh_routing_benchmark import (
    HIGH_FIXED_MODEL_ID,
    HOLDOUT_CASE_COUNT,
    LOW_FIXED_MODEL_ID,
    _all_case_pools,
    _cohort_drafts,
    _combine_bidirectional_quality_passes,
    _paired_cost_savings_summary,
    _quality_summary,
    _routing_summary,
    assess_routing_value,
    build_holdout_cases,
    build_report,
)


def test_bidirectional_quality_passes_are_averaged_and_costs_are_summed():
    combined = _combine_bidirectional_quality_passes(
        [
            {
                "status": "completed",
                "baseline": {"score": 92},
                "candidate": {"score": 78},
                "confidence_score": 0.85,
                "judge_cost": 0.0004,
            },
            {
                "status": "completed",
                "baseline": {"score": 90},
                "candidate": {"score": 70},
                "confidence_score": 0.9,
                "judge_cost": 0.0005,
            },
        ]
    )

    assert combined["status"] == "completed"
    assert combined["baseline_score"] == 91.0
    assert combined["candidate_score"] == 74.0
    assert combined["delta"] == -17.0
    assert combined["confidence"] == "high"
    assert combined["judge_cost"] == pytest.approx(0.0009)


def test_paired_cost_evidence_confirms_small_but_consistent_savings():
    high_rows = [
        SimpleNamespace(
            case=SimpleNamespace(case_id=f"case-{index}"),
            run_status="success",
            total_cost=cost,
        )
        for index, cost in enumerate((1.00, 1.10, 0.90, 1.05, 0.95), start=1)
    ]
    automatic_rows = [
        SimpleNamespace(
            case=SimpleNamespace(case_id=f"case-{index}"),
            run_status="success",
            total_cost=cost,
        )
        for index, cost in enumerate((0.94, 1.03, 0.84, 0.98, 0.89), start=1)
    ]

    evidence = _paired_cost_savings_summary(high_rows, automatic_rows)

    assert evidence["paired_samples"] == 5
    assert evidence["mean_savings_per_request"] == pytest.approx(0.064)
    assert evidence["confidence_interval_low"] > 0
    assert evidence["confirmed_positive"] is True


def test_routing_summary_counts_only_applied_discount_rules_and_checks_expected_evidence():
    rows = [
        SimpleNamespace(
            case=SimpleNamespace(expected_cohort_key="finance_closing_approval"),
            matched_cohort_key="account_access_request",
            selected_model="gpt-5.4-mini",
            reason_code="validated_adaptive_cohort",
            policy_version="v1",
            fallback_used=False,
        ),
        SimpleNamespace(
            case=SimpleNamespace(expected_cohort_key="routine_usage_guidance"),
            matched_cohort_key="account_access_request",
            selected_model="gpt-5.4-mini",
            reason_code="validated_adaptive_cohort",
            policy_version="v1",
            fallback_used=False,
        ),
        SimpleNamespace(
            case=SimpleNamespace(expected_cohort_key="security_privacy_incident"),
            matched_cohort_key="security_privacy_incident",
            selected_model="gpt-4.1",
            reason_code="semantic_matched_no_rule_default",
            policy_version="v1",
            fallback_used=False,
        ),
    ]
    policy = {
        "active_policy": {
            "default_model_id": "gpt-4.1",
            "rules": [
                {
                    "when": {"semantic_cohort_id": "account_access_request"},
                    "selected_model_id": "gpt-5.4-mini",
                },
                {
                    "when": {"semantic_cohort_id": "finance_closing_approval"},
                    "selected_model_id": "gpt-5.4-mini",
                },
            ],
        }
    }

    summary = _routing_summary(rows, policy=policy)

    assert summary["route_coverage_pct"] == pytest.approx(200 / 3)
    assert summary["validated_model_precision_pct"] == 50.0
    assert summary["routed_precision_pct"] == 0.0
    assert summary["high_risk_protection_rate_pct"] == 100.0


def test_routing_summary_uses_the_configured_high_model_for_safety_protection():
    """고성능 기준 모델을 CLI로 바꿔도 보호율은 실제 실험 설정을 따라야 한다."""
    rows = [
        SimpleNamespace(
            case=SimpleNamespace(expected_cohort_key="security_privacy_incident"),
            matched_cohort_key="security_privacy_incident",
            selected_model="gpt-5.4",
            reason_code="semantic_matched_no_rule_default",
            policy_version="v1",
            fallback_used=False,
        )
    ]

    summary = _routing_summary(
        rows,
        policy={"active_policy": {"rules": []}},
        high_model_id="gpt-5.4",
    )

    assert summary["high_risk_protection_rate_pct"] == 100.0


def test_routing_summary_reports_recall_only_for_cohorts_with_active_rules():
    """전체 할인 비율과 활성 규칙 입력군의 실제 매칭률을 분리한다."""
    rows = [
        SimpleNamespace(
            case=SimpleNamespace(expected_cohort_key="account_access_request"),
            matched_cohort_key="account_access_request",
            selected_model="gpt-5.6-luna",
            reason_code="validated_adaptive_cohort",
            policy_version="v1",
            fallback_used=False,
        ),
        SimpleNamespace(
            case=SimpleNamespace(expected_cohort_key="account_access_request"),
            matched_cohort_key=None,
            selected_model="gpt-5.4",
            reason_code="semantic_no_match_default",
            policy_version="v1",
            fallback_used=False,
        ),
        SimpleNamespace(
            case=SimpleNamespace(expected_cohort_key="security_privacy_incident"),
            matched_cohort_key="security_privacy_incident",
            selected_model="gpt-5.4",
            reason_code="safety_override_baseline",
            policy_version="v1",
            fallback_used=False,
        ),
    ]
    policy = {
        "active_policy": {
            "rules": [
                {
                    "when": {"semantic_cohort_id": "account_access_request"},
                    "selected_model_id": "gpt-5.6-luna",
                    "reason_code": "validated_adaptive_cohort",
                }
            ]
        }
    }

    summary = _routing_summary(rows, policy=policy, high_model_id="gpt-5.4")

    assert summary["route_coverage_pct"] == pytest.approx(100 / 3)
    assert summary["eligible_route_recall_pct"] == 50.0


def test_quality_summary_attributes_severe_drop_only_when_model_changed():
    """동일 모델의 확률적 출력 차이를 자동 라우팅 사고로 오인하지 않는다."""
    summary = _quality_summary(
        [
            {
                "status": "completed",
                "baseline_score": 90,
                "candidate_score": 70,
                "delta": -20,
                "model_changed": False,
            },
            {
                "status": "completed",
                "baseline_score": 90,
                "candidate_score": 72,
                "delta": -18,
                "model_changed": True,
            },
        ]
    )

    assert summary["severe_regressions"] == 2
    assert summary["routing_attributable_severe_regressions"] == 1


def test_holdout_is_balanced_reproducible_and_disjoint_from_bootstrap_examples():
    cases = build_holdout_cases(shuffle_seed=272)
    repeated = build_holdout_cases(shuffle_seed=272)
    bootstrap_queries = {
        query
        for draft in _cohort_drafts()
        for query in draft["representative_examples"]
    }
    previous_experiment_queries = {
        query
        for rows in _all_case_pools().values()
        for query, _department, _role in rows
    }

    assert len(cases) == HOLDOUT_CASE_COUNT == 48
    assert [case.case_id for case in cases] == [case.case_id for case in repeated]
    assert len({case.query for case in cases}) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in cases) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert bootstrap_queries.isdisjoint(case.query for case in cases)
    assert previous_experiment_queries.isdisjoint(case.query for case in cases)
    v3_queries = {
        case.query
        for case in build_holdout_cases(shuffle_seed=272, holdout_version="v3")
    }
    assert v3_queries.isdisjoint(case.query for case in cases)


def test_v5_holdout_is_disjoint_from_v4_after_safety_guard_calibration():
    """V4 안전 오분류를 본 뒤에는 같은 문장으로 개선 효과를 재평가하지 않는다."""
    v4 = build_holdout_cases(shuffle_seed=417, holdout_version="v4")
    v5 = build_holdout_cases(shuffle_seed=518, holdout_version="v5")
    v3 = build_holdout_cases(shuffle_seed=272, holdout_version="v3")

    assert len(v5) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v5) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert {case.query for case in v4}.isdisjoint(case.query for case in v5)
    assert {case.query for case in v3}.isdisjoint(case.query for case in v5)


def test_v6_holdout_is_disjoint_after_active_route_revalidation_fix():
    """활성 규칙 재검증을 고친 뒤에는 V5에서 본 문장을 다시 평가에 쓰지 않는다."""
    v4 = build_holdout_cases(shuffle_seed=417, holdout_version="v4")
    v5 = build_holdout_cases(shuffle_seed=518, holdout_version="v5")
    v6 = build_holdout_cases(shuffle_seed=619, holdout_version="v6")

    assert len(v6) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v6) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert {case.query for case in v4}.isdisjoint(case.query for case in v6)
    assert {case.query for case in v5}.isdisjoint(case.query for case in v6)


def test_finance_and_security_cohorts_are_safety_protected():
    """금액 승인과 보안 사고 입력군은 검증 전 할인 모델로 내려가면 안 된다."""
    drafts = {draft["key"]: draft for draft in _cohort_drafts()}

    assert drafts["finance_closing_approval"]["safety_protected"] is True
    assert drafts["security_privacy_incident"]["safety_protected"] is True
    assert drafts["account_access_request"]["safety_protected"] is False
    assert drafts["routine_usage_guidance"]["safety_protected"] is False


def test_v7_holdout_is_disjoint_after_safety_policy_reclassification():
    """안전 정책을 바꾼 뒤에는 V4~V6에서 본 문장을 최종 판정에 재사용하지 않는다."""
    previous = {
        case.query
        for version, seed in (("v4", 417), ("v5", 518), ("v6", 619))
        for case in build_holdout_cases(shuffle_seed=seed, holdout_version=version)
    }
    v7 = build_holdout_cases(shuffle_seed=720, holdout_version="v7")

    assert len(v7) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v7) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v7)


def test_v8_holdout_is_disjoint_after_balanced_safety_boundary():
    """과잉 보호 경계를 고친 최종 실험은 V4~V7 holdout과 완전히 분리한다."""
    previous = {
        case.query
        for version, seed in (
            ("v4", 417),
            ("v5", 518),
            ("v6", 619),
            ("v7", 720),
        )
        for case in build_holdout_cases(shuffle_seed=seed, holdout_version=version)
    }
    v8 = build_holdout_cases(shuffle_seed=821, holdout_version="v8")

    assert len(v8) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v8) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v8)


def test_v9_holdout_is_disjoint_after_robust_quality_outlier_gate():
    """품질 이상치 gate를 고친 재실험은 V4~V8 결과를 학습하지 않은 새 입력을 쓴다."""
    previous = {
        case.query
        for version, seed in (
            ("v4", 417),
            ("v5", 518),
            ("v6", 619),
            ("v7", 720),
            ("v8", 821),
        )
        for case in build_holdout_cases(shuffle_seed=seed, holdout_version=version)
    }
    v9 = build_holdout_cases(shuffle_seed=922, holdout_version="v9")

    assert len(v9) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v9) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v9)


def test_v10_holdout_is_disjoint_after_safety_drift_guard():
    """안전 drift guard 최종 검증은 V4~V9와 겹치지 않는 새 문의를 사용한다."""
    previous = {
        case.query
        for version, seed in (
            ("v4", 417),
            ("v5", 518),
            ("v6", 619),
            ("v7", 720),
            ("v8", 821),
            ("v9", 922),
        )
        for case in build_holdout_cases(shuffle_seed=seed, holdout_version=version)
    }
    v10 = build_holdout_cases(shuffle_seed=1023, holdout_version="v10")

    assert len(v10) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v10) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v10)


def test_v11_holdout_is_disjoint_after_validated_route_drift_recovery():
    """검증된 rule의 작은 drift 복구 효과는 V4~V10과 다른 문의로 판정한다."""
    previous = {
        case.query
        for version, seed in (
            ("v4", 417),
            ("v5", 518),
            ("v6", 619),
            ("v7", 720),
            ("v8", 821),
            ("v9", 922),
            ("v10", 1023),
        )
        for case in build_holdout_cases(shuffle_seed=seed, holdout_version=version)
    }
    v11 = build_holdout_cases(shuffle_seed=1124, holdout_version="v11")

    assert len(v11) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v11) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v11)


def test_v12_holdout_is_disjoint_after_quality_and_safety_gate_hardening():
    """품질·안전 gate 강화 효과는 V4~V11에서 보지 않은 문의로 평가한다."""
    previous = {
        case.query
        for version, seed in (
            ("v4", 417),
            ("v5", 518),
            ("v6", 619),
            ("v7", 720),
            ("v8", 821),
            ("v9", 922),
            ("v10", 1023),
            ("v11", 1124),
        )
        for case in build_holdout_cases(shuffle_seed=seed, holdout_version=version)
    }
    v12 = build_holdout_cases(shuffle_seed=1225, holdout_version="v12")

    assert len(v12) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v12) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v12)


def test_v13_holdout_is_disjoint_after_dual_quality_gate():
    """평균+보수적 하한 이중 gate는 V4~V12와 다른 문의로 검증한다."""
    previous = {
        case.query
        for version, seed in (
            ("v4", 417),
            ("v5", 518),
            ("v6", 619),
            ("v7", 720),
            ("v8", 821),
            ("v9", 922),
            ("v10", 1023),
            ("v11", 1124),
            ("v12", 1225),
        )
        for case in build_holdout_cases(shuffle_seed=seed, holdout_version=version)
    }
    v13 = build_holdout_cases(shuffle_seed=1326, holdout_version="v13")

    assert len(v13) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v13) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v13)


def test_v14_holdout_is_disjoint_after_candidate_isolation_fix():
    """V14는 후보 fallback/품질 계약 수정 뒤 쓰는 새로운 독립 holdout이다."""
    previous = {
        case.query
        for version, seed in (
            ("v3", 803),
            ("v4", 914),
            ("v5", 1025),
            ("v6", 1036),
            ("v7", 1147),
            ("v8", 1168),
            ("v9", 1189),
            ("v10", 1200),
            ("v11", 1211),
            ("v12", 1222),
            ("v13", 1326),
        )
        for case in build_holdout_cases(shuffle_seed=seed, holdout_version=version)
    }

    v14 = build_holdout_cases(shuffle_seed=1437, holdout_version="v14")

    assert len(v14) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v14) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v14)


def test_v15_holdout_is_disjoint_after_quality_and_margin_fix():
    """V15는 V14 품질 이상치·입력군 경계 보정 뒤 쓰는 독립 holdout이다."""
    previous_versions = (
        "v3",
        "v4",
        "v5",
        "v6",
        "v7",
        "v8",
        "v9",
        "v10",
        "v11",
        "v12",
        "v13",
        "v14",
    )
    previous = {
        case.query
        for version in previous_versions
        for case in build_holdout_cases(shuffle_seed=1437, holdout_version=version)
    }

    v15 = build_holdout_cases(shuffle_seed=1537, holdout_version="v15")

    assert len(v15) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v15) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v15)


def test_v16_holdout_is_disjoint_after_semantic_precision_fix():
    """V16은 ambiguity·overlap 경계 수정 뒤 쓰는 새로운 독립 holdout이다."""
    previous = {
        case.query
        for version in (
            "v3",
            "v4",
            "v5",
            "v6",
            "v7",
            "v8",
            "v9",
            "v10",
            "v11",
            "v12",
            "v13",
            "v14",
            "v15",
        )
        for case in build_holdout_cases(shuffle_seed=1638, holdout_version=version)
    }

    v16 = build_holdout_cases(shuffle_seed=1638, holdout_version="v16")

    assert len(v16) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v16) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v16)


def test_v17_holdout_is_disjoint_after_single_output_quality_floor_fix():
    """V17은 V16 단일 응답 품질 하한 강화 후 쓰는 독립 holdout이다."""
    previous = {
        case.query
        for version in (
            "v3",
            "v4",
            "v5",
            "v6",
            "v7",
            "v8",
            "v9",
            "v10",
            "v11",
            "v12",
            "v13",
            "v14",
            "v15",
            "v16",
        )
        for case in build_holdout_cases(shuffle_seed=1739, holdout_version=version)
    }

    v17 = build_holdout_cases(shuffle_seed=1739, holdout_version="v17")

    assert len(v17) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v17) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v17)


def test_v18_holdout_is_disjoint_after_bidirectional_quality_judge_fix():
    """V18은 품질 Judge 순서 편향 수정 뒤 쓰는 새로운 독립 holdout이다."""
    previous = {
        case.query
        for version in (
            "v3",
            "v4",
            "v5",
            "v6",
            "v7",
            "v8",
            "v9",
            "v10",
            "v11",
            "v12",
            "v13",
            "v14",
            "v15",
            "v16",
            "v17",
        )
        for case in build_holdout_cases(shuffle_seed=1840, holdout_version=version)
    }
    v18 = build_holdout_cases(shuffle_seed=1840, holdout_version="v18")

    assert len(v18) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v18) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v18)


def test_v19_holdout_is_disjoint_after_grounding_aware_quality_judge_fix():
    """V19는 근거 인식 Judge 적용 뒤 쓰는 새로운 독립 holdout이다."""
    previous = {
        case.query
        for version in (
            "v3",
            "v4",
            "v5",
            "v6",
            "v7",
            "v8",
            "v9",
            "v10",
            "v11",
            "v12",
            "v13",
            "v14",
            "v15",
            "v16",
            "v17",
            "v18",
        )
        for case in build_holdout_cases(shuffle_seed=1941, holdout_version=version)
    }
    v19 = build_holdout_cases(shuffle_seed=1941, holdout_version="v19")

    assert len(v19) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v19) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v19)


def test_v20_holdout_is_disjoint_after_relative_quality_promotion_fix():
    """V20은 상대 품질을 반영한 승격 gate 뒤 쓰는 새로운 독립 holdout이다."""
    previous = {
        case.query
        for version in (
            "v3",
            "v4",
            "v5",
            "v6",
            "v7",
            "v8",
            "v9",
            "v10",
            "v11",
            "v12",
            "v13",
            "v14",
            "v15",
            "v16",
            "v17",
            "v18",
            "v19",
        )
        for case in build_holdout_cases(shuffle_seed=2042, holdout_version=version)
    }
    v20 = build_holdout_cases(shuffle_seed=2042, holdout_version="v20")

    assert len(v20) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v20) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v20)


def test_v21_holdout_is_disjoint_after_threshold_drift_recovery_removal():
    """V21은 검증 경계 밖 강제 복구 제거 뒤 쓰는 새로운 독립 holdout이다."""
    previous = {
        case.query
        for version in (
            "v3",
            "v4",
            "v5",
            "v6",
            "v7",
            "v8",
            "v9",
            "v10",
            "v11",
            "v12",
            "v13",
            "v14",
            "v15",
            "v16",
            "v17",
            "v18",
            "v19",
            "v20",
        )
        for case in build_holdout_cases(shuffle_seed=2143, holdout_version=version)
    }
    v21 = build_holdout_cases(shuffle_seed=2143, holdout_version="v21")

    assert len(v21) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v21) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v21)


def test_v22_holdout_is_disjoint_for_quality_margin_selection():
    previous = {
        case.query
        for version, seed in (
            ("v3", 392),
            ("v4", 419),
            ("v5", 503),
            ("v6", 607),
            ("v7", 701),
            ("v8", 809),
            ("v9", 907),
            ("v10", 1013),
            ("v11", 1117),
            ("v12", 1213),
            ("v13", 1319),
            ("v14", 1423),
            ("v15", 1511),
            ("v16", 1613),
            ("v17", 1709),
            ("v18", 1811),
            ("v19", 1907),
            ("v20", 2017),
            ("v21", 2143),
        )
        for case in build_holdout_cases(shuffle_seed=seed, holdout_version=version)
    }
    v22 = build_holdout_cases(shuffle_seed=2287, holdout_version="v22")

    assert len(v22) == HOLDOUT_CASE_COUNT
    assert Counter(case.expected_cohort_key for case in v22) == {
        "routine_usage_guidance": 12,
        "account_access_request": 12,
        "finance_closing_approval": 12,
        "security_privacy_incident": 12,
    }
    assert previous.isdisjoint(case.query for case in v22)


def test_routing_value_requires_cost_savings_and_quality_advantage_over_low_fixed():
    assessment = assess_routing_value(
        high_fixed_summary={"total_cost": 0.096, "successes": 48},
        low_fixed_summary={"total_cost": 0.040, "successes": 48},
        automatic_summary={"total_cost": 0.064, "successes": 48},
        quality_summary={
            "automatic_vs_high": {
                "completed": 48,
                "average_delta": -1.0,
                "severe_regressions": 0,
            },
            "low_vs_high": {
                "completed": 48,
                "average_delta": -8.0,
                "severe_regressions": 5,
            },
            "automatic_vs_low": {
                "completed": 48,
                "average_delta": 7.0,
                "severe_regressions": 0,
            },
        },
        routing_summary={
            "routed_precision_pct": 100.0,
            "validated_model_precision_pct": 100.0,
            "route_coverage_pct": 45.0,
            "eligible_route_recall_pct": 50.0,
            "trace_record_rate_pct": 100.0,
            "high_risk_protection_rate_pct": 100.0,
        },
        validation_cost_usd=0.18,
    )

    assert assessment["verdict"] == "justified_at_sufficient_volume"
    assert assessment["cost_advantage_over_high"] is True
    assert assessment["quality_maintained_vs_high"] is True
    assert assessment["quality_advantage_over_low"] is True
    assert assessment["break_even_requests"] == 270
    assert assessment["low_fixed_tradeoff"]["avoided_severe_regressions"] == 5
    assert assessment["low_fixed_tradeoff"]["cost_per_avoided_severe_regression_usd"] == pytest.approx(
        (0.064 - 0.040) / 5
    )


def test_routing_value_does_not_claim_success_when_a_low_fixed_model_is_equally_safe():
    assessment = assess_routing_value(
        high_fixed_summary={"total_cost": 0.096, "successes": 48},
        low_fixed_summary={"total_cost": 0.040, "successes": 48},
        automatic_summary={"total_cost": 0.064, "successes": 48},
        quality_summary={
            "automatic_vs_high": {
                "completed": 48,
                "average_delta": -1.0,
                "severe_regressions": 0,
            },
            "low_vs_high": {
                "completed": 48,
                "average_delta": -1.0,
                "severe_regressions": 0,
            },
            "automatic_vs_low": {
                "completed": 48,
                "average_delta": 0.0,
                "severe_regressions": 0,
            },
        },
        routing_summary={
            "routed_precision_pct": 100.0,
            "validated_model_precision_pct": 100.0,
            "route_coverage_pct": 45.0,
            "eligible_route_recall_pct": 50.0,
            "trace_record_rate_pct": 100.0,
            "high_risk_protection_rate_pct": 100.0,
        },
        validation_cost_usd=0.18,
    )

    assert assessment["verdict"] == "fixed_low_model_recommended"
    assert assessment["quality_advantage_over_low"] is False
    assert assessment["low_fixed_tradeoff"]["cost_per_avoided_severe_regression_usd"] is None


def test_routing_value_reports_confirmed_small_savings_as_high_volume_value():
    assessment = assess_routing_value(
        high_fixed_summary={"total_cost": 0.075, "successes": 48},
        low_fixed_summary={"total_cost": 0.005, "successes": 48},
        automatic_summary={"total_cost": 0.071, "successes": 48},
        quality_summary={
            "automatic_vs_high": {
                "completed": 48,
                "average_delta": 1.0,
                "severe_regressions": 0,
            },
            "low_vs_high": {
                "completed": 48,
                "average_delta": -8.0,
                "severe_regressions": 5,
                "high_risk_severe_regressions": 1,
            },
            "automatic_vs_low": {
                "completed": 48,
                "average_delta": 9.0,
                "severe_regressions": 0,
            },
        },
        routing_summary={
            "validated_model_precision_pct": 100.0,
            "route_coverage_pct": 25.0,
            "eligible_route_recall_pct": 50.0,
            "trace_record_rate_pct": 100.0,
            "high_risk_protection_rate_pct": 100.0,
        },
        validation_cost_usd=0.20,
        paired_cost_evidence={
            "paired_samples": 48,
            "mean_savings_per_request": 0.004 / 48,
            "confidence_interval_low": 0.00001,
            "confidence_interval_high": 0.00016,
            "confirmed_positive": True,
        },
    )

    assert assessment["verdict"] == "justified_at_high_volume"
    assert assessment["cost_advantage_over_high"] is True
    assert assessment["meets_target_savings_rate"] is False
    assert assessment["low_fixed_tradeoff"]["avoided_severe_regressions"] == 5


def test_report_explains_all_three_variants_quality_and_break_even():
    payload = {
        "metadata": {
            "holdout_case_count_per_variant": 0,
            "high_fixed_model_id": "gpt-5.4",
            "low_fixed_model_id": "gpt-4o-mini",
        },
        "targets": {
            "automatic": {"workflow_id": "auto-wf", "deployment_id": "auto-dep"},
            "high_fixed": {"workflow_id": "high-wf", "deployment_id": "high-dep"},
            "low_fixed": {"workflow_id": "low-wf", "deployment_id": "low-dep"},
        },
        "automatic": {"initial_policy": {}, "final_policy": {}},
        "benchmark": {
            "high_fixed": [],
            "low_fixed": [],
            "automatic": [],
            "high_fixed_summary": {"successes": 0, "total_cost": 0},
            "low_fixed_summary": {"successes": 0, "total_cost": 0},
            "automatic_summary": {"successes": 0, "total_cost": 0},
        },
        "quality": {
            "automatic_vs_high": {"completed": 0},
            "low_vs_high": {"completed": 0},
            "automatic_vs_low": {"completed": 0},
            "judge_cost_usd": 0,
        },
        "routing_summary": {
            "cohort_accuracy_pct": 0,
            "routed_precision_pct": 0,
            "validated_model_precision_pct": 0,
            "route_coverage_pct": 0,
            "trace_record_rate_pct": 0,
            "high_risk_protection_rate_pct": 0,
        },
        "assessment": {
            "verdict": "insufficient_evidence",
            "break_even_requests": None,
        },
    }

    report = build_report(payload)

    assert "고성능 모델 고정: `gpt-5.4`" in report
    assert LOW_FIXED_MODEL_ID in report
    assert "저비용 모델 고정" in report
    assert "품질" in report
    assert "손익분기" in report
    assert "품질 사고" in report
    assert "economics.png" in report
