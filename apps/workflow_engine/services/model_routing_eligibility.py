"""Workflow-aware semantic model routing의 적용 가능성을 판정한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from apps.workflow_engine.services.model_routing_evidence import RoutingEvidenceBatch
from apps.workflow_engine.services.model_routing_semantic_router import (
    semantic_catalog_from_policy,
)


@dataclass(frozen=True)
class ModelRoutingEligibility:
    status: str
    reason_code: str
    eligible_model_ids: tuple[str, ...]
    excluded_model_ids: tuple[str, ...]
    evidence_model_ids: tuple[str, ...]


class ModelRoutingEligibilityService:
    """권한, Route catalog, 후보 증거를 순서대로 확인한다."""

    @classmethod
    def evaluate(
        cls,
        *,
        candidate_model_ids: Iterable[str],
        available_model_ids: set[str],
        semantic_catalog: dict[str, Any],
        evidence_batch: RoutingEvidenceBatch,
        current_model_id: str,
    ) -> ModelRoutingEligibility:
        candidates = cls._unique_model_ids(candidate_model_ids)
        available = {str(model_id).strip() for model_id in available_model_ids}
        eligible = tuple(model_id for model_id in candidates if model_id in available)
        excluded = tuple(model_id for model_id in candidates if model_id not in available)

        if len(eligible) < 2:
            return ModelRoutingEligibility(
                status="fixed_model_recommended",
                reason_code="executable_candidates_insufficient",
                eligible_model_ids=eligible,
                excluded_model_ids=excluded,
                evidence_model_ids=(),
            )

        try:
            parsed_catalog = semantic_catalog_from_policy(semantic_catalog)
        except (TypeError, ValueError):
            parsed_catalog = None
        if parsed_catalog is None:
            return ModelRoutingEligibility(
                status="fixed_model_recommended",
                reason_code="semantic_catalog_unavailable",
                eligible_model_ids=eligible,
                excluded_model_ids=excluded,
                evidence_model_ids=(),
            )

        evidence_models = tuple(
            sorted(
                {
                    str(getattr(sample, "model_id", "") or "").strip()
                    for sample in evidence_batch.samples
                    if str(getattr(sample, "model_id", "") or "").strip()
                    in eligible
                    and str(getattr(sample, "model_id", "") or "").strip()
                    != current_model_id
                }
            )
        )
        if not evidence_models:
            return ModelRoutingEligibility(
                status="needs_evidence",
                reason_code="validated_candidate_evidence_unavailable",
                eligible_model_ids=eligible,
                excluded_model_ids=excluded,
                evidence_model_ids=(),
            )

        return ModelRoutingEligibility(
            status="eligible",
            reason_code="semantic_routing_evidence_available",
            eligible_model_ids=eligible,
            excluded_model_ids=excluded,
            evidence_model_ids=evidence_models,
        )

    @staticmethod
    def _unique_model_ids(values: Iterable[str]) -> tuple[str, ...]:
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values:
            model_id = str(value or "").strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            ordered.append(model_id)
        return tuple(ordered)
