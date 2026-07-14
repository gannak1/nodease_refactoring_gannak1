"""입력군 발견과 수명 주기의 순수 정책을 제공한다."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Iterable, Sequence


LOW_SHARE_THRESHOLD = 0.05
REACTIVATION_SHARE_THRESHOLD = 0.10
LOW_SHARE_REVIEW_COUNT = 3
DORMANT_RETENTION = timedelta(days=90)


@dataclass(frozen=True)
class CohortObservation:
    input_hash: str
    embedding: Sequence[float]
    review_window: int
    observed_at: datetime


@dataclass(frozen=True)
class DiscoveredCohort:
    member_input_hashes: tuple[str, ...]
    centroid: tuple[float, ...]
    distinct_input_count: int
    review_windows: tuple[int, ...]


@dataclass(frozen=True)
class CohortState:
    status: str
    required: bool
    safety_protected: bool
    low_share_streak: int
    last_seen_at: datetime | None
    dormant_since: datetime | None = None


class AdaptiveCohortService:
    """DB와 provider에 의존하지 않는 입력군 발견 및 lifecycle 규칙."""

    @classmethod
    def discover(
        cls,
        observations: Iterable[CohortObservation],
        *,
        minimum_distinct_inputs: int,
        minimum_review_windows: int,
        similarity_threshold: float,
    ) -> list[DiscoveredCohort]:
        clusters: list[list[CohortObservation]] = []

        for observation in sorted(
            observations,
            key=lambda item: (item.review_window, item.observed_at, item.input_hash),
        ):
            if not cls._valid_embedding(observation.embedding):
                continue
            target = cls._nearest_cluster(
                observation.embedding,
                clusters,
                similarity_threshold=similarity_threshold,
            )
            if target is None:
                clusters.append([observation])
            else:
                target.append(observation)

        discovered: list[DiscoveredCohort] = []
        for cluster in clusters:
            hashes = tuple(sorted({item.input_hash for item in cluster if item.input_hash}))
            windows = tuple(sorted({item.review_window for item in cluster}))
            if len(hashes) < minimum_distinct_inputs:
                continue
            if len(windows) < minimum_review_windows:
                continue
            discovered.append(
                DiscoveredCohort(
                    member_input_hashes=hashes,
                    centroid=cls._centroid(item.embedding for item in cluster),
                    distinct_input_count=len(hashes),
                    review_windows=windows,
                )
            )

        return sorted(
            discovered,
            key=lambda item: (-item.distinct_input_count, item.member_input_hashes),
        )

    @classmethod
    def advance_lifecycle(
        cls,
        state: CohortState,
        *,
        current_share: float,
        now: datetime,
    ) -> CohortState:
        share = max(0.0, float(current_share))
        if state.status == "retired":
            return state

        if state.status == "dormant":
            if share >= REACTIVATION_SHARE_THRESHOLD:
                return replace(
                    state,
                    status="active",
                    low_share_streak=0,
                    last_seen_at=now,
                    dormant_since=None,
                )
            if (
                state.dormant_since is not None
                and now - state.dormant_since >= DORMANT_RETENTION
            ):
                return replace(state, status="retired")
            return state

        if state.required or state.safety_protected:
            return replace(
                state,
                low_share_streak=0,
                last_seen_at=now if share > 0 else state.last_seen_at,
            )

        if share <= LOW_SHARE_THRESHOLD:
            streak = state.low_share_streak + 1
            if streak >= LOW_SHARE_REVIEW_COUNT:
                return replace(
                    state,
                    status="dormant",
                    low_share_streak=streak,
                    dormant_since=now,
                )
            return replace(state, low_share_streak=streak)

        return replace(
            state,
            low_share_streak=0,
            last_seen_at=now,
        )

    @classmethod
    def _nearest_cluster(
        cls,
        embedding: Sequence[float],
        clusters: list[list[CohortObservation]],
        *,
        similarity_threshold: float,
    ) -> list[CohortObservation] | None:
        winner: list[CohortObservation] | None = None
        winner_score = float("-inf")
        for cluster in clusters:
            score = cls._cosine_similarity(embedding, cls._centroid(item.embedding for item in cluster))
            if score >= similarity_threshold and score > winner_score:
                winner = cluster
                winner_score = score
        return winner

    @staticmethod
    def _valid_embedding(embedding: Sequence[float]) -> bool:
        return bool(embedding) and all(math.isfinite(float(value)) for value in embedding)

    @staticmethod
    def _centroid(embeddings: Iterable[Sequence[float]]) -> tuple[float, ...]:
        vectors = [tuple(float(value) for value in embedding) for embedding in embeddings]
        if not vectors:
            return ()
        size = len(vectors[0])
        if any(len(vector) != size for vector in vectors):
            return ()
        return tuple(sum(vector[index] for vector in vectors) / len(vectors) for index in range(size))

    @staticmethod
    def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right) or not left:
            return float("-inf")
        numerator = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
        right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
        if left_norm == 0 or right_norm == 0:
            return float("-inf")
        return numerator / (left_norm * right_norm)
