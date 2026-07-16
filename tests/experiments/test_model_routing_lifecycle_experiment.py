from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.experiment_model_routing_lifecycle import (
    _cohort_breakdown,
    _lifecycle_summary,
    _policy_checkpoint,
    _safe_lifecycle_payload,
    build_report,
)


def test_policy_checkpoint_exposes_refresh_validation_and_active_rules():
    policy = {
        "policy_version": "adaptive-v3",
        "status": "active",
        "refresh": {
            "eligible_runs_since_last_refresh": 2,
            "last_refresh_result": "applied",
        },
        "active_policy": {
            "rules": [{"id": "rule-a"}, {"id": "rule-b"}],
        },
        "adaptive": {
            "spent_usd": 0.17,
            "latest_batch": {"id": "batch-2", "status": "completed"},
        },
    }

    checkpoint = _policy_checkpoint(sequence=20, policy=policy, rows=[])

    assert checkpoint["sequence"] == 20
    assert checkpoint["policy_version"] == "adaptive-v3"
    assert checkpoint["active_rule_count"] == 2
    assert checkpoint["validation_spend_usd"] == pytest.approx(0.17)
    assert checkpoint["last_refresh_result"] == "applied"
    assert checkpoint["latest_batch_id"] == "batch-2"


def test_lifecycle_summary_requires_refresh_matching_and_model_diversity():
    rows = [
        SimpleNamespace(
            case=SimpleNamespace(expected_cohort_key="routine"),
            matched_cohort_key="routine",
            semantic_match_status="matched",
            selected_model="gpt-4.1-mini",
            reason_code="validated_adaptive_cohort",
            policy_version="v2",
            fallback_used=False,
            run_status="success",
            node_status="success",
        ),
        SimpleNamespace(
            case=SimpleNamespace(expected_cohort_key="security"),
            matched_cohort_key="security",
            semantic_match_status="matched",
            selected_model="gpt-4.1",
            reason_code="semantic_matched_no_rule_default",
            policy_version="v2",
            fallback_used=False,
            run_status="success",
            node_status="success",
        ),
    ]
    checkpoints = [
        {"sequence": 0, "policy_version": "v1", "latest_batch_id": "batch-1"},
        {"sequence": 20, "policy_version": "v2", "latest_batch_id": "batch-2"},
    ]

    summary = _lifecycle_summary(rows=rows, checkpoints=checkpoints)

    assert summary["all_runs_succeeded"] is True
    assert summary["cohort_accuracy_pct"] == 100.0
    assert summary["route_coverage_pct"] == 50.0
    assert summary["selected_model_count"] == 2
    assert summary["policy_refresh_observed"] is True
    assert summary["criteria_passed"] is True


def test_lifecycle_state_removes_raw_queries_and_embedding_vectors():
    payload = {
        "rows": [
            {
                "case": {
                    "case_id": "case-1",
                    "query": "저장하면 안 되는 실제 문의",
                    "expected_cohort_key": "billing",
                }
            }
        ],
        "final_policy": {
            "active_policy": {
                "semantic_router": {
                    "routes": [
                        {
                            "cohort_id": "billing",
                            "centroid_embedding": [0.1, 0.2],
                            "representatives": [{"embedding": [0.3, 0.4]}],
                        }
                    ]
                }
            }
        },
    }

    safe = _safe_lifecycle_payload(payload)
    serialized = str(safe)

    assert "저장하면 안 되는 실제 문의" not in serialized
    assert "centroid_embedding" not in serialized
    assert "embedding" not in serialized
    assert safe["rows"][0]["case"]["case_id"] == "case-1"
    assert safe["rows"][0]["case"]["query_sha256"]


def test_lifecycle_report_explains_results_by_cohort_and_refresh_trigger():
    rows = [
        SimpleNamespace(
            case=SimpleNamespace(expected_cohort_key="routine"),
            matched_cohort_key="routine",
            semantic_match_status="matched",
            selected_model="gpt-4.1-mini",
            reason_code="validated_adaptive_cohort",
            run_status="success",
            node_status="success",
            error_code=None,
        ),
        SimpleNamespace(
            case=SimpleNamespace(expected_cohort_key="security"),
            matched_cohort_key="routine",
            semantic_match_status="matched",
            selected_model="gpt-4.1",
            reason_code="semantic_matched_no_rule_default",
            run_status="failed",
            node_status="failed",
            error_code="provider_timeout",
        ),
    ]
    breakdown = _cohort_breakdown(rows)
    assert breakdown["routine"]["match_accuracy_pct"] == 100.0
    assert breakdown["routine"]["validated_route_coverage_pct"] == 100.0
    assert breakdown["security"]["match_accuracy_pct"] == 0.0
    assert breakdown["security"]["failures"] == 1

    payload = {
        "summary": {
            "criteria_passed": False,
            "requests": 2,
            "success_count": 1,
            "failure_count": 1,
            "all_runs_succeeded": False,
            "cohort_accuracy_pct": 50.0,
            "route_coverage_pct": 50.0,
            "models": {"gpt-4.1": 1, "gpt-4.1-mini": 1},
            "policy_refresh_observed": True,
            "cohort_breakdown": breakdown,
            "failure_reasons": {"provider_timeout": 1},
        },
        "checkpoints": [
            {
                "sequence": 20,
                "policy_version": "v2",
                "active_rule_count": 1,
                "validation_spend_usd": 0.1,
                "last_refresh_result": "pending_review",
                "latest_batch_id": "batch-2",
                "latest_batch_status": "completed",
                "latest_batch_trigger": "auto_n_runs",
                "refresh_observed": True,
            }
        ],
    }

    report = build_report(payload)

    assert "## 입력군별 결과" in report
    assert "routine" in report
    assert "provider_timeout" in report
    assert "auto_n_runs" in report
    assert "다음 개선 판단" in report
