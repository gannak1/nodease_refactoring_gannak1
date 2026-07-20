import pytest

from tests.evaluation.kb_recommendation_release_gates import (
    _ranking_metrics,
    evaluate_release_gates,
)


REQUIRED_CASE_TAGS = (
    "metadata_poor",
    "name_only_irrelevant",
    "flat",
    "duplicate_collection",
    "denied_distractor",
    "korean",
    "english",
    "candidate_budget_5000",
)


def _case(index, *, metadata_poor=False, no_result=False):
    relevant = [] if no_result else [f"kb-{index}"]
    baseline = [] if metadata_poor or no_result else [f"kb-{index}"]
    parent_first = [] if no_result else [f"kb-{index}"]
    case_tags = [tag for tag_index, tag in enumerate(REQUIRED_CASE_TAGS) if index == tag_index]
    if metadata_poor and "metadata_poor" not in case_tags:
        case_tags.append("metadata_poor")
    candidate_count = 5000 if "candidate_budget_5000" in case_tags else 20
    return {
        "case_id": f"case-{index}",
        "case_tags": case_tags,
        "metadata_poor": metadata_poor,
        "expected_relevant": relevant,
        "baseline_ranked": baseline,
        "parent_first_ranked": parent_first,
        "latency_ms": 1000 + index,
        "authorized_candidate_count": candidate_count,
        "processed_cohort_count": 1,
        "embedding_calls": 1,
        "discovery_sql": 1,
        "parent_sql": 1,
        "candidate_sql": 0,
        "leakage_count": 0,
    }


def test_release_gate_accepts_thirty_cases_with_metadata_poor_improvement():
    cases = [
        _case(index, metadata_poor=index < 10, no_result=index in {28, 29})
        for index in range(30)
    ]

    report = evaluate_release_gates(cases)

    assert report["passed"] is True
    assert report["case_count"] == 30
    assert report["metadata_poor_case_count"] == 10
    assert report["parent_first"]["recall@5"] >= report["baseline"]["recall@5"]
    assert report["parent_first"]["mrr"] >= report["baseline"]["mrr"]
    assert report["failed_gates"] == []
    assert "cases" not in report


def test_release_gate_rejects_precision_regression_over_two_percentage_points():
    cases = [_case(index, metadata_poor=index < 10) for index in range(30)]
    for case in cases:
        case["baseline_ranked"] = [
            case["expected_relevant"][0],
            "baseline-irrelevant-1",
            "baseline-irrelevant-2",
            "baseline-irrelevant-3",
            "baseline-irrelevant-4",
        ]
        case["parent_first_ranked"] = [
            "irrelevant-1",
            "irrelevant-2",
            "irrelevant-3",
            "irrelevant-4",
            "irrelevant-5",
        ]

    report = evaluate_release_gates(cases)

    assert report["passed"] is False
    assert "precision_at_5" in report["failed_gates"]


def test_release_gate_requires_documented_dataset_size():
    with pytest.raises(ValueError):
        evaluate_release_gates([_case(index, metadata_poor=True) for index in range(29)])


def test_precision_at_five_uses_five_slots_for_short_rankings():
    metrics = _ranking_metrics(
        [{"expected_relevant": ["relevant"], "ranked": ["relevant"]}],
        "ranked",
    )

    assert metrics["precision@5"] == pytest.approx(0.2)


def test_release_gate_rejects_calls_above_processed_cohort_count():
    cases = [_case(index, metadata_poor=index < 10) for index in range(30)]
    cases[0]["embedding_calls"] = 2

    report = evaluate_release_gates(cases)

    assert report["passed"] is False
    assert "embedding_calls_per_cohort" in report["failed_gates"]


def test_release_gate_requires_exact_discovery_and_candidate_budget():
    cases = [_case(index, metadata_poor=index < 10) for index in range(30)]
    cases[0]["discovery_sql"] = 0
    cases[1]["authorized_candidate_count"] = 5001

    report = evaluate_release_gates(cases)

    assert "discovery_sql" in report["failed_gates"]
    assert "candidate_budget" in report["failed_gates"]


def test_release_gate_requires_unique_cases_and_documented_categories():
    cases = [_case(index, metadata_poor=index < 10) for index in range(30)]
    cases[1]["case_id"] = cases[0]["case_id"]

    with pytest.raises(ValueError, match="unique case_id"):
        evaluate_release_gates(cases)

    cases = [_case(index, metadata_poor=index < 10) for index in range(30)]
    for case in cases:
        case["case_tags"] = [
            tag for tag in case["case_tags"] if tag != "denied_distractor"
        ]

    with pytest.raises(ValueError, match="required case categories"):
        evaluate_release_gates(cases)


def test_release_gate_rejects_negative_operational_evidence():
    cases = [_case(index, metadata_poor=index < 10) for index in range(30)]
    cases[0]["latency_ms"] = -1

    with pytest.raises(ValueError, match="non-negative operational evidence"):
        evaluate_release_gates(cases)


def test_candidate_budget_category_requires_exact_five_thousand_candidates():
    cases = [_case(index, metadata_poor=index < 10) for index in range(30)]
    budget_case = next(
        case for case in cases if "candidate_budget_5000" in case["case_tags"]
    )
    budget_case["authorized_candidate_count"] = 4999

    with pytest.raises(ValueError, match="candidate_budget_5000"):
        evaluate_release_gates(cases)
