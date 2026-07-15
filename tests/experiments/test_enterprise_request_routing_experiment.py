from __future__ import annotations

from collections import Counter

from scripts.experiment_enterprise_request_routing import (
    CHECKPOINTS,
    EXPECTED_COHORT_COUNTS,
    build_experiment_cases,
    build_run_payload,
    estimate_provider_call_ceiling,
)


def test_build_experiment_cases_is_balanced_unique_and_reproducible():
    cases = build_experiment_cases(shuffle_seed=270)
    repeated = build_experiment_cases(shuffle_seed=270)

    assert len(cases) == 50
    assert [case.case_id for case in cases] == [case.case_id for case in repeated]
    assert len({case.query for case in cases}) == 50
    assert Counter(case.expected_cohort_key for case in cases) == Counter(
        EXPECTED_COHORT_COUNTS
    )


def test_each_refresh_window_contains_every_expected_cohort():
    cases = build_experiment_cases(shuffle_seed=270)

    for start in range(0, len(cases), 10):
        window = cases[start : start + 10]
        counts = Counter(case.expected_cohort_key for case in window)
        assert set(counts) == set(EXPECTED_COHORT_COUNTS)
        assert min(counts.values()) >= 2

    assert CHECKPOINTS == frozenset({10, 20, 30, 40, 50})


def test_run_payload_matches_deployed_webhook_schema():
    case = build_experiment_cases(shuffle_seed=270)[0]

    assert build_run_payload(case) == {
        "inputs": {
            "query": case.query,
            "department": case.department,
            "requesterRole": case.requester_role,
            "locale": case.locale,
        }
    }


def test_provider_call_ceiling_stays_within_live_experiment_budget():
    cases = build_experiment_cases(shuffle_seed=270)

    assert estimate_provider_call_ceiling(cases) == 205
    assert estimate_provider_call_ceiling(cases) <= 500
