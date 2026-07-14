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
    observation_ids: tuple[str, ...]
    candidates: tuple[CandidateValidationRequest, ...]


@dataclass(frozen=True)
class PlannedValidationItem:
    cohort_id: str
    observation_id: str
    model_id: str
    estimated_cost_usd: float


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
            observation_ids = tuple(dict.fromkeys(cohort.observation_ids))[
                : cls.REPLAYS_PER_CANDIDATE
            ]
            if len(observation_ids) < cls.REPLAYS_PER_CANDIDATE:
                continue
            for candidate in cohort.candidates:
                estimated = max(0.0, float(candidate.estimated_item_cost))
                candidate_total = estimated * cls.REPLAYS_PER_CANDIDATE
                # 후보 한 개의 검증은 5개 대표 입력을 모두 처리할 때만 유효하다.
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
                        observation_id=observation_id,
                        model_id=candidate.model_id,
                        estimated_cost_usd=estimated,
                    )
                    for observation_id in observation_ids
                )
                total += candidate_total

        return ValidationPlan(
            status="planned" if items else "no_eligible_candidates",
            items=tuple(items),
            reserved_cost_usd=total,
        )
