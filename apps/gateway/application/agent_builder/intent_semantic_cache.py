from __future__ import annotations

import math

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedIntentPlanV1,
)
from apps.gateway.application.agent_builder.intent_rehydration_registry import (
    RequestIntentSummaryProjector,
)


SEMANTIC_QUERY_PROJECTION_VERSION = "semantic-query-projection-v1"


class SemanticQueryProjectionV1:
    """One-request derived-sensitive semantic input that cannot be serialized."""

    __slots__ = ("_text", "_version")
    __hash__ = None

    def __init__(self, *, text: str, version: str) -> None:
        if type(text) is not str or not 1 <= len(text) <= 240:
            raise ValueError("invalid semantic query projection")
        if version != SEMANTIC_QUERY_PROJECTION_VERSION:
            raise ValueError("invalid semantic query projection version")
        object.__setattr__(self, "_text", text)
        object.__setattr__(self, "_version", version)

    @property
    def text(self) -> str:
        return self._text

    @property
    def version(self) -> str:
        return self._version

    def __setattr__(self, _name, _value) -> None:
        raise TypeError("semantic query projection is immutable")

    def __repr__(self) -> str:
        return "<SemanticQueryProjectionV1 redacted>"

    def __getstate__(self):
        raise TypeError("semantic query projection is not serializable")

    def __reduce_ex__(self, _protocol):
        raise TypeError("semantic query projection is not serializable")


class SemanticQueryProjectionBuilder:
    def __init__(self, projector: RequestIntentSummaryProjector | None = None) -> None:
        self._projector = projector or RequestIntentSummaryProjector()

    def build(self, full_safe_message: str) -> SemanticQueryProjectionV1 | None:
        text = self._projector.project_semantic(full_safe_message)
        if text is None:
            return None
        return SemanticQueryProjectionV1(
            text=text,
            version=SEMANTIC_QUERY_PROJECTION_VERSION,
        )


class SemanticCachePolicy:
    __slots__ = (
        "assist_enabled",
        "planner_free_serving_enabled",
        "embedding_profile_version",
        "embedding_model_version",
        "embedding_dimension",
        "top_k",
        "rehydration_contract_version",
    )

    def __init__(
        self,
        *,
        assist_enabled: bool,
        planner_free_serving_enabled: bool,
        embedding_profile_version: str,
        embedding_model_version: str,
        embedding_dimension: int,
        top_k: int,
        rehydration_contract_version: str,
    ) -> None:
        if (
            type(assist_enabled) is not bool
            or type(planner_free_serving_enabled) is not bool
        ):
            raise TypeError("invalid semantic feature flags")
        if planner_free_serving_enabled and not assist_enabled:
            raise ValueError("semantic serving requires candidate assist")
        for value in (
            embedding_profile_version,
            embedding_model_version,
            rehydration_contract_version,
        ):
            if type(value) is not str or not 1 <= len(value) <= 128:
                raise ValueError("invalid semantic contract version")
        if type(embedding_dimension) is not int or not 1 <= embedding_dimension <= 4096:
            raise ValueError("invalid semantic embedding dimension")
        if type(top_k) is not int or not 1 <= top_k <= 20:
            raise ValueError("invalid semantic top-k")
        object.__setattr__(self, "assist_enabled", assist_enabled)
        object.__setattr__(
            self,
            "planner_free_serving_enabled",
            planner_free_serving_enabled,
        )
        object.__setattr__(self, "embedding_profile_version", embedding_profile_version)
        object.__setattr__(self, "embedding_model_version", embedding_model_version)
        object.__setattr__(self, "embedding_dimension", embedding_dimension)
        object.__setattr__(self, "top_k", top_k)
        object.__setattr__(
            self,
            "rehydration_contract_version",
            rehydration_contract_version,
        )

    def __setattr__(self, _name, _value) -> None:
        raise TypeError("semantic policy is immutable")


class SemanticEmbedding:
    __slots__ = ("_values",)
    __hash__ = None

    def __init__(self, *, values: tuple[float, ...]) -> None:
        if (
            type(values) is not tuple
            or not values
            or any(
                type(value) is not float or not math.isfinite(value) for value in values
            )
        ):
            raise ValueError("invalid semantic embedding")
        object.__setattr__(self, "_values", values)

    @property
    def values(self) -> tuple[float, ...]:
        return self._values

    def __setattr__(self, _name, _value) -> None:
        raise TypeError("semantic embedding is immutable")

    def __repr__(self) -> str:
        return "<SemanticEmbedding redacted>"

    def __getstate__(self):
        raise TypeError("semantic embedding is not serializable")

    def __reduce_ex__(self, _protocol):
        raise TypeError("semantic embedding is not serializable")


class SemanticIntentPlanCandidate:
    __slots__ = ("plan",)
    __hash__ = None

    def __init__(self, *, plan: CachedIntentPlanV1) -> None:
        if not isinstance(plan, CachedIntentPlanV1):
            raise TypeError("invalid semantic intent-plan candidate")
        object.__setattr__(self, "plan", plan)

    def __setattr__(self, _name, _value) -> None:
        raise TypeError("semantic candidate is immutable")

    def __repr__(self) -> str:
        return "<SemanticIntentPlanCandidate redacted>"


class SemanticVerificationResult:
    __slots__ = ("status",)

    def __init__(
        self,
        *,
        status: str,
    ) -> None:
        if status not in {
            "verified",
            "rejected",
            "uncertain",
            "unavailable",
            "error",
        }:
            raise ValueError("invalid semantic verification result")
        object.__setattr__(self, "status", status)

    def __setattr__(self, _name, _value) -> None:
        raise TypeError("semantic verification result is immutable")

    def __repr__(self) -> str:
        return "<SemanticVerificationResult redacted>"

    def __getstate__(self):
        raise TypeError("semantic verification result is not serializable")

    def __reduce_ex__(self, _protocol):
        raise TypeError("semantic verification result is not serializable")


class SemanticExternalCallBinding:
    """Opaque request-local authority and usage binding for one provider purpose."""

    __slots__ = ("_purpose",)

    def __init__(self, *, purpose: str) -> None:
        if purpose not in {"query_embedding", "semantic_verification"}:
            raise ValueError("invalid semantic external-call binding purpose")
        object.__setattr__(self, "_purpose", purpose)

    @property
    def purpose(self) -> str:
        return self._purpose

    def __setattr__(self, _name, _value) -> None:
        raise TypeError("semantic external-call binding is immutable")

    def __repr__(self) -> str:
        return "<SemanticExternalCallBinding redacted>"

    def __getstate__(self):
        raise TypeError("semantic external-call binding is not serializable")

    def __reduce_ex__(self, _protocol):
        raise TypeError("semantic external-call binding is not serializable")


class SemanticExternalCallAdmissionResult:
    __slots__ = ("status", "binding")

    def __init__(
        self,
        *,
        status: str,
        binding: SemanticExternalCallBinding | None = None,
    ) -> None:
        if status not in {"admitted", "denied", "unavailable"}:
            raise ValueError("invalid semantic external-call admission result")
        if status == "admitted":
            if not isinstance(binding, SemanticExternalCallBinding):
                raise TypeError("admitted semantic external call requires a binding")
        elif binding is not None:
            raise ValueError("non-admitted semantic external call forbids a binding")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "binding", binding)

    def __setattr__(self, _name, _value) -> None:
        raise TypeError("semantic external-call admission result is immutable")

    def __repr__(self) -> str:
        return "<SemanticExternalCallAdmissionResult redacted>"

    def __getstate__(self):
        raise TypeError("semantic external-call admission result is not serializable")

    def __reduce_ex__(self, _protocol):
        raise TypeError("semantic external-call admission result is not serializable")


__all__ = [
    "SEMANTIC_QUERY_PROJECTION_VERSION",
    "SemanticCachePolicy",
    "SemanticEmbedding",
    "SemanticExternalCallBinding",
    "SemanticExternalCallAdmissionResult",
    "SemanticIntentPlanCandidate",
    "SemanticQueryProjectionBuilder",
    "SemanticQueryProjectionV1",
    "SemanticVerificationResult",
]
