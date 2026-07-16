"""Reusable fixed-fixture experiment harness for model routing strategies."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Mapping, Sequence

from apps.workflow_engine.services.model_routing_constraint_difficulty import (
    ConstraintDifficultyFeatureExtractor,
    ConstraintDifficultyRequest,
    ConstraintDifficultyRouter,
    ConstraintModelCandidate,
    ConstraintValidationEvidence,
)
from apps.workflow_engine.services.model_routing_semantic_router import (
    SemanticRouteCatalog,
    SemanticRouteMatcher,
)


@dataclass(frozen=True)
class ConstraintRoutingExperimentCase:
    case_id: str
    workflow_type: str
    request: ConstraintDifficultyRequest

    def request_fingerprint(self, *, rag_context_tokens: int | None = None) -> str:
        request = self.request
        payload = {
            "workflow_type": self.workflow_type,
            "node_data": request.node_data,
            "inputs": request.inputs,
            "available_model_ids": sorted(request.available_model_ids),
            "downstream_requirements": request.downstream_requirements,
            "estimated_input_tokens": request.estimated_input_tokens,
            "actual_rag_context_tokens": (
                request.actual_rag_context_tokens
                if rag_context_tokens is None
                else rag_context_tokens
            ),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ExperimentStrategySelection:
    model_id: str
    reason_code: str


class SemanticCohortExperimentStrategy:
    """Run the production semantic matcher with deterministic fixture vectors."""

    def __init__(
        self,
        *,
        catalog: SemanticRouteCatalog,
        query_vector_provider: Callable[
            [ConstraintRoutingExperimentCase], Sequence[float]
        ],
        model_by_cohort: Mapping[str, str],
        default_model_id: str,
    ) -> None:
        self._catalog = catalog
        self._query_vector_provider = query_vector_provider
        self._model_by_cohort = dict(model_by_cohort)
        self._default_model_id = default_model_id

    def select(
        self, case: ConstraintRoutingExperimentCase
    ) -> ExperimentStrategySelection:
        match = SemanticRouteMatcher.match(
            self._catalog,
            query_vector=self._query_vector_provider(case),
            query_text=_safe_input_text(case.request.inputs),
        )
        if match.status == "matched" and match.cohort_id in self._model_by_cohort:
            return ExperimentStrategySelection(
                model_id=self._model_by_cohort[match.cohort_id],
                reason_code=f"semantic_cohort_matched:{match.cohort_id}",
            )
        return ExperimentStrategySelection(
            model_id=self._default_model_id,
            reason_code=f"semantic_{match.status}_safe_default",
        )


@dataclass(frozen=True)
class ExperimentModelResult:
    success: bool
    schema_passed: bool | None
    downstream_passed: bool | None
    fallback_used: bool
    cost_usd: float
    total_tokens: int
    latency_ms: int
    quality_score: float | None
    critical_quality_failure: bool = False


@dataclass(frozen=True)
class ExperimentRow:
    case_id: str
    workflow_type: str
    strategy_id: str
    selected_model_id: str
    reason_code: str
    schema_required: bool
    downstream_required: bool
    result: ExperimentModelResult

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "workflow_type": self.workflow_type,
            "strategy_id": self.strategy_id,
            "selected_model_id": self.selected_model_id,
            "reason_code": self.reason_code,
            "schema_required": self.schema_required,
            "downstream_required": self.downstream_required,
            "success": self.result.success,
            "schema_passed": self.result.schema_passed,
            "downstream_passed": self.result.downstream_passed,
            "fallback_used": self.result.fallback_used,
            "cost_usd": self.result.cost_usd,
            "total_tokens": self.result.total_tokens,
            "latency_ms": self.result.latency_ms,
            "quality_score": self.result.quality_score,
            "critical_quality_failure": self.result.critical_quality_failure,
        }


@dataclass(frozen=True)
class ExperimentStrategySummary:
    run_count: int
    selected_models: tuple[str, ...]
    success_rate: float
    schema_pass_rate: float | None
    downstream_success_rate: float | None
    fallback_rate: float
    total_cost_usd: float
    total_tokens: int
    avg_latency_ms: float
    p95_latency_ms: int
    avg_quality_score: float | None
    quality_evaluation_rate: float

    def as_dict(self) -> dict:
        return {
            "run_count": self.run_count,
            "selected_models": list(self.selected_models),
            "success_rate": self.success_rate,
            "schema_pass_rate": self.schema_pass_rate,
            "downstream_success_rate": self.downstream_success_rate,
            "fallback_rate": self.fallback_rate,
            "total_cost_usd": self.total_cost_usd,
            "total_tokens": self.total_tokens,
            "avg_latency_ms": self.avg_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "avg_quality_score": self.avg_quality_score,
            "quality_evaluation_rate": self.quality_evaluation_rate,
        }


@dataclass(frozen=True)
class ExperimentAdoptionCriterion:
    passed: bool | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class ExperimentAdoptionAssessment:
    criteria: dict[str, ExperimentAdoptionCriterion]
    replacement_candidate: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "criteria": {
                key: criterion.as_dict() for key, criterion in self.criteria.items()
            },
            "replacement_candidate": self.replacement_candidate,
        }


@dataclass(frozen=True)
class ConstraintRoutingExperimentReport:
    strategy_summaries: dict[str, ExperimentStrategySummary]
    rows: tuple[ExperimentRow, ...]
    provider_result_count: int
    provider_result_estimated_cost_usd: float
    retrieval_result_count: int
    adoption_assessment: ExperimentAdoptionAssessment

    def as_dict(self) -> dict:
        return {
            "strategy_summaries": {
                key: value.as_dict() for key, value in self.strategy_summaries.items()
            },
            "provider_result_count": self.provider_result_count,
            "provider_result_estimated_cost_usd": self.provider_result_estimated_cost_usd,
            "retrieval_result_count": self.retrieval_result_count,
            "adoption_assessment": self.adoption_assessment.as_dict(),
            "rows": [row.as_dict() for row in self.rows],
        }


class ReusableExperimentResultMatrix:
    """Cache one provider result for each workflow input and model pair."""

    def __init__(
        self,
        *,
        result_provider: Callable[
            [ConstraintRoutingExperimentCase, str, int], ExperimentModelResult
        ],
    ) -> None:
        self._result_provider = result_provider
        self._results: dict[tuple[str, str, str, str], ExperimentModelResult] = {}

    @property
    def result_count(self) -> int:
        return len(self._results)

    @property
    def estimated_cost_usd(self) -> float:
        return sum(result.cost_usd for result in self._results.values())

    def get_or_run(
        self,
        *,
        case: ConstraintRoutingExperimentCase,
        model_id: str,
        rag_context_tokens: int,
    ) -> ExperimentModelResult:
        key = (
            case.workflow_type,
            case.case_id,
            case.request_fingerprint(rag_context_tokens=rag_context_tokens),
            model_id,
        )
        if key not in self._results:
            self._results[key] = self._result_provider(
                case, model_id, rag_context_tokens
            )
        return self._results[key]


class ConstraintRoutingExperimentRunner:
    STRATEGIES = (
        "fixed_high",
        "fixed_low",
        "semantic_cohort_v1",
        "constraint_difficulty_v1",
    )

    def __init__(
        self,
        *,
        candidates: Iterable[ConstraintModelCandidate],
        evidence: Iterable[ConstraintValidationEvidence],
        result_matrix: ReusableExperimentResultMatrix,
        retrieval_provider: Callable[[ConstraintRoutingExperimentCase], int],
        high_model_id: str,
        low_model_id: str,
        safe_default_model_id: str,
        semantic_strategy: SemanticCohortExperimentStrategy,
        blind_quality_noninferior: bool | None = None,
    ) -> None:
        self._candidates = tuple(candidates)
        self._evidence = tuple(evidence)
        self._result_matrix = result_matrix
        self._retrieval_provider = retrieval_provider
        self._high_model_id = high_model_id
        self._low_model_id = low_model_id
        self._safe_default_model_id = safe_default_model_id
        self._semantic_strategy = semantic_strategy
        self._blind_quality_noninferior = blind_quality_noninferior
        self._router = ConstraintDifficultyRouter()

    def run(
        self, cases: Sequence[ConstraintRoutingExperimentCase]
    ) -> ConstraintRoutingExperimentReport:
        rows: list[ExperimentRow] = []
        retrieval_cache: dict[tuple[str, str, str], int] = {}
        for original_case in cases:
            rag_enabled = bool(
                original_case.request.node_data.get("knowledgeBases")
                or original_case.request.node_data.get("knowledgeCollections")
            )
            rag_tokens = 0
            case = original_case
            if rag_enabled:
                retrieval_key = (
                    original_case.workflow_type,
                    original_case.case_id,
                    original_case.request_fingerprint(),
                )
                if retrieval_key not in retrieval_cache:
                    retrieval_cache[retrieval_key] = max(
                        int(self._retrieval_provider(original_case)), 0
                    )
                rag_tokens = retrieval_cache[retrieval_key]
                case = replace(
                    original_case,
                    request=replace(
                        original_case.request,
                        actual_rag_context_tokens=rag_tokens,
                    ),
                )

            selections = self._selections(case)
            signature = ConstraintDifficultyFeatureExtractor.extract(
                case.request
            ).signature
            schema_required = signature.schema_complexity != "none"
            downstream_required = signature.downstream_strictness != "none"
            for strategy_id, model_id, reason_code in selections:
                result = self._result_matrix.get_or_run(
                    case=case,
                    model_id=model_id,
                    rag_context_tokens=rag_tokens,
                )
                rows.append(
                    ExperimentRow(
                        case_id=case.case_id,
                        workflow_type=case.workflow_type,
                        strategy_id=strategy_id,
                        selected_model_id=model_id,
                        reason_code=reason_code,
                        schema_required=schema_required,
                        downstream_required=downstream_required,
                        result=result,
                    )
                )

        summaries = {
            strategy_id: self._summarize(
                [row for row in rows if row.strategy_id == strategy_id]
            )
            for strategy_id in self.STRATEGIES
        }
        provider_cost = self._result_matrix.estimated_cost_usd
        return ConstraintRoutingExperimentReport(
            strategy_summaries=summaries,
            rows=tuple(rows),
            provider_result_count=self._result_matrix.result_count,
            provider_result_estimated_cost_usd=provider_cost,
            retrieval_result_count=len(retrieval_cache),
            adoption_assessment=self._assess_adoption(
                rows=rows,
                summaries=summaries,
                verification_cost_usd=provider_cost,
            ),
        )

    def _selections(
        self, case: ConstraintRoutingExperimentCase
    ) -> tuple[tuple[str, str, str], ...]:
        decision = self._router.route(
            request=case.request,
            candidates=self._candidates,
            evidence=self._evidence,
            safe_default_model_id=self._safe_default_model_id,
        )
        semantic_selection = self._semantic_strategy.select(case)
        return (
            ("fixed_high", self._high_model_id, "fixed_high_model"),
            ("fixed_low", self._low_model_id, "fixed_low_model"),
            (
                "semantic_cohort_v1",
                semantic_selection.model_id,
                semantic_selection.reason_code,
            ),
            (
                "constraint_difficulty_v1",
                decision.selected_model_id,
                decision.reason_code,
            ),
        )

    @staticmethod
    def _summarize(rows: Sequence[ExperimentRow]) -> ExperimentStrategySummary:
        if not rows:
            return ExperimentStrategySummary(
                run_count=0,
                selected_models=(),
                success_rate=0.0,
                schema_pass_rate=None,
                downstream_success_rate=None,
                fallback_rate=0.0,
                total_cost_usd=0.0,
                total_tokens=0,
                avg_latency_ms=0.0,
                p95_latency_ms=0,
                avg_quality_score=None,
                quality_evaluation_rate=0.0,
            )
        schema_rows = [row for row in rows if row.schema_required]
        downstream_rows = [row for row in rows if row.downstream_required]
        quality_scores = [
            row.result.quality_score
            for row in rows
            if row.result.quality_score is not None
        ]
        latencies = sorted(row.result.latency_ms for row in rows)
        p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
        return ExperimentStrategySummary(
            run_count=len(rows),
            selected_models=tuple(sorted({row.selected_model_id for row in rows})),
            success_rate=sum(row.result.success for row in rows) / len(rows),
            schema_pass_rate=(
                sum(row.result.schema_passed is True for row in schema_rows)
                / len(schema_rows)
                if schema_rows
                else None
            ),
            downstream_success_rate=(
                sum(row.result.downstream_passed is True for row in downstream_rows)
                / len(downstream_rows)
                if downstream_rows
                else None
            ),
            fallback_rate=sum(row.result.fallback_used for row in rows) / len(rows),
            total_cost_usd=sum(row.result.cost_usd for row in rows),
            total_tokens=sum(row.result.total_tokens for row in rows),
            avg_latency_ms=sum(row.result.latency_ms for row in rows) / len(rows),
            p95_latency_ms=latencies[p95_index],
            avg_quality_score=(
                sum(quality_scores) / len(quality_scores) if quality_scores else None
            ),
            quality_evaluation_rate=len(quality_scores) / len(rows),
        )

    def _assess_adoption(
        self,
        *,
        rows: Sequence[ExperimentRow],
        summaries: Mapping[str, ExperimentStrategySummary],
        verification_cost_usd: float,
    ) -> ExperimentAdoptionAssessment:
        high = summaries["fixed_high"]
        low = summaries["fixed_low"]
        constraint = summaries["constraint_difficulty_v1"]

        schema_not_degraded = _nullable_rate_not_lower(
            constraint.schema_pass_rate, high.schema_pass_rate
        )
        downstream_not_degraded = _nullable_rate_not_lower(
            constraint.downstream_success_rate, high.downstream_success_rate
        )
        constraint_rows = [
            row for row in rows if row.strategy_id == "constraint_difficulty_v1"
        ]
        critical_rows = [
            row
            for row in constraint_rows
            if not row.result.success
            or (row.schema_required and row.result.schema_passed is not True)
            or (row.downstream_required and row.result.downstream_passed is not True)
            or row.result.critical_quality_failure
        ]
        no_critical_failure = not critical_rows
        p95_limit = high.p95_latency_ms * 1.1
        latency_ok = constraint.p95_latency_ms <= p95_limit

        high_average_cost = (
            high.total_cost_usd / high.run_count if high.run_count else 0
        )
        constraint_average_cost = (
            constraint.total_cost_usd / constraint.run_count
            if constraint.run_count
            else 0
        )
        saving_per_run = high_average_cost - constraint_average_cost
        if saving_per_run > 0:
            break_even_runs = math.ceil(verification_cost_usd / saving_per_run)
            break_even_ok = break_even_runs < 1_000
        else:
            break_even_runs = None
            break_even_ok = False

        high_1000_cost = high_average_cost * 1_000
        constraint_1000_cost = constraint_average_cost * 1_000 + verification_cost_usd
        projected_reduction = (
            (high_1000_cost - constraint_1000_cost) / high_1000_cost
            if high_1000_cost > 0
            else 0.0
        )
        projected_cost_ok = projected_reduction >= 0.10

        per_workflow_cost_ok, workflow_cost_detail = _per_workflow_cost_guard(rows)
        low_stability_better = (
            constraint.success_rate > low.success_rate
            and _nullable_rate_not_lower(
                constraint.schema_pass_rate, low.schema_pass_rate
            )
            and _nullable_rate_not_lower(
                constraint.downstream_success_rate, low.downstream_success_rate
            )
            and (
                constraint.avg_quality_score is not None
                and low.avg_quality_score is not None
                and constraint.avg_quality_score > low.avg_quality_score
            )
        )

        criteria = {
            "schema_downstream_not_degraded": ExperimentAdoptionCriterion(
                passed=schema_not_degraded and downstream_not_degraded,
                detail=(
                    f"schema={constraint.schema_pass_rate}/{high.schema_pass_rate}, "
                    f"downstream={constraint.downstream_success_rate}/"
                    f"{high.downstream_success_rate}"
                ),
            ),
            "blind_quality_non_inferior": ExperimentAdoptionCriterion(
                passed=self._blind_quality_noninferior,
                detail=(
                    "실제 Provider 출력의 blind 평가가 필요합니다."
                    if self._blind_quality_noninferior is None
                    else "외부 blind 평가 결과를 사용했습니다."
                ),
            ),
            "no_critical_single_failure": ExperimentAdoptionCriterion(
                passed=no_critical_failure,
                detail=f"critical_rows={len(critical_rows)}",
            ),
            "fallback_not_increased": ExperimentAdoptionCriterion(
                passed=constraint.fallback_rate <= high.fallback_rate,
                detail=f"constraint={constraint.fallback_rate}, high={high.fallback_rate}",
            ),
            "p95_latency_within_10_percent": ExperimentAdoptionCriterion(
                passed=latency_ok,
                detail=f"constraint={constraint.p95_latency_ms}ms, limit={p95_limit:.1f}ms",
            ),
            "break_even_before_1000_runs": ExperimentAdoptionCriterion(
                passed=break_even_ok,
                detail=(
                    f"break_even_runs={break_even_runs}, "
                    f"verification_cost=${verification_cost_usd:.6f}"
                ),
            ),
            "projected_1000_run_cost_reduction_at_least_10_percent": ExperimentAdoptionCriterion(
                passed=projected_cost_ok,
                detail=f"projected_reduction={projected_reduction:.2%}",
            ),
            "no_workflow_cost_worse_than_5_percent": ExperimentAdoptionCriterion(
                passed=per_workflow_cost_ok,
                detail=workflow_cost_detail,
            ),
            "selects_at_least_two_models": ExperimentAdoptionCriterion(
                passed=len(constraint.selected_models) >= 2,
                detail=f"models={list(constraint.selected_models)}",
            ),
            "more_stable_than_fixed_low": ExperimentAdoptionCriterion(
                passed=low_stability_better,
                detail=(
                    f"success={constraint.success_rate}/{low.success_rate}, "
                    f"quality={constraint.avg_quality_score}/{low.avg_quality_score}"
                ),
            ),
        }
        replacement_candidate = all(
            criterion.passed is True for criterion in criteria.values()
        )
        return ExperimentAdoptionAssessment(
            criteria=criteria,
            replacement_candidate=replacement_candidate,
        )


def _safe_input_text(inputs: Mapping[str, Any]) -> str:
    return json.dumps(
        inputs,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _nullable_rate_not_lower(candidate: float | None, baseline: float | None) -> bool:
    if baseline is None:
        return candidate is None or candidate >= 0
    return candidate is not None and candidate >= baseline


def _per_workflow_cost_guard(
    rows: Sequence[ExperimentRow],
) -> tuple[bool, str]:
    workflow_types = sorted({row.workflow_type for row in rows})
    ratios: list[str] = []
    passed = True
    for workflow_type in workflow_types:
        high_rows = [
            row
            for row in rows
            if row.workflow_type == workflow_type and row.strategy_id == "fixed_high"
        ]
        constraint_rows = [
            row
            for row in rows
            if row.workflow_type == workflow_type
            and row.strategy_id == "constraint_difficulty_v1"
        ]
        high_cost = sum(row.result.cost_usd for row in high_rows)
        constraint_cost = sum(row.result.cost_usd for row in constraint_rows)
        ratio = constraint_cost / high_cost if high_cost > 0 else float("inf")
        passed = passed and ratio <= 1.05
        ratios.append(f"{workflow_type}={ratio:.3f}x")
    return passed, ", ".join(ratios)
