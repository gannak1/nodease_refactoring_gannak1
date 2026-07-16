"""적응형 입력군을 runtime policy와 검증 후보 계획으로 변환한다.

이 모듈은 DB, Celery, provider에 의존하지 않는다. 따라서 정책에 포함될 수 있는
입력군과 실제 비용을 쓰기 전 검증할 후보 범위를 한 곳에서 테스트할 수 있다.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from apps.shared.services.model_routing_lexical import (
    tokenize_model_routing_lexical_text,
)


@dataclass(frozen=True)
class AdaptiveCohortRoute:
    cohort_id: str
    label: str
    status: str
    validated: bool
    centroid_embedding: Sequence[float]
    representative_embeddings: Sequence[Sequence[float]] = ()
    representative_texts: Sequence[str] = ()
    safety_override: bool = False
    threshold: float = 0.72
    calibration: dict | None = None


@dataclass(frozen=True)
class SemanticThresholdCalibration:
    """합성 대표 예시로 계산한 입력군별 semantic match 경계."""

    threshold: float
    status: str
    positive_sample_count: int
    negative_sample_count: int
    positive_floor: float | None = None
    negative_ceiling: float | None = None

    def as_policy_metadata(self) -> dict:
        return {
            "status": self.status,
            "positive_sample_count": self.positive_sample_count,
            "negative_sample_count": self.negative_sample_count,
            "positive_floor": self.positive_floor,
            "negative_ceiling": self.negative_ceiling,
        }


@dataclass(frozen=True)
class AdaptiveCandidate:
    model_id: str
    estimated_cost: float
    validated: bool


class AdaptiveModelRoutingPolicyService:
    """자동 발견/검증 결과에 대한 순수 policy projection 규칙."""

    # 입력군 매칭 준비와 저가 모델 승격은 서로 다른 검증이다. 사용자가 대표
    # 예시를 직접 제공한 필수 입력군은 후보 모델이 탈락해도 기본 모델로 분류할
    # 수 있어야 하므로, caller가 validated=True로 표시한 대기 상태도 허용한다.
    RUNTIME_STATUSES = frozenset(
        {"active", "proposed", "validating", "validated_waiting"}
    )
    CANDIDATE_COST_TIER_MULTIPLIER = 2.0
    MIN_CALIBRATION_EXAMPLES = 3
    MIN_CALIBRATED_THRESHOLD = 0.35
    MAX_CALIBRATED_THRESHOLD = 0.90
    CALIBRATION_SEPARATION_MARGIN = 0.05
    RUNTIME_AGGREGATIONS = frozenset({"centroid", "max", "top_k_mean"})
    MAX_LEXICAL_SIGNALS_PER_ROUTE = 8
    MIN_REPEATED_LEXICAL_TERM_EXAMPLES = 2

    @classmethod
    def build_runtime_catalog(
        cls,
        *,
        encoder_model_id: str,
        input_paths: Iterable[str],
        routes: Iterable[AdaptiveCohortRoute],
        lexical_representative_texts: Mapping[str, Sequence[str]] | None = None,
        preserved_safety_routes: Iterable[dict] = (),
        aggregation: str = "top_k_mean",
        top_k: int = 2,
        min_margin: float = 0.05,
    ) -> dict:
        """검증 완료 cohort와 policy-owned 안전 route를 runtime 형식으로 투영한다."""
        normalized_paths = cls._input_paths(input_paths)
        runtime_min_margin = max(0.0, min(float(min_margin), 1.0))
        runtime_routes = [route for route in routes if cls._is_runtime_route(route)]
        lexical_signals_by_cohort = cls._derive_lexical_signals(
            runtime_routes,
            representative_texts_by_cohort=lexical_representative_texts,
        )
        projected_routes: list[dict] = []
        for route in runtime_routes:
            representative_vectors = cls._representative_vectors(route)
            projected_route = {
                    "cohort_id": route.cohort_id,
                    "label": route.label,
                    "threshold": max(0.0, min(float(route.threshold), 1.0)),
                    "calibration": dict(route.calibration or {}),
                    "safety_override": bool(route.safety_override),
                    "lexical_signals": lexical_signals_by_cohort.get(
                        route.cohort_id,
                        [],
                    ),
                    "lexical_override_threshold": 1.0,
                    "centroid_embedding": [
                        float(value) for value in route.centroid_embedding
                    ],
                    # 운영 입력 원문은 저장하지 않는다. 검증된 입력군에서 뽑은
                    # 비가역 벡터만 여러 개 보존해 표현이 달라도 가까운 예시를 찾는다.
                    "representatives": [
                        {
                            "utterance_hash": hashlib.sha256(
                                f"adaptive:{route.cohort_id}:{index}".encode("utf-8")
                            ).hexdigest(),
                            "embedding": vector,
                        }
                        for index, vector in enumerate(representative_vectors)
                    ],
                }
            dense_override_threshold = cls._dense_safety_override_threshold(
                route,
                min_margin=runtime_min_margin,
            )
            if dense_override_threshold is not None:
                projected_route["dense_override_threshold"] = dense_override_threshold
            projected_routes.append(projected_route)
        # 안전 route는 사용자가/정책이 이미 정의한 rule이다. 검증 전 자동 cohort가
        # 고위험 입력을 싼 모델 route로 오분류하지 않도록 catalog에 계속 남긴다.
        projected_ids = {str(route["cohort_id"]) for route in projected_routes}
        for route in preserved_safety_routes:
            if not isinstance(route, dict) or not route.get("safety_override"):
                continue
            cohort_id = str(route.get("cohort_id") or "").strip()
            if not cohort_id or cohort_id in projected_ids:
                continue
            representatives = route.get("representatives")
            centroid = route.get("centroid_embedding")
            if not isinstance(representatives, list) or not representatives:
                continue
            projected_routes.append(
                {
                    "cohort_id": cohort_id,
                    "label": str(route.get("label") or cohort_id),
                    "threshold": max(0.0, min(float(route.get("threshold", 0.72)), 1.0)),
                    "safety_override": True,
                    "lexical_signals": route.get("lexical_signals") or [],
                    "lexical_override_threshold": float(
                        route.get("lexical_override_threshold", 1.0)
                    ),
                    **(
                        {
                            "dense_override_threshold": float(
                                route["dense_override_threshold"]
                            )
                        }
                        if route.get("dense_override_threshold") is not None
                        else {}
                    ),
                    "centroid_embedding": centroid,
                    "representatives": representatives,
                }
            )
        runtime_aggregation = cls._runtime_aggregation(aggregation)
        runtime_top_k = max(1, min(int(top_k), 8))
        return {
            "route_catalog_version": "adaptive-cohorts-v1",
            "encoder_model_id": str(encoder_model_id or "").strip(),
            "input_paths": normalized_paths,
            "top_k": runtime_top_k,
            "aggregation": runtime_aggregation,
            "min_margin": runtime_min_margin,
            "routes": projected_routes,
        }

    @classmethod
    def _derive_lexical_signals(
        cls,
        routes: Sequence[AdaptiveCohortRoute],
        *,
        representative_texts_by_cohort: Mapping[str, Sequence[str]] | None = None,
    ) -> dict[str, list[dict[str, float | str]]]:
        """Derive bounded, cohort-unique hints from synthetic representative text.

        Runtime never learns domain words from a source constant or from raw
        operating requests. These signals only come from the user-authored or
        wizard-generated representative examples already stored for a cohort.
        """
        # Runtime rule은 검증된 입력군만 포함하지만, 아직 검증 중인 입력군의
        # 대표 예문도 단어의 소유권을 판단할 때는 필요하다. 예를 들어 플랫폼
        # 초안에도 "권한"이 있다면, 플랫폼 후보가 아직 탈락/대기 상태여도 이
        # 단어를 영업 rule의 고유 신호로 쓰면 안 된다.
        all_representative_texts: dict[str, tuple[str, ...]] = {
            route.cohort_id: tuple(route.representative_texts)
            for route in routes
        }
        if representative_texts_by_cohort is not None:
            for cohort_id, texts in representative_texts_by_cohort.items():
                normalized_cohort_id = str(cohort_id or "").strip()
                if not normalized_cohort_id:
                    continue
                all_representative_texts[normalized_cohort_id] = tuple(
                    str(text or "").strip() for text in texts if str(text or "").strip()
                )

        terms_by_cohort: dict[str, dict[str, int]] = {}
        cohorts_by_term: dict[str, set[str]] = {}
        for cohort_id, representative_texts in all_representative_texts.items():
            term_counts: dict[str, int] = {}
            for text in representative_texts:
                terms = set(cls._lexical_tokens(text))
                for term in terms:
                    term_counts[term] = term_counts.get(term, 0) + 1
            terms_by_cohort[cohort_id] = term_counts
            for term in term_counts:
                cohorts_by_term.setdefault(term, set()).add(cohort_id)

        signals_by_cohort: dict[str, list[dict[str, float | str]]] = {}
        for route in routes:
            term_counts = terms_by_cohort.get(route.cohort_id, {})
            ranked: list[tuple[float, str]] = []
            for term, occurrence_count in term_counts.items():
                if len(cohorts_by_term.get(term, set())) != 1:
                    continue
                is_short_ascii_identifier = term.isascii() and 2 <= len(term) <= 12
                if (
                    occurrence_count < cls.MIN_REPEATED_LEXICAL_TERM_EXAMPLES
                    and not is_short_ascii_identifier
                ):
                    continue
                weight = 1.5 if occurrence_count >= 2 else 1.0
                ranked.append((weight, term))
            signals_by_cohort[route.cohort_id] = [
                {"term": term, "weight": weight}
                for weight, term in sorted(
                    ranked,
                    key=lambda item: (-item[0], -len(item[1]), item[1]),
                )[: cls.MAX_LEXICAL_SIGNALS_PER_ROUTE]
            ]
        return signals_by_cohort

    @staticmethod
    def _lexical_tokens(value: str) -> list[str]:
        return tokenize_model_routing_lexical_text(value)

    @staticmethod
    def _dense_safety_override_threshold(
        route: AdaptiveCohortRoute,
        *,
        min_margin: float,
    ) -> float | None:
        """안전 입력의 학습 하한을 놓치지 않는 범위에서 오탐 경계를 계산한다."""
        if not route.safety_override or not isinstance(route.calibration, dict):
            return None
        try:
            negative_ceiling = float(route.calibration.get("negative_ceiling"))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(negative_ceiling):
            return None
        # 양성 하한까지 낮추면 일반 입력이 과도하게 안전군으로 흡수된다. 반대로
        # 학습된 음성 최고점을 그대로 쓰면 실제 운영 표현의 작은 embedding
        # drift도 놓칠 수 있다. 음성 상한 아래 0.03만 보호 여유로 두되 route
        # 자체 threshold보다 낮아지지 않게 한다.
        threshold = max(
            float(route.threshold),
            negative_ceiling - AdaptiveModelRoutingPolicyService.SAFETY_NEGATIVE_DRIFT_TOLERANCE,
        )
        return round(max(0.0, min(threshold, 1.0)), 6)

    @classmethod
    def calibrate_similarity_threshold(
        cls,
        *,
        positive_embeddings: Sequence[Sequence[float]],
        negative_embeddings: Sequence[Sequence[float]],
        default_threshold: float,
        aggregation: str = "top_k_mean",
        top_k: int = 2,
    ) -> SemanticThresholdCalibration:
        """입력군 내부 응집도와 다른 입력군과의 분리도로 route 기준을 정한다.

        각 양성 예시는 자기 자신을 제외한 같은 입력군 예시와 비교한다. 따라서
        동일 vector끼리의 1.0 점수로 기준이 과도하게 높아지는 일을 막는다.
        """
        positives = cls._normalized_vectors(positive_embeddings)
        negatives = cls._normalized_vectors(negative_embeddings)
        runtime_aggregation = cls._runtime_aggregation(aggregation)
        runtime_top_k = max(1, min(int(top_k), 8))
        safe_default = cls._bounded_threshold(default_threshold)
        if len(positives) < cls.MIN_CALIBRATION_EXAMPLES:
            return SemanticThresholdCalibration(
                threshold=safe_default,
                status="insufficient_positive_examples",
                positive_sample_count=len(positives),
                negative_sample_count=len(negatives),
            )

        positive_scores = [
            cls._top_k_mean_similarity(
                query,
                [candidate for candidate_index, candidate in enumerate(positives) if candidate_index != index],
                aggregation=runtime_aggregation,
                top_k=runtime_top_k,
            )
            for index, query in enumerate(positives)
        ]
        positive_floor = min(positive_scores)
        negative_scores = [
            cls._top_k_mean_similarity(
                query,
                positives,
                aggregation=runtime_aggregation,
                top_k=runtime_top_k,
            )
            for query in negatives
        ]
        negative_ceiling = max(negative_scores) if negative_scores else None

        if negative_ceiling is not None:
            if positive_floor - negative_ceiling < cls.CALIBRATION_SEPARATION_MARGIN:
                # 하나의 threshold로 양성과 음성을 완전히 나눌 수 없는 구간이다.
                # 겹친 구간의 낮은 쪽을 모두 열면 다른 입력군을 저가 모델 rule로
                # 보내게 된다. 양성 하한과 음성 상한의 중간값을 사용해 일부
                # recall을 포기하고 runtime 오분류를 줄인다.
                threshold = (positive_floor + negative_ceiling) / 2
                return SemanticThresholdCalibration(
                    threshold=round(cls._bounded_threshold(threshold), 6),
                    status="conservative_overlap",
                    positive_sample_count=len(positives),
                    negative_sample_count=len(negatives),
                    positive_floor=round(positive_floor, 6),
                    negative_ceiling=round(negative_ceiling, 6),
                )
            threshold = (positive_floor + negative_ceiling) / 2
        else:
            # 입력군이 하나뿐이면 오분류 표본이 없으므로 내부 표현 범위보다 조금
            # 낮게만 열고, 제품 전체 하한보다 낮아지지 않게 제한한다.
            threshold = positive_floor - cls.CALIBRATION_SEPARATION_MARGIN

        return SemanticThresholdCalibration(
            threshold=round(cls._bounded_threshold(threshold), 6),
            status="calibrated",
            positive_sample_count=len(positives),
            negative_sample_count=len(negatives),
            positive_floor=round(positive_floor, 6),
            negative_ceiling=(
                round(negative_ceiling, 6) if negative_ceiling is not None else None
            ),
        )

    @classmethod
    def _bounded_threshold(cls, value: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = cls.MIN_CALIBRATED_THRESHOLD
        if not math.isfinite(numeric):
            numeric = cls.MIN_CALIBRATED_THRESHOLD
        return max(
            cls.MIN_CALIBRATED_THRESHOLD,
            min(numeric, cls.MAX_CALIBRATED_THRESHOLD),
        )

    @staticmethod
    def _normalized_vectors(
        vectors: Sequence[Sequence[float]],
    ) -> list[tuple[float, ...]]:
        normalized: list[tuple[float, ...]] = []
        dimensions: int | None = None
        for raw in vectors:
            try:
                vector = tuple(float(value) for value in raw)
            except (TypeError, ValueError):
                continue
            if (
                not vector
                or not all(math.isfinite(value) for value in vector)
                or not any(value != 0 for value in vector)
            ):
                continue
            if dimensions is None:
                dimensions = len(vector)
            if len(vector) != dimensions or vector in normalized:
                continue
            normalized.append(vector)
        return normalized

    @classmethod
    def _top_k_mean_similarity(
        cls,
        query: Sequence[float],
        representatives: Sequence[Sequence[float]],
        *,
        aggregation: str = "top_k_mean",
        top_k: int = 2,
    ) -> float:
        if not representatives:
            return 0.0
        if aggregation == "centroid":
            dimensions = len(representatives[0])
            centroid = [
                sum(float(vector[index]) for vector in representatives)
                / len(representatives)
                for index in range(dimensions)
            ]
            return cls._cosine(query, centroid)
        scores = sorted(
            (cls._cosine(query, representative) for representative in representatives),
            reverse=True,
        )
        if aggregation == "max":
            return scores[0]
        selected = scores[: max(1, min(int(top_k), len(scores)))]
        return sum(selected) / len(selected)

    @classmethod
    def _runtime_aggregation(cls, value: str) -> str:
        normalized = str(value or "").strip()
        return normalized if normalized in cls.RUNTIME_AGGREGATIONS else "top_k_mean"

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        return max(-1.0, min(1.0, numerator / (left_norm * right_norm)))

    @staticmethod
    def _representative_vectors(route: AdaptiveCohortRoute) -> list[list[float]]:
        vectors: list[list[float]] = []
        seen: set[tuple[float, ...]] = set()
        source = route.representative_embeddings or (route.centroid_embedding,)
        for raw_vector in source:
            vector = tuple(float(value) for value in raw_vector)
            if not vector or vector in seen:
                continue
            seen.add(vector)
            vectors.append(list(vector))
        if not vectors:
            vectors.append([float(value) for value in route.centroid_embedding])
        return vectors

    @classmethod
    def plan_candidates(
        cls,
        *,
        candidates: Iterable[AdaptiveCandidate],
        available_model_ids: Iterable[str],
        maximum_candidates: int,
    ) -> list[AdaptiveCandidate]:
        """권한이 있고 아직 검증되지 않은 저비용 후보만 최대 N개 선택한다."""
        available = {str(model_id).strip() for model_id in available_model_ids if str(model_id).strip()}
        unique: dict[str, AdaptiveCandidate] = {}
        for candidate in candidates:
            model_id = str(candidate.model_id or "").strip()
            if (
                not model_id
                or model_id not in available
                or candidate.validated
                or model_id in unique
            ):
                continue
            unique[model_id] = candidate
        ordered = sorted(
            unique.values(),
            key=lambda candidate: (float(candidate.estimated_cost), candidate.model_id),
        )
        limit = max(0, int(maximum_candidates))
        if limit <= 1 or len(ordered) <= 1:
            return ordered[:limit]

        # 두 후보 모두 최저가 근처에 몰리면 "싼 모델은 실패했다"는 정보만 얻고
        # 품질을 유지하는 다음 비용대 모델을 검증하지 못한다. 가격은 품질 등급이
        # 아니라 검증 표본의 다양성을 위한 비용 축일 뿐이며, 실제 승격은 동일한
        # Replay/Schema/Downstream/Judge gate가 결정한다.
        selected = [ordered[0]]
        next_tier_minimum = float(ordered[0].estimated_cost) * cls.CANDIDATE_COST_TIER_MULTIPLIER
        tier_candidate = next(
            (
                candidate
                for candidate in ordered[1:]
                if float(candidate.estimated_cost) >= next_tier_minimum
            ),
            None,
        )
        if tier_candidate is not None:
            selected.append(tier_candidate)
        else:
            selected.append(ordered[1])

        for candidate in ordered:
            if len(selected) >= limit:
                break
            if candidate.model_id not in {item.model_id for item in selected}:
                selected.append(candidate)
        return selected[:limit]

    @classmethod
    def _is_runtime_route(cls, route: AdaptiveCohortRoute) -> bool:
        return (
            (
                (route.status in cls.RUNTIME_STATUSES and bool(route.validated))
                or bool(route.safety_override)
            )
            and bool(route.cohort_id)
            and bool(route.centroid_embedding)
        )

    @staticmethod
    def _input_paths(paths: Iterable[str]) -> list[str]:
        result: list[str] = []
        for raw_path in paths:
            path = str(raw_path or "").strip()
            if path and path not in result:
                result.append(path)
        return result[:8]
    SAFETY_NEGATIVE_DRIFT_TOLERANCE = 0.03
