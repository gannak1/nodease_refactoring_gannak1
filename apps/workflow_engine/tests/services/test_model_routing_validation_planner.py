"""FR-011-A51~A54: 자동 후보 검증의 예산·완결성 규칙."""

from apps.workflow_engine.services.model_routing_validation_planner import (
    CandidateValidationRequest,
    CohortValidationInput,
    ModelRoutingValidationPlanner,
)


def test_planner_schedules_five_replays_for_each_selected_candidate():
    """한 후보를 일부 입력만 실행한 결과로 활성화하지 않는다."""
    plan = ModelRoutingValidationPlanner.plan(
        cohorts=[
            CohortValidationInput(
                cohort_id="billing",
                observation_ids=("1", "2", "3", "4", "5", "6"),
                candidates=(
                    CandidateValidationRequest("gpt-4.1-mini", estimated_item_cost=0.01),
                ),
            )
        ],
        remaining_budget_usd=0.10,
    )

    assert plan.status == "planned"
    assert len(plan.items) == 5
    assert {item.model_id for item in plan.items} == {"gpt-4.1-mini"}


def test_planner_does_not_partially_validate_a_candidate_when_budget_is_short():
    """예산이 부족하면 후보 한 개의 5회 검증을 잘라서 실행하지 않는다."""
    plan = ModelRoutingValidationPlanner.plan(
        cohorts=[
            CohortValidationInput(
                cohort_id="billing",
                observation_ids=("1", "2", "3", "4", "5"),
                candidates=(
                    CandidateValidationRequest("gpt-4.1-mini", estimated_item_cost=0.03),
                ),
            )
        ],
        remaining_budget_usd=0.10,
    )

    assert plan.status == "budget_insufficient"
    assert plan.items == ()


def test_planner_can_add_two_candidates_when_each_complete_replay_set_fits_budget():
    """상위 두 후보 모두 완결된 증거를 만들 수 있을 때만 함께 예약한다."""
    plan = ModelRoutingValidationPlanner.plan(
        cohorts=[
            CohortValidationInput(
                cohort_id="billing",
                observation_ids=("1", "2", "3", "4", "5"),
                candidates=(
                    CandidateValidationRequest("gpt-4o-mini", estimated_item_cost=0.004),
                    CandidateValidationRequest("gpt-4.1-mini", estimated_item_cost=0.008),
                ),
            )
        ],
        remaining_budget_usd=0.10,
    )

    assert plan.status == "planned"
    assert len(plan.items) == 10
    assert round(plan.reserved_cost_usd, 3) == 0.06


def test_bootstrap_planner_uses_cohort_examples_without_operational_observations():
    """배포 직후에는 운영 로그 대신 입력군 대표 예시로 유료 검증을 계획한다."""
    plan = ModelRoutingValidationPlanner.plan(
        cohorts=[
            CohortValidationInput(
                cohort_id="billing",
                observation_ids=(),
                cohort_example_ids=("example-1", "example-2"),
                required_replays=2,
                candidates=(
                    CandidateValidationRequest("gpt-4.1-mini", estimated_item_cost=0.01),
                ),
            )
        ],
        remaining_budget_usd=0.10,
    )

    assert plan.status == "planned"
    assert [item.cohort_example_id for item in plan.items] == [
        "example-1",
        "example-2",
    ]
    assert all(item.observation_id is None for item in plan.items)
