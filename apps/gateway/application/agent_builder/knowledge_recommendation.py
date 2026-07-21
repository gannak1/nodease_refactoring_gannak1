from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast
from uuid import UUID


MAX_RECOMMENDATION_DEADLINE_MS = 10_000
CountBucket = Literal["zero", "one", "few", "many"]
_COUNT_BUCKETS = frozenset({"zero", "one", "few", "many"})
_PERSISTED_RECOMMENDATION_KEYS = frozenset(
    {
        "confidence",
        "parent_relevance",
        "reason_category",
        "recommendation_state",
        "retrieval_state",
        "safe_reason_code",
        "score",
        "semantic_state",
        "threshold_result",
    }
)


EmbeddingFailureReason = Literal[
    "model_ambiguous",
    "credential_unavailable",
    "provider_unavailable",
    "deadline_exceeded",
]
_EMBEDDING_FAILURE_REASONS = frozenset(
    {
        "model_ambiguous",
        "credential_unavailable",
        "provider_unavailable",
        "deadline_exceeded",
    }
)


SemanticState = Literal[
    "available",
    "flat",
    "hierarchy_unavailable",
    "artifact_inconsistent",
    "model_ambiguous",
    "credential_unavailable",
    "provider_unavailable",
    "retrieval_unavailable",
    "parent_search_timeout",
    "cohort_budget_exceeded",
    "deadline_exceeded",
]
_SEMANTIC_STATES = frozenset(
    {
        "available",
        "flat",
        "hierarchy_unavailable",
        "artifact_inconsistent",
        "model_ambiguous",
        "credential_unavailable",
        "provider_unavailable",
        "retrieval_unavailable",
        "parent_search_timeout",
        "cohort_budget_exceeded",
        "deadline_exceeded",
    }
)


SafeReasonCode = Literal[
    "content_match",
    "metadata_fallback",
    "flat",
    "hierarchy_unavailable",
    "artifact_inconsistent",
    "model_ambiguous",
    "credential_unavailable",
    "provider_unavailable",
    "retrieval_unavailable",
    "parent_search_timeout",
    "cohort_budget_exceeded",
    "deadline_exceeded",
]
_SAFE_REASON_CODES = frozenset(
    {
        "content_match",
        "metadata_fallback",
        "flat",
        "hierarchy_unavailable",
        "artifact_inconsistent",
        "model_ambiguous",
        "credential_unavailable",
        "provider_unavailable",
        "retrieval_unavailable",
        "parent_search_timeout",
        "cohort_budget_exceeded",
        "deadline_exceeded",
    }
)


def coerce_embedding_failure_reason(value: object) -> EmbeddingFailureReason:
    if isinstance(value, str) and value in _EMBEDDING_FAILURE_REASONS:
        return cast(EmbeddingFailureReason, value)
    return "provider_unavailable"


def coerce_semantic_state(value: object) -> SemanticState:
    if isinstance(value, str) and value in _SEMANTIC_STATES:
        return cast(SemanticState, value)
    return "retrieval_unavailable"


def coerce_safe_reason_code(value: object) -> SafeReasonCode:
    if isinstance(value, str) and value in _SAFE_REASON_CODES:
        return cast(SafeReasonCode, value)
    return "retrieval_unavailable"


def semantic_state_for_embedding_failure(value: object) -> SemanticState:
    return cast(SemanticState, coerce_embedding_failure_reason(value))


@dataclass(frozen=True, slots=True)
class EmbeddingResolution:
    vector: tuple[float, ...] | None
    failure_reason: EmbeddingFailureReason | None = None

    def __post_init__(self) -> None:
        if self.vector is not None:
            if self.failure_reason is not None:
                raise ValueError("available embedding must not carry a failure reason")
            return
        object.__setattr__(
            self,
            "failure_reason",
            coerce_embedding_failure_reason(self.failure_reason),
        )

    @classmethod
    def unavailable(cls, reason: object) -> EmbeddingResolution:
        return cls(
            vector=None,
            failure_reason=coerce_embedding_failure_reason(reason),
        )


class RecommendationEmbeddingResolver(Protocol):
    def embed_query(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        embedding_model: str,
        safe_query: str,
        timeout_seconds: float,
        deadline: RecommendationDeadline | None = None,
    ) -> EmbeddingResolution: ...


@dataclass(frozen=True, slots=True)
class RecommendationDeadline:
    started_at_monotonic: float
    expires_at_monotonic: float

    def __post_init__(self) -> None:
        started_at = float(self.started_at_monotonic)
        expires_at = float(self.expires_at_monotonic)
        duration_ms = (expires_at - started_at) * 1000
        if not math.isfinite(started_at) or not math.isfinite(expires_at):
            raise ValueError("recommendation deadline must be finite")
        if not (
            1.0 - 1e-6
            <= duration_ms
            <= MAX_RECOMMENDATION_DEADLINE_MS + 1e-6
        ):
            raise ValueError("recommendation deadline is out of bounds")
        object.__setattr__(self, "started_at_monotonic", started_at)
        object.__setattr__(self, "expires_at_monotonic", expires_at)

    @classmethod
    def from_timeout_ms(
        cls,
        timeout_ms: int,
        *,
        now_monotonic: float | None = None,
    ) -> RecommendationDeadline:
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or not 1 <= timeout_ms <= MAX_RECOMMENDATION_DEADLINE_MS
        ):
            raise ValueError("recommendation deadline is out of bounds")
        started_at = (
            time.monotonic() if now_monotonic is None else float(now_monotonic)
        )
        return cls(
            started_at_monotonic=started_at,
            expires_at_monotonic=started_at + timeout_ms / 1000,
        )

    @property
    def budget_ms(self) -> int:
        return round(
            (self.expires_at_monotonic - self.started_at_monotonic) * 1000
        )

    def remaining_seconds(self, *, now_monotonic: float | None = None) -> float:
        now = time.monotonic() if now_monotonic is None else float(now_monotonic)
        if not math.isfinite(now):
            return 0.0
        return max(0.0, self.expires_at_monotonic - now)

    def accepts_result(self, *, completed_at_monotonic: float) -> bool:
        completed_at = float(completed_at_monotonic)
        return (
            math.isfinite(completed_at)
            and completed_at <= self.expires_at_monotonic
        )


@dataclass(frozen=True, slots=True)
class KnowledgeRecommendationRetrievalRequest:
    organization_id: UUID
    actor_id: UUID
    safe_query_topics: tuple[str, ...]
    candidate_kb_ids: tuple[UUID, ...]
    candidate_snapshot_ref: str
    deadline_ms: int = MAX_RECOMMENDATION_DEADLINE_MS
    deadline: RecommendationDeadline | None = None
    cancellation_predicate: Callable[[], bool] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not 1 <= len(self.safe_query_topics) <= 20:
            raise ValueError("safe query topic count is out of bounds")
        if any(not isinstance(topic, str) or not topic for topic in self.safe_query_topics):
            raise ValueError("safe query topics must be non-empty strings")
        if sum(len(topic) for topic in self.safe_query_topics) > 1000:
            raise ValueError("safe query topics exceed the total length bound")
        if not 1 <= len(self.candidate_kb_ids) <= 5000:
            raise ValueError("candidate count is out of bounds")
        if len(self.candidate_kb_ids) != len(set(self.candidate_kb_ids)):
            raise ValueError("candidate knowledge base IDs must be unique")
        if (
            isinstance(self.deadline_ms, bool)
            or not isinstance(self.deadline_ms, int)
            or not 1 <= self.deadline_ms <= MAX_RECOMMENDATION_DEADLINE_MS
        ):
            raise ValueError("semantic deadline is out of bounds")
        if not self.candidate_snapshot_ref or len(self.candidate_snapshot_ref) > 255:
            raise ValueError("candidate snapshot reference is invalid")
        if self.cancellation_predicate is not None and not callable(
            self.cancellation_predicate
        ):
            raise ValueError("recommendation cancellation predicate is invalid")
        if self.deadline is None:
            object.__setattr__(
                self,
                "deadline",
                RecommendationDeadline.from_timeout_ms(self.deadline_ms),
            )
            return
        if not isinstance(self.deadline, RecommendationDeadline):
            raise ValueError("absolute recommendation deadline is invalid")
        absolute_budget_ms = self.deadline.budget_ms
        if (
            self.deadline_ms != MAX_RECOMMENDATION_DEADLINE_MS
            and self.deadline_ms != absolute_budget_ms
        ):
            raise ValueError("relative and absolute recommendation deadlines differ")
        object.__setattr__(self, "deadline_ms", absolute_budget_ms)

    def is_cancellation_requested(self) -> bool:
        predicate = self.cancellation_predicate
        if predicate is None:
            return False
        try:
            result = predicate()
        except Exception:
            return True
        return result if isinstance(result, bool) else True


@dataclass(frozen=True, slots=True)
class CandidateSemanticScore:
    knowledge_base_id: UUID
    semantic_state: SemanticState
    parent_relevance: float | None
    safe_reason_code: SafeReasonCode

    def __post_init__(self) -> None:
        raw_semantic_state = self.semantic_state
        semantic_state = coerce_semantic_state(raw_semantic_state)
        object.__setattr__(self, "semantic_state", semantic_state)
        if semantic_state == "available":
            if self.parent_relevance is None:
                raise ValueError("available semantic score requires parent relevance")
            object.__setattr__(
                self,
                "parent_relevance",
                normalize_cosine_similarity(self.parent_relevance),
            )
            object.__setattr__(self, "safe_reason_code", "content_match")
            return

        if self.parent_relevance is not None:
            if raw_semantic_state == semantic_state:
                raise ValueError("unavailable semantic score must not carry relevance")
            object.__setattr__(self, "parent_relevance", None)

        safe_reason_code = coerce_safe_reason_code(self.safe_reason_code)
        if safe_reason_code == "content_match":
            safe_reason_code = cast(SafeReasonCode, semantic_state)
        object.__setattr__(self, "safe_reason_code", safe_reason_code)


@dataclass(frozen=True, slots=True)
class KnowledgeRecommendationRetrievalResult:
    state: Literal["complete", "degraded"] = "complete"
    scores: tuple[CandidateSemanticScore, ...] = ()
    failed_cohort_count_bucket: Literal["zero", "one", "few", "many"] = "zero"
    latency_bucket: str = "unknown"
    candidate_count_bucket: CountBucket = "zero"
    result_count_bucket: CountBucket = "zero"
    cohort_count_bucket: CountBucket = "zero"
    metadata_fallback_count_bucket: CountBucket = "zero"

    def __post_init__(self) -> None:
        candidate_ids = [score.knowledge_base_id for score in self.scores]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("semantic result contains duplicate knowledge base IDs")
        for bucket in (
            self.candidate_count_bucket,
            self.result_count_bucket,
            self.cohort_count_bucket,
            self.metadata_fallback_count_bucket,
        ):
            if bucket not in _COUNT_BUCKETS:
                raise ValueError("semantic result contains an invalid count bucket")


class KnowledgeRecommendationRetrievalPort(Protocol):
    def retrieve(
        self,
        request: KnowledgeRecommendationRetrievalRequest,
    ) -> KnowledgeRecommendationRetrievalResult: ...


def redact_persisted_knowledge_recommendation_tree(value: Any) -> None:
    """Remove request-scoped recommendation signals from a durable subtree."""

    if isinstance(value, dict):
        for key in _PERSISTED_RECOMMENDATION_KEYS:
            value.pop(key, None)
        for child in value.values():
            redact_persisted_knowledge_recommendation_tree(child)
    elif isinstance(value, list):
        for child in value:
            redact_persisted_knowledge_recommendation_tree(child)


def normalize_cosine_similarity(cosine_similarity: float) -> float:
    """Map cosine similarity to the fixed recommendation score interval."""
    return max(0.0, min(float(cosine_similarity), 1.0))


def aggregate_parent_relevance(parent_scores: Iterable[float]) -> float:
    """Aggregate the best three normalized parent scores for one KB."""
    top_scores = sorted(
        (normalize_cosine_similarity(score) for score in parent_scores),
        reverse=True,
    )[:3]
    if not top_scores:
        raise ValueError("parent scores must not be empty")
    return 0.7 * top_scores[0] + 0.3 * (sum(top_scores) / len(top_scores))


def select_parent_first_relevance(
    *,
    parent_relevance: float | None,
    metadata_relevance: float,
    semantic_available: bool,
) -> float:
    """Apply the fixed parent_first_v1 relevance policy."""
    if semantic_available:
        if parent_relevance is None:
            raise ValueError("available semantic result requires parent relevance")
        return normalize_cosine_similarity(parent_relevance)
    return normalize_cosine_similarity(metadata_relevance)


def compose_final_recommendation_score(
    *,
    relevance: float,
    source_tier: float,
    availability: float,
    freshness: float,
) -> float:
    """Compose the final KB score while preserving the relevance-zero gate."""
    normalized_relevance = normalize_cosine_similarity(relevance)
    if normalized_relevance == 0.0:
        return 0.0
    return min(
        1.0,
        0.7 * normalized_relevance
        + 0.1 * normalize_cosine_similarity(source_tier)
        + 0.1 * normalize_cosine_similarity(availability)
        + 0.1 * normalize_cosine_similarity(freshness),
    )
