"""Cost Optimizer Replay 결과를 모델 라우팅용 검증 증거로 변환한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal

from sqlalchemy.orm import Session

from apps.shared.db.models.cost_optimizer import (
    CostOptimizerCandidate,
    CostOptimizerExperiment,
)


@dataclass(frozen=True)
class RoutingEvidenceSample:
    """라우팅 정책이 모델별 품질과 비용을 비교할 때 사용하는 안전한 표본."""

    source: Literal["replay", "operational"]
    model_id: str
    semantic_cohort_id: str
    baseline_model_id: str | None
    execution_succeeded: bool
    schema_passed: bool | None
    downstream_passed: bool | None
    quality_score: float | None
    baseline_quality_score: float | None
    quality_confidence: float | None
    execution_cost: float | None
    baseline_execution_cost: float | None
    evaluation_cost: float | None
    latency_ms: float | None
    baseline_latency_ms: float | None
    candidate_id: str | None = None
    route_catalog_version: str | None = None


@dataclass(frozen=True)
class RoutingEvidenceBatch:
    """채택된 표본과 제외 이유별 개수를 함께 반환한다."""

    samples: tuple[RoutingEvidenceSample, ...]
    excluded_reason_counts: dict[str, int]


class ReplayEvidenceAdapter:
    """저장된 A/B Replay 후보 중 현재 노드와 비교 가능한 결과만 채택한다."""

    _SUCCESS_STATUSES = frozenset({"success", "completed"})
    _SCHEMA_PASS_STATUSES = frozenset({"pass", "passed", "valid"})
    _DOWNSTREAM_PASS_STATES = frozenset({"compatible", "passed", "pass"})

    @classmethod
    def collect(
        cls,
        db: Session,
        *,
        workflow_id: Any,
        node_id: str,
        organization_id: Any,
        current_node_fingerprint: str,
        limit: int = 200,
    ) -> RoutingEvidenceBatch:
        """현재 workflow/node/organization 범위의 최근 Replay만 읽는다."""
        query = (
            db.query(CostOptimizerCandidate, CostOptimizerExperiment)
            .join(
                CostOptimizerExperiment,
                CostOptimizerExperiment.id == CostOptimizerCandidate.experiment_id,
            )
            .filter(
                CostOptimizerExperiment.workflow_id == workflow_id,
                CostOptimizerExperiment.node_id == node_id,
            )
        )
        if organization_id is not None:
            query = query.filter(
                CostOptimizerExperiment.organization_id == organization_id
            )
        rows = (
            query.order_by(CostOptimizerCandidate.created_at.desc())
            .limit(max(1, min(int(limit), 500)))
            .all()
        )
        return cls.from_rows(
            rows,
            current_node_fingerprint=current_node_fingerprint,
        )

    @classmethod
    def from_rows(
        cls,
        rows: Iterable[tuple[Any, Any]],
        *,
        current_node_fingerprint: str,
    ) -> RoutingEvidenceBatch:
        samples: list[RoutingEvidenceSample] = []
        excluded: dict[str, int] = {}

        for candidate, experiment in rows:
            reason = cls._exclusion_reason(
                candidate,
                current_node_fingerprint=current_node_fingerprint,
            )
            if reason is not None:
                excluded[reason] = excluded.get(reason, 0) + 1
                continue

            trace = cls._mapping(getattr(experiment, "baseline_trace_summary", None))
            routing = cls._mapping(trace.get("model_routing"))
            cohort_id = cls._text(routing.get("matched_cohort_id"))
            if not cohort_id:
                excluded["semantic_cohort_unavailable"] = (
                    excluded.get("semantic_cohort_unavailable", 0) + 1
                )
                continue

            diff = cls._mapping(getattr(candidate, "diff_summary", None))
            quality = cls._mapping(diff.get("quality_evaluation"))
            baseline_quality = cls._mapping(quality.get("baseline"))
            candidate_quality = cls._mapping(quality.get("candidate"))
            routing_evidence = cls._mapping(diff.get("routing_evidence"))
            baseline_options = cls._mapping(
                getattr(experiment, "baseline_node_options", None)
            )
            baseline_usage = cls._mapping(
                getattr(experiment, "baseline_usage_summary", None)
            )
            schema_required = routing_evidence.get("schema_required") is True
            schema_status = cls._text(
                getattr(candidate, "schema_status", None)
            ).lower()
            downstream_state = cls._text(
                getattr(candidate, "downstream_state", None)
            ).lower()
            quality_completed = (
                cls._text(quality.get("status")).lower() == "completed"
            )

            samples.append(
                RoutingEvidenceSample(
                    source="replay",
                    model_id=cls._text(getattr(candidate, "model_id", None)),
                    semantic_cohort_id=cohort_id,
                    baseline_model_id=(
                        cls._text(
                            baseline_usage.get("model")
                            or baseline_options.get("model_id")
                        )
                        or None
                    ),
                    execution_succeeded=(
                        cls._text(getattr(candidate, "status", None)).lower()
                        in cls._SUCCESS_STATUSES
                    ),
                    schema_passed=(
                        True
                        if not schema_required
                        else schema_status in cls._SCHEMA_PASS_STATUSES
                    ),
                    downstream_passed=(
                        True
                        if downstream_state in cls._DOWNSTREAM_PASS_STATES
                        else False
                        if downstream_state
                        else None
                    ),
                    quality_score=(
                        cls._number(candidate_quality.get("score"))
                        if quality_completed
                        else None
                    ),
                    baseline_quality_score=(
                        cls._number(baseline_quality.get("score"))
                        if quality_completed
                        else None
                    ),
                    quality_confidence=(
                        cls._quality_confidence(quality)
                        if quality_completed
                        else None
                    ),
                    execution_cost=cls._number(
                        getattr(candidate, "total_cost", None)
                    ),
                    baseline_execution_cost=cls._number(
                        baseline_usage.get("cost")
                        or baseline_usage.get("total_cost")
                    ),
                    evaluation_cost=cls._number(quality.get("judge_cost")),
                    latency_ms=cls._number(getattr(candidate, "latency_ms", None)),
                    baseline_latency_ms=cls._number(
                        baseline_usage.get("latency_ms")
                    ),
                    candidate_id=cls._text(getattr(candidate, "id", None)) or None,
                    route_catalog_version=(
                        cls._text(routing.get("route_catalog_version")) or None
                    ),
                )
            )

        return RoutingEvidenceBatch(tuple(samples), excluded)

    @classmethod
    def _exclusion_reason(
        cls,
        candidate: Any,
        *,
        current_node_fingerprint: str,
    ) -> str | None:
        settings = cls._mapping(getattr(candidate, "candidate_settings", None))
        baseline_fingerprint = cls._text(
            settings.get("_baseline_node_config_fingerprint")
        )
        if not baseline_fingerprint or baseline_fingerprint != current_node_fingerprint:
            return "node_fingerprint_mismatch"

        if not cls._text(getattr(candidate, "model_id", None)):
            return "model_unavailable"
        return None

    @classmethod
    def _quality_confidence(cls, quality: dict[str, Any]) -> float | None:
        explicit = cls._number(quality.get("confidence_score"))
        if explicit is not None:
            return max(0.0, min(explicit, 1.0))
        return {
            "high": 0.9,
            "medium": 0.7,
            "low": 0.4,
        }.get(cls._text(quality.get("confidence")).lower())

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _number(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
