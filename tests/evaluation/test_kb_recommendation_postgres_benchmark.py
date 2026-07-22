import json

from tests.evaluation.kb_recommendation_postgres_benchmark import (
    CONTROLLED_DB_DATA_CLASSIFICATION,
    build_controlled_case_plan,
    build_controlled_db_report,
)


def test_controlled_case_plan_has_required_synthetic_coverage_without_fixture_changes():
    dataset, plans = build_controlled_case_plan()

    assert dataset["data_classification"] == "synthetic_non_secret"
    assert len(dataset["cases"]) == 30
    assert len(plans) == 30
    assert sum(case["metadata_poor"] for case in dataset["cases"]) >= 10
    assert any(
        "candidate_budget_5000" in case["case_tags"]
        and case["authorized_candidate_count"] == 5000
        for case in dataset["cases"]
    )
    budget_case = next(
        case
        for case in dataset["cases"]
        if "candidate_budget_5000" in case["case_tags"]
    )
    assert budget_case["expected_relevant"]
    assert "no_result" not in budget_case["case_tags"]
    assert all(len(case["candidate_labels"]) <= 5000 for case in dataset["cases"])


def test_controlled_db_report_is_aggregate_only_and_explicitly_not_release_evidence():
    gate_report = {
        "passed": True,
        "case_count": 30,
        "metadata_poor_case_count": 12,
        "baseline": {
            "precision@5": 0.1,
            "recall@5": 0.5,
            "mrr": 0.5,
            "no_result_accuracy": 1.0,
        },
        "parent_first": {
            "precision@5": 0.2,
            "recall@5": 1.0,
            "mrr": 1.0,
            "no_result_accuracy": 1.0,
        },
        "metadata_poor": {
            "baseline_recall@5": 0.0,
            "parent_first_recall@5": 1.0,
        },
        "operational": {
            "p50_latency_ms": 10,
            "p95_latency_ms": 20,
            "max_latency_ms": 30,
            "max_authorized_candidate_count": 5000,
            "max_processed_cohort_count": 1,
            "max_embedding_calls": 1,
            "max_discovery_sql": 1,
            "max_parent_sql": 1,
            "max_candidate_sql": 0,
            "leakage_count": 0,
        },
        "failed_gates": [],
    }

    report = build_controlled_db_report(
        gate_report=gate_report,
        provider_calls=0,
        synthetic_embedding_resolver_calls=30,
    )

    assert report["data_classification"] == CONTROLLED_DB_DATA_CLASSIFICATION
    assert report["evidence_scope"] == "controlled_db_not_release_evidence"
    assert report["provider_calls"] == 0
    assert report["release_ready"] is False
    serialized = json.dumps(report, ensure_ascii=False)
    assert "candidate_labels" not in serialized
    assert "expected_relevant" not in serialized
    assert "query" not in serialized
    assert "embedding_vector" not in serialized
