import json
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from apps.shared.db.models.llm import (
    LLMCredential,
    LLMModel,
    LLMRelCredentialModel,
    LLMUsageLog,
)
from apps.shared.db.models.workflow_run import (
    NodeRunStatus,
    RunStatus,
    RunTriggerMode,
    WorkflowNodeRun,
    WorkflowRun,
)
from apps.workflow_engine.services.model_routing_mdeberta_classifier import (
    MDebertaDifficultyClassifier,
)
OPERATIONAL_TRIGGER_MODES = {
    RunTriggerMode.API,
    RunTriggerMode.WEBHOOK,
    RunTriggerMode.SCHEDULER,
    RunTriggerMode.APP,
}

WORKFLOW_CHAT_MODEL_ALIASES = {
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.6",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.4-pro",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5",
    "o3-pro",
    "o3",
    "gpt-4.1",
    "gpt-4o",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1-mini",
    "gpt-4o-mini",
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5-20251101",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5-20251001",
    "claude-haiku-4-5",
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
}
BLOCKED_WORKFLOW_MODEL_KEYWORDS = (
    "embedding",
    "image",
    "audio",
    "realtime",
    "moderation",
    "tts",
    "whisper",
    "transcribe",
    "sora",
    "search",
)
BLOCKED_WORKFLOW_MODEL_TYPES = {
    "embedding",
    "image",
    "audio",
    "realtime",
    "moderation",
}
VERSION_SUFFIX_PATTERN = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$")

# 입력군/업무 도메인과 무관하게, 한국어 정책 문구의 부분 일치에서만 의미가
# 약한 연결어와 정중 표현이다. 실제 업무 단어는 bootstrap policy에 저장된
# Planner 결과만 사용한다.
ROUTING_LOW_SIGNAL_TOKENS = {
    "같이",
    "관련",
    "내용",
    "다시",
    "대해",
    "모두",
    "방법",
    "부탁",
    "사항",
    "알려",
    "요청",
    "정리",
    "주세요",
    "함께",
    "확인",
    "해당",
    "해주세요",
    "합니다",
    "하세요",
}


@dataclass(frozen=True)
class ModelCandidate:
    model_id: str
    display_name: str
    input_price_1k: Optional[float] = None
    output_price_1k: Optional[float] = None

    @property
    def price_score(self) -> float:
        prices = [
            price
            for price in (self.input_price_1k, self.output_price_1k)
            if price is not None
        ]
        if not prices:
            return float("inf")
        return float(sum(prices))

    @classmethod
    def from_model(cls, model: Any) -> "ModelCandidate":
        return cls(
            model_id=str(model.model_id_for_api_call),
            display_name=str(getattr(model, "name", None) or model.model_id_for_api_call),
            input_price_1k=_float_or_none(getattr(model, "input_price_1k", None)),
            output_price_1k=_float_or_none(getattr(model, "output_price_1k", None)),
        )


@dataclass
class ModelPerformance:
    model_id: str
    run_count: int = 0
    success_count: int = 0
    schema_pass_count: int = 0
    schema_eval_count: int = 0
    downstream_success_count: int = 0
    downstream_eval_count: int = 0
    fallback_count: int = 0
    retry_count: int = 0
    total_cost: float = 0.0
    total_tokens: int = 0
    total_latency_ms: int = 0

    @property
    def success_rate(self) -> Optional[float]:
        return _ratio(self.success_count, self.run_count)

    @property
    def schema_pass_rate(self) -> Optional[float]:
        return _ratio(self.schema_pass_count, self.schema_eval_count)

    @property
    def downstream_success_rate(self) -> Optional[float]:
        return _ratio(self.downstream_success_count, self.downstream_eval_count)

    @property
    def fallback_rate(self) -> Optional[float]:
        return _ratio(self.fallback_count, self.run_count)

    @property
    def avg_cost(self) -> Optional[float]:
        if self.run_count <= 0:
            return None
        return self.total_cost / self.run_count

    @property
    def avg_total_tokens(self) -> Optional[float]:
        if self.run_count <= 0:
            return None
        return self.total_tokens / self.run_count

    @property
    def avg_latency_ms(self) -> Optional[float]:
        if self.run_count <= 0:
            return None
        return self.total_latency_ms / self.run_count

    def as_summary(self) -> dict[str, Any]:
        return {
            "run_count": self.run_count,
            "success_rate": self.success_rate,
            "schema_pass_rate": self.schema_pass_rate,
            "downstream_success_rate": self.downstream_success_rate,
            "fallback_rate": self.fallback_rate,
            "retry_count": self.retry_count,
            "avg_cost": self.avg_cost,
            "avg_total_tokens": self.avg_total_tokens,
            "avg_latency_ms": self.avg_latency_ms,
        }


@dataclass
class NodeRunProfile:
    operational_usable_runs: int = 0
    model_performance: dict[str, ModelPerformance] = field(default_factory=dict)
    segment_performance: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_snapshot(self) -> dict[str, Any]:
        return {
            "operational_usable_runs": self.operational_usable_runs,
            "model_performance": {
                model_id: performance.as_summary()
                for model_id, performance in self.model_performance.items()
            },
            "segment_performance": [
                {
                    "conditions": segment["conditions"],
                    "model_performance": {
                        model_id: performance.as_summary()
                        for model_id, performance in segment[
                            "model_performance"
                        ].items()
                    },
                }
                for _key, segment in sorted(self.segment_performance.items())
            ],
        }


@dataclass(frozen=True)
class ModelRouterContext:
    workflow_id: str
    node_id: str
    current_model_id: Optional[str]
    deployment_id: Optional[str] = None
    candidate_models: Iterable[ModelCandidate] = field(default_factory=list)
    node_profile: Optional[NodeRunProfile] = None
    fallback_model_id: Optional[str] = None
    customer_facing: bool = False
    knowledge_enabled: bool = False
    output_format: Optional[str] = None


@dataclass(frozen=True)
class ModelRouterDecision:
    routing_stage: str
    selected_model_id: str
    fallback_model_id: Optional[str]
    reason: str
    policy_version: str = "model-router-v1"
    confidence: Optional[float] = None
    metrics_snapshot: dict[str, Any] = field(default_factory=dict)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "recommendation_type": "user_click_model_routing",
            "analysis_stage": self.routing_stage,
            "recommended_model": self.selected_model_id,
            "recommended_fallback_model": self.fallback_model_id,
            "reason": self.reason,
            "policy_version": self.policy_version,
            "confidence": self.confidence,
            "metrics_snapshot": self.metrics_snapshot,
        }


@dataclass(frozen=True)
class ModelRoutingRuntimeContext:
    text: str
    intent: str
    risk_level: str
    customer_facing: bool
    knowledge_enabled: bool
    output_format: str
    schema_required: bool
    has_file_input: bool
    input_length: int
    input_length_bucket: str
    prompt_length: int
    prompt_length_bucket: str
    node_task: str

    def as_metadata(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "risk_level": self.risk_level,
            "customer_facing": self.customer_facing,
            "knowledge_enabled": self.knowledge_enabled,
            "output_format": self.output_format,
            "schema_required": self.schema_required,
            "has_file_input": self.has_file_input,
            "input_length": self.input_length,
            "input_length_bucket": self.input_length_bucket,
            "prompt_length": self.prompt_length,
            "prompt_length_bucket": self.prompt_length_bucket,
            "node_task": self.node_task,
        }


@dataclass(frozen=True)
class ModelRoutingPolicyDecision:
    selected_model_id: str
    fallback_model_id: Optional[str]
    matched_rule_id: Optional[str]
    reason_code: str
    runtime_context: ModelRoutingRuntimeContext
    decision_source: str = "active_policy"
    strategy_id: Optional[str] = None
    decision_factors: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BootstrapRuleSignals:
    """Bootstrap phrase rule의 강한/약한 일치 근거다.

    여러 단어로 만든 Planner phrase에서 단어 하나만 우연히 겹치는 경우는
    ``weak``으로 보관한다. 단일 난이도 분기를 만들기에는 부족하지만, 서로 다른
    phrase에서 나온 두 개 이상의 약한 근거가 함께 있으면 복합 요청의 보조 근거로
    사용할 수 있다.
    """

    strong_terms: tuple[str, ...]
    weak_terms: tuple[str, ...]
    score: int


class ModelRoutingUnavailableError(ValueError):
    pass


class ModelRouter:
    POLICY_CONDITION_KEYS = {
        "intent",
        "customer_facing",
        "knowledge_enabled",
        "output_format",
        "schema_required",
        "has_file_input",
        "input_length_bucket",
        "prompt_length_bucket",
        "node_task",
        "keyword_any",
        "keyword_all",
        "minimum_keyword_matches",
    }
    COLD_START_MAX_USABLE_RUNS = 20
    OPTIMIZED_MIN_USABLE_RUNS = 90
    SCHEMA_PASS_RATE_MIN = 0.98
    DOWNSTREAM_SUCCESS_RATE_MIN = 0.99
    FALLBACK_RATE_MAX = 0.02
    MIN_WARMING_MODEL_SAMPLES = 5
    MIN_OPTIMIZED_MODEL_SAMPLES = 10

    @classmethod
    def resolve(
        cls,
        context: ModelRouterContext,
        *,
        db: Optional[Session] = None,
    ) -> ModelRouterDecision:
        if not context.current_model_id:
            raise ModelRoutingUnavailableError("current_model_id is required.")

        profile = context.node_profile
        if profile is None and db is not None:
            profile = cls.collect_profile(db, context)
        profile = profile or NodeRunProfile()

        candidates = cls._normalize_candidates(context)
        if not candidates:
            raise ModelRoutingUnavailableError("No executable model candidate.")

        stage = cls._stage_for(profile)
        high = cls._current_or_highest_candidate(candidates, context.current_model_id)

        if stage == "cold_start":
            return cls._decision(
                stage=stage,
                selected=high,
                fallback=high,
                reason="운영 로그가 부족해 보수적 규칙 기반으로 모델을 선택합니다.",
                profile=profile,
            )

        passing = cls._passing_candidates(candidates, profile, stage)
        lower_cost_passing = cls._lower_cost_candidates(
            passing, context.current_model_id
        )
        if lower_cost_passing:
            selected = lower_cost_passing[0]
            return cls._decision(
                stage=stage,
                selected=selected,
                fallback=high,
                reason="최근 운영 로그의 품질 gate를 통과한 저비용 모델을 선택합니다.",
                profile=profile,
                confidence=0.8 if stage == "warming_up" else 0.9,
            )

        if passing:
            selected = passing[0]
            return cls._decision(
                stage=stage,
                selected=selected,
                fallback=high,
                reason="현재 모델만 품질 gate를 통과해 안정 모델을 유지합니다.",
                profile=profile,
                confidence=0.75,
            )

        return cls._decision(
            stage=stage,
            selected=high,
            fallback=None,
            reason="저비용 후보가 품질 gate를 통과하지 못해 상위 모델을 사용합니다.",
            profile=profile,
            confidence=0.7,
        )

    @classmethod
    def resolve_policy(
        cls,
        policy: dict[str, Any],
        *,
        inputs: dict[str, Any],
        node_data: Any,
        available_model_ids: Optional[Iterable[str]] = None,
        routing_feature_text: str | None = None,
        node_profile: NodeRunProfile | None = None,
    ) -> ModelRoutingPolicyDecision:
        active_policy = policy.get("active_policy") if isinstance(policy, dict) else None
        active_policy = active_policy if isinstance(active_policy, dict) else {}
        default_model_id = cls._first_non_empty(
            active_policy.get("default_model_id"),
            getattr(node_data, "model_id", None),
        )
        fallback_model_id = cls._first_non_empty(
            active_policy.get("fallback_model_id"),
            getattr(node_data, "fallback_model_id", None),
        )
        if not default_model_id:
            raise ModelRoutingUnavailableError("default model is required.")

        allowed_models = (
            {cls.normalize_model_id(model_id) for model_id in available_model_ids}
            if available_model_ids is not None
            else None
        )
        runtime_context = cls.infer_runtime_context(inputs, node_data)
        strategy_id = cls._first_non_empty(active_policy.get("strategy_id"))
        if strategy_id == "bootstrap_mdeberta_difficulty_v1":
            return cls._resolve_bootstrap_difficulty_policy(
                active_policy,
                inputs=inputs,
                node_data=node_data,
                runtime_context=runtime_context,
                allowed_models=allowed_models,
                default_model_id=default_model_id,
                fallback_model_id=fallback_model_id,
                strategy_id=strategy_id,
                routing_feature_text=routing_feature_text,
                node_profile=node_profile,
            )
        rules = active_policy.get("rules")
        normalized_rules = [
            rule
            for rule in (rules if isinstance(rules, list) else [])
            if isinstance(rule, dict)
        ]
        normalized_rules.sort(key=cls._rule_sort_key)
        for rule in normalized_rules:
            if not cls._matches_rule(
                rule.get("when"),
                runtime_context,
            ):
                continue
            selected_model = cls._first_non_empty(rule.get("selected_model_id"))
            rule_fallback_model = cls._first_non_empty(rule.get("fallback_model_id"))
            selected_model = cls._first_available_model(
                [selected_model],
                allowed_models,
            )
            if not selected_model:
                continue
            resolved_fallback = cls._first_available_model(
                [rule_fallback_model, fallback_model_id],
                allowed_models,
                exclude=selected_model,
            )
            return ModelRoutingPolicyDecision(
                selected_model_id=selected_model,
                fallback_model_id=resolved_fallback,
                matched_rule_id=cls._first_non_empty(rule.get("id")),
                reason_code=cls._first_non_empty(rule.get("reason_code"))
                or "policy_rule_matched",
                runtime_context=runtime_context,
                strategy_id=strategy_id,
                decision_factors=cls._decision_factors(
                    active_policy,
                    runtime_context=runtime_context,
                    selected_model_id=selected_model,
                ),
            )

        selected_model = cls._first_available_model(
            [
                default_model_id,
                fallback_model_id,
                getattr(node_data, "model_id", None),
                getattr(node_data, "fallback_model_id", None),
            ],
            allowed_models,
        )
        if not selected_model:
            raise ModelRoutingUnavailableError(
                "No policy model is currently available to the execution subject."
            )
        resolved_fallback = cls._first_available_model(
            [
                fallback_model_id,
                default_model_id,
                getattr(node_data, "fallback_model_id", None),
                getattr(node_data, "model_id", None),
            ],
            allowed_models,
            exclude=selected_model,
        )
        return ModelRoutingPolicyDecision(
            selected_model_id=selected_model,
            fallback_model_id=resolved_fallback,
            matched_rule_id=None,
            reason_code="policy_default",
            runtime_context=runtime_context,
            strategy_id=strategy_id,
            decision_factors=cls._decision_factors(
                active_policy,
                runtime_context=runtime_context,
                selected_model_id=selected_model,
            ),
        )

    @classmethod
    def _resolve_bootstrap_difficulty_policy(
        cls,
        active_policy: dict[str, Any],
        *,
        inputs: dict[str, Any],
        node_data: Any,
        runtime_context: ModelRoutingRuntimeContext,
        allowed_models: set[str] | None,
        default_model_id: str,
        fallback_model_id: str | None,
        strategy_id: str,
        routing_feature_text: str | None,
        node_profile: NodeRunProfile | None,
    ) -> ModelRoutingPolicyDecision:
        """초기 bootstrap artifact로 난이도를 예측해 tier 모델을 선택한다.

        classifier 오류나 낮은 confidence는 실패가 아니라 builder가 정한 기본 모델로
        닫는다. 따라서 첫 배포의 routing이 artifact 준비 실패 때문에 중단되지 않는다.
        """
        artifact = active_policy.get("classifier_artifact")
        difficulty_models = active_policy.get("difficulty_models")
        difficulty_models = (
            difficulty_models if isinstance(difficulty_models, dict) else {}
        )
        catalog_model_ids = cls._bootstrap_catalog_model_ids(active_policy)
        default_selected = cls._first_available_model(
            [
                default_model_id,
                fallback_model_id,
                getattr(node_data, "model_id", None),
                *catalog_model_ids,
            ],
            allowed_models,
        )
        if not default_selected:
            raise ModelRoutingUnavailableError(
                "No bootstrap routing model is currently available to the execution subject."
            )
        default_fallback = cls._first_available_model(
            [
                fallback_model_id,
                default_model_id,
                getattr(node_data, "fallback_model_id", None),
                getattr(node_data, "model_id", None),
                *catalog_model_ids,
            ],
            allowed_models,
            exclude=default_selected,
        )
        generalization_validation = active_policy.get("generalization_validation")
        generalization_validation = (
            generalization_validation
            if isinstance(generalization_validation, dict)
            else None
        )
        rule_validation = (
            generalization_validation.get("rules")
            if isinstance(generalization_validation, dict)
            else None
        )
        rule_validation = rule_validation if isinstance(rule_validation, dict) else {}
        classifier_validation = (
            generalization_validation.get("classifier")
            if isinstance(generalization_validation, dict)
            else None
        )
        classifier_validation = (
            classifier_validation if isinstance(classifier_validation, dict) else {}
        )
        # 새 bootstrap은 holdout에서 개별적으로 검증된 구조 규칙만 먼저 적용한다.
        # 과거 policy는 ``validated_rule_ids``가 없으므로 기존의 묶음 검증
        # metadata를 읽어 classifier-first 동작을 유지한다.
        validated_rule_ids_value = rule_validation.get("validated_rule_ids")
        has_individual_rule_validation = isinstance(validated_rule_ids_value, list)
        validated_rule_ids = {
            str(rule_id).strip()
            for rule_id in validated_rule_ids_value
            if str(rule_id).strip()
        } if has_individual_rule_validation else None
        # 의미 분류기는 학습 표본과 다른 표현까지 분류하기 위한 주 경로다. holdout을
        # 통과한 classifier가 있으면 먼저 사용하고, Planner phrase rule은 confidence가
        # 낮거나 해당 난이도가 아직 검증되지 않았을 때만 보조한다. 그렇지 않으면
        # ``순서`` 같은 넓은 단어가 고위험 요청을 먼저 가로채 일반화가 무너진다.
        can_use_planner_rules = (
            bool(validated_rule_ids)
            if has_individual_rule_validation
            else generalization_validation is None
            or bool(rule_validation.get("passed"))
        )
        planner_rule_ids = (
            validated_rule_ids if has_individual_rule_validation else None
        )
        planner_validation_status = (
            "validated_planner_rule"
            if generalization_validation is not None
            else "planner_rule"
        )

        prediction = None
        fallback_reason = "bootstrap_classifier_missing"
        fallback_factors: dict[str, Any] = {"classification_status": "artifact_missing"}
        classifier_globally_allowed = (
            generalization_validation is None or bool(classifier_validation.get("passed"))
        )
        validated_difficulties = {
            str(value).strip()
            for value in classifier_validation.get("validated_difficulties", [])
            if str(value).strip()
        }
        classifier_can_classify_a_tier = (
            classifier_globally_allowed or bool(validated_difficulties)
        )
        classifier_validation_scope: str | None = (
            "global" if classifier_globally_allowed else None
        )
        if isinstance(artifact, dict) and classifier_can_classify_a_tier:
            feature_text = routing_feature_text or cls._bootstrap_feature_text(
                inputs,
                node_data,
                runtime_context,
            )
            try:
                prediction = MDebertaDifficultyClassifier.predict(artifact, feature_text)
            except (RuntimeError, ValueError):
                fallback_reason = "bootstrap_classifier_unavailable"
                fallback_factors = {"classification_status": "unavailable"}
        elif isinstance(artifact, dict) and not classifier_can_classify_a_tier:
            fallback_reason = "bootstrap_classifier_generalization_unverified"
            fallback_factors = {
                "classification_status": "generalization_unverified",
                "generalization_validation": {
                    "status": classifier_validation.get("status"),
                    "accuracy": classifier_validation.get("accuracy"),
                    "total_count": classifier_validation.get("total_count"),
                },
            }

        if prediction is not None:
            if not classifier_globally_allowed:
                per_difficulty = classifier_validation.get("per_difficulty")
                per_difficulty = (
                    per_difficulty if isinstance(per_difficulty, dict) else {}
                )
                difficulty_validation = per_difficulty.get(prediction.difficulty)
                difficulty_validation = (
                    difficulty_validation
                    if isinstance(difficulty_validation, dict)
                    else {}
                )
                if prediction.difficulty not in validated_difficulties:
                    fallback_reason = "bootstrap_classifier_generalization_unverified"
                    fallback_factors = {
                        "classification_status": "generalization_unverified",
                        "difficulty": prediction.difficulty,
                        "confidence": prediction.confidence,
                        "generalization_validation": {
                            "status": classifier_validation.get("status"),
                            "accuracy": classifier_validation.get("accuracy"),
                            "total_count": classifier_validation.get("total_count"),
                            "validated_difficulties": sorted(validated_difficulties),
                        },
                    }
                    prediction = None
                else:
                    classifier_validation_scope = "difficulty"
                    difficulty_minimum_confidence = difficulty_validation.get(
                        "minimum_confidence"
                    )
            else:
                difficulty_minimum_confidence = None

        if prediction is not None:
            min_confidence = cls._normalize_confidence(
                (
                    difficulty_minimum_confidence
                    if classifier_validation_scope == "difficulty"
                    else active_policy.get("minimum_confidence")
                ),
                default=0.55,
            )
            if prediction.confidence >= min_confidence:
                global_profile_decision = cls._bootstrap_global_profile_decision(
                    active_policy,
                    difficulty=prediction.difficulty,
                    probabilities=prediction.probabilities,
                    runtime_context=runtime_context,
                    node_data=node_data,
                    allowed_models=allowed_models,
                    default_model_id=default_model_id,
                    fallback_model_id=fallback_model_id,
                    strategy_id=strategy_id,
                    node_profile=node_profile,
                    classification_factors={
                        "classification_status": "matched",
                        "confidence": prediction.confidence,
                        "difficulty_score": getattr(
                            prediction, "difficulty_score", None
                        ),
                        "minimum_confidence": min_confidence,
                        "probabilities": prediction.probabilities,
                        "classification_validation_scope": classifier_validation_scope,
                    },
                )
                if global_profile_decision is not None:
                    return global_profile_decision

            selected_model = cls._first_available_model(
                [difficulty_models.get(prediction.difficulty)],
                allowed_models,
            )
            if selected_model and prediction.confidence >= min_confidence:
                resolved_fallback = cls._first_available_model(
                    [fallback_model_id, default_model_id],
                    allowed_models,
                    exclude=selected_model,
                )
                return ModelRoutingPolicyDecision(
                    selected_model_id=selected_model,
                    fallback_model_id=resolved_fallback,
                    matched_rule_id=f"difficulty-{prediction.difficulty}",
                    reason_code=f"bootstrap_difficulty_{prediction.difficulty}",
                    runtime_context=runtime_context,
                    strategy_id=strategy_id,
                    decision_factors={
                        "classification_status": "matched",
                        "difficulty": prediction.difficulty,
                        "confidence": prediction.confidence,
                        "difficulty_score": getattr(
                            prediction, "difficulty_score", None
                        ),
                        "minimum_confidence": min_confidence,
                        "probabilities": prediction.probabilities,
                        "classification_validation_scope": classifier_validation_scope,
                    },
                )
            fallback_reason = (
                "bootstrap_difficulty_low_confidence"
                if prediction.confidence < min_confidence
                else "bootstrap_difficulty_model_unavailable"
            )
            fallback_factors = {
                "classification_status": "fallback",
                "difficulty": prediction.difficulty,
                "confidence": prediction.confidence,
                "difficulty_score": getattr(prediction, "difficulty_score", None),
                "minimum_confidence": min_confidence,
                "probabilities": prediction.probabilities,
            }

        # 의미 분류기가 확신을 내지 못하거나 해당 난이도가 holdout 검증 밖인 경우에
        # 한해, 검증된 Planner phrase rule을 보조 수단으로 쓴다.
        if can_use_planner_rules:
            planner_decision = cls._bootstrap_planner_rule_decision(
                active_policy,
                runtime_context=runtime_context,
                allowed_models=allowed_models,
                default_model_id=default_model_id,
                fallback_model_id=fallback_model_id,
                strategy_id=strategy_id,
                validation_status=planner_validation_status,
                classifier_fallback_reason=fallback_reason,
                allowed_rule_ids=planner_rule_ids,
                node_data=node_data,
                node_profile=node_profile,
            )
            if planner_decision is not None:
                return planner_decision

        return ModelRoutingPolicyDecision(
            selected_model_id=default_selected,
            fallback_model_id=default_fallback,
            matched_rule_id=None,
            reason_code=fallback_reason,
            runtime_context=runtime_context,
            strategy_id=strategy_id,
            decision_factors=fallback_factors,
        )

    @staticmethod
    def _bootstrap_catalog_model_ids(active_policy: dict[str, Any]) -> list[str]:
        """새 bootstrap policy가 저장한 전역 후보 ID를 순서 보존해 읽는다."""
        catalog = active_policy.get("global_profile_catalog")
        candidates = catalog.get("candidates") if isinstance(catalog, dict) else None
        if not isinstance(candidates, list):
            return []
        values: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            model_id = str(candidate.get("model_id") or "").strip()
            normalized = ModelRouter.normalize_model_id(model_id)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            values.append(normalized)
        return values

    @classmethod
    def _bootstrap_global_profile_decision(
        cls,
        active_policy: dict[str, Any],
        *,
        difficulty: str,
        probabilities: Any,
        runtime_context: ModelRoutingRuntimeContext,
        node_data: Any,
        allowed_models: set[str] | None,
        default_model_id: str,
        fallback_model_id: str | None,
        strategy_id: str,
        node_profile: NodeRunProfile | None,
        classification_factors: dict[str, Any],
        matched_rule_id: str | None = None,
        reason_prefix: str = "bootstrap_global_profile",
    ) -> ModelRoutingPolicyDecision | None:
        """난이도 결과로 policy snapshot의 모든 후보 모델을 순위화한다.

        ``difficulty_models``는 새 profile snapshot이 없는 과거 정책을 위한
        호환성 fallback이다. 새 bootstrap policy는 여기에서 현재 credential로
        사용할 수 있는 모든 모델을 비교한다. 전역 profile은 policy 안에 저장된
        snapshot을 읽으므로, runtime이 catalog DB나 Planner/Judge를 호출하지 않는다.
        """
        catalog_snapshot = active_policy.get("global_profile_catalog")
        if not isinstance(catalog_snapshot, dict):
            return None
        try:
            from apps.workflow_engine.services.model_routing_global_profiles import (
                ModelRoutingDifficultyDistribution,
                ModelRoutingGlobalProfileScorer,
            )

            probability_mapping = (
                probabilities if isinstance(probabilities, Mapping) else {}
            )
            if not probability_mapping:
                probability_mapping = {difficulty: 1.0}
            distribution = ModelRoutingDifficultyDistribution.from_mapping(
                probability_mapping
            )
            input_tokens, output_tokens = cls._bootstrap_runtime_token_estimate(
                node_data,
                runtime_context=runtime_context,
            )
            result = ModelRoutingGlobalProfileScorer.rank_policy_catalog(
                catalog_snapshot=catalog_snapshot,
                available_model_ids=allowed_models,
                difficulty=distribution,
                input_profile=runtime_context.input_length_bucket,
                estimated_input_tokens=input_tokens,
                estimated_output_tokens=output_tokens,
                default_model_id=default_model_id,
                node_profile=node_profile,
            )
        except (TypeError, ValueError):
            return None
        if result is None:
            return None
        selected_score = result.by_model.get(result.selected_model_id)
        if selected_score is None:
            return None
        resolved_fallback = cls._first_available_model(
            [result.fallback_model_id, fallback_model_id, default_model_id],
            allowed_models,
            exclude=result.selected_model_id,
        )
        factors = {
            **classification_factors,
            "selection_mode": "global_profile_score",
            "compared_model_count": len(result.ranked_candidates),
            "quality_floor": result.quality_floor,
            "selected_quality_lower_bound": selected_score.quality_lower_bound,
            "selected_expected_cost_usd": selected_score.expected_cost_usd,
            "selected_expected_latency_ms": selected_score.expected_latency_ms,
            "selected_expected_fallback_rate": selected_score.expected_fallback_rate,
            "effective_operational_samples": (
                selected_score.effective_operational_samples
            ),
            "profile_source": selected_score.profile_source,
            "profile_version": selected_score.profile_version,
        }
        return ModelRoutingPolicyDecision(
            selected_model_id=result.selected_model_id,
            fallback_model_id=resolved_fallback,
            matched_rule_id=matched_rule_id or f"difficulty-{difficulty}",
            reason_code=f"{reason_prefix}_{difficulty}",
            runtime_context=runtime_context,
            strategy_id=strategy_id,
            decision_factors=factors,
        )

    @staticmethod
    def _bootstrap_runtime_token_estimate(
        node_data: Any,
        *,
        runtime_context: ModelRoutingRuntimeContext,
    ) -> tuple[int, int]:
        """실행 전 알고 있는 입력과 노드 설정으로 비용 비교 token을 추정한다."""
        input_tokens = max(
            1,
            (runtime_context.input_length + runtime_context.prompt_length) // 4,
        )
        parameters = getattr(node_data, "parameters", None)
        parameters = parameters if isinstance(parameters, dict) else {}
        try:
            configured_output = int(parameters.get("max_tokens") or 512)
        except (TypeError, ValueError):
            configured_output = 512
        return input_tokens, min(max(configured_output, 64), 8_192)

    @classmethod
    def _bootstrap_planner_rule_decision(
        cls,
        active_policy: dict[str, Any],
        *,
        runtime_context: ModelRoutingRuntimeContext,
        allowed_models: set[str] | None,
        default_model_id: str,
        fallback_model_id: str | None,
        strategy_id: str,
        validation_status: str,
        classifier_fallback_reason: str,
        allowed_rule_ids: set[str] | None = None,
        node_data: Any,
        node_profile: NodeRunProfile | None,
    ) -> ModelRoutingPolicyDecision | None:
        """저장된 bootstrap 구조 규칙 하나를 runtime decision으로 바꾼다."""
        planner_rule = cls._match_bootstrap_difficulty_rule(
            active_policy.get("difficulty_rules"),
            runtime_context=runtime_context,
            allowed_rule_ids=allowed_rule_ids,
        )
        if planner_rule is None:
            return None
        global_profile_decision = cls._bootstrap_global_profile_decision(
            active_policy,
            difficulty=planner_rule["difficulty"],
            probabilities={planner_rule["difficulty"]: 1.0},
            runtime_context=runtime_context,
            node_data=node_data,
            allowed_models=allowed_models,
            default_model_id=default_model_id,
            fallback_model_id=fallback_model_id,
            strategy_id=strategy_id,
            node_profile=node_profile,
            matched_rule_id=str(planner_rule["id"]),
            reason_prefix="bootstrap_planner_global_profile",
            classification_factors={
                "classification_status": validation_status,
                "difficulty": planner_rule["difficulty"],
                "confidence": planner_rule["confidence"],
                "minimum_confidence": 0.0,
                "matched_terms": planner_rule["matched_terms"],
                "matched_signal_count": len(planner_rule["matched_terms"]),
                "match_score": planner_rule["match_score"],
                "planner_reason": planner_rule.get("reason"),
                "classifier_fallback_reason": classifier_fallback_reason,
            },
        )
        if global_profile_decision is not None:
            return global_profile_decision
        difficulty_models = active_policy.get("difficulty_models")
        difficulty_models = (
            difficulty_models if isinstance(difficulty_models, dict) else {}
        )
        selected_model = cls._first_available_model(
            [difficulty_models.get(planner_rule["difficulty"])],
            allowed_models,
        )
        if not selected_model:
            return None
        resolved_fallback = cls._first_available_model(
            [fallback_model_id, default_model_id],
            allowed_models,
            exclude=selected_model,
        )
        return ModelRoutingPolicyDecision(
            selected_model_id=selected_model,
            fallback_model_id=resolved_fallback,
            matched_rule_id=str(planner_rule["id"]),
            reason_code=f"bootstrap_planner_rule_{planner_rule['difficulty']}",
            runtime_context=runtime_context,
            strategy_id=strategy_id,
            decision_factors={
                "classification_status": validation_status,
                "difficulty": planner_rule["difficulty"],
                "confidence": planner_rule["confidence"],
                "minimum_confidence": 0.0,
                "matched_terms": planner_rule["matched_terms"],
                "matched_signal_count": len(planner_rule["matched_terms"]),
                "match_score": planner_rule["match_score"],
                "planner_reason": planner_rule.get("reason"),
                "classifier_fallback_reason": classifier_fallback_reason,
            },
        )

    @classmethod
    def _match_bootstrap_difficulty_rule(
        cls,
        rules: Any,
        *,
        runtime_context: ModelRoutingRuntimeContext,
        allowed_rule_ids: set[str] | None = None,
    ) -> dict[str, Any] | None:
        """Planner가 저장한 난이도 신호만 평가한다.

        이 함수에는 업무 도메인 단어가 없다. 입력군이 아니라 bootstrap 시점의
        Planner가 현재 노드 설정과 안전한 표본을 보고 만든 phrase rule만 읽는다.
        """
        if not isinstance(rules, list):
            return None
        text = " ".join(str(runtime_context.text or "").casefold().split())
        if not text:
            return None
        text_tokens = cls._routing_text_tokens(text)
        matches: list[dict[str, Any]] = []
        for index, rule in enumerate(rules, start=1):
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("id") or "").strip()
            if allowed_rule_ids is not None and rule_id not in allowed_rule_ids:
                continue
            difficulty = str(rule.get("difficulty") or "").strip()
            if difficulty not in {"economy", "balanced", "advanced"}:
                continue
            keyword_any = cls._rule_terms(rule.get("keyword_any"))
            keyword_all = cls._rule_terms(rule.get("keyword_all"))
            if not keyword_any and not keyword_all:
                continue
            matched_any = cls._bootstrap_rule_signals(
                keyword_any,
                text=text,
                text_tokens=text_tokens,
            )
            matched_all = cls._bootstrap_rule_signals(
                keyword_all,
                text=text,
                text_tokens=text_tokens,
            )
            if keyword_all and len(matched_all.strong_terms) != len(keyword_all):
                continue
            try:
                minimum_matches = int(rule.get("minimum_matches") or 1)
            except (TypeError, ValueError):
                minimum_matches = 1
            required_matches = max(1, minimum_matches)
            matched_any_terms = list(matched_any.strong_terms)
            # 한 단어만 겹친 다단어 phrase는 단독 분기에 쓰지 않는다. 다만
            # advanced처럼 둘 이상의 독립 근거를 요구한 rule은 서로 다른
            # phrase의 약한 근거가 함께 있을 때만 복합 판단 신호로 허용한다.
            if required_matches >= 2:
                matched_any_terms.extend(matched_any.weak_terms)
            if keyword_any and len(matched_any_terms) < required_matches:
                continue
            matched_terms = [*matched_any_terms, *matched_all.strong_terms]
            specificity = len(matched_terms) + len(keyword_all)
            try:
                priority = int(rule.get("priority") or 0)
            except (TypeError, ValueError):
                priority = 0
            matches.append(
                {
                    "id": rule_id or f"planner-{difficulty}-{index}",
                    "difficulty": difficulty,
                    "matched_terms": matched_terms,
                    "reason": str(rule.get("reason") or "").strip() or None,
                    "priority": priority,
                    "specificity": specificity,
                    # 정확한 phrase 일치에는 더 큰 점수를 준다. 나머지는 Planner가
                    # 만든 phrase 내부의 재사용 가능한 단어 신호를 합산한다.
                    "match_score": matched_any.score + matched_all.score,
                    "confidence": min(
                        0.95,
                        0.68 + (0.04 * (matched_any.score + matched_all.score)),
                    ),
                }
            )
        if not matches:
            return None
        matches.sort(
            # advanced 우선순위만으로 generic 단어 한 개가 더 구체적인 economy/
            # balanced 신호를 덮지 않게, 먼저 실제 매칭 근거의 양을 비교한다.
            key=lambda item: (
                -item["match_score"],
                -item["priority"],
                -item["specificity"],
                item["id"],
            )
        )
        return matches[0]

    @staticmethod
    def _rule_terms(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        terms: list[str] = []
        seen: set[str] = set()
        for item in value:
            term = " ".join(str(item or "").casefold().split())
            if len(term) < 2 or term in seen:
                continue
            seen.add(term)
            terms.append(term)
        return terms

    @staticmethod
    def _routing_text_tokens(text: str) -> set[str]:
        """정책 문구의 조사 차이 정도만 흡수하는 가벼운 token 경계다.

        도메인 단어 목록을 이 함수에 두지 않는다. 예를 들어 Planner가 정책에
        ``정책이 충돌``을 저장하면 입력의 ``정책은 충돌``도 같은 정책 신호로
        비교할 수 있도록, 자연어의 종결/조사만 제거한다.
        """
        tokens: set[str] = set()
        for raw_token in re.findall(r"[0-9a-zA-Z가-힣]+", text.casefold()):
            token = ModelRouter._strip_routing_particle(raw_token)
            if len(token) >= 2:
                tokens.add(token)
        return tokens

    @staticmethod
    def _strip_routing_particle(token: str) -> str:
        """한국어 조사/활용형을 최소한으로 제거해 policy phrase를 비교한다."""
        suffixes = (
            "에서는",
            "으로",
            "에게",
            "부터",
            "까지",
            "처럼",
            "보다",
            "하고",
            "하며",
            "하면",
            "하는",
            "할",
            "된",
            "되는",
            "에서",
            "은",
            "는",
            "이",
            "가",
            "을",
            "를",
            "에",
            "와",
            "과",
            "의",
            "만",
            "도",
        )
        for suffix in suffixes:
            if token.endswith(suffix) and len(token) - len(suffix) >= 2:
                return token[: -len(suffix)]
        return token

    @classmethod
    def _bootstrap_rule_signals(
        cls,
        terms: list[str],
        *,
        text: str,
        text_tokens: set[str],
    ) -> BootstrapRuleSignals:
        """Planner policy phrase를 exact/핵심 token 신호로 평가한다.

        ``keyword_any``의 각 항목은 데이터베이스에 저장된 policy에서만 온다.
        즉 여기서는 workflow별 위험/업무 단어를 해석하지 않고, 정책 생성 시
        Planner가 정한 표현을 재사용할 뿐이다. 다만 조사·정중 표현 같은
        일반 언어 token은 업무 난이도를 설명하지 못하므로 부분 매칭 근거에서
        제외한다.
        """
        strong_terms: list[str] = []
        weak_terms: list[str] = []
        score = 0
        for term in terms:
            if term in text:
                strong_terms.append(term)
                score += 3
                continue
            term_tokens = cls._routing_text_tokens(term)
            partial_tokens = sorted(
                token
                for token in term_tokens
                if token in text_tokens and token not in ROUTING_LOW_SIGNAL_TOKENS
            )
            if not partial_tokens:
                continue
            matched_phrase_tokens = [f"{term} ({token})" for token in partial_tokens]
            # 한 단어 cue는 그 단어 자체가 Planner가 고른 난이도 신호다. 반면
            # 다단어 cue는 두 개 이상의 의미 단어가 함께 있을 때만 강한 일치다.
            if len(term_tokens) == 1 or len(partial_tokens) >= 2:
                strong_terms.extend(matched_phrase_tokens)
                score += len(partial_tokens)
            else:
                weak_terms.extend(matched_phrase_tokens)
        return BootstrapRuleSignals(
            strong_terms=tuple(strong_terms),
            weak_terms=tuple(weak_terms),
            score=score,
        )

    @classmethod
    def _bootstrap_feature_text(
        cls,
        inputs: dict[str, Any],
        node_data: Any,
        runtime_context: ModelRoutingRuntimeContext,
    ) -> str:
        """분류용 입력은 변하는 요청과 구조적 제약만 포함한다.

        한 bootstrap policy는 하나의 LLM node에만 연결된다. 해당 node의 prompt는
        모든 표본에 공통이므로 feature에 섞으면 질문 간 난이도 차이가 희석된다.
        """
        metadata = {
            "output_format": runtime_context.output_format,
            "schema_required": runtime_context.schema_required,
            "knowledge_enabled": runtime_context.knowledge_enabled,
            "input_length_bucket": runtime_context.input_length_bucket,
        }
        return "\n".join(
            part
            for part in (
                cls._flatten_text(inputs),
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            )
            if part
        )

    @classmethod
    def bootstrap_classifier_feature_text(
        cls,
        inputs: dict[str, Any],
        node_data: Any,
        *,
        rendered_prompt_parts: Iterable[str] | None = None,
        rag_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Bootstrap 학습과 runtime이 동일하게 쓰는 난이도 분류 feature 계약이다.

        렌더된 prompt와 실제 RAG 검색 결과는 bootstrap 표본에 존재하지 않는 실행 전용
        데이터다. 호환성을 위해 인자는 남기지만 분류 feature에 넣지 않는다.
        """
        _ = rendered_prompt_parts, rag_metadata
        runtime_context = cls.infer_runtime_context(inputs, node_data)
        return cls._bootstrap_feature_text(inputs, node_data, runtime_context)

    @staticmethod
    def _normalize_confidence(value: Any, *, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    @classmethod
    def _decision_factors(
        cls,
        active_policy: dict[str, Any],
        *,
        runtime_context: ModelRoutingRuntimeContext,
        selected_model_id: str,
    ) -> dict[str, Any]:
        """정책 생성 근거 중 원문 없이 사용자에게 공개 가능한 요약만 반환한다."""
        profiles = active_policy.get("decision_profiles")
        if not isinstance(profiles, list):
            return {}
        profile_name = runtime_context.input_length_bucket
        profile = next(
            (
                item
                for item in profiles
                if isinstance(item, dict) and item.get("profile") == profile_name
            ),
            None,
        )
        if not isinstance(profile, dict):
            return {}

        candidate_scores = profile.get("candidate_scores")
        candidate_scores = candidate_scores if isinstance(candidate_scores, dict) else {}
        selected_score = candidate_scores.get(selected_model_id)
        selected_score = selected_score if isinstance(selected_score, dict) else {}
        safe_score_keys = (
            "quality_lower_bound",
            "expected_total_cost_usd",
            "expected_latency_ms",
            "expected_fallback_rate",
            "effective_evidence_samples",
            "prior_source",
        )
        safe_score = {
            key: selected_score[key]
            for key in safe_score_keys
            if key in selected_score
        }
        excluded_models = profile.get("excluded_models")
        excluded_models = excluded_models if isinstance(excluded_models, dict) else {}
        signature = profile.get("constraint_signature")
        signature = signature if isinstance(signature, dict) else {}
        safe_signature_keys = (
            "context_input_bucket",
            "rag_context_bucket",
            "output_contract",
            "schema_complexity",
            "downstream_strictness",
            "file_input",
            "required_input_missing",
            "required_capability_tier",
            "schema_required",
        )
        safe_signature = {
            key: signature[key]
            for key in safe_signature_keys
            if key in signature
        }
        return {
            "profile": profile_name,
            "evaluated_candidate_count": len(candidate_scores),
            "excluded_candidate_count": len(excluded_models),
            "selected_model_score": safe_score,
            "constraint_signature": safe_signature,
        }

    @classmethod
    def infer_runtime_context(
        cls, inputs: dict[str, Any], node_data: Any
    ) -> ModelRoutingRuntimeContext:
        text = cls._flatten_text(inputs)
        prompts = " ".join(
            prompt
            for prompt in (
                str(value or "").strip()
                for value in (
                    getattr(node_data, "system_prompt", None),
                    getattr(node_data, "user_prompt", None),
                    getattr(node_data, "assistant_prompt", None),
                )
            )
            if prompt
        )
        routing_context = getattr(node_data, "model_routing_context", None)
        routing_context = routing_context if isinstance(routing_context, dict) else {}
        knowledge_enabled = bool(
            getattr(node_data, "knowledgeBases", None)
            or getattr(node_data, "knowledgeCollections", None)
        )
        output_format = cls._output_format_name(
            getattr(node_data, "output_format", None)
        )
        schema_required = cls._schema_required(getattr(node_data, "output_format", None))
        customer_facing = bool(routing_context.get("customer_facing", False))
        node_task = cls._first_non_empty(
            routing_context.get("node_task"),
            routing_context.get("category"),
            getattr(node_data, "task_type", None),
        ) or "generate"
        risk_level = cls._first_non_empty(routing_context.get("risk_level")) or "medium"
        intent = cls._first_non_empty(routing_context.get("intent"), node_task) or "generate"
        input_length = len(text)
        prompt_length = len(prompts)

        return ModelRoutingRuntimeContext(
            text=text,
            intent=intent,
            risk_level=risk_level,
            customer_facing=customer_facing,
            knowledge_enabled=knowledge_enabled,
            output_format=output_format,
            schema_required=schema_required,
            has_file_input=cls._has_file_input(inputs),
            input_length=input_length,
            input_length_bucket=cls._length_bucket(input_length),
            prompt_length=prompt_length,
            prompt_length_bucket=cls._length_bucket(prompt_length),
            node_task=node_task,
        )

    @classmethod
    def collect_profile(cls, db: Session, context: ModelRouterContext) -> NodeRunProfile:
        try:
            workflow_uuid = uuid.UUID(str(context.workflow_id))
        except (TypeError, ValueError):
            return NodeRunProfile()
        deployment_uuid = None
        if context.deployment_id:
            try:
                deployment_uuid = uuid.UUID(str(context.deployment_id))
            except (TypeError, ValueError):
                return NodeRunProfile()
        query = (
            db.query(WorkflowNodeRun, WorkflowRun, LLMUsageLog, LLMModel)
            .join(WorkflowRun, WorkflowNodeRun.workflow_run_id == WorkflowRun.id)
            .outerjoin(
                LLMUsageLog,
                and_(
                    LLMUsageLog.workflow_run_id == WorkflowRun.id,
                    LLMUsageLog.node_id == WorkflowNodeRun.node_id,
                    LLMUsageLog.cost_optimizer_candidate_id.is_(None),
                ),
            )
            .outerjoin(LLMModel, LLMUsageLog.model_id == LLMModel.id)
            .filter(WorkflowRun.workflow_id == workflow_uuid)
            .filter(WorkflowRun.deployment_id.isnot(None))
            .filter(WorkflowRun.trigger_mode.in_(OPERATIONAL_TRIGGER_MODES))
            .filter(WorkflowRun.status.in_([RunStatus.SUCCESS, RunStatus.FAILED]))
            .filter(WorkflowNodeRun.node_id == context.node_id)
            .filter(WorkflowNodeRun.node_type == "llmNode")
            .filter(WorkflowNodeRun.status.in_([NodeRunStatus.SUCCESS, NodeRunStatus.FAILED]))
        )
        if deployment_uuid is not None:
            query = query.filter(WorkflowRun.deployment_id == deployment_uuid)
        rows = query.order_by(WorkflowNodeRun.started_at.desc()).limit(200).all()

        performances: dict[str, ModelPerformance] = {}
        segment_performance: dict[str, dict[str, Any]] = {}
        usable_runs = 0
        for node_run, workflow_run, usage_log, model in rows:
            metadata = (
                node_run.trace_metadata
                if isinstance(getattr(node_run, "trace_metadata", None), dict)
                else {}
            )
            llm_metadata = metadata.get("llm")
            llm_metadata = llm_metadata if isinstance(llm_metadata, dict) else {}
            model_id = (
                getattr(model, "model_id_for_api_call", None)
                or getattr(usage_log, "model_id", None)
                or llm_metadata.get("selected_model")
            )
            if not model_id:
                continue

            # usage가 누락된 실패 run도 정책의 품질 판단에는 포함한다. 비용/토큰은
            # 알 수 없지만, model_routing trace가 선택 모델을 남기므로 실패율과
            # downstream 결과를 그 모델에 귀속할 수 있다.
            usable_runs += 1
            performance = performances.setdefault(
                str(model_id), ModelPerformance(model_id=str(model_id))
            )
            performance.run_count += 1
            usage_succeeded = usage_log is None or getattr(usage_log, "status", None) == "success"
            if node_run.status == NodeRunStatus.SUCCESS and usage_succeeded:
                performance.success_count += 1
            performance.total_cost += float(getattr(usage_log, "total_cost", 0) or 0)
            performance.total_tokens += int(
                getattr(usage_log, "prompt_tokens", 0) or 0
            ) + int(getattr(usage_log, "completion_tokens", 0) or 0)
            performance.total_latency_ms += int(
                getattr(usage_log, "latency_ms", 0) or 0
            )
            performance.retry_count += int(node_run.retry_count or 0)

            # workflow engine이 저장하는 canonical contract는 trace_metadata.llm/rag다.
            # 최상위 키는 기존 실행 이력 호환을 위한 fallback으로만 유지한다.
            schema_status = (
                llm_metadata.get("schema_status")
                or metadata.get("schema_status")
                or metadata.get("schema")
            )
            if schema_status is not None:
                performance.schema_eval_count += 1
                if schema_status in ("passed", "pass", "valid", True):
                    performance.schema_pass_count += 1
            downstream_status = (
                llm_metadata.get("downstream_status")
                or metadata.get("downstream_status")
                or metadata.get("downstream")
            )
            if downstream_status is not None:
                performance.downstream_eval_count += 1
                if downstream_status in ("passed", "pass", "compatible", True):
                    performance.downstream_success_count += 1
            elif workflow_run.status in (RunStatus.SUCCESS, RunStatus.FAILED):
                # 명시적인 downstream contract check가 아직 없는 일반 실행에서는
                # workflow 전체 성공 여부를 LLM 출력이 후속 노드를 통과했는지의 보수적 근거로 사용합니다.
                performance.downstream_eval_count += 1
                if workflow_run.status == RunStatus.SUCCESS:
                    performance.downstream_success_count += 1
            if llm_metadata.get("fallback_used"):
                performance.fallback_count += 1

            conditions = cls._segment_conditions(llm_metadata)
            if conditions:
                segment_key = json.dumps(
                    conditions,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                segment = segment_performance.setdefault(
                    segment_key,
                    {"conditions": conditions, "model_performance": {}},
                )
                segment_model_performance = segment["model_performance"].setdefault(
                    str(model_id),
                    ModelPerformance(model_id=str(model_id)),
                )
                segment_model_performance.run_count += 1
                if node_run.status == NodeRunStatus.SUCCESS and usage_succeeded:
                    segment_model_performance.success_count += 1
                segment_model_performance.total_cost += float(
                    getattr(usage_log, "total_cost", 0) or 0
                )
                segment_model_performance.total_tokens += int(
                    getattr(usage_log, "prompt_tokens", 0) or 0
                ) + int(getattr(usage_log, "completion_tokens", 0) or 0)
                segment_model_performance.total_latency_ms += int(
                    getattr(usage_log, "latency_ms", 0) or 0
                )
                segment_model_performance.retry_count += int(node_run.retry_count or 0)
                schema_status = llm_metadata.get("schema_status")
                if schema_status in ("passed", "pass", "valid", True):
                    segment_model_performance.schema_eval_count += 1
                    segment_model_performance.schema_pass_count += 1
                elif schema_status in ("failed", "schema_failed", "truncated"):
                    segment_model_performance.schema_eval_count += 1
                downstream_status = llm_metadata.get("downstream_status")
                if downstream_status in ("passed", "pass", "compatible", True):
                    segment_model_performance.downstream_eval_count += 1
                    segment_model_performance.downstream_success_count += 1
                elif downstream_status in ("failed", "incompatible"):
                    segment_model_performance.downstream_eval_count += 1
                elif workflow_run.status in (RunStatus.SUCCESS, RunStatus.FAILED):
                    segment_model_performance.downstream_eval_count += 1
                    if workflow_run.status == RunStatus.SUCCESS:
                        segment_model_performance.downstream_success_count += 1
                if llm_metadata.get("fallback_used"):
                    segment_model_performance.fallback_count += 1

        return NodeRunProfile(
            operational_usable_runs=usable_runs,
            model_performance=performances,
            segment_performance=segment_performance,
        )

    @staticmethod
    def _segment_conditions(llm_metadata: dict[str, Any]) -> dict[str, Any]:
        """입력 원문 없이 policy rule에 쓸 수 있는 일반적인 실행 특징만 남긴다."""
        allowed = (
            "customer_facing",
            "knowledge_enabled",
            "output_format",
            "schema_required",
            "has_file_input",
            "input_length_bucket",
            "prompt_length_bucket",
            "node_task",
        )
        conditions = {
            key: llm_metadata[key]
            for key in allowed
            if key in llm_metadata and llm_metadata[key] is not None
        }
        return conditions

    @classmethod
    def collect_candidates(
        cls, db: Session, *, organization_id: uuid.UUID
    ) -> list[ModelCandidate]:
        models = (
            db.query(LLMModel)
            .join(LLMRelCredentialModel, LLMRelCredentialModel.model_id == LLMModel.id)
            .join(LLMCredential, LLMCredential.id == LLMRelCredentialModel.credential_id)
            .filter(LLMModel.is_active.is_(True))
            .filter(LLMModel.type == "chat")
            .filter(LLMCredential.organization_id == organization_id)
            .filter(LLMCredential.is_valid.is_(True))
            .filter(LLMRelCredentialModel.is_verified.is_(True))
            .all()
        )
        by_model_id: dict[str, ModelCandidate] = {}
        for model in models:
            if not cls.is_workflow_chat_model(model):
                continue
            candidate = ModelCandidate.from_model(model)
            by_model_id[candidate.model_id] = candidate
        return list(by_model_id.values())

    @classmethod
    def is_workflow_chat_model(cls, model: Any) -> bool:
        # DB model, ModelCandidate, API model ID 문자열이 같은 경계에서 재사용된다.
        # 문자열을 getattr로 읽으면 빈 ID가 되어 정상 후보가 전부 탈락하므로 명시적으로 처리한다.
        raw_model_id = (
            model
            if isinstance(model, str)
            else getattr(model, "model_id_for_api_call", None)
            or getattr(model, "model_id", "")
        )
        model_id = cls.normalize_model_id(raw_model_id)
        model_name = str(getattr(model, "name", "") or "").lower()
        model_type = str(getattr(model, "type", "") or "").lower()
        is_active = bool(getattr(model, "is_active", True))

        if not is_active:
            return False
        if model_type in BLOCKED_WORKFLOW_MODEL_TYPES:
            return False
        if any(keyword in model_id for keyword in BLOCKED_WORKFLOW_MODEL_KEYWORDS):
            return False
        if any(keyword in model_name for keyword in BLOCKED_WORKFLOW_MODEL_KEYWORDS):
            return False
        if VERSION_SUFFIX_PATTERN.search(model_id):
            return False
        return model_id in WORKFLOW_CHAT_MODEL_ALIASES

    @staticmethod
    def normalize_model_id(model_id: str) -> str:
        return str(model_id or "").lower().removeprefix("models/")

    @classmethod
    def _matches_rule(
        cls,
        when: Any,
        runtime_context: ModelRoutingRuntimeContext,
    ) -> bool:
        if when in (None, {}, []):
            return True
        if not isinstance(when, dict):
            return False
        if any(key not in cls.POLICY_CONDITION_KEYS for key in when):
            return False
        context = runtime_context.as_metadata()
        keyword_any = cls._rule_terms(when.get("keyword_any"))
        keyword_all = cls._rule_terms(when.get("keyword_all"))
        if "keyword_any" in when and not keyword_any:
            return False
        if "keyword_all" in when and not keyword_all:
            return False
        text = " ".join(str(runtime_context.text or "").casefold().split())
        matched_any = [term for term in keyword_any if term in text]
        if keyword_all and any(term not in text for term in keyword_all):
            return False
        if keyword_any:
            try:
                minimum_matches = int(when.get("minimum_keyword_matches") or 1)
            except (TypeError, ValueError):
                minimum_matches = 1
            if len(matched_any) < max(1, minimum_matches):
                return False
        for key in (
            "intent",
            "customer_facing",
            "knowledge_enabled",
            "output_format",
            "schema_required",
            "has_file_input",
            "input_length_bucket",
            "prompt_length_bucket",
            "node_task",
        ):
            if key not in when:
                continue
            if not cls._condition_value_matches(context.get(key), when[key]):
                return False
        return True

    @staticmethod
    def _rule_sort_key(rule: dict[str, Any]) -> tuple[int, int, int]:
        when = rule.get("when") if isinstance(rule.get("when"), dict) else {}
        specificity = -len(when)
        return (int(rule.get("priority") or 1000), specificity, 0)

    @staticmethod
    def _condition_value_matches(value: Any, condition: Any) -> bool:
        if isinstance(condition, list):
            return value in condition
        return value == condition

    @staticmethod
    def _length_bucket(length: int) -> str:
        if length <= 500:
            return "short"
        if length <= 2_000:
            return "medium"
        return "long"

    @classmethod
    def _schema_required(cls, output_format: Any) -> bool:
        if not isinstance(output_format, dict):
            return False
        if str(output_format.get("type") or "").lower() != "json":
            return False
        schema = output_format.get("schema")
        return isinstance(schema, dict) and bool(schema)

    @classmethod
    def _has_file_input(cls, value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key).casefold()
                if key_text in {
                    "file",
                    "files",
                    "file_id",
                    "filename",
                    "attachment",
                    "attachments",
                } and cls._has_meaningful_value(item):
                    return True
                if cls._has_file_input(item):
                    return True
            return False
        if isinstance(value, list):
            return any(cls._has_file_input(item) for item in value)
        return False

    @classmethod
    def _has_meaningful_value(cls, value: Any) -> bool:
        if value is None or value == "":
            return False
        if isinstance(value, dict):
            return any(cls._has_meaningful_value(item) for item in value.values())
        if isinstance(value, list):
            return any(cls._has_meaningful_value(item) for item in value)
        return True

    @classmethod
    def _first_available_model(
        cls,
        model_ids: Iterable[Any],
        allowed_models: Optional[set[str]],
        *,
        exclude: Optional[str] = None,
    ) -> Optional[str]:
        normalized_exclude = cls.normalize_model_id(exclude or "")
        for model_id in model_ids:
            candidate = cls._first_non_empty(model_id)
            if not candidate:
                continue
            normalized_candidate = cls.normalize_model_id(candidate)
            if normalized_exclude and normalized_candidate == normalized_exclude:
                continue
            if allowed_models is not None and normalized_candidate not in allowed_models:
                continue
            return candidate
        return None

    @staticmethod
    def _first_non_empty(*values: Any) -> Optional[str]:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return None

    @classmethod
    def _flatten_text(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, dict):
            parts: list[str] = []
            for key, child in value.items():
                child_text = cls._flatten_text(child)
                if child_text:
                    parts.append(f"{key}: {child_text}")
            return " ".join(parts)
        if isinstance(value, (list, tuple, set)):
            return " ".join(cls._flatten_text(item) for item in value)
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            return str(value)

    @staticmethod
    def _output_format_name(output_format: Any) -> str:
        if isinstance(output_format, dict):
            return str(output_format.get("type") or "text").lower()
        if isinstance(output_format, str):
            return output_format.lower()
        return "text"

    @classmethod
    def _normalize_candidates(
        cls, context: ModelRouterContext
    ) -> list[ModelCandidate]:
        by_id: dict[str, ModelCandidate] = {}
        for candidate in context.candidate_models:
            if isinstance(candidate, ModelCandidate):
                by_id[candidate.model_id] = candidate
            else:
                normalized = ModelCandidate.from_model(candidate)
                by_id[normalized.model_id] = normalized

        if context.current_model_id and context.current_model_id not in by_id:
            by_id[context.current_model_id] = ModelCandidate(
                model_id=context.current_model_id,
                display_name=context.current_model_id,
            )
        if context.fallback_model_id and context.fallback_model_id not in by_id:
            by_id[context.fallback_model_id] = ModelCandidate(
                model_id=context.fallback_model_id,
                display_name=context.fallback_model_id,
            )
        return list(by_id.values())

    @classmethod
    def _stage_for(cls, profile: NodeRunProfile) -> str:
        count = profile.operational_usable_runs
        if count < cls.COLD_START_MAX_USABLE_RUNS:
            return "cold_start"
        if count < cls.OPTIMIZED_MIN_USABLE_RUNS:
            return "warming_up"
        return "optimized"

    @classmethod
    def _passing_candidates(
        cls,
        candidates: list[ModelCandidate],
        profile: NodeRunProfile,
        stage: str,
    ) -> list[ModelCandidate]:
        min_samples = (
            cls.MIN_OPTIMIZED_MODEL_SAMPLES
            if stage == "optimized"
            else cls.MIN_WARMING_MODEL_SAMPLES
        )
        passing = [
            candidate
            for candidate in candidates
            if cls._passes_quality_gate(
                profile.model_performance.get(candidate.model_id), min_samples
            )
        ]
        return sorted(passing, key=lambda candidate: candidate.price_score)

    @classmethod
    def _lower_cost_candidates(
        cls, candidates: list[ModelCandidate], current_model_id: Optional[str]
    ) -> list[ModelCandidate]:
        current = next(
            (
                candidate
                for candidate in candidates
                if candidate.model_id == current_model_id
            ),
            None,
        )
        current_score = current.price_score if current is not None else float("inf")
        return [
            candidate
            for candidate in candidates
            if candidate.model_id != current_model_id
            and candidate.price_score < current_score
        ]

    @classmethod
    def _passes_quality_gate(
        cls, performance: Optional[ModelPerformance], min_samples: int
    ) -> bool:
        if performance is None or performance.run_count < min_samples:
            return False
        if (performance.success_rate or 0) < cls.SCHEMA_PASS_RATE_MIN:
            return False
        schema_rate = performance.schema_pass_rate
        if schema_rate is not None and schema_rate < cls.SCHEMA_PASS_RATE_MIN:
            return False
        downstream_rate = performance.downstream_success_rate
        if (
            downstream_rate is not None
            and downstream_rate < cls.DOWNSTREAM_SUCCESS_RATE_MIN
        ):
            return False
        fallback_rate = performance.fallback_rate
        if fallback_rate is not None and fallback_rate > cls.FALLBACK_RATE_MAX:
            return False
        return True

    @classmethod
    def _decision(
        cls,
        *,
        stage: str,
        selected: ModelCandidate,
        fallback: Optional[ModelCandidate],
        reason: str,
        profile: NodeRunProfile,
        confidence: Optional[float] = None,
    ) -> ModelRouterDecision:
        fallback_id = (
            fallback.model_id
            if fallback is not None and fallback.model_id != selected.model_id
            else None
        )
        return ModelRouterDecision(
            routing_stage=stage,
            selected_model_id=selected.model_id,
            fallback_model_id=fallback_id,
            reason=reason,
            confidence=confidence,
            metrics_snapshot=profile.as_snapshot(),
        )

    @staticmethod
    def _highest_cost_candidate(
        candidates: list[ModelCandidate], current_model_id: Optional[str]
    ) -> ModelCandidate:
        finite = [
            candidate
            for candidate in candidates
            if candidate.price_score != float("inf")
        ]
        if finite:
            return sorted(finite, key=lambda candidate: candidate.price_score)[-1]
        for candidate in candidates:
            if candidate.model_id == current_model_id:
                return candidate
        return candidates[-1]

    @classmethod
    def _current_or_highest_candidate(
        cls, candidates: list[ModelCandidate], current_model_id: Optional[str]
    ) -> ModelCandidate:
        for candidate in candidates:
            if candidate.model_id == current_model_id:
                return candidate
        return cls._highest_cost_candidate(candidates, current_model_id)


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return numerator / denominator


def _float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
