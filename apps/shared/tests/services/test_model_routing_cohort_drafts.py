import pytest

from apps.shared.services.model_routing_cohort_drafts import (
    validate_model_routing_cohort_examples,
)
from apps.shared.services.model_routing_model_filter import (
    filter_model_routing_available_model_ids,
    model_routing_excluded_model_ids,
)


def test_regular_cohort_requires_at_least_three_representative_examples():
    with pytest.raises(
        ValueError,
        match="model_routing.cohort_examples_insufficient",
    ):
        validate_model_routing_cohort_examples(
            ["첫 번째 표현", "두 번째 표현"],
            safety_protected=False,
        )


def test_high_risk_cohort_requires_five_representative_examples():
    with pytest.raises(
        ValueError,
        match="model_routing.cohort_examples_insufficient",
    ):
        validate_model_routing_cohort_examples(
            ["표현 1", "표현 2", "표현 3", "표현 4"],
            safety_protected=True,
        )

    validate_model_routing_cohort_examples(
        ["표현 1", "표현 2", "표현 3", "표현 4", "표현 5"],
        safety_protected=True,
    )


def test_excluded_models_use_one_canonical_form_across_provider_id_formats():
    """Google의 ``models/`` 접두사와 대소문자 차이도 같은 모델로 취급한다."""
    node_data = {
        "model_routing_policy": {
            "excluded_model_ids": [" models/GEMINI-2.5-Flash "]
        }
    }

    assert model_routing_excluded_model_ids(node_data) == {"gemini-2.5-flash"}
    assert filter_model_routing_available_model_ids(
        ["models/gemini-2.5-flash", "gpt-4.1-mini"],
        node_data=node_data,
    ) == ["gpt-4.1-mini"]
