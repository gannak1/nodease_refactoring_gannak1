"""Versioned semantic cohort matching for model-routing policies.

The matcher is intentionally provider-agnostic. Policy activation prepares route
vectors, while runtime supplies exactly one query vector and receives a safe
decision summary.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Sequence


Vector = tuple[float, ...]
Aggregation = Literal["centroid", "mean", "max", "sum", "top_k_mean"]
MatchStatus = Literal["matched", "no_match", "ambiguous", "unavailable"]
DecisionSource = Literal["dense", "safety_override", "unavailable"]


@dataclass(frozen=True)
class SemanticLexicalSignal:
    """One policy-owned sparse signal used by a generic runtime matcher."""

    term: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        normalized = _normalize_lexical_text(self.term)
        if not normalized:
            raise ValueError("lexical signal term is required")
        if len(normalized) > 160:
            raise ValueError("lexical signal term exceeds the supported length")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("lexical signal weight must be a positive finite number")


@dataclass(frozen=True)
class SemanticRouteDefinition:
    cohort_id: str
    label: str
    threshold: float
    representative_vectors: tuple[Vector, ...]
    centroid_vector: Vector | None = None
    safety_override: bool = False
    lexical_override_threshold: float = 1.0
    lexical_signals: tuple[SemanticLexicalSignal, ...] = ()

    def __post_init__(self) -> None:
        if not self.cohort_id.strip():
            raise ValueError("cohort_id is required")
        if not self.label.strip():
            raise ValueError("label is required")
        if not math.isfinite(self.threshold):
            raise ValueError("threshold must be finite")
        if not self.representative_vectors:
            raise ValueError("representative_vectors must not be empty")
        _validate_vector_dimensions(self.representative_vectors)
        if self.centroid_vector is not None:
            _validate_vector_dimensions((self.centroid_vector,))
            if len(self.centroid_vector) != len(self.representative_vectors[0]):
                raise ValueError("centroid vector dimensions must match representatives")
        if (
            not math.isfinite(self.lexical_override_threshold)
            or self.lexical_override_threshold <= 0
        ):
            raise ValueError(
                "lexical_override_threshold must be a positive finite number"
            )
        normalized_terms = [
            _normalize_lexical_text(signal.term)
            for signal in self.lexical_signals
        ]
        if len(normalized_terms) != len(set(normalized_terms)):
            raise ValueError("lexical signal terms must be unique within a route")


@dataclass(frozen=True)
class SemanticRouteCatalog:
    version: str
    encoder_model_id: str
    routes: tuple[SemanticRouteDefinition, ...]
    input_paths: tuple[str, ...] = ()
    top_k: int = 5
    aggregation: Aggregation = "mean"
    min_margin: float = 0.05

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version is required")
        if not self.encoder_model_id.strip():
            raise ValueError("encoder_model_id is required")
        if not self.routes:
            raise ValueError("routes must not be empty")
        if self.top_k < 1:
            raise ValueError("top_k must be at least 1")
        if self.aggregation not in {"centroid", "mean", "max", "sum", "top_k_mean"}:
            raise ValueError(
                "aggregation must be centroid, mean, max, sum, or top_k_mean"
            )
        if not math.isfinite(self.min_margin) or self.min_margin < 0:
            raise ValueError("min_margin must be a finite non-negative number")

        cohort_ids = [route.cohort_id for route in self.routes]
        if len(cohort_ids) != len(set(cohort_ids)):
            raise ValueError("route cohort_id values must be unique")

        dimensions = {
            len(vector)
            for route in self.routes
            for vector in route.representative_vectors
        }
        if len(dimensions) != 1:
            raise ValueError("all representative vectors must have equal dimensions")


@dataclass(frozen=True)
class SemanticCohortScore:
    """Trace 화면에 표시할 입력군별 safe 유사도 정보다."""

    cohort_id: str
    label: str
    similarity: float
    threshold: float

    def as_metadata(self) -> dict[str, object]:
        return {
            "cohort_id": self.cohort_id,
            "label": self.label,
            "similarity": self.similarity,
            "threshold": self.threshold,
        }


@dataclass(frozen=True)
class SemanticRouteMatch:
    status: MatchStatus
    cohort_id: str | None
    label: str | None
    candidate_cohort_id: str | None
    candidate_label: str | None
    similarity: float | None
    threshold: float | None
    runner_up_score: float | None
    margin: float | None
    catalog_version: str
    encoder_model_id: str
    decision_source: DecisionSource = "dense"
    lexical_score: float = 0.0
    lexical_signal_count: int = 0
    safety_override: bool = False
    matcher: Literal["semantic", "hybrid"] = "semantic"
    candidate_scores: tuple[SemanticCohortScore, ...] = ()
    min_margin: float | None = None

    @classmethod
    def unavailable(cls, catalog: SemanticRouteCatalog) -> "SemanticRouteMatch":
        return cls(
            status="unavailable",
            cohort_id=None,
            label=None,
            candidate_cohort_id=None,
            candidate_label=None,
            similarity=None,
            threshold=None,
            runner_up_score=None,
            margin=None,
            catalog_version=catalog.version,
            encoder_model_id=catalog.encoder_model_id,
            decision_source="unavailable",
            matcher=_matcher_name(catalog),
            min_margin=catalog.min_margin,
        )

    def as_metadata(self) -> dict[str, object | None]:
        """Return trace-safe routing evidence without input text or vectors."""
        return {
            "cohort_matcher": self.matcher,
            "semantic_match_status": self.status,
            "semantic_route_label": self.label,
            "semantic_candidate_cohort_id": self.candidate_cohort_id,
            "semantic_candidate_label": self.candidate_label,
            "semantic_similarity": self.similarity,
            "semantic_threshold": self.threshold,
            "semantic_runner_up_score": self.runner_up_score,
            "semantic_margin": self.margin,
            "semantic_min_margin": self.min_margin,
            "semantic_cohort_scores": [
                score.as_metadata() for score in self.candidate_scores
            ],
            "route_catalog_version": self.catalog_version,
            "semantic_encoder_model": self.encoder_model_id,
            "semantic_decision_source": self.decision_source,
            "semantic_lexical_score": self.lexical_score,
            "semantic_lexical_signal_count": self.lexical_signal_count,
            "semantic_safety_override": self.safety_override,
        }


class SemanticRouteMatcher:
    """Match one query vector against precomputed route representatives."""

    @classmethod
    def match(
        cls,
        catalog: SemanticRouteCatalog,
        *,
        query_vector: Sequence[float],
        query_text: str | None = None,
    ) -> SemanticRouteMatch:
        query = tuple(float(value) for value in query_vector)
        _validate_query_vector(query, catalog)

        if catalog.aggregation == "centroid":
            route_scores = sorted(
                (
                    (
                        _cosine_similarity(
                            query,
                            route.centroid_vector
                            or _centroid(route.representative_vectors),
                        ),
                        route,
                    )
                    for route in catalog.routes
                ),
                key=lambda item: (-item[0], item[1].cohort_id),
            )
        elif catalog.aggregation == "max":
            # max는 입력군마다 가장 가까운 대표 예시 하나를 비교하는 의미다.
            # 전체 representative를 먼저 top-k로 자르면 한 입력군이 슬롯을
            # 독점해 runner-up과 min_margin 검사를 건너뛸 수 있다.
            route_scores = sorted(
                (
                    (
                        max(
                            _cosine_similarity(query, vector)
                            for vector in route.representative_vectors
                        ),
                        route,
                    )
                    for route in catalog.routes
                ),
                key=lambda item: (-item[0], item[1].cohort_id),
            )
        elif catalog.aggregation == "top_k_mean":
            # 각 입력군 안에서 가까운 예문을 고른 뒤 평균한다. 전체 예문을 먼저
            # 자르면 예문이 많은 입력군이 top-k 슬롯을 독점할 수 있다.
            route_scores = sorted(
                (
                    (
                        sum(scores) / len(scores),
                        route,
                    )
                    for route in catalog.routes
                    for scores in [
                        sorted(
                            (
                                _cosine_similarity(query, vector)
                                for vector in route.representative_vectors
                            ),
                            reverse=True,
                        )[: catalog.top_k]
                    ]
                ),
                key=lambda item: (-item[0], item[1].cohort_id),
            )
        else:
            scored_representatives = sorted(
                (
                    (_cosine_similarity(query, vector), route)
                    for route in catalog.routes
                    for vector in route.representative_vectors
                ),
                key=lambda item: item[0],
                reverse=True,
            )[: catalog.top_k]

            scores_by_cohort: dict[str, list[float]] = {}
            route_by_cohort = {route.cohort_id: route for route in catalog.routes}
            for score, route in scored_representatives:
                scores_by_cohort.setdefault(route.cohort_id, []).append(score)

            route_scores = sorted(
                (
                    (
                        _aggregate(scores, catalog.aggregation),
                        route_by_cohort[cohort_id],
                    )
                    for cohort_id, scores in scores_by_cohort.items()
                ),
                key=lambda item: (-item[0], item[1].cohort_id),
            )
        if not route_scores:
            raise ValueError("catalog has no scorable representatives")

        candidate_scores = _candidate_scores(catalog, query, route_scores)

        sparse_matches = _score_lexical_routes(catalog, query_text)
        matched_safety_routes = [
            (score, count, route)
            for score, count, route in sparse_matches
            if route.safety_override
            and score >= route.lexical_override_threshold
        ]
        if matched_safety_routes:
            dense_score_by_cohort = {
                route.cohort_id: score for score, route in route_scores
            }
            sparse_score, signal_count, selected_route = sorted(
                matched_safety_routes,
                key=lambda item: (
                    -item[0],
                    -dense_score_by_cohort.get(item[2].cohort_id, -1.0),
                    item[2].cohort_id,
                ),
            )[0]
            selected_dense_score = dense_score_by_cohort.get(
                selected_route.cohort_id
            )
            other_dense_scores = [
                score
                for score, route in route_scores
                if route.cohort_id != selected_route.cohort_id
            ]
            runner_up_score = max(other_dense_scores) if other_dense_scores else None
            margin = (
                selected_dense_score - runner_up_score
                if selected_dense_score is not None and runner_up_score is not None
                else None
            )
            return SemanticRouteMatch(
                status="matched",
                cohort_id=selected_route.cohort_id,
                label=selected_route.label,
                candidate_cohort_id=selected_route.cohort_id,
                candidate_label=selected_route.label,
                similarity=selected_dense_score,
                threshold=selected_route.threshold,
                runner_up_score=runner_up_score,
                margin=margin,
                catalog_version=catalog.version,
                encoder_model_id=catalog.encoder_model_id,
                decision_source="safety_override",
                lexical_score=sparse_score,
                lexical_signal_count=signal_count,
                safety_override=True,
                matcher=_matcher_name(catalog),
                candidate_scores=candidate_scores,
                min_margin=catalog.min_margin,
            )

        top_score, top_route = route_scores[0]
        runner_up_score = route_scores[1][0] if len(route_scores) > 1 else None
        margin = (
            top_score - runner_up_score if runner_up_score is not None else None
        )

        if top_score < top_route.threshold:
            status: MatchStatus = "no_match"
        elif margin is not None and margin < catalog.min_margin:
            status = "ambiguous"
        else:
            status = "matched"

        best_sparse_score, best_sparse_count = _best_sparse_diagnostic(
            sparse_matches
        )

        return SemanticRouteMatch(
            status=status,
            cohort_id=top_route.cohort_id if status == "matched" else None,
            label=top_route.label if status == "matched" else None,
            candidate_cohort_id=top_route.cohort_id,
            candidate_label=top_route.label,
            similarity=top_score,
            threshold=top_route.threshold,
            runner_up_score=runner_up_score,
            margin=margin,
            catalog_version=catalog.version,
            encoder_model_id=catalog.encoder_model_id,
            decision_source="dense",
            lexical_score=best_sparse_score,
            lexical_signal_count=best_sparse_count,
            safety_override=False,
            matcher=_matcher_name(catalog),
            candidate_scores=candidate_scores,
            min_margin=catalog.min_margin,
        )


def semantic_catalog_from_policy(value: Any) -> SemanticRouteCatalog | None:
    """Parse the internal active-policy catalog without accepting loose shapes."""
    if not isinstance(value, dict) or not value:
        return None

    routes_value = value.get("routes")
    if not isinstance(routes_value, list) or not routes_value:
        raise ValueError("semantic_router.routes must be a non-empty list")

    aggregation = str(value.get("aggregation") or "mean")
    routes: list[SemanticRouteDefinition] = []
    for route_value in routes_value:
        if not isinstance(route_value, dict):
            raise ValueError("semantic route must be an object")
        representatives_value = route_value.get("representatives")
        if not isinstance(representatives_value, list) or not representatives_value:
            raise ValueError("semantic route representatives must be non-empty")

        representative_vectors: list[Vector] = []
        for representative in representatives_value:
            embedding = (
                representative.get("embedding")
                if isinstance(representative, dict)
                else None
            )
            if not isinstance(embedding, (list, tuple)):
                raise ValueError("semantic representative embedding is required")
            representative_vectors.append(tuple(float(value) for value in embedding))

        centroid_value = route_value.get("centroid_embedding")
        centroid_vector = (
            tuple(float(item) for item in centroid_value)
            if isinstance(centroid_value, (list, tuple))
            else None
        )
        lexical_signals_value = route_value.get("lexical_signals")
        lexical_signals: list[SemanticLexicalSignal] = []
        if lexical_signals_value is not None:
            if not isinstance(lexical_signals_value, list):
                raise ValueError("semantic route lexical_signals must be a list")
            for signal_value in lexical_signals_value:
                if not isinstance(signal_value, dict):
                    raise ValueError("semantic lexical signal must be an object")
                lexical_signals.append(
                    SemanticLexicalSignal(
                        term=str(signal_value.get("term") or ""),
                        weight=float(signal_value.get("weight", 1.0)),
                    )
                )
        if aggregation == "centroid" and centroid_vector is None:
            centroid_vector = _centroid(tuple(representative_vectors))

        routes.append(
            SemanticRouteDefinition(
                cohort_id=str(route_value.get("cohort_id") or ""),
                label=str(route_value.get("label") or ""),
                threshold=float(route_value.get("threshold", 0.0)),
                representative_vectors=tuple(representative_vectors),
                centroid_vector=centroid_vector,
                safety_override=bool(route_value.get("safety_override", False)),
                lexical_override_threshold=float(
                    route_value.get("lexical_override_threshold", 1.0)
                ),
                lexical_signals=tuple(lexical_signals),
            )
        )

    encoder = value.get("encoder")
    encoder_model_id = value.get("encoder_model_id")
    if not encoder_model_id and isinstance(encoder, dict):
        encoder_model_id = encoder.get("model_id")

    return SemanticRouteCatalog(
        version=str(
            value.get("route_catalog_version") or value.get("version") or ""
        ),
        encoder_model_id=str(encoder_model_id or ""),
        routes=tuple(routes),
        input_paths=tuple(
            str(path).strip()
            for path in value.get("input_paths", [])
            if str(path).strip()
        ),
        top_k=int(value.get("top_k", 5)),
        aggregation=aggregation,  # type: ignore[arg-type]
        min_margin=float(value.get("min_margin", 0.05)),
    )


def _validate_vector_dimensions(vectors: Sequence[Sequence[float]]) -> None:
    dimensions = {len(vector) for vector in vectors}
    if dimensions == {0}:
        raise ValueError("vectors must not be empty")
    if len(dimensions) != 1:
        raise ValueError("vectors must have equal dimensions")
    for vector in vectors:
        if not all(math.isfinite(float(value)) for value in vector):
            raise ValueError("vectors must contain only finite numbers")
        if _vector_norm(vector) == 0:
            raise ValueError("vectors must not be zero vectors")


def _validate_query_vector(
    query: Vector,
    catalog: SemanticRouteCatalog,
) -> None:
    if not query:
        raise ValueError("query_vector must not be empty")
    if not all(math.isfinite(value) for value in query):
        raise ValueError("query_vector must contain only finite numbers")
    if _vector_norm(query) == 0:
        raise ValueError("query_vector must not be a zero vector")
    expected_dimensions = len(catalog.routes[0].representative_vectors[0])
    if len(query) != expected_dimensions:
        raise ValueError(
            "query_vector dimensions must match representative vectors"
        )


def _aggregate(scores: Sequence[float], aggregation: Aggregation) -> float:
    if aggregation in {"mean", "top_k_mean"}:
        return sum(scores) / len(scores)
    if aggregation == "max":
        return max(scores)
    return sum(scores)


def _candidate_scores(
    catalog: SemanticRouteCatalog,
    query: Vector,
    routing_scores: Sequence[tuple[float, SemanticRouteDefinition]],
) -> tuple[SemanticCohortScore, ...]:
    """Keep a safe, complete per-cohort diagnostic without changing selection."""
    routing_score_by_cohort = {
        route.cohort_id: score for score, route in routing_scores
    }
    scores: list[SemanticCohortScore] = []

    for route in catalog.routes:
        score = routing_score_by_cohort.get(route.cohort_id)
        if score is None:
            if catalog.aggregation == "centroid":
                score = _cosine_similarity(
                    query,
                    route.centroid_vector or _centroid(route.representative_vectors),
                )
            else:
                representative_scores = sorted(
                    (
                        _cosine_similarity(query, vector)
                        for vector in route.representative_vectors
                    ),
                    reverse=True,
                )[: catalog.top_k]
                score = _aggregate(representative_scores, catalog.aggregation)

        scores.append(
            SemanticCohortScore(
                cohort_id=route.cohort_id,
                label=route.label,
                similarity=float(score),
                threshold=route.threshold,
            )
        )

    return tuple(
        sorted(scores, key=lambda item: (-item.similarity, item.cohort_id))
    )


def _centroid(vectors: Sequence[Sequence[float]]) -> Vector:
    return tuple(
        sum(values) / len(vectors)
        for values in zip(*vectors, strict=True)
    )


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = _vector_norm(left) * _vector_norm(right)
    return numerator / denominator


def _vector_norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) ** 2 for value in vector))


def _normalize_lexical_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(normalized.split())


def _score_lexical_routes(
    catalog: SemanticRouteCatalog,
    query_text: str | None,
) -> list[tuple[float, int, SemanticRouteDefinition]]:
    normalized_query = _normalize_lexical_text(query_text or "")
    if not normalized_query:
        return []

    scored: list[tuple[float, int, SemanticRouteDefinition]] = []
    for route in catalog.routes:
        matched_signals = [
            signal
            for signal in route.lexical_signals
            if _normalize_lexical_text(signal.term) in normalized_query
        ]
        if matched_signals:
            scored.append(
                (
                    sum(signal.weight for signal in matched_signals),
                    len(matched_signals),
                    route,
                )
            )
    return scored


def _best_sparse_diagnostic(
    sparse_matches: Sequence[tuple[float, int, SemanticRouteDefinition]],
) -> tuple[float, int]:
    if not sparse_matches:
        return 0.0, 0
    score, count, _route = sorted(
        sparse_matches,
        key=lambda item: (-item[0], -item[1], item[2].cohort_id),
    )[0]
    return score, count


def _matcher_name(
    catalog: SemanticRouteCatalog,
) -> Literal["semantic", "hybrid"]:
    return (
        "hybrid"
        if any(route.safety_override and route.lexical_signals for route in catalog.routes)
        else "semantic"
    )
