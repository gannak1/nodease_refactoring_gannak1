"""Workflow constraint-based experimental model routing strategy.

This module intentionally does not read semantic cohorts, intent, task type, or
domain keywords. It is an experiment boundary and is not wired into the active
deployment policy runtime.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Iterable, Mapping, Sequence

import tiktoken


STRATEGY_ID = "constraint_difficulty_v1"
SEMANTIC_STRATEGY_ID = "semantic_cohort_v1"
_TIER_RANK = {"low": 0, "balanced": 1, "high": 2}
_MAX_RAG_CHUNKS_PER_KB = 8
_UNBOUNDED_RAG_CHUNK_TOKEN_ESTIMATE = 4_000


@dataclass(frozen=True)
class ConstraintSignature:
    context_input_bucket: str
    rag_context_bucket: str
    output_contract: str
    schema_complexity: str
    downstream_strictness: str
    file_input: bool
    required_input_missing: bool
    required_capability_tier: str

    def as_metadata(self) -> dict[str, Any]:
        return {
            "context_input_bucket": self.context_input_bucket,
            "rag_context_bucket": self.rag_context_bucket,
            "output_contract": self.output_contract,
            "schema_complexity": self.schema_complexity,
            "downstream_strictness": self.downstream_strictness,
            "file_input": self.file_input,
            "required_input_missing": self.required_input_missing,
            "required_capability_tier": self.required_capability_tier,
        }


@dataclass(frozen=True)
class ConstraintDifficultyRequest:
    node_data: Mapping[str, Any]
    inputs: Mapping[str, Any]
    available_model_ids: set[str]
    downstream_requirements: Sequence[Mapping[str, Any]] = ()
    estimated_input_tokens: int | None = None
    actual_rag_context_tokens: int | None = None


@dataclass(frozen=True)
class ConstraintDifficultyFeatures:
    signature: ConstraintSignature
    estimated_input_tokens: int
    estimated_prompt_tokens: int
    estimated_rag_context_tokens: int
    reserved_output_tokens: int

    @property
    def required_context_tokens(self) -> int:
        return (
            self.estimated_input_tokens
            + self.estimated_prompt_tokens
            + self.estimated_rag_context_tokens
            + self.reserved_output_tokens
        )


@dataclass(frozen=True)
class ConstraintModelCandidate:
    model_id: str
    context_window: int
    input_price_1k: float | None
    output_price_1k: float | None
    capability_tier: str
    supports_strict_structured_output: bool = False

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model_id is required")
        if self.context_window <= 0:
            raise ValueError("context_window must be positive")
        if self.capability_tier not in _TIER_RANK:
            raise ValueError(f"Unknown capability tier: {self.capability_tier}")
        for price in (self.input_price_1k, self.output_price_1k):
            if price is not None and (not math.isfinite(price) or price < 0):
                raise ValueError("model prices must be finite non-negative numbers")

    def estimated_cost(self, features: ConstraintDifficultyFeatures) -> float:
        if self.input_price_1k is None or self.output_price_1k is None:
            return float("inf")
        input_tokens = (
            features.estimated_input_tokens
            + features.estimated_prompt_tokens
            + features.estimated_rag_context_tokens
        )
        return (input_tokens / 1_000) * self.input_price_1k + (
            features.reserved_output_tokens / 1_000
        ) * self.output_price_1k


@dataclass(frozen=True)
class ConstraintValidationEvidence:
    model_id: str
    signature: ConstraintSignature
    sample_count: int
    success_rate: float
    schema_pass_rate: float | None
    downstream_success_rate: float | None
    fallback_rate: float
    quality_score: float | None

    def __post_init__(self) -> None:
        if self.sample_count < 0:
            raise ValueError("sample_count must be non-negative")
        for name, value in (
            ("success_rate", self.success_rate),
            ("schema_pass_rate", self.schema_pass_rate),
            ("downstream_success_rate", self.downstream_success_rate),
            ("fallback_rate", self.fallback_rate),
            ("quality_score", self.quality_score),
        ):
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class ConstraintCandidateFilterResult:
    eligible: tuple[ConstraintModelCandidate, ...]
    excluded_by_model: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ConstraintDifficultyDecision:
    selected_model_id: str
    fallback_model_id: str | None
    matched_signature: ConstraintSignature
    excluded_models: dict[str, tuple[str, ...]]
    reason_code: str
    validation_candidate_ids: tuple[str, ...] = ()
    strategy_id: str = STRATEGY_ID
    judge_called: bool = False

    def as_trace_metadata(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "selected_model_id": self.selected_model_id,
            "fallback_model_id": self.fallback_model_id,
            "matched_constraint_signature": self.matched_signature.as_metadata(),
            "excluded_models": {
                model_id: list(reasons)
                for model_id, reasons in self.excluded_models.items()
            },
            "reason_code": self.reason_code,
            "judge_called": self.judge_called,
        }


class ConstraintRoutingUnavailableError(ValueError):
    pass


class ConstraintDifficultyFeatureExtractor:
    """Create a non-semantic signature from node and request constraints."""

    @classmethod
    def extract(
        cls, request: ConstraintDifficultyRequest
    ) -> ConstraintDifficultyFeatures:
        node_data = request.node_data
        input_tokens = (
            max(int(request.estimated_input_tokens), 0)
            if request.estimated_input_tokens is not None
            else cls._estimate_tokens(request.inputs)
        )
        prompt_tokens = sum(
            cls._estimate_tokens(node_data.get(key) or "")
            for key in ("system_prompt", "user_prompt", "assistant_prompt")
        )
        rag_enabled = bool(
            node_data.get("knowledgeBases") or node_data.get("knowledgeCollections")
        )
        rag_tokens = cls._rag_tokens(request, rag_enabled=rag_enabled)
        output_format = node_data.get("output_format")
        output_contract, schema = cls._output_contract(output_format)
        schema_complexity = cls._schema_complexity(schema)
        downstream_strictness = cls._downstream_strictness(
            request.downstream_requirements
        )
        file_input = cls._has_file_input(request.inputs)
        required_input_missing = cls._required_input_missing(
            node_data.get("referenced_variables"), request.inputs
        )
        context_bucket = cls._bucket(
            input_tokens + prompt_tokens,
            small_max=4_000,
            medium_max=16_000,
        )
        rag_bucket = (
            "none"
            if not rag_enabled and rag_tokens == 0
            else cls._bucket(rag_tokens, small_max=2_000, medium_max=8_000)
        )
        required_tier = cls._required_tier(
            context_bucket=context_bucket,
            rag_bucket=rag_bucket,
            output_contract=output_contract,
            schema_complexity=schema_complexity,
            downstream_strictness=downstream_strictness,
            file_input=file_input,
        )
        parameters = node_data.get("parameters")
        parameters = parameters if isinstance(parameters, Mapping) else {}
        reserved_output_tokens = cls._positive_int(parameters.get("max_tokens"), 512)

        return ConstraintDifficultyFeatures(
            signature=ConstraintSignature(
                context_input_bucket=context_bucket,
                rag_context_bucket=rag_bucket,
                output_contract=output_contract,
                schema_complexity=schema_complexity,
                downstream_strictness=downstream_strictness,
                file_input=file_input,
                required_input_missing=required_input_missing,
                required_capability_tier=required_tier,
            ),
            estimated_input_tokens=input_tokens,
            estimated_prompt_tokens=prompt_tokens,
            estimated_rag_context_tokens=rag_tokens,
            reserved_output_tokens=reserved_output_tokens,
        )

    @staticmethod
    def _estimate_tokens(value: Any) -> int:
        if value in (None, "", {}, []):
            return 0
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        try:
            # 모델 공급자마다 tokenizer가 다르므로 정확한 billing 수치가 아니라
            # 공통 preflight 상한에 가깝게 10% 여유를 둔 추정값을 사용한다.
            return max(1, math.ceil(len(_preflight_encoding().encode(text)) * 1.1))
        except Exception:
            # UTF-8 byte 기반 fallback은 한글을 글자 수/3으로 계산하던 기존
            # 휴리스틱보다 context 부족 위험을 보수적으로 방어한다.
            return max(1, math.ceil(len(text.encode("utf-8")) / 2))

    @classmethod
    def _rag_tokens(
        cls, request: ConstraintDifficultyRequest, *, rag_enabled: bool
    ) -> int:
        if request.actual_rag_context_tokens is not None:
            return max(int(request.actual_rag_context_tokens), 0)
        if not rag_enabled:
            return 0
        max_chars = request.node_data.get("retrievedContextMaxChars")
        if max_chars is None:
            top_k = min(
                cls._positive_int(request.node_data.get("topK"), 3),
                _MAX_RAG_CHUNKS_PER_KB,
            )
            knowledge_refs = len(request.node_data.get("knowledgeBases") or []) + len(
                request.node_data.get("knowledgeCollections") or []
            )
            return top_k * max(knowledge_refs, 1) * _UNBOUNDED_RAG_CHUNK_TOKEN_ESTIMATE
        # 실제 문서가 아직 검색되지 않은 preflight에서는 글자 수 제한을
        # 토큰 수로 낙관적으로 나누지 않고 상한 추정치로 취급한다.
        return cls._positive_int(max_chars, 6_000)

    @staticmethod
    def _output_contract(output_format: Any) -> tuple[str, Mapping[str, Any] | None]:
        if not isinstance(output_format, Mapping):
            return "text", None
        if str(output_format.get("type") or "text").lower() != "json":
            return "text", None
        schema = output_format.get("schema")
        schema = schema if isinstance(schema, Mapping) and schema else None
        if output_format.get("strict") is True and schema is not None:
            return "strict_json_schema", schema
        return "json", schema

    @classmethod
    def _schema_complexity(cls, schema: Mapping[str, Any] | None) -> str:
        if schema is None:
            return "none"
        field_count, max_depth, has_nested_array = cls._schema_shape(schema)
        if field_count <= 5 and max_depth <= 2 and not has_nested_array:
            return "simple"
        return "complex"

    @classmethod
    def _schema_shape(cls, value: Any, depth: int = 0) -> tuple[int, int, bool]:
        if not isinstance(value, Mapping):
            return 0, depth, False
        properties = value.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        field_count = len(properties)
        max_depth = depth
        nested_array = False
        for child in properties.values():
            if not isinstance(child, Mapping):
                continue
            child_type = str(child.get("type") or "")
            if child_type == "array":
                nested_array = True
                child = child.get("items")
            child_count, child_depth, child_array = cls._schema_shape(child, depth + 1)
            field_count += child_count
            max_depth = max(max_depth, child_depth)
            nested_array = nested_array or child_array
        return field_count, max_depth, nested_array

    @staticmethod
    def _downstream_strictness(
        requirements: Sequence[Mapping[str, Any]],
    ) -> str:
        if not requirements:
            return "none"
        required = [item for item in requirements if item.get("required") is True]
        typed_required = [item for item in required if item.get("type")]
        if len(typed_required) >= 1:
            return "strict"
        return "lenient"

    @classmethod
    def _required_input_missing(cls, variables: Any, inputs: Mapping[str, Any]) -> bool:
        if not isinstance(variables, Sequence) or isinstance(variables, (str, bytes)):
            return False
        for variable in variables:
            if not isinstance(variable, Mapping):
                continue
            selector = variable.get("value_selector")
            if not isinstance(selector, Sequence) or isinstance(selector, (str, bytes)):
                continue
            if not selector or cls._resolve_path(inputs, selector) is None:
                return True
        return False

    @staticmethod
    def _resolve_path(value: Any, path: Sequence[Any]) -> Any:
        current = value
        for key in path:
            if not isinstance(current, Mapping) or key not in current:
                return None
            current = current[key]
        return current

    @classmethod
    def _has_file_input(cls, value: Any) -> bool:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if str(key).casefold() in {
                    "file",
                    "files",
                    "file_id",
                    "filename",
                    "attachment",
                    "attachments",
                } and cls._has_meaningful_value(child):
                    return True
                if cls._has_file_input(child):
                    return True
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return any(cls._has_file_input(child) for child in value)
        return False

    @classmethod
    def _has_meaningful_value(cls, value: Any) -> bool:
        if value is None or value == "":
            return False
        if isinstance(value, Mapping):
            return any(cls._has_meaningful_value(child) for child in value.values())
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return any(cls._has_meaningful_value(child) for child in value)
        return True

    @staticmethod
    def _required_tier(
        *,
        context_bucket: str,
        rag_bucket: str,
        output_contract: str,
        schema_complexity: str,
        downstream_strictness: str,
        file_input: bool,
    ) -> str:
        if rag_bucket == "large":
            return "high"
        if schema_complexity == "complex" and downstream_strictness == "strict":
            return "high"
        if context_bucket == "large" and (file_input or rag_bucket != "none"):
            return "high"
        if (
            context_bucket == "large"
            or rag_bucket == "medium"
            or schema_complexity == "complex"
            or downstream_strictness == "strict"
            or output_contract == "strict_json_schema"
            or file_input
        ):
            return "balanced"
        return "low"

    @staticmethod
    def _bucket(value: int, *, small_max: int, medium_max: int) -> str:
        if value <= small_max:
            return "small"
        if value <= medium_max:
            return "medium"
        return "large"

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default


class ConstraintDifficultyCandidateFilter:
    @staticmethod
    def filter(
        *,
        candidates: Iterable[ConstraintModelCandidate],
        request: ConstraintDifficultyRequest,
        features: ConstraintDifficultyFeatures,
    ) -> ConstraintCandidateFilterResult:
        eligible: list[ConstraintModelCandidate] = []
        excluded: dict[str, tuple[str, ...]] = {}
        available = {str(model_id) for model_id in request.available_model_ids}
        for candidate in candidates:
            reasons: list[str] = []
            if candidate.model_id not in available:
                reasons.append("model_not_available")
            if candidate.context_window < features.required_context_tokens:
                reasons.append("context_window_insufficient")
            if (
                features.signature.output_contract == "strict_json_schema"
                and not candidate.supports_strict_structured_output
            ):
                reasons.append("strict_structured_output_unsupported")
            if features.signature.required_input_missing:
                reasons.append("required_input_missing")
            if reasons:
                excluded[candidate.model_id] = tuple(reasons)
            else:
                eligible.append(candidate)
        return ConstraintCandidateFilterResult(tuple(eligible), excluded)


class ConstraintDifficultyRouter:
    MIN_VALIDATION_SAMPLES = 3
    SUCCESS_RATE_MIN = 0.98
    SCHEMA_PASS_RATE_MIN = 0.98
    DOWNSTREAM_SUCCESS_RATE_MIN = 0.99
    FALLBACK_RATE_MAX = 0.02
    QUALITY_SCORE_MIN = 0.85

    def route(
        self,
        *,
        request: ConstraintDifficultyRequest,
        candidates: Iterable[ConstraintModelCandidate],
        evidence: Iterable[ConstraintValidationEvidence],
        safe_default_model_id: str,
    ) -> ConstraintDifficultyDecision:
        features = ConstraintDifficultyFeatureExtractor.extract(request)
        filter_result = ConstraintDifficultyCandidateFilter.filter(
            candidates=candidates,
            request=request,
            features=features,
        )
        eligible = list(filter_result.eligible)
        if not eligible:
            raise ConstraintRoutingUnavailableError(
                "No model satisfies execution-subject and structural constraints."
            )

        tier_floor = _TIER_RANK[features.signature.required_capability_tier]
        structurally_suitable = [
            item for item in eligible if _TIER_RANK[item.capability_tier] >= tier_floor
        ]
        if not structurally_suitable:
            # capability tier는 공식 capability Hard Gate가 아니라 보수적 선택
            # 기준이다. 요구 tier가 catalog에 없으면 실행 가능한 후보 중 가장
            # 강한 tier를 사용하되 저가 모델로 조용히 하향하지 않는다.
            highest_available_tier = max(
                _TIER_RANK[item.capability_tier] for item in eligible
            )
            structurally_suitable = [
                item
                for item in eligible
                if _TIER_RANK[item.capability_tier] == highest_available_tier
            ]

        configured_default = next(
            (
                item
                for item in structurally_suitable
                if item.model_id == safe_default_model_id
            ),
            None,
        )
        safest_tier = max(
            _TIER_RANK[item.capability_tier] for item in structurally_suitable
        )
        safest_available = [
            item
            for item in structurally_suitable
            if _TIER_RANK[item.capability_tier] == safest_tier
        ]
        default = configured_default or min(
            safest_available,
            key=lambda item: (
                item.estimated_cost(features),
                item.model_id,
            ),
        )
        evidence_by_model = {
            item.model_id: item
            for item in evidence
            if item.signature == features.signature
        }
        validated = [
            item
            for item in structurally_suitable
            if self._passes_quality_gate(
                evidence_by_model.get(item.model_id),
                signature=features.signature,
            )
            and math.isfinite(item.estimated_cost(features))
        ]
        validated.sort(key=lambda item: item.estimated_cost(features))

        validation_candidates = tuple(
            item.model_id
            for item in sorted(
                structurally_suitable, key=lambda item: item.estimated_cost(features)
            )
            if item.model_id != default.model_id
            and item.estimated_cost(features) < default.estimated_cost(features)
        )
        if validated:
            selected = validated[0]
            fallback = self._fallback_candidate(
                selected=selected,
                configured_default=configured_default,
                structurally_suitable=structurally_suitable,
                features=features,
            )
            reason_code = (
                "validated_high_constraint_model_selected"
                if features.signature.required_capability_tier == "high"
                else "validated_economic_model_selected"
            )
        else:
            selected = default
            fallback = None
            reason_code = (
                "freeform_quality_evidence_insufficient"
                if features.signature.output_contract == "text"
                else "validated_evidence_insufficient_safe_default"
            )

        return ConstraintDifficultyDecision(
            selected_model_id=selected.model_id,
            fallback_model_id=fallback.model_id if fallback is not None else None,
            matched_signature=features.signature,
            excluded_models=filter_result.excluded_by_model,
            reason_code=reason_code,
            validation_candidate_ids=validation_candidates,
        )

    @staticmethod
    def _fallback_candidate(
        *,
        selected: ConstraintModelCandidate,
        configured_default: ConstraintModelCandidate | None,
        structurally_suitable: Sequence[ConstraintModelCandidate],
        features: ConstraintDifficultyFeatures,
    ) -> ConstraintModelCandidate | None:
        if (
            configured_default is not None
            and configured_default.model_id != selected.model_id
        ):
            return configured_default
        alternatives = [
            item for item in structurally_suitable if item.model_id != selected.model_id
        ]
        if not alternatives:
            return None
        return min(
            alternatives,
            key=lambda item: (
                -_TIER_RANK[item.capability_tier],
                item.estimated_cost(features),
                item.model_id,
            ),
        )

    def _passes_quality_gate(
        self,
        evidence: ConstraintValidationEvidence | None,
        *,
        signature: ConstraintSignature,
    ) -> bool:
        if evidence is None or evidence.sample_count < self.MIN_VALIDATION_SAMPLES:
            return False
        if evidence.success_rate < self.SUCCESS_RATE_MIN:
            return False
        if signature.output_contract != "text":
            if (
                evidence.schema_pass_rate is None
                or evidence.schema_pass_rate < self.SCHEMA_PASS_RATE_MIN
            ):
                return False
        if signature.downstream_strictness == "strict":
            if (
                evidence.downstream_success_rate is None
                or evidence.downstream_success_rate < self.DOWNSTREAM_SUCCESS_RATE_MIN
            ):
                return False
        if evidence.fallback_rate > self.FALLBACK_RATE_MAX:
            return False
        if signature.output_contract == "text":
            return (
                evidence.quality_score is not None
                and evidence.quality_score >= self.QUALITY_SCORE_MIN
            )
        return evidence.quality_score is None or evidence.quality_score >= 0.8


class ConstraintRoutingStrategyDispatcher:
    """Thin dispatch used by experiments; active runtime wiring is unchanged."""

    def __init__(
        self,
        *,
        semantic_strategy: Callable[..., Any],
        constraint_strategy: ConstraintDifficultyRouter,
    ) -> None:
        self._semantic_strategy = semantic_strategy
        self._constraint_strategy = constraint_strategy

    def dispatch(self, strategy_id: str, **kwargs: Any) -> Any:
        if strategy_id == SEMANTIC_STRATEGY_ID:
            return self._semantic_strategy(**kwargs)
        if strategy_id == STRATEGY_ID:
            return self._constraint_strategy.route(**kwargs)
        raise ValueError(f"Unknown model routing strategy: {strategy_id}")


@lru_cache(maxsize=1)
def _preflight_encoding():
    return tiktoken.get_encoding("o200k_base")
