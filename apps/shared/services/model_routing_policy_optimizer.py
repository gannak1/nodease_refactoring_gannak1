"""검증된 evidence만 사용해 cohort별 모델 정책을 계산한다."""

from __future__ import annotations

import hashlib
import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal


def wilson_lower_bound(successes: int, total: int, *, z: float = 1.96) -> float:
    """작은 표본의 성공률을 과신하지 않도록 Wilson 신뢰구간 하한을 계산한다."""
    if total <= 0:
        return 0.0
    successes = max(0, min(int(successes), int(total)))
    proportion = successes / total
    z_squared = z * z
    denominator = 1 + z_squared / total
    center = proportion + z_squared / (2 * total)
    adjustment = z * math.sqrt(
        (proportion * (1 - proportion) + z_squared / (4 * total)) / total
    )
    return max(0.0, (center - adjustment) / denominator)


@dataclass(frozen=True)
class ModelRoutingGateProfile:
    version: str = "workflow-aware-gate-v1"
    min_samples: int = 5
    min_binary_lower_bound: float = 0.5
    allowed_quality_drop: float = 3.0
    min_quality_confidence: float = 0.7
    quality_z: float = 1.0


@dataclass(frozen=True)
class ModelRoutingOptimizationRequest:
    default_model_id: str
    evidence_samples: Iterable[Any]
    objective: Literal["cost", "latency"] = "cost"
    expected_request_count: int = 100
    embedding_cost_per_request: float = 0.0
    evidence_version: str = "evidence-v1"
    gate_profile: ModelRoutingGateProfile = field(
        default_factory=ModelRoutingGateProfile
    )
    cohort_traffic_shares: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelRoutingCohortDecision:
    cohort_id: str
    selected_model_id: str
    baseline_model_id: str
    reason_code: str
    expected_net_savings: float = 0.0
    candidate_sample_count: int = 0
    candidate_quality_lower_bound: float | None = None
    baseline_quality_lower_bound: float | None = None


@dataclass(frozen=True)
class ModelRoutingOptimizationResult:
    status: Literal["applied", "kept_current", "pending_review"]
    rules: tuple[dict[str, Any], ...]
    cohort_decisions: tuple[ModelRoutingCohortDecision, ...]
    expected_net_savings: float


class ModelRoutingPolicyOptimizer:
    """품질 하한과 실제 부대비용을 통과한 모델만 policy rule로 승격한다."""

    @classmethod
    def optimize(
        cls, request: ModelRoutingOptimizationRequest
    ) -> ModelRoutingOptimizationResult:
        grouped = cls._group_samples(request.evidence_samples)
        traffic_shares = cls._traffic_shares(
            grouped,
            explicit=request.cohort_traffic_shares,
        )
        decisions: list[ModelRoutingCohortDecision] = []
        rules: list[dict[str, Any]] = []

        for cohort_id in sorted(grouped):
            cohort_samples = grouped[cohort_id]
            decision = cls._optimize_cohort(
                cohort_id,
                cohort_samples,
                request=request,
                traffic_share=traffic_shares.get(cohort_id, 0.0),
            )
            decisions.append(decision)
            if decision.selected_model_id == decision.baseline_model_id:
                continue
            rules.append(
                {
                    "id": cls._rule_id(cohort_id),
                    "priority": len(rules) * 10 + 10,
                    "when": {"semantic_cohort_id": cohort_id},
                    "selected_model_id": decision.selected_model_id,
                    "fallback_model_id": decision.baseline_model_id,
                    "reason_code": decision.reason_code,
                    "evidence_version": request.evidence_version,
                    "gate_profile_version": request.gate_profile.version,
                }
            )

        total_savings = sum(item.expected_net_savings for item in decisions)
        return ModelRoutingOptimizationResult(
            status="applied" if rules else "kept_current",
            rules=tuple(rules),
            cohort_decisions=tuple(decisions),
            expected_net_savings=total_savings,
        )

    @classmethod
    def _optimize_cohort(
        cls,
        cohort_id: str,
        samples: list[Any],
        *,
        request: ModelRoutingOptimizationRequest,
        traffic_share: float,
    ) -> ModelRoutingCohortDecision:
        baseline_model_id = cls._baseline_model(samples, request.default_model_id)
        by_candidate: dict[str, list[Any]] = {}
        for sample in samples:
            model_id = str(getattr(sample, "model_id", "") or "").strip()
            if model_id and model_id != baseline_model_id:
                by_candidate.setdefault(model_id, []).append(sample)

        if not by_candidate:
            return cls._keep(
                cohort_id,
                baseline_model_id,
                "candidate_evidence_unavailable",
            )

        passing: list[tuple[float, float, ModelRoutingCohortDecision]] = []
        rejected: list[ModelRoutingCohortDecision] = []
        for model_id, model_samples in sorted(by_candidate.items()):
            evaluated = cls._evaluate_candidate(
                cohort_id,
                model_id,
                baseline_model_id,
                model_samples,
                request=request,
                traffic_share=traffic_share,
            )
            if evaluated.selected_model_id == baseline_model_id:
                rejected.append(evaluated)
                continue
            objective_value = cls._objective_value(
                model_samples,
                request.objective,
            )
            passing.append(
                (objective_value, -evaluated.expected_net_savings, evaluated)
            )

        if not passing:
            dominant_reason = cls._dominant_rejection_reason(
                [item.reason_code for item in rejected]
            )
            matching = [
                item for item in rejected if item.reason_code == dominant_reason
            ]
            if matching:
                return max(
                    matching,
                    key=lambda item: (
                        item.candidate_sample_count,
                        item.selected_model_id,
                    ),
                )
            return cls._keep(
                cohort_id,
                baseline_model_id,
                dominant_reason,
                sample_count=max((len(items) for items in by_candidate.values()), default=0),
            )

        passing.sort(key=lambda item: (item[0], item[1], item[2].selected_model_id))
        return passing[0][2]

    @classmethod
    def _evaluate_candidate(
        cls,
        cohort_id: str,
        model_id: str,
        baseline_model_id: str,
        samples: list[Any],
        *,
        request: ModelRoutingOptimizationRequest,
        traffic_share: float,
    ) -> ModelRoutingCohortDecision:
        gate = request.gate_profile
        count = len(samples)
        if count < gate.min_samples:
            return cls._keep(
                cohort_id,
                baseline_model_id,
                "candidate_samples_insufficient",
                sample_count=count,
            )

        binary_checks = (
            cls._binary_lower_bound(samples, "execution_succeeded"),
            cls._binary_lower_bound(samples, "schema_passed"),
            cls._binary_lower_bound(samples, "downstream_passed"),
        )
        if any(
            value is not None and value < gate.min_binary_lower_bound
            for value in binary_checks
        ):
            return cls._keep(
                cohort_id,
                baseline_model_id,
                "binary_quality_gate_failed",
                sample_count=count,
            )

        quality_scores = cls._numbers(samples, "quality_score")
        baseline_scores = cls._numbers(samples, "baseline_quality_score")
        confidences = cls._numbers(samples, "quality_confidence")
        if len(quality_scores) < gate.min_samples or len(baseline_scores) < gate.min_samples:
            return cls._keep(
                cohort_id,
                baseline_model_id,
                "quality_evidence_insufficient",
                sample_count=count,
            )
        if not confidences or statistics.fmean(confidences) < gate.min_quality_confidence:
            return cls._keep(
                cohort_id,
                baseline_model_id,
                "quality_confidence_insufficient",
                sample_count=count,
            )

        quality_lower = cls._mean_lower_bound(quality_scores, z=gate.quality_z)
        baseline_lower = cls._mean_lower_bound(baseline_scores, z=gate.quality_z)
        if quality_lower < baseline_lower - gate.allowed_quality_drop:
            return cls._keep(
                cohort_id,
                baseline_model_id,
                "quality_floor_failed",
                sample_count=count,
                candidate_quality_lower_bound=quality_lower,
                baseline_quality_lower_bound=baseline_lower,
            )

        candidate_metric = cls._objective_value(samples, request.objective)
        baseline_metric = cls._baseline_objective_value(samples, request.objective)
        if not math.isfinite(candidate_metric) or not math.isfinite(baseline_metric):
            return cls._keep(
                cohort_id,
                baseline_model_id,
                "objective_metric_unavailable",
                sample_count=count,
            )
        if candidate_metric >= baseline_metric:
            return cls._keep(
                cohort_id,
                baseline_model_id,
                "objective_improvement_unavailable",
                sample_count=count,
            )

        net_savings = cls._expected_net_savings(
            samples,
            expected_request_count=request.expected_request_count,
            traffic_share=traffic_share,
            embedding_cost_per_request=request.embedding_cost_per_request,
        )
        if net_savings <= 0:
            return cls._keep(
                cohort_id,
                baseline_model_id,
                "net_savings_not_positive",
                sample_count=count,
                candidate_quality_lower_bound=quality_lower,
                baseline_quality_lower_bound=baseline_lower,
            )

        return ModelRoutingCohortDecision(
            cohort_id=cohort_id,
            selected_model_id=model_id,
            baseline_model_id=baseline_model_id,
            reason_code="validated_quality_floor_cost_reduction",
            expected_net_savings=net_savings,
            candidate_sample_count=count,
            candidate_quality_lower_bound=quality_lower,
            baseline_quality_lower_bound=baseline_lower,
        )

    @staticmethod
    def _group_samples(samples: Iterable[Any]) -> dict[str, list[Any]]:
        grouped: dict[str, list[Any]] = {}
        for sample in samples:
            cohort_id = str(
                getattr(sample, "semantic_cohort_id", "") or ""
            ).strip()
            if cohort_id:
                grouped.setdefault(cohort_id, []).append(sample)
        return grouped

    @staticmethod
    def _traffic_shares(
        grouped: dict[str, list[Any]],
        *,
        explicit: dict[str, float],
    ) -> dict[str, float]:
        if explicit:
            safe = {
                key: max(0.0, float(value))
                for key, value in explicit.items()
                if key in grouped
            }
            total = sum(safe.values())
            if total > 0:
                return {key: value / total for key, value in safe.items()}
        total_samples = sum(len(items) for items in grouped.values())
        if total_samples <= 0:
            return {}
        return {
            key: len(items) / total_samples
            for key, items in grouped.items()
        }

    @staticmethod
    def _baseline_model(samples: list[Any], default_model_id: str) -> str:
        model_ids = [
            str(getattr(sample, "baseline_model_id", "") or "").strip()
            for sample in samples
        ]
        model_ids = [model_id for model_id in model_ids if model_id]
        if model_ids:
            return statistics.mode(model_ids)
        return default_model_id

    @classmethod
    def _expected_net_savings(
        cls,
        samples: list[Any],
        *,
        expected_request_count: int,
        traffic_share: float,
        embedding_cost_per_request: float,
    ) -> float:
        candidate_costs = cls._numbers(samples, "execution_cost")
        baseline_costs = cls._numbers(samples, "baseline_execution_cost")
        if not candidate_costs or not baseline_costs:
            return float("-inf")
        execution_successes = sum(
            1 for sample in samples if getattr(sample, "execution_succeeded", False)
        )
        fallback_rate = 1 - execution_successes / len(samples)
        baseline_cost = statistics.fmean(baseline_costs)
        per_request_candidate_cost = (
            statistics.fmean(candidate_costs)
            + max(0.0, embedding_cost_per_request)
            + fallback_rate * baseline_cost
        )
        request_volume = max(0, expected_request_count) * max(0.0, traffic_share)
        evaluation_overhead = sum(cls._numbers(samples, "evaluation_cost"))
        return (
            baseline_cost - per_request_candidate_cost
        ) * request_volume - evaluation_overhead

    @classmethod
    def _objective_value(cls, samples: list[Any], objective: str) -> float:
        field_name = "latency_ms" if objective == "latency" else "execution_cost"
        values = cls._numbers(samples, field_name)
        return statistics.fmean(values) if values else float("inf")

    @classmethod
    def _baseline_objective_value(
        cls, samples: list[Any], objective: str
    ) -> float:
        field_name = (
            "baseline_latency_ms"
            if objective == "latency"
            else "baseline_execution_cost"
        )
        values = cls._numbers(samples, field_name)
        return statistics.fmean(values) if values else float("inf")

    @classmethod
    def _binary_lower_bound(
        cls, samples: list[Any], field_name: str
    ) -> float | None:
        values = [
            getattr(sample, field_name, None)
            for sample in samples
            if getattr(sample, field_name, None) is not None
        ]
        if not values:
            return None
        successes = sum(value is True for value in values)
        return wilson_lower_bound(successes, len(values))

    @staticmethod
    def _mean_lower_bound(values: list[float], *, z: float) -> float:
        mean = statistics.fmean(values)
        if len(values) <= 1:
            return mean
        deviation = statistics.stdev(values)
        return mean - max(0.0, z) * deviation / math.sqrt(len(values))

    @staticmethod
    def _numbers(samples: Iterable[Any], field_name: str) -> list[float]:
        numbers: list[float] = []
        for sample in samples:
            value = getattr(sample, field_name, None)
            if value is None or isinstance(value, bool):
                continue
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(parsed):
                numbers.append(parsed)
        return numbers

    @staticmethod
    def _dominant_rejection_reason(reasons: list[str]) -> str:
        priority = (
            "candidate_samples_insufficient",
            "binary_quality_gate_failed",
            "quality_evidence_insufficient",
            "quality_confidence_insufficient",
            "quality_floor_failed",
            "objective_metric_unavailable",
            "objective_improvement_unavailable",
            "net_savings_not_positive",
        )
        for reason in priority:
            if reason in reasons:
                return reason
        return reasons[0] if reasons else "candidate_evidence_unavailable"

    @staticmethod
    def _keep(
        cohort_id: str,
        baseline_model_id: str,
        reason_code: str,
        *,
        sample_count: int = 0,
        candidate_quality_lower_bound: float | None = None,
        baseline_quality_lower_bound: float | None = None,
    ) -> ModelRoutingCohortDecision:
        return ModelRoutingCohortDecision(
            cohort_id=cohort_id,
            selected_model_id=baseline_model_id,
            baseline_model_id=baseline_model_id,
            reason_code=reason_code,
            candidate_sample_count=sample_count,
            candidate_quality_lower_bound=candidate_quality_lower_bound,
            baseline_quality_lower_bound=baseline_quality_lower_bound,
        )

    @staticmethod
    def _rule_id(cohort_id: str) -> str:
        suffix = hashlib.sha256(cohort_id.encode("utf-8")).hexdigest()[:10]
        return f"semantic-{suffix}"
