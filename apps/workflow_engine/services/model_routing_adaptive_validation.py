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
    # 작은 Replay 표본에서 평균만 좋다고 입력군 전체에 후보 모델을 적용하면,
    # 대표 입력 하나의 큰 품질 하락이 실제 운영 요청에서도 반복될 수 있다.
    # 절대 품질·보수적 하한·기준 모델 대비 변화를 함께 보고, 단일 10점 초과
    # 하락은 평균으로 상쇄하지 않는다.
    MIN_QUALITY_SCORE_AVERAGE = 85.0
    MIN_QUALITY_SCORE_LOWER_BOUND = 76.5
    # RAG 답변은 정답지 없이 기준 모델과 후보 모델을 같은 Judge가 상대 비교한다.
    # 이 경우 기준 모델 자체도 낮은 절대 점수를 받을 수 있으므로, 비고위험 입력군은
    # "기준보다 크게 나빠지지 않는가"를 우선 본다. 다만 빈 답변이나 무관한 응답을
    # 막기 위한 최소 절대 점수는 유지한다.
    MIN_RELATIVE_SINGLE_QUALITY_SCORE = 30.0
    MAX_MEAN_QUALITY_DROP = 5.0
    MAX_SINGLE_QUALITY_DROP = 10.0
    MAX_EXTREME_SINGLE_QUALITY_DROP = 25.0
    MIN_SINGLE_QUALITY_SCORE = 70.0
    # 평균과 신뢰 하한만으로 단일 저품질 응답을 숨기지는 않는다. 다만
    # 비고위험 후보는 기준 모델보다 안정적으로 나은 80점대 응답까지
    # 허용하고, 고위험 입력군은 기존 85점 하한을 유지한다.
    MIN_PROMOTABLE_SINGLE_QUALITY_SCORE = 80.0
    HIGH_RISK_MIN_PROMOTABLE_SINGLE_QUALITY_SCORE = 85.0
    MAX_QUALITY_OUTLIER_RATE = 0.0
    MAX_FALLBACK_RATE = 0.02
    MIN_NET_SAVINGS_RATIO = 0.10
    HIGH_RISK_MIN_SAMPLES = 5
    HIGH_RISK_MIN_QUALITY_CONFIDENCE = 0.85
    HIGH_RISK_MIN_QUALITY_SCORE_LOWER_BOUND = 85.0
    HIGH_RISK_MAX_MEAN_QUALITY_DROP = 0.0
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
        safety_protected: bool = False,
        validation_stage: str = "production",
    ) -> AdaptiveEvidenceResult:
        rows = list(outcomes)
        count = len(rows)
        relative_bootstrap = (
            validation_stage == "bootstrap" and not safety_protected
        )
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
        quality_outlier_count = sum(
            delta < -cls.MAX_SINGLE_QUALITY_DROP for delta in quality_deltas
        )
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
            "quality_delta_minimum": min(quality_deltas) if quality_deltas else None,
            "quality_score_average": cls._average(quality_scores),
            "quality_score_minimum": min(quality_scores) if quality_scores else None,
            "quality_score_lower_bound": cls._lower_confidence_bound(quality_scores),
            "quality_confidence_average": cls._average(quality_confidences),
            "quality_outlier_count": quality_outlier_count,
            "quality_outlier_rate": cls._ratio(quality_outlier_count, len(quality_deltas)),
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

        if safety_protected and count < cls.HIGH_RISK_MIN_SAMPLES:
            return cls._result(
                "rejected",
                "high_risk_samples_insufficient",
                quality_summary,
                efficiency_summary,
            )
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
        minimum_confidence = (
            cls.HIGH_RISK_MIN_QUALITY_CONFIDENCE
            if safety_protected
            else cls.MIN_QUALITY_CONFIDENCE
        )
        if any(value < minimum_confidence for value in quality_confidences):
            return cls._result("rejected", "quality_confidence_insufficient", quality_summary, efficiency_summary)
        minimum_delta = quality_summary["quality_delta_minimum"]
        minimum_score = quality_summary["quality_score_minimum"]
        outlier_rate = quality_summary["quality_outlier_rate"]
        if (
            minimum_delta is None
            or minimum_score is None
            or outlier_rate is None
            or minimum_delta < -cls.MAX_EXTREME_SINGLE_QUALITY_DROP
            or (
                not relative_bootstrap
                and minimum_score < cls.MIN_SINGLE_QUALITY_SCORE
            )
            or outlier_rate
            > (0.0 if safety_protected else cls.MAX_QUALITY_OUTLIER_RATE)
        ):
            return cls._result(
                "rejected",
                "quality_outlier_gate_failed",
                quality_summary,
                efficiency_summary,
            )
        if relative_bootstrap:
            # 정답지가 없는 RAG 비교는 기준 모델도 낮은 절대 점수를 받을 수 있다.
            # Bootstrap에서는 후보가 기준보다 크게 나빠지지 않고 빈 답변 수준이
            # 아닌지 확인해 첫 정책을 만든다. 운영 재검증은 아래 절대 gate를 쓴다.
            if minimum_score < cls.MIN_RELATIVE_SINGLE_QUALITY_SCORE:
                return cls._result(
                    "rejected",
                    "quality_relative_safety_gate_failed",
                    quality_summary,
                    efficiency_summary,
                )
        else:
            minimum_quality_floor = (
                cls.HIGH_RISK_MIN_QUALITY_SCORE_LOWER_BOUND
                if safety_protected
                else cls.MIN_QUALITY_SCORE_LOWER_BOUND
            )
            if (
                quality_summary["quality_score_lower_bound"] is None
                or quality_summary["quality_score_lower_bound"]
                < minimum_quality_floor
            ):
                return cls._result(
                    "rejected",
                    (
                        "high_risk_quality_floor_not_met"
                        if safety_protected
                        else "quality_floor_not_met"
                    ),
                    quality_summary,
                    efficiency_summary,
                )
            if (
                not safety_protected
                and (
                    quality_summary["quality_score_average"] is None
                    or quality_summary["quality_score_average"]
                    < cls.MIN_QUALITY_SCORE_AVERAGE
                )
            ):
                return cls._result(
                    "rejected",
                    "quality_average_not_met",
                    quality_summary,
                    efficiency_summary,
                )
            promotable_single_score = (
                cls.HIGH_RISK_MIN_PROMOTABLE_SINGLE_QUALITY_SCORE
                if safety_protected
                else cls.MIN_PROMOTABLE_SINGLE_QUALITY_SCORE
            )
            if minimum_score < promotable_single_score:
                return cls._result(
                    "rejected",
                    "quality_single_score_not_met",
                    quality_summary,
                    efficiency_summary,
                )
        maximum_quality_drop = (
            cls.HIGH_RISK_MAX_MEAN_QUALITY_DROP
            if safety_protected
            else cls.MAX_MEAN_QUALITY_DROP
        )
        if (
            quality_summary["quality_delta_average"] is None
            or quality_summary["quality_delta_average"] < -maximum_quality_drop
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
        revoked_cohort_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        active = dict(current_policy or {})
        revoked_cohorts = {str(cohort_id) for cohort_id in revoked_cohort_ids}
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
                if cohort_id not in revoked_cohorts:
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
