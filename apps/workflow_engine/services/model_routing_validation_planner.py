"""자동 모델 검증 replay 배치를 비용 한도 안에서 계획한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class CandidateValidationRequest:
    model_id: str
    estimated_item_cost: float


@dataclass(frozen=True)
class CohortValidationInput:
    cohort_id: str
    candidates: tuple[CandidateValidationRequest, ...]
    observation_ids: tuple[str, ...] = ()
    cohort_example_ids: tuple[str, ...] = ()
    required_replays: int = 5


@dataclass(frozen=True)
class PlannedValidationItem:
    cohort_id: str
    model_id: str
    estimated_cost_usd: float
    observation_id: str | None = None
    cohort_example_id: str | None = None


@dataclass(frozen=True)
class ValidationPlan:
    status: str
    items: tuple[PlannedValidationItem, ...]
    reserved_cost_usd: float


class ModelRoutingValidationPlanner:
    """후보별 5회 완결 replay와 월간 검증 예산을 함께 강제한다."""

    REPLAYS_PER_CANDIDATE = 5

    @classmethod
    def plan(
        cls,
        *,
        cohorts: Iterable[CohortValidationInput],
        remaining_budget_usd: float,
    ) -> ValidationPlan:
        remaining = max(0.0, float(remaining_budget_usd))
        items: list[PlannedValidationItem] = []
        total = 0.0

        for cohort in cohorts:
            required_replays = max(
                1,
                min(cls.REPLAYS_PER_CANDIDATE, int(cohort.required_replays)),
            )
            observation_ids = tuple(dict.fromkeys(cohort.observation_ids))[
                :required_replays
            ]
            cohort_example_ids = tuple(dict.fromkeys(cohort.cohort_example_ids))[
                :required_replays
            ]
            if observation_ids:
                replay_sources = tuple((item, None) for item in observation_ids)
            else:
                replay_sources = tuple((None, item) for item in cohort_example_ids)
            if len(replay_sources) < required_replays:
                continue
            for candidate in cohort.candidates:
                estimated = max(0.0, float(candidate.estimated_item_cost))
                candidate_total = estimated * required_replays
                # 후보 한 개의 검증은 계획한 대표 입력을 모두 처리할 때만 유효하다.
                if total + candidate_total > remaining + 1e-12:
                    if not items:
                        return ValidationPlan(
                            status="budget_insufficient",
                            items=(),
                            reserved_cost_usd=0.0,
                        )
                    return ValidationPlan(
                        status="planned",
                        items=tuple(items),
                        reserved_cost_usd=total,
                    )
                items.extend(
                    PlannedValidationItem(
                        cohort_id=cohort.cohort_id,
                        model_id=candidate.model_id,
                        estimated_cost_usd=estimated,
                        observation_id=observation_id,
                        cohort_example_id=cohort_example_id,
                    )
                    for observation_id, cohort_example_id in replay_sources
                )
                total += candidate_total

        return ValidationPlan(
            status="planned" if items else "no_eligible_candidates",
            items=tuple(items),
            reserved_cost_usd=total,
        )
