"""Build trace-safe semantic route catalogs before policy activation."""

from __future__ import annotations

import hashlib
import math
import unicodedata
from collections.abc import Callable
from typing import Any


EmbeddingFunction = Callable[[str], list[float]]


class SemanticRouteCatalogBuilder:
    """Precompute curated route vectors without retaining utterance text."""

    MAX_ROUTES = 32
    MAX_UTTERANCES_PER_ROUTE = 64
    MAX_INPUT_PATHS = 8
    MAX_LEXICAL_SIGNALS_PER_ROUTE = 64
    MAX_LEXICAL_SIGNAL_LENGTH = 160

    @classmethod
    def build(
        cls,
        source: dict[str, Any],
        *,
        embed: EmbeddingFunction,
    ) -> dict[str, Any]:
        if not isinstance(source, dict):
            raise ValueError("semantic route catalog source must be an object")

        version = str(source.get("route_catalog_version") or "").strip()
        encoder_model_id = str(source.get("encoder_model_id") or "").strip()
        input_paths = cls._input_paths(source.get("input_paths"))
        routes = source.get("routes")
        if not version:
            raise ValueError("route_catalog_version is required")
        if not encoder_model_id:
            raise ValueError("encoder_model_id is required")
        if not isinstance(routes, list) or not routes:
            raise ValueError("routes must be a non-empty list")
        if len(routes) > cls.MAX_ROUTES:
            raise ValueError("route count exceeds the supported limit")

        cohort_ids = [
            str(route.get("cohort_id") or "").strip()
            for route in routes
            if isinstance(route, dict)
        ]
        if len(cohort_ids) != len(routes) or any(not value for value in cohort_ids):
            raise ValueError("every route requires cohort_id")
        if len(cohort_ids) != len(set(cohort_ids)):
            raise ValueError("route cohort_id values must be unique")

        built_routes: list[dict[str, Any]] = []
        vector_size: int | None = None
        for route in routes:
            label = str(route.get("label") or "").strip()
            utterances = route.get("utterances")
            threshold = cls._finite_number(route.get("threshold"), "threshold")
            safety_override = bool(route.get("safety_override", False))
            lexical_override_threshold = cls._finite_number(
                route.get("lexical_override_threshold", 1.0),
                "lexical_override_threshold",
                minimum=0.0,
            )
            if lexical_override_threshold <= 0:
                raise ValueError("lexical_override_threshold must be positive")
            lexical_signals = cls._lexical_signals(route.get("lexical_signals"))
            if not label:
                raise ValueError("every route requires label")
            if not isinstance(utterances, list) or not utterances:
                raise ValueError("every route requires curated utterances")
            if len(utterances) > cls.MAX_UTTERANCES_PER_ROUTE:
                raise ValueError("utterance count exceeds the supported limit")

            representatives: list[dict[str, Any]] = []
            for raw_utterance in utterances:
                utterance = str(raw_utterance or "").strip()
                if not utterance:
                    raise ValueError("route utterances must not be empty")
                vector = [float(value) for value in embed(utterance)]
                if not vector or not all(math.isfinite(value) for value in vector):
                    raise ValueError("embedding must contain finite values")
                if not any(value != 0 for value in vector):
                    raise ValueError("embedding must not be a zero vector")
                if vector_size is None:
                    vector_size = len(vector)
                elif len(vector) != vector_size:
                    raise ValueError("all embeddings must have equal dimensions")
                representatives.append(
                    {
                        "utterance_hash": hashlib.sha256(
                            utterance.encode("utf-8")
                        ).hexdigest(),
                        "embedding": vector,
                    }
                )

            built_routes.append(
                {
                    "cohort_id": str(route["cohort_id"]).strip(),
                    "label": label,
                    "threshold": threshold,
                    "safety_override": safety_override,
                    "lexical_override_threshold": lexical_override_threshold,
                    "lexical_signals": lexical_signals,
                    "centroid_embedding": cls._centroid(
                        [item["embedding"] for item in representatives]
                    ),
                    "representatives": representatives,
                }
            )

        return {
            "route_catalog_version": version,
            "encoder_model_id": encoder_model_id,
            "input_paths": input_paths,
            "top_k": cls._bounded_int(source.get("top_k", 5), 1, 50, "top_k"),
            "aggregation": cls._aggregation(source.get("aggregation")),
            "min_margin": cls._finite_number(
                source.get("min_margin", 0.05), "min_margin", minimum=0.0
            ),
            "routes": built_routes,
        }

    @staticmethod
    def _finite_number(
        value: Any,
        name: str,
        *,
        minimum: float | None = None,
    ) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a number") from exc
        if not math.isfinite(parsed) or (minimum is not None and parsed < minimum):
            raise ValueError(f"{name} is out of range")
        return parsed

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int, name: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer") from exc
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"{name} is out of range")
        return parsed

    @staticmethod
    def _aggregation(value: Any) -> str:
        aggregation = str(value or "centroid").strip().lower()
        if aggregation not in {"centroid", "mean", "max", "sum"}:
            raise ValueError("aggregation must be centroid, mean, max, or sum")
        return aggregation

    @classmethod
    def _input_paths(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > cls.MAX_INPUT_PATHS:
            raise ValueError("input_paths must be a bounded list")
        paths: list[str] = []
        for raw_path in value:
            path = str(raw_path or "").strip()
            if not path or any(not segment for segment in path.split(".")):
                raise ValueError("input_paths must contain valid dotted paths")
            if path not in paths:
                paths.append(path)
        return paths

    @classmethod
    def _lexical_signals(cls, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > cls.MAX_LEXICAL_SIGNALS_PER_ROUTE:
            raise ValueError("lexical_signals must be a bounded list")

        signals: list[dict[str, Any]] = []
        normalized_terms: set[str] = set()
        for raw_signal in value:
            if not isinstance(raw_signal, dict):
                raise ValueError("lexical signal must be an object")
            term = str(raw_signal.get("term") or "").strip()
            normalized_term = cls._normalize_lexical_text(term)
            if not normalized_term:
                raise ValueError("lexical signal term is required")
            if len(normalized_term) > cls.MAX_LEXICAL_SIGNAL_LENGTH:
                raise ValueError("lexical signal term exceeds the supported length")
            if normalized_term in normalized_terms:
                raise ValueError("lexical signal terms must be unique within a route")
            normalized_terms.add(normalized_term)
            weight = cls._finite_number(
                raw_signal.get("weight", 1.0),
                "lexical signal weight",
                minimum=0.0,
            )
            if weight <= 0:
                raise ValueError("lexical signal weight must be positive")
            signals.append({"term": term, "weight": weight})
        return signals

    @staticmethod
    def _normalize_lexical_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return " ".join(normalized.split())

    @staticmethod
    def _centroid(vectors: list[list[float]]) -> list[float]:
        centroid = [
            sum(values) / len(vectors)
            for values in zip(*vectors, strict=True)
        ]
        if not any(value != 0 for value in centroid):
            raise ValueError("route centroid must not be a zero vector")
        return centroid
