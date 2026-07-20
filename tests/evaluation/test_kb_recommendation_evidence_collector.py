import json
from pathlib import Path

import pytest

from tests.evaluation.kb_recommendation_evidence_collector import (
    collect_evidence,
    load_controlled_dataset,
)
from tests.evaluation.kb_recommendation_release_gates import (
    REQUIRED_CASE_TAGS,
    evaluate_release_gates,
)


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "kb_recommendation_cases.json"
)


def _dataset():
    return {
        "schema_version": "mba-342-synthetic-v1",
        "data_classification": "synthetic_non_secret",
        "cases": [
            {
                "case_id": "mba342-syn-case-001",
                "case_tags": ["english"],
                "metadata_poor": False,
                "query": "synthetic travel policy request",
                "candidate_labels": [
                    "mba342-syn-kb-001-target",
                    "mba342-syn-kb-001-distractor",
                ],
                "expected_relevant": ["mba342-syn-kb-001-target"],
                "authorized_candidate_count": 2,
            },
            {
                "case_id": "mba342-syn-case-002",
                "case_tags": ["korean", "metadata_poor"],
                "metadata_poor": True,
                "query": "합성 온보딩 절차 요청",
                "candidate_labels": [
                    "mba342-syn-kb-002-target",
                    "mba342-syn-kb-002-distractor",
                ],
                "expected_relevant": ["mba342-syn-kb-002-target"],
                "authorized_candidate_count": 2,
            },
        ],
    }


def _baseline(case_id, ranked, *, candidate_count=2, **extra):
    return {
        "case_id": case_id,
        "ranked_labels": ranked,
        "authorized_candidate_count": candidate_count,
        **extra,
    }


def _parent(case_id, ranked, *, candidate_count=2, **extra):
    return {
        "case_id": case_id,
        "ranked_labels": ranked,
        "authorized_candidate_count": candidate_count,
        "latency_ms": 900,
        "processed_cohort_count": 1,
        "embedding_calls": 1,
        "discovery_sql": 1,
        "parent_sql": 1,
        "candidate_sql": 0,
        "leakage_count": 0,
        **extra,
    }


def test_collector_joins_observations_by_case_id_and_projects_safe_fields_only():
    dataset = _dataset()
    baseline = [
        _baseline("mba342-syn-case-002", []),
        _baseline("mba342-syn-case-001", ["mba342-syn-kb-001-target"]),
    ]
    parent_first = [
        _parent("mba342-syn-case-002", ["mba342-syn-kb-002-target"]),
        _parent("mba342-syn-case-001", ["mba342-syn-kb-001-target"]),
    ]

    evidence = collect_evidence(dataset, baseline, parent_first)

    assert [case["case_id"] for case in evidence] == [
        "mba342-syn-case-001",
        "mba342-syn-case-002",
    ]
    assert set(evidence[0]) == {
        "case_id",
        "case_tags",
        "metadata_poor",
        "expected_relevant",
        "baseline_ranked",
        "parent_first_ranked",
        "latency_ms",
        "authorized_candidate_count",
        "processed_cohort_count",
        "embedding_calls",
        "discovery_sql",
        "parent_sql",
        "candidate_sql",
        "leakage_count",
    }
    serialized = json.dumps(evidence, ensure_ascii=False)
    assert "synthetic travel policy request" not in serialized
    assert "합성 온보딩 절차 요청" not in serialized
    assert "query" not in serialized


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("raw_query", "must-not-cross"),
        ("content", "must-not-cross"),
        ("kb_id", "550e8400-e29b-41d4-a716-446655440000"),
        ("provider_payload", {"embedding": [0.1, 0.2]}),
    ],
)
def test_collector_rejects_raw_or_identity_bearing_observation_fields(field, value):
    dataset = _dataset()
    baseline = [
        _baseline("mba342-syn-case-001", [], **{field: value}),
        _baseline("mba342-syn-case-002", []),
    ]
    parent_first = [
        _parent("mba342-syn-case-001", ["mba342-syn-kb-001-target"]),
        _parent("mba342-syn-case-002", ["mba342-syn-kb-002-target"]),
    ]

    with pytest.raises(ValueError, match="safe aggregate fields"):
        collect_evidence(dataset, baseline, parent_first)


def test_collector_rejects_ranked_identity_outside_controlled_fixture():
    dataset = _dataset()
    baseline = [
        _baseline(
            "mba342-syn-case-001",
            ["550e8400-e29b-41d4-a716-446655440000"],
        ),
        _baseline("mba342-syn-case-002", []),
    ]
    parent_first = [
        _parent("mba342-syn-case-001", ["mba342-syn-kb-001-target"]),
        _parent("mba342-syn-case-002", ["mba342-syn-kb-002-target"]),
    ]

    with pytest.raises(ValueError, match="controlled candidate labels"):
        collect_evidence(dataset, baseline, parent_first)


def test_collector_rejects_missing_duplicate_or_mismatched_case_observations():
    dataset = _dataset()
    valid_baseline = [
        _baseline("mba342-syn-case-001", []),
        _baseline("mba342-syn-case-002", []),
    ]
    valid_parent = [
        _parent("mba342-syn-case-001", ["mba342-syn-kb-001-target"]),
        _parent("mba342-syn-case-002", ["mba342-syn-kb-002-target"]),
    ]

    with pytest.raises(ValueError, match="same case_id set"):
        collect_evidence(dataset, valid_baseline[:-1], valid_parent)

    with pytest.raises(ValueError, match="unique case_id"):
        collect_evidence(dataset, valid_baseline, [valid_parent[0], valid_parent[0]])

    mismatched_parent = [dict(item) for item in valid_parent]
    mismatched_parent[0]["authorized_candidate_count"] = 1
    with pytest.raises(ValueError, match="candidate snapshot"):
        collect_evidence(dataset, valid_baseline, mismatched_parent)


def test_checked_in_controlled_fixture_produces_passing_evaluator_input():
    dataset = load_controlled_dataset(FIXTURE_PATH)
    cases = dataset["cases"]
    case_ids = [case["case_id"] for case in cases]
    observed_tags = {tag for case in cases for tag in case["case_tags"]}

    assert dataset["data_classification"] == "synthetic_non_secret"
    assert len(cases) >= 30
    assert len(case_ids) == len(set(case_ids))
    assert sum(bool(case["metadata_poor"]) for case in cases) >= 10
    assert REQUIRED_CASE_TAGS <= observed_tags
    assert all(case_id.startswith("mba342-syn-case-") for case_id in case_ids)
    assert all(
        label.startswith("mba342-syn-kb-")
        for case in cases
        for label in case["candidate_labels"]
    )

    baseline = []
    parent_first = []
    for case in cases:
        expected = case["expected_relevant"]
        baseline_ranked = [] if case["metadata_poor"] else expected
        baseline.append(
            _baseline(
                case["case_id"],
                baseline_ranked,
                candidate_count=case["authorized_candidate_count"],
            )
        )
        parent_first.append(
            _parent(
                case["case_id"],
                expected,
                candidate_count=case["authorized_candidate_count"],
            )
        )

    evidence = collect_evidence(dataset, baseline, parent_first)
    report = evaluate_release_gates(evidence)

    assert report["passed"] is True
    assert report["case_count"] == len(cases)
    assert "cases" not in report
    serialized = json.dumps(evidence, ensure_ascii=False)
    assert all(case["query"] not in serialized for case in cases)
