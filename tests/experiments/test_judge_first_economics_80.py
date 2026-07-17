from scripts.experiment_judge_first_economics_80 import (
    HIGH_MODEL,
    LOW_MODEL,
    ROUTING_JUDGE_MODEL,
    build_cases,
)


def test_economics_dataset_has_80_unique_diverse_cases():
    cases = build_cases()

    assert len(cases) == 80
    assert len({case.message for case in cases}) == 80
    assert {case.expected_difficulty for case in cases} == {
        "economy",
        "balanced",
        "advanced",
    }
    assert len({case.category for case in cases}) >= 8


def test_economics_experiment_uses_distinct_high_low_and_judge_models():
    assert HIGH_MODEL != LOW_MODEL
    assert ROUTING_JUDGE_MODEL not in {"gpt-5.6-sol"}
