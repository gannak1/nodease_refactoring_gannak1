"""적응형 입력군을 runtime policy와 검증 후보 계획으로 변환한다.

이 모듈은 DB, Celery, provider에 의존하지 않는다. 따라서 정책에 포함될 수 있는
입력군과 실제 비용을 쓰기 전 검증할 후보 범위를 한 곳에서 테스트할 수 있다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class AdaptiveCohortRoute:
    cohort_id: str
    label: str
    status: str
    validated: bool
    centroid_embedding: Sequence[float]
    representative_embeddings: Sequence[Sequence[float]] = ()
    safety_override: bool = False
    threshold: float = 0.72


@dataclass(frozen=True)
class AdaptiveCandidate:
    model_id: str
    estimated_cost: float
    validated: bool


class AdaptiveModelRoutingPolicyService:
    """자동 발견/검증 결과에 대한 순수 policy projection 규칙."""

    RUNTIME_STATUSES = frozenset({"active"})
    CANDIDATE_COST_TIER_MULTIPLIER = 2.0

    @classmethod
    def build_runtime_catalog(
        cls,
        *,
        encoder_model_id: str,
        input_paths: Iterable[str],
        routes: Iterable[AdaptiveCohortRoute],
        preserved_safety_routes: Iterable[dict] = (),
    ) -> dict:
        """검증 완료 cohort와 policy-owned 안전 route를 runtime 형식으로 투영한다."""
        normalized_paths = cls._input_paths(input_paths)
        projected_routes: list[dict] = []
        for route in routes:
            if not cls._is_runtime_route(route):
                continue
            representative_vectors = cls._representative_vectors(route)
            projected_routes.append(
                {
                    "cohort_id": route.cohort_id,
                    "label": route.label,
                    "threshold": max(0.0, min(float(route.threshold), 1.0)),
                    "safety_override": bool(route.safety_override),
                    "lexical_signals": [],
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
            )
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
                    "centroid_embedding": centroid,
                    "representatives": representatives,
                }
            )
        return {
            "route_catalog_version": "adaptive-cohorts-v1",
            "encoder_model_id": str(encoder_model_id or "").strip(),
            "input_paths": normalized_paths,
            "top_k": 5,
            "aggregation": "max",
            "min_margin": 0.05,
            "routes": projected_routes,
        }

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
            route.status in cls.RUNTIME_STATUSES
            and bool(route.validated)
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
