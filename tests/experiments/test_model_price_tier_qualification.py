from apps.workflow_engine.services.model_router import ModelCandidate
from scripts.experiment_judge_first_economics_80 import build_cases
from scripts.experiment_model_price_tier_qualification import (
    HIGH_TIER,
    LOW_TIER,
    MID_TIER,
    PRO_TIER,
    build_qualification_cases,
    build_qualification_dry_run,
    partition_price_tiers,
    select_tier_representative,
)


def _candidate(model_id: str, input_price: float, output_price: float) -> ModelCandidate:
    return ModelCandidate(
        model_id=model_id,
        display_name=model_id,
        input_price_1k=input_price,
        output_price_1k=output_price,
    )


def test_price_tiers_use_four_input_tokens_per_output_token_and_separate_pro():
    candidates = [
        _candidate("gpt-5-nano", 0.00005, 0.0004),
        _candidate("gpt-4.1-mini", 0.0004, 0.0016),
        _candidate("gpt-5.4-mini", 0.00075, 0.0045),
        _candidate("gpt-5.4", 0.0025, 0.015),
        _candidate("gpt-5.5", 0.005, 0.03),
        _candidate("gpt-5.4-pro", 0.03, 0.18),
    ]

    tiers = partition_price_tiers(candidates)

    assert [item.model_id for item in tiers[LOW_TIER]] == [
        "gpt-5-nano",
        "gpt-4.1-mini",
    ]
    assert [item.model_id for item in tiers[MID_TIER]] == [
        "gpt-5.4-mini",
        "gpt-5.4",
    ]
    assert [item.model_id for item in tiers[HIGH_TIER]] == ["gpt-5.5"]
    assert [item.model_id for item in tiers[PRO_TIER]] == ["gpt-5.4-pro"]


def test_qualification_dataset_is_separate_and_covers_structure_length_difficulty():
    cases = build_qualification_cases()
    final_messages = {case.message for case in build_cases()}

    assert len(cases) == 16
    assert len({case.case_id for case in cases}) == 16
    assert len({case.message for case in cases}) == 16
    assert not ({case.message for case in cases} & final_messages)
    assert {case.expected_difficulty for case in cases} == {
        "economy",
        "balanced",
        "advanced",
    }
    assert len({case.category for case in cases}) >= 8
    assert {structure: sum(case.input_structure == structure for case in cases) for structure in {case.input_structure for case in cases}} == {
        "flat_text": 4,
        "nested_ticket": 4,
        "conversation": 4,
        "batch_record": 4,
    }
    assert {length: sum(case.input_length_bucket == length for case in cases) for length in {case.input_length_bucket for case in cases}} == {
        "short": 4,
        "medium": 4,
        "long": 4,
        "very_long": 4,
    }


def test_representative_is_cheapest_reliable_model_within_three_quality_points():
    summaries = [
        {
            "model_id": "cheap-near-best",
            "run_count": 16,
            "workflow_success_rate": 1.0,
            "schema_pass_rate": 1.0,
            "quality_pass_rate": 0.95,
            "quality_score_average": 91.0,
            "average_cost_usd": 0.01,
            "average_latency_ms": 900,
        },
        {
            "model_id": "expensive-best",
            "run_count": 16,
            "workflow_success_rate": 1.0,
            "schema_pass_rate": 1.0,
            "quality_pass_rate": 1.0,
            "quality_score_average": 93.0,
            "average_cost_usd": 0.03,
            "average_latency_ms": 800,
        },
        {
            "model_id": "unreliable-high-score",
            "run_count": 16,
            "workflow_success_rate": 0.75,
            "schema_pass_rate": 1.0,
            "quality_pass_rate": 1.0,
            "quality_score_average": 98.0,
            "average_cost_usd": 0.005,
            "average_latency_ms": 700,
        },
    ]

    decision = select_tier_representative(summaries, expected_run_count=16)

    assert decision["selected_model_id"] == "cheap-near-best"
    assert decision["best_quality_score"] == 93.0
    assert decision["quality_margin_points"] == 3.0
    assert decision["eligible_model_ids"] == [
        "cheap-near-best",
        "expensive-best",
    ]


def test_dry_run_counts_all_non_pro_workflows_and_blind_judge_batches():
    tiers = {
        LOW_TIER: [_candidate(f"low-{index}", 0.0001, 0.001) for index in range(5)],
        MID_TIER: [_candidate(f"mid-{index}", 0.001, 0.005) for index in range(10)],
        HIGH_TIER: [_candidate(f"high-{index}", 0.005, 0.03) for index in range(2)],
        PRO_TIER: [_candidate(f"pro-{index}", 0.03, 0.18) for index in range(2)],
    }

    summary = build_qualification_dry_run(tiers, case_count=16)

    assert summary["candidate_model_count"] == 17
    assert summary["workflow_execution_count"] == 272
    assert summary["quality_judge_call_count"] == 64
    assert summary["excluded_pro_model_count"] == 2
