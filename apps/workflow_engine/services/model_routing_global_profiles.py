"""전역 모델 profile과 노드별 운영 성적을 결합해 후보 모델을 점수화한다.

난이도 분류기는 이 모듈의 입력을 만든다. 이 모듈은 분류기를 호출하거나
특정 업무 키워드를 해석하지 않는다. 따라서 분류기 구현과 독립적으로 모든
사용 가능한 모델을 같은 기준으로 비교할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from sqlalchemy.orm import Session

from apps.shared.db.models.llm import LLMModel
from apps.shared.db.models.model_routing_policy import (
    LLMModelRoutingGlobalProfile,
)
from apps.workflow_engine.services.model_router import (
    ModelCandidate,
    ModelPerformance,
    NodeRunProfile,
)
from apps.workflow_engine.services.model_routing_constraint_difficulty import (
    ConstraintModelCandidate,
)


DIFFICULTY_LEVELS = ("economy", "balanced", "advanced")
INPUT_PROFILES = ("short", "medium", "long", "unknown")


@dataclass(frozen=True)
class ModelRoutingDifficultyDistribution:
    """난이도 분류기가 반환하는 경제형·균형형·고성능형 확률."""

    economy: float = 0.0
    balanced: float = 0.0
    advanced: float = 0.0

    def __post_init__(self) -> None:
        values = self.as_mapping()
        if any(not math.isfinite(value) or value < 0 for value in values.values()):
            raise ValueError("difficulty probabilities must be finite non-negative")
        if sum(values.values()) <= 0:
            raise ValueError("at least one difficulty probability is required")

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "ModelRoutingDifficultyDistribution":
        return cls(
            economy=_float(value.get("economy"), default=0.0),
            balanced=_float(value.get("balanced"), default=0.0),
            advanced=_float(value.get("advanced"), default=0.0),
        )

    def as_mapping(self) -> dict[str, float]:
        return {
            "economy": self.economy,
            "balanced": self.balanced,
            "advanced": self.advanced,
        }

    def normalized(self) -> dict[str, float]:
        values = self.as_mapping()
        total = sum(values.values())
        return {key: value / total for key, value in values.items()}

    @property
    def dominant_level(self) -> str:
        return max(self.normalized().items(), key=lambda item: (item[1], item[0]))[0]


@dataclass(frozen=True)
class ModelRoutingComplexityEstimate:
    """요청별 연속 복잡도 점수와 예측 오차 범위."""

    score: float
    uncertainty: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.score) or not 0 <= self.score <= 100:
            raise ValueError("complexity score must be between 0 and 100")
        if not math.isfinite(self.uncertainty) or self.uncertainty < 0:
            raise ValueError("complexity uncertainty must be non-negative")


@dataclass(frozen=True)
class GlobalModelProfile:
    """한 모델의 전역 사전 지식 profile.

    quality 값은 모델 자체의 절대 순위를 뜻하지 않는다. 입력 난이도별로 해당
    모델이 성공할 것으로 예상하는 초기값이며, 실제 노드 운영 성적이 생기면
    아래 scorer에서 그 성적으로 보정된다.
    """

    model_id: str
    quality_by_difficulty: Mapping[str, float]
    uncertainty_by_difficulty: Mapping[str, float]
    expected_latency_ms_by_input_profile: Mapping[str, int]
    fallback_rate: float
    prior_strength: float
    source: str
    profile_version: str
    capability_tier: str = "balanced"

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model_id is required")
        if self.capability_tier not in {"low", "balanced", "high"}:
            raise ValueError("capability_tier must be low, balanced, or high")
        if not math.isfinite(self.fallback_rate) or not 0 <= self.fallback_rate <= 1:
            raise ValueError("fallback_rate must be between 0 and 1")
        if not math.isfinite(self.prior_strength) or self.prior_strength <= 0:
            raise ValueError("prior_strength must be positive")
        for difficulty in DIFFICULTY_LEVELS:
            quality = _float(self.quality_by_difficulty.get(difficulty), default=-1)
            uncertainty = _float(
                self.uncertainty_by_difficulty.get(difficulty), default=-1
            )
            if not 0 <= quality <= 1:
                raise ValueError(f"{difficulty} quality must be between 0 and 1")
            if not 0 <= uncertainty <= 1:
                raise ValueError(f"{difficulty} uncertainty must be between 0 and 1")
        if not any(
            _int(value, default=0) > 0
            for value in self.expected_latency_ms_by_input_profile.values()
        ):
            raise ValueError("at least one expected latency value is required")

    def expected_quality(
        self, difficulty: ModelRoutingDifficultyDistribution
    ) -> float:
        distribution = difficulty.normalized()
        return sum(
            distribution[level]
            * _float(self.quality_by_difficulty.get(level), default=0.0)
            for level in DIFFICULTY_LEVELS
        )

    def expected_uncertainty(
        self, difficulty: ModelRoutingDifficultyDistribution
    ) -> float:
        distribution = difficulty.normalized()
        return sum(
            distribution[level]
            * _float(self.uncertainty_by_difficulty.get(level), default=0.0)
            for level in DIFFICULTY_LEVELS
        )

    def expected_quality_at_complexity(self, complexity: ModelRoutingComplexityEstimate) -> float:
        return self._interpolate_complexity_curve(
            self.quality_by_difficulty,
            complexity.score,
        )

    def expected_uncertainty_at_complexity(
        self,
        complexity: ModelRoutingComplexityEstimate,
    ) -> float:
        return self._interpolate_complexity_curve(
            self.uncertainty_by_difficulty,
            complexity.score,
        )

    @staticmethod
    def _interpolate_complexity_curve(
        values: Mapping[str, float],
        score: float,
    ) -> float:
        low = _float(values.get("economy"), default=0.0)
        middle = _float(values.get("balanced"), default=low)
        high = _float(values.get("advanced"), default=middle)
        if score <= 50:
            return low + (middle - low) * (score / 50.0)
        return middle + (high - middle) * ((score - 50.0) / 50.0)

    def expected_latency_ms(self, input_profile: str) -> int:
        normalized = str(input_profile or "unknown").strip().lower()
        for key in (normalized, "unknown", "medium", "short", "long"):
            value = _int(self.expected_latency_ms_by_input_profile.get(key), default=0)
            if value > 0:
                return value
        return 1_000


@dataclass(frozen=True)
class ModelRoutingCandidateScore:
    """전역 profile과 노드 운영 성적을 합친 후보 점수."""

    model_id: str
    posterior_quality_mean: float
    quality_lower_bound: float
    quality_uncertainty: float
    expected_cost_usd: float
    expected_latency_ms: int
    expected_fallback_rate: float
    utility_score: float
    selection_eligible: bool
    effective_operational_samples: int
    profile_source: str
    profile_version: str


@dataclass(frozen=True)
class ModelRoutingProfileScoreResult:
    selected_model_id: str
    fallback_model_id: str | None
    ranked_candidates: tuple[ModelRoutingCandidateScore, ...]
    quality_floor: float
    dominant_difficulty: str
    complexity_score: float | None = None

    @property
    def by_model(self) -> dict[str, ModelRoutingCandidateScore]:
        return {item.model_id: item for item in self.ranked_candidates}


class ModelRoutingGlobalProfileScorer:
    """난이도 분류 결과에 대해 모든 사용 가능한 모델을 비교한다.

    가격은 `LLMModel` catalog에서, 품질·지연·fallback의 사전 지식은 global
    profile에서, 실제 운영 성적은 policy별 performance aggregate에서 읽는다.
    노드 성적을 global profile에 다시 쓰지 않으므로 한 노드의 특수한 실패가
    다른 workflow의 기본 평가를 오염시키지 않는다.
    """

    _QUALITY_FLOOR = {
        "economy": 0.66,
        "balanced": 0.78,
        "advanced": 0.86,
    }
    _LOWER_CONFIDENCE_BETA = 1.28
    _COST_WEIGHT = 0.14
    _LATENCY_WEIGHT = 0.05
    _FALLBACK_WEIGHT = 0.08
    _MAX_QUALITY_HEADROOM_UTILITY = 0.02

    @classmethod
    def rank(
        cls,
        *,
        candidates: Iterable[ConstraintModelCandidate],
        global_profiles: Mapping[str, GlobalModelProfile],
        difficulty: ModelRoutingDifficultyDistribution,
        complexity: ModelRoutingComplexityEstimate | None = None,
        input_profile: str,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        default_model_id: str,
        node_profile: NodeRunProfile | None = None,
    ) -> ModelRoutingProfileScoreResult:
        candidate_rows = tuple(candidates)
        if not candidate_rows:
            raise ValueError("at least one routable candidate is required")
        normalized_input_profile = str(input_profile or "unknown").strip().lower()
        model_ids = {item.model_id for item in candidate_rows}
        normalized_default = cls._normalize_model_id(default_model_id)
        if normalized_default not in model_ids:
            normalized_default = min(
                candidate_rows,
                key=lambda item: (cls._catalog_cost(item, estimated_input_tokens, estimated_output_tokens), item.model_id),
            ).model_id

        scores = [
            cls._score_candidate(
                candidate=candidate,
                profile=global_profiles.get(candidate.model_id)
                or CatalogGlobalProfileDefaults.for_candidate(candidate),
                difficulty=difficulty,
                complexity=complexity,
                input_profile=normalized_input_profile,
                estimated_input_tokens=estimated_input_tokens,
                estimated_output_tokens=estimated_output_tokens,
                performance=cls._performance_for(
                    node_profile,
                    model_id=candidate.model_id,
                    input_profile=normalized_input_profile,
                ),
            )
            for candidate in candidate_rows
        ]
        quality_floor = (
            cls._quality_floor_for_complexity(complexity)
            if complexity is not None
            else cls._QUALITY_FLOOR[difficulty.dominant_level]
        )
        eligible = [item for item in scores if item.quality_lower_bound >= quality_floor]
        scored = cls._apply_utility(
            scores,
            eligible=eligible,
            quality_floor=quality_floor,
        )
        eligible = [item for item in scored if item.selection_eligible]
        if eligible:
            selected = max(eligible, key=lambda item: (item.utility_score, item.model_id))
        else:
            selected = next(item for item in scored if item.model_id == normalized_default)

        ranked = tuple(
            sorted(
                scored,
                key=lambda item: (
                    item.selection_eligible is False,
                    -item.utility_score,
                    item.model_id,
                ),
            )
        )
        fallback = (
            normalized_default if normalized_default != selected.model_id else None
        )
        if fallback is None:
            alternate = next(
                (item for item in ranked if item.model_id != selected.model_id),
                None,
            )
            fallback = alternate.model_id if alternate is not None else None
        return ModelRoutingProfileScoreResult(
            selected_model_id=selected.model_id,
            fallback_model_id=fallback,
            ranked_candidates=ranked,
            quality_floor=quality_floor,
            dominant_difficulty=difficulty.dominant_level,
            complexity_score=complexity.score if complexity is not None else None,
        )

    @classmethod
    def rank_catalog_candidates(
        cls,
        *,
        candidates: Iterable[ModelCandidate],
        global_profiles: Mapping[str, GlobalModelProfile],
        difficulty: ModelRoutingDifficultyDistribution,
        complexity: ModelRoutingComplexityEstimate | None = None,
        input_profile: str,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        default_model_id: str,
        node_profile: NodeRunProfile | None = None,
    ) -> ModelRoutingProfileScoreResult:
        """기존 catalog 후보 타입을 점수화 API에 연결한다.

        Bootstrap 작성자는 `ModelCandidate`를 쓰고, 제약 기반 router는
        `ConstraintModelCandidate`를 쓴다. 둘의 공통 필드만 여기에서 한 번
        변환해 중복된 가격 정렬 로직이 생기지 않게 한다.
        """
        converted: list[ConstraintModelCandidate] = []
        normalized_profiles = {
            cls._normalize_model_id(model_id): profile
            for model_id, profile in global_profiles.items()
        }
        for candidate in candidates:
            model_id = cls._normalize_model_id(candidate.model_id)
            profile = normalized_profiles.get(model_id)
            converted.append(
                ConstraintModelCandidate(
                    model_id=model_id,
                    context_window=1,
                    input_price_1k=candidate.input_price_1k,
                    output_price_1k=candidate.output_price_1k,
                    capability_tier=(
                        profile.capability_tier if profile else "balanced"
                    ),
                    supports_strict_structured_output=True,
                )
            )
        return cls.rank(
            candidates=converted,
            global_profiles=normalized_profiles,
            difficulty=difficulty,
            complexity=complexity,
            input_profile=input_profile,
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            default_model_id=cls._normalize_model_id(default_model_id),
            node_profile=node_profile,
        )

    @classmethod
    def catalog_snapshot(
        cls,
        *,
        candidates: Iterable[ModelCandidate],
        global_profiles: Mapping[str, GlobalModelProfile],
    ) -> dict[str, Any]:
        """배포 정책에 넣을 전역 후보 profile의 안전한 snapshot을 만든다.

        runtime은 catalog DB를 다시 읽지 않는다. 정책 생성 시점에 허용된 모델과
        profile만 snapshot으로 보관하고, 실행 시에는 execution subject가 지금도
        사용할 수 있는 모델인지 한 번 더 제한한다. 가격과 routing profile은
        credential이나 원문 입력을 포함하지 않는 공개 가능한 metadata다.
        """
        normalized_profiles = {
            cls._normalize_model_id(model_id): profile
            for model_id, profile in global_profiles.items()
        }
        candidate_rows: list[dict[str, Any]] = []
        profile_rows: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        for candidate in candidates:
            model_id = cls._normalize_model_id(candidate.model_id)
            if not model_id or model_id in seen:
                continue
            profile = normalized_profiles.get(model_id)
            if profile is None:
                # 새 정책은 모든 후보에 profile을 반드시 남긴다. 누락 후보는
                # historical policy의 fallback 경로로 넘겨 실행 중 이름 기반으로
                # 임시 profile을 만들지 않는다.
                continue
            seen.add(model_id)
            candidate_rows.append(
                {
                    "model_id": model_id,
                    "display_name": str(candidate.display_name or model_id),
                    "input_price_1k": candidate.input_price_1k,
                    "output_price_1k": candidate.output_price_1k,
                }
            )
            profile_rows[model_id] = cls._profile_snapshot(profile)
        return {
            "version": "global-model-profile-catalog-v1",
            "candidates": candidate_rows,
            "profiles": profile_rows,
        }

    @classmethod
    def rank_policy_catalog(
        cls,
        *,
        catalog_snapshot: Any,
        available_model_ids: Iterable[str] | None,
        difficulty: ModelRoutingDifficultyDistribution,
        complexity: ModelRoutingComplexityEstimate | None = None,
        input_profile: str,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        default_model_id: str,
        node_profile: NodeRunProfile | None = None,
    ) -> ModelRoutingProfileScoreResult | None:
        """저장된 policy snapshot의 모든 현재 사용 가능 후보를 다시 점수화한다.

        snapshot이 없거나 손상된 과거 policy는 ``None``을 반환한다. 호출자는
        기존 difficulty_models 경로로 호환성 fallback을 제공한다.
        """
        if not isinstance(catalog_snapshot, Mapping):
            return None
        raw_candidates = catalog_snapshot.get("candidates")
        raw_profiles = catalog_snapshot.get("profiles")
        if not isinstance(raw_candidates, list) or not isinstance(raw_profiles, Mapping):
            return None
        allowed = (
            {cls._normalize_model_id(model_id) for model_id in available_model_ids}
            if available_model_ids is not None
            else None
        )
        candidates: list[ModelCandidate] = []
        profiles: dict[str, GlobalModelProfile] = {}
        seen: set[str] = set()
        for raw_candidate in raw_candidates:
            if not isinstance(raw_candidate, Mapping):
                continue
            model_id = cls._normalize_model_id(raw_candidate.get("model_id"))
            if not model_id or model_id in seen:
                continue
            if allowed is not None and model_id not in allowed:
                continue
            raw_profile = raw_profiles.get(model_id)
            profile = cls._profile_from_snapshot(model_id, raw_profile)
            if profile is None:
                continue
            seen.add(model_id)
            candidates.append(
                ModelCandidate(
                    model_id=model_id,
                    display_name=str(raw_candidate.get("display_name") or model_id),
                    input_price_1k=_optional_non_negative_float(
                        raw_candidate.get("input_price_1k")
                    ),
                    output_price_1k=_optional_non_negative_float(
                        raw_candidate.get("output_price_1k")
                    ),
                )
            )
            profiles[model_id] = profile
        if not candidates:
            return None
        try:
            return cls.rank_catalog_candidates(
                candidates=candidates,
                global_profiles=profiles,
                difficulty=difficulty,
                complexity=complexity,
                input_profile=input_profile,
                estimated_input_tokens=estimated_input_tokens,
                estimated_output_tokens=estimated_output_tokens,
                default_model_id=default_model_id,
                node_profile=node_profile,
            )
        except ValueError:
            return None

    @staticmethod
    def _profile_snapshot(profile: GlobalModelProfile) -> dict[str, Any]:
        return {
            "quality_by_difficulty": dict(profile.quality_by_difficulty),
            "uncertainty_by_difficulty": dict(profile.uncertainty_by_difficulty),
            "expected_latency_ms_by_input_profile": dict(
                profile.expected_latency_ms_by_input_profile
            ),
            "fallback_rate": profile.fallback_rate,
            "prior_strength": profile.prior_strength,
            "source": profile.source,
            "profile_version": profile.profile_version,
            "capability_tier": profile.capability_tier,
        }

    @staticmethod
    def _profile_from_snapshot(
        model_id: str,
        value: Any,
    ) -> GlobalModelProfile | None:
        if not isinstance(value, Mapping):
            return None
        try:
            return GlobalModelProfile(
                model_id=model_id,
                quality_by_difficulty=(
                    value.get("quality_by_difficulty")
                    if isinstance(value.get("quality_by_difficulty"), Mapping)
                    else {}
                ),
                uncertainty_by_difficulty=(
                    value.get("uncertainty_by_difficulty")
                    if isinstance(value.get("uncertainty_by_difficulty"), Mapping)
                    else {}
                ),
                expected_latency_ms_by_input_profile=(
                    value.get("expected_latency_ms_by_input_profile")
                    if isinstance(
                        value.get("expected_latency_ms_by_input_profile"), Mapping
                    )
                    else {}
                ),
                fallback_rate=_float(value.get("fallback_rate"), default=-1.0),
                prior_strength=_float(value.get("prior_strength"), default=0.0),
                source=str(value.get("source") or "global_profile"),
                profile_version=str(value.get("profile_version") or "unknown"),
                capability_tier=str(value.get("capability_tier") or "balanced"),
            )
        except ValueError:
            return None

    @classmethod
    def _score_candidate(
        cls,
        *,
        candidate: ConstraintModelCandidate,
        profile: GlobalModelProfile,
        difficulty: ModelRoutingDifficultyDistribution,
        complexity: ModelRoutingComplexityEstimate | None,
        input_profile: str,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        performance: ModelPerformance | None,
    ) -> ModelRoutingCandidateScore:
        prior_quality = (
            profile.expected_quality_at_complexity(complexity)
            if complexity is not None
            else profile.expected_quality(difficulty)
        )
        prior_uncertainty = (
            profile.expected_uncertainty_at_complexity(complexity)
            if complexity is not None
            else profile.expected_uncertainty(difficulty)
        )
        prior_strength = profile.prior_strength
        observed_quality = cls._operational_quality(performance)
        sample_count = int(performance.run_count or 0) if performance else 0
        effective_samples = sample_count if observed_quality is not None else 0
        denominator = prior_strength + effective_samples
        posterior_quality = (
            (prior_quality * prior_strength + (observed_quality or 0.0) * effective_samples)
            / denominator
        )
        uncertainty = max(
            0.01,
            prior_uncertainty / math.sqrt(1 + effective_samples / prior_strength),
        )
        fallback_rate = cls._blend(
            prior=profile.fallback_rate,
            observed=(performance.fallback_rate if performance else None),
            prior_strength=prior_strength,
            sample_count=effective_samples,
        )
        catalog_cost = cls._catalog_cost(
            candidate, estimated_input_tokens, estimated_output_tokens
        )
        observed_cost = performance.avg_cost if performance else None
        expected_cost = (
            observed_cost
            if observed_cost is not None and observed_cost >= 0
            else catalog_cost
        )
        observed_latency = performance.avg_latency_ms if performance else None
        expected_latency = (
            max(1, round(observed_latency))
            if observed_latency is not None and observed_latency > 0
            else profile.expected_latency_ms(input_profile)
        )
        source = profile.source
        if effective_samples:
            source = f"{source}+node_operational"
        return ModelRoutingCandidateScore(
            model_id=candidate.model_id,
            posterior_quality_mean=posterior_quality,
            quality_lower_bound=max(
                posterior_quality - cls._LOWER_CONFIDENCE_BETA * uncertainty,
                0.0,
            ),
            quality_uncertainty=uncertainty,
            expected_cost_usd=expected_cost,
            expected_latency_ms=expected_latency,
            expected_fallback_rate=fallback_rate,
            utility_score=float("-inf"),
            selection_eligible=False,
            effective_operational_samples=effective_samples,
            profile_source=source,
            profile_version=profile.profile_version,
        )

    @classmethod
    def _apply_utility(
        cls,
        scores: list[ModelRoutingCandidateScore],
        *,
        eligible: list[ModelRoutingCandidateScore],
        quality_floor: float,
    ) -> list[ModelRoutingCandidateScore]:
        if not scores:
            return []
        finite_costs = [item.expected_cost_usd for item in scores if math.isfinite(item.expected_cost_usd)]
        min_cost = min(finite_costs, default=0.0)
        max_cost = max(finite_costs, default=0.0)
        min_latency = min((item.expected_latency_ms for item in scores), default=1)
        max_latency = max((item.expected_latency_ms for item in scores), default=1)
        eligible_ids = {item.model_id for item in eligible}
        resolved: list[ModelRoutingCandidateScore] = []
        for item in scores:
            cost_penalty = cls._normalized(item.expected_cost_usd, min_cost, max_cost)
            latency_penalty = cls._normalized(
                float(item.expected_latency_ms), float(min_latency), float(max_latency)
            )
            # 품질 gate를 통과한 뒤에는 "더 비싼 모델일수록 더 좋은" 방향으로
            # 무한히 보상하지 않는다. 충분한 품질을 확보한 후보 중 비용과 지연이
            # 가장 낮은 모델을 고르는 것이 라우터의 목표다. 남는 품질 여유는 동률을
            # 안정적으로 풀기 위한 작은 보조 신호로만 사용한다.
            quality_headroom = min(
                max(item.quality_lower_bound - quality_floor, 0.0),
                cls._MAX_QUALITY_HEADROOM_UTILITY,
            )
            utility = (
                quality_headroom
                - cls._COST_WEIGHT * cost_penalty
                - cls._LATENCY_WEIGHT * latency_penalty
                - cls._FALLBACK_WEIGHT * item.expected_fallback_rate
            )
            resolved.append(
                ModelRoutingCandidateScore(
                    **{
                        **item.__dict__,
                        "utility_score": utility,
                        "selection_eligible": item.model_id in eligible_ids,
                    }
                )
            )
        return resolved

    @classmethod
    def _quality_floor_for_complexity(
        cls,
        complexity: ModelRoutingComplexityEstimate,
    ) -> float:
        """복잡할수록 품질 기준을 부드럽게 높인다.

        0점은 기존 economy 기준, 50점은 balanced 기준, 100점은 advanced
        기준에 대응한다. 세 구간으로 분기하지 않으므로 64점과 65점도 다른
        품질 기준으로 후보를 평가한다.
        """
        protected_score = min(100.0, complexity.score + complexity.uncertainty)
        if protected_score <= 50:
            return cls._QUALITY_FLOOR["economy"] + (
                cls._QUALITY_FLOOR["balanced"] - cls._QUALITY_FLOOR["economy"]
            ) * (protected_score / 50.0)
        return cls._QUALITY_FLOOR["balanced"] + (
            cls._QUALITY_FLOOR["advanced"] - cls._QUALITY_FLOOR["balanced"]
        ) * ((protected_score - 50.0) / 50.0)

    @staticmethod
    def _normalized(value: float, low: float, high: float) -> float:
        if not math.isfinite(value) or high <= low:
            return 0.0
        return min(max((value - low) / (high - low), 0.0), 1.0)

    @staticmethod
    def _catalog_cost(
        candidate: ConstraintModelCandidate,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        if candidate.input_price_1k is None or candidate.output_price_1k is None:
            return float("inf")
        return max(input_tokens, 0) / 1_000 * candidate.input_price_1k + max(
            output_tokens, 0
        ) / 1_000 * candidate.output_price_1k

    @staticmethod
    def _performance_for(
        profile: NodeRunProfile | None,
        *,
        model_id: str,
        input_profile: str,
    ) -> ModelPerformance | None:
        if profile is None:
            return None
        segment = profile.segment_performance.get(input_profile)
        if isinstance(segment, dict):
            segment_models = segment.get("model_performance")
            if isinstance(segment_models, dict):
                value = segment_models.get(model_id)
                if isinstance(value, ModelPerformance):
                    return value
            # 구간 데이터가 있다면 다른 구간 성적을 섞지 않는다.
            return None
        return profile.model_performance.get(model_id)

    @staticmethod
    def _operational_quality(performance: ModelPerformance | None) -> float | None:
        if performance is None or performance.run_count <= 0:
            return None
        parts = [performance.success_rate]
        if performance.schema_pass_rate is not None:
            parts.append(performance.schema_pass_rate)
        if performance.downstream_success_rate is not None:
            parts.append(performance.downstream_success_rate)
        values = [value for value in parts if value is not None]
        return min(values) if values else None

    @staticmethod
    def _blend(
        *,
        prior: float,
        observed: float | None,
        prior_strength: float,
        sample_count: int,
    ) -> float:
        if observed is None or sample_count <= 0:
            return prior
        return (prior * prior_strength + observed * sample_count) / (
            prior_strength + sample_count
        )

    @staticmethod
    def _normalize_model_id(value: Any) -> str:
        return str(value or "").strip().lower().removeprefix("models/")


class CatalogGlobalProfileDefaults:
    """DB row가 아직 없는 catalog 모델의 보수적인 초기 profile 생성기.

    이 값은 이름만 보고 실행 중에 임시로 분기하는 runtime rule이 아니다. policy
    생성 시 DB에 `catalog_seed_v1` source로 materialize되는 초기 데이터다. 이후
    운영 성적은 policy별 누계에만 기록하며 이 전역 값을 직접 덮어쓰지 않는다.
    """

    _TEMPLATES: tuple[tuple[str, tuple[str, ...], dict[str, Any]], ...] = (
        (
            "low",
            ("nano", "lite"),
            {
                "quality": {"economy": 0.88, "balanced": 0.70, "advanced": 0.48},
                "uncertainty": {"economy": 0.12, "balanced": 0.15, "advanced": 0.18},
                "latency": 420,
            },
        ),
        (
            "balanced",
            ("mini", "flash", "haiku", "terra", "luna"),
            {
                "quality": {"economy": 0.94, "balanced": 0.84, "advanced": 0.68},
                "uncertainty": {"economy": 0.08, "balanced": 0.10, "advanced": 0.13},
                "latency": 650,
            },
        ),
        (
            "high",
            ("-pro", "-opus", "-sol", "o3", "fable"),
            {
                "quality": {"economy": 0.99, "balanced": 0.97, "advanced": 0.95},
                "uncertainty": {"economy": 0.04, "balanced": 0.05, "advanced": 0.06},
                "latency": 1_400,
            },
        ),
        (
            "high",
            ("gpt-5.6", "gpt-5.5", "gpt-5.4", "gpt-5.3", "gpt-5.2", "gpt-5.1", "gpt-5", "gemini-2.5-pro", "gemini-3.1-pro", "sonnet"),
            {
                "quality": {"economy": 0.98, "balanced": 0.95, "advanced": 0.90},
                "uncertainty": {"economy": 0.05, "balanced": 0.06, "advanced": 0.08},
                "latency": 1_100,
            },
        ),
    )

    @classmethod
    def for_candidate(cls, candidate: ConstraintModelCandidate) -> GlobalModelProfile:
        return cls.for_model(
            model_id=candidate.model_id,
            metadata={},
            capability_tier=candidate.capability_tier,
        )

    @classmethod
    def for_model(
        cls,
        *,
        model_id: str,
        metadata: Mapping[str, Any],
        capability_tier: str | None = None,
    ) -> GlobalModelProfile:
        explicit = metadata.get("routing_global_profile")
        if isinstance(explicit, Mapping):
            return cls._from_explicit(
                model_id=model_id,
                explicit=explicit,
                fallback_tier=capability_tier or "balanced",
            )
        normalized = str(model_id or "").strip().lower()
        explicit_tier = str(metadata.get("routing_capability_tier") or "").lower()
        resolved_tier = (
            explicit_tier
            if explicit_tier in {"low", "balanced", "high"}
            else capability_tier
        )
        for tier, markers, values in cls._TEMPLATES:
            if any(marker in normalized for marker in markers):
                return cls._from_template(
                    model_id=normalized,
                    values=values,
                    tier=resolved_tier or tier,
                )
        return cls._from_template(
            model_id=normalized,
            values={
                "quality": {"economy": 0.86, "balanced": 0.76, "advanced": 0.62},
                "uncertainty": {"economy": 0.15, "balanced": 0.17, "advanced": 0.20},
                "latency": 900,
            },
            tier=resolved_tier or "balanced",
        )

    @classmethod
    def _from_explicit(
        cls,
        *,
        model_id: str,
        explicit: Mapping[str, Any],
        fallback_tier: str,
    ) -> GlobalModelProfile:
        quality = cls._number_map(explicit.get("quality_by_difficulty"), fallback=0.7)
        uncertainty = cls._number_map(
            explicit.get("uncertainty_by_difficulty"), fallback=0.15
        )
        latency = cls._latency_map(explicit.get("expected_latency_ms_by_input_profile"), fallback=900)
        tier = str(explicit.get("capability_tier") or fallback_tier).lower()
        if tier not in {"low", "balanced", "high"}:
            tier = fallback_tier
        return GlobalModelProfile(
            model_id=model_id,
            quality_by_difficulty=quality,
            uncertainty_by_difficulty=uncertainty,
            expected_latency_ms_by_input_profile=latency,
            fallback_rate=_bounded(explicit.get("fallback_rate"), default=0.02),
            prior_strength=max(_float(explicit.get("prior_strength"), default=6.0), 0.1),
            source=str(explicit.get("source") or "catalog_explicit_profile"),
            profile_version=str(explicit.get("profile_version") or "catalog-explicit-v1"),
            capability_tier=tier,
        )

    @classmethod
    def _from_template(
        cls,
        *,
        model_id: str,
        values: Mapping[str, Any],
        tier: str,
    ) -> GlobalModelProfile:
        latency = _int(values.get("latency"), default=900)
        return GlobalModelProfile(
            model_id=model_id,
            quality_by_difficulty=dict(values["quality"]),
            uncertainty_by_difficulty=dict(values["uncertainty"]),
            expected_latency_ms_by_input_profile={
                "short": max(1, round(latency * 0.8)),
                "medium": latency,
                "long": max(1, round(latency * 1.8)),
                "unknown": latency,
            },
            fallback_rate=0.02,
            prior_strength=6.0,
            source="catalog_seed_v1",
            profile_version="catalog-seed-v1",
            capability_tier=tier,
        )

    @staticmethod
    def _number_map(value: Any, *, fallback: float) -> dict[str, float]:
        raw = value if isinstance(value, Mapping) else {}
        return {level: _bounded(raw.get(level), default=fallback) for level in DIFFICULTY_LEVELS}

    @staticmethod
    def _latency_map(value: Any, *, fallback: int) -> dict[str, int]:
        raw = value if isinstance(value, Mapping) else {}
        return {
            profile: max(1, _int(raw.get(profile), default=fallback))
            for profile in INPUT_PROFILES
        }


class ModelRoutingGlobalProfileStore:
    """전역 profile DB row를 조회하고 없는 catalog 모델은 초기 profile로 등록한다."""

    @classmethod
    def resolve_available_profiles(
        cls,
        db: Session,
        *,
        available_model_ids: Iterable[str],
        materialize_missing: bool = True,
    ) -> dict[str, GlobalModelProfile]:
        available = {
            cls._normalize(model_id) for model_id in available_model_ids if model_id
        }
        if not available:
            return {}
        rows = (
            db.query(LLMModel, LLMModelRoutingGlobalProfile)
            .outerjoin(
                LLMModelRoutingGlobalProfile,
                LLMModelRoutingGlobalProfile.llm_model_id == LLMModel.id,
            )
            .filter(LLMModel.is_active.is_(True))
            .all()
        )
        profiles: dict[str, GlobalModelProfile] = {}
        for model, persisted in rows:
            model_id = cls._normalize(model.model_id_for_api_call)
            if model_id not in available or model_id in profiles:
                continue
            profile = (
                cls._from_persisted(model_id=model_id, row=persisted)
                if persisted is not None and bool(persisted.is_active)
                else CatalogGlobalProfileDefaults.for_model(
                    model_id=model_id,
                    metadata=(
                        model.model_metadata
                        if isinstance(model.model_metadata, Mapping)
                        else {}
                    ),
                )
            )
            profiles[model_id] = profile
            if persisted is None and materialize_missing:
                db.add(cls._to_persisted(model_id=model_id, llm_model_id=model.id, profile=profile))
        return profiles

    @classmethod
    def _from_persisted(
        cls,
        *,
        model_id: str,
        row: LLMModelRoutingGlobalProfile,
    ) -> GlobalModelProfile:
        return GlobalModelProfile(
            model_id=model_id,
            quality_by_difficulty=(
                row.quality_by_difficulty
                if isinstance(row.quality_by_difficulty, Mapping)
                else {}
            ),
            uncertainty_by_difficulty=(
                row.uncertainty_by_difficulty
                if isinstance(row.uncertainty_by_difficulty, Mapping)
                else {}
            ),
            expected_latency_ms_by_input_profile=(
                row.expected_latency_ms_by_input_profile
                if isinstance(row.expected_latency_ms_by_input_profile, Mapping)
                else {}
            ),
            fallback_rate=_float(row.fallback_rate, default=0.02),
            prior_strength=max(_float(row.prior_strength, default=6.0), 0.1),
            source=str(row.source or "global_profile"),
            profile_version=str(row.profile_version or "global-profile-v1"),
            capability_tier=str(row.capability_tier or "balanced"),
        )

    @staticmethod
    def _to_persisted(
        *,
        model_id: str,
        llm_model_id: Any,
        profile: GlobalModelProfile,
    ) -> LLMModelRoutingGlobalProfile:
        del model_id
        return LLMModelRoutingGlobalProfile(
            llm_model_id=llm_model_id,
            capability_tier=profile.capability_tier,
            quality_by_difficulty=dict(profile.quality_by_difficulty),
            uncertainty_by_difficulty=dict(profile.uncertainty_by_difficulty),
            expected_latency_ms_by_input_profile=dict(
                profile.expected_latency_ms_by_input_profile
            ),
            fallback_rate=profile.fallback_rate,
            prior_strength=profile.prior_strength,
            source=profile.source,
            profile_version=profile.profile_version,
            is_active=True,
        )

    @staticmethod
    def _normalize(model_id: Any) -> str:
        return str(model_id or "").strip().lower().removeprefix("models/")


def _float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_non_negative_float(value: Any) -> float | None:
    if value is None:
        return None
    parsed = _float(value, default=float("nan"))
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _bounded(value: Any, *, default: float) -> float:
    return min(max(_float(value, default=default), 0.0), 1.0)
