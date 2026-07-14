"""자동 model validation 결과를 안전한 policy evidence로 바꾼다.

이 모듈은 provider, DB, Celery에 의존하지 않는다. 실제 Replay 실행기는 각 실행의
안전한 결과만 ``AdaptiveValidationOutcome``으로 전달하고, 여기서는 품질 gate와
policy projection만 결정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, stdev
from typing import Any, Iterable


@dataclass(frozen=True)
class AdaptiveValidationOutcome:
    execution_succeeded: bool
    schema_passed: bool | None
    downstream_passed: bool | None
    quality_score: float | None
    baseline_quality_score: float | None
    quality_confidence: float | None
    candidate_cost: float | None
    baseline_cost: float | None
    candidate_latency_ms: float | None
    baseline_latency_ms: float | None
    fallback_used: bool


@dataclass(frozen=True)
class AdaptiveEvidenceResult:
    status: str
    reason_code: str
    quality_summary: dict[str, Any]
    efficiency_summary: dict[str, Any]


class AdaptiveValidationResultService:
    """후보를 active policy에 넣기 전에 통과해야 하는 최소 품질 gate."""

    MIN_QUALITY_CONFIDENCE = 0.7
    # Replay는 다섯 개의 실제 운영 입력만 쓰므로 Judge 한 번의 점수 흔들림을
    # 절대 실패로 보면 좋은 후보도 반복해서 버리게 된다. 대신 평균 품질의
    # 보수적 하한과 평균 품질 변화량을 함께 확인한다.
    MIN_QUALITY_SCORE_LOWER_BOUND = 70.0
    MAX_MEAN_QUALITY_DROP = 5.0
    MAX_FALLBACK_RATE = 0.02
    MIN_NET_SAVINGS_RATIO = 0.10
    _T_CRITICAL_95 = {
        2: 12.706,
        3: 4.303,
        4: 3.182,
        5: 2.776,
        6: 2.571,
        7: 2.447,
        8: 2.365,
        9: 2.306,
        10: 2.262,
    }

    @classmethod
    def evaluate(
        cls,
        outcomes: Iterable[AdaptiveValidationOutcome],
        *,
        expected_samples: int,
    ) -> AdaptiveEvidenceResult:
        rows = list(outcomes)
        count = len(rows)
        succeeded = [row for row in rows if row.execution_succeeded]
        schema_checked = [row for row in rows if row.schema_passed is not None]
        downstream_checked = [row for row in rows if row.downstream_passed is not None]
        quality_checked = [
            row
            for row in rows
            if row.quality_score is not None
            and row.baseline_quality_score is not None
            and row.quality_confidence is not None
        ]
        candidate_costs = [row.candidate_cost for row in rows if row.candidate_cost is not None]
        baseline_costs = [row.baseline_cost for row in rows if row.baseline_cost is not None]
        candidate_latency = [
            row.candidate_latency_ms for row in rows if row.candidate_latency_ms is not None
        ]
        baseline_latency = [
            row.baseline_latency_ms for row in rows if row.baseline_latency_ms is not None
        ]
        fallback_rate = cls._ratio(sum(row.fallback_used for row in rows), count)
        quality_deltas = [
            float(row.quality_score) - float(row.baseline_quality_score)
            for row in quality_checked
        ]
        quality_scores = [float(row.quality_score) for row in quality_checked]
        quality_confidences = [float(row.quality_confidence) for row in quality_checked]
        candidate_cost_average = cls._average(candidate_costs)
        baseline_cost_average = cls._average(baseline_costs)
        net_savings = cls._net_savings(candidate_costs, baseline_costs)
        quality_summary = {
            "sample_count": count,
            "success_rate": cls._ratio(len(succeeded), count),
            "schema_pass_rate": cls._ratio(
                sum(row.schema_passed is True for row in schema_checked), len(schema_checked)
            ),
            "downstream_pass_rate": cls._ratio(
                sum(row.downstream_passed is True for row in downstream_checked),
                len(downstream_checked),
            ),
            "quality_delta_average": cls._average(quality_deltas),
            "quality_score_average": cls._average(quality_scores),
            "quality_score_lower_bound": cls._lower_confidence_bound(quality_scores),
            "quality_confidence_average": cls._average(quality_confidences),
            "fallback_rate": fallback_rate,
        }
        efficiency_summary = {
            "candidate_cost_average": candidate_cost_average,
            "baseline_cost_average": baseline_cost_average,
            "net_savings_per_request": net_savings,
            "net_savings_ratio": cls._savings_ratio(
                net_savings=net_savings,
                baseline_cost=baseline_cost_average,
            ),
            "candidate_latency_ms_average": cls._average(candidate_latency),
            "baseline_latency_ms_average": cls._average(baseline_latency),
        }

        if count < expected_samples:
            return cls._result("rejected", "insufficient_replay_samples", quality_summary, efficiency_summary)
        if len(succeeded) != count:
            return cls._result("rejected", "execution_gate_failed", quality_summary, efficiency_summary)
        if schema_checked and any(row.schema_passed is not True for row in schema_checked):
            return cls._result("rejected", "schema_gate_failed", quality_summary, efficiency_summary)
        if downstream_checked and any(row.downstream_passed is not True for row in downstream_checked):
            return cls._result("rejected", "downstream_gate_failed", quality_summary, efficiency_summary)
        if len(quality_checked) != count:
            return cls._result("rejected", "quality_evidence_unavailable", quality_summary, efficiency_summary)
        if any(value < cls.MIN_QUALITY_CONFIDENCE for value in quality_confidences):
            return cls._result("rejected", "quality_confidence_insufficient", quality_summary, efficiency_summary)
        if (
            quality_summary["quality_score_lower_bound"] is None
            or quality_summary["quality_score_lower_bound"] < cls.MIN_QUALITY_SCORE_LOWER_BOUND
        ):
            return cls._result("rejected", "quality_floor_not_met", quality_summary, efficiency_summary)
        if (
            quality_summary["quality_delta_average"] is None
            or quality_summary["quality_delta_average"] < -cls.MAX_MEAN_QUALITY_DROP
        ):
            return cls._result("rejected", "quality_gate_failed", quality_summary, efficiency_summary)
        if fallback_rate is not None and fallback_rate > cls.MAX_FALLBACK_RATE:
            return cls._result("rejected", "fallback_gate_failed", quality_summary, efficiency_summary)
        if (
            efficiency_summary["net_savings_per_request"] is None
            or efficiency_summary["net_savings_ratio"] is None
            or efficiency_summary["net_savings_ratio"] < cls.MIN_NET_SAVINGS_RATIO
        ):
            return cls._result("rejected", "net_savings_insufficient", quality_summary, efficiency_summary)
        return cls._result("validated", "quality_and_efficiency_gate_passed", quality_summary, efficiency_summary)

    @staticmethod
    def project_active_policy(
        *,
        current_policy: dict[str, Any],
        semantic_router: dict[str, Any],
        validated_routes: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        active = dict(current_policy or {})
        # semantic_cohort_id 자체는 정적 안전 route와 적응형 할인 route가 함께
        # 사용한다. 이전 구현처럼 조건 키만 보고 제거하면 고위험 입력을 baseline
        # 으로 고정하던 안전 rule도 다음 검증 결과 적용 때 사라진다. 이 함수가
        # 소유하는 rule만 명시적인 reason_code로 교체한다.
        non_adaptive_rules: list[dict[str, Any]] = []
        adaptive_rules_by_cohort: dict[str, dict[str, Any]] = {}
        for rule in active.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            when = rule.get("when")
            cohort_id = (
                str(when.get("semantic_cohort_id"))
                if isinstance(when, dict) and when.get("semantic_cohort_id")
                else None
            )
            if (
                str(rule.get("reason_code") or "") == "validated_adaptive_cohort"
                and cohort_id is not None
            ):
                # 한 validation batch는 일부 cohort만 재검증한다. 이전 batch에서
                # 통과한 다른 cohort의 route는 그대로 유지하고, 같은 cohort만 새
                # evidence로 교체한다.
                adaptive_rules_by_cohort[cohort_id] = dict(rule)
            else:
                non_adaptive_rules.append(dict(rule))

        for route in validated_routes:
            cohort_id = route.get("cohort_id")
            model_id = route.get("model_id")
            fallback_model_id = route.get("fallback_model_id")
            if not cohort_id or not model_id or not fallback_model_id:
                continue
            adaptive_rules_by_cohort[str(cohort_id)] = {
                "id": f"adaptive-cohort-{cohort_id}",
                "when": {"semantic_cohort_id": str(cohort_id)},
                "selected_model_id": str(model_id),
                "fallback_model_id": str(fallback_model_id),
                "priority": 100,
                "reason_code": "validated_adaptive_cohort",
                "evidence_version": str(route["evidence_version"]),
            }
        active.update(
            {
                "strategy": "workflow_aware_adaptive",
                "rules": [
                    *non_adaptive_rules,
                    *(
                        adaptive_rules_by_cohort[cohort_id]
                        for cohort_id in sorted(adaptive_rules_by_cohort)
                    ),
                ],
                "semantic_router": semantic_router,
            }
        )
        return active

    @staticmethod
    def _result(status: str, reason_code: str, quality_summary: dict[str, Any], efficiency_summary: dict[str, Any]) -> AdaptiveEvidenceResult:
        return AdaptiveEvidenceResult(status, reason_code, quality_summary, efficiency_summary)

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    @staticmethod
    def _average(values: Iterable[float | None]) -> float | None:
        numeric = [float(value) for value in values if value is not None]
        return mean(numeric) if numeric else None

    @classmethod
    def _lower_confidence_bound(cls, values: Iterable[float | None]) -> float | None:
        """작은 Replay 표본에서도 과신하지 않는 95% 평균 품질 하한을 계산한다."""
        numeric = [float(value) for value in values if value is not None]
        if not numeric:
            return None
        if len(numeric) == 1:
            return numeric[0]
        critical = cls._T_CRITICAL_95.get(len(numeric), 1.96)
        return mean(numeric) - critical * stdev(numeric) / sqrt(len(numeric))

    @classmethod
    def _net_savings(cls, candidate_costs: Iterable[float | None], baseline_costs: Iterable[float | None]) -> float | None:
        candidate = cls._average(candidate_costs)
        baseline = cls._average(baseline_costs)
        if candidate is None or baseline is None:
            return None
        return baseline - candidate

    @staticmethod
    def _savings_ratio(*, net_savings: float | None, baseline_cost: float | None) -> float | None:
        if net_savings is None or baseline_cost is None or baseline_cost <= 0:
            return None
        return net_savings / baseline_cost
