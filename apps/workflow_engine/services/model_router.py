"""Judge-first + 점진적 local learning 모델 라우팅 runtime."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from jinja2 import Environment
from sqlalchemy.orm import Session

from apps.shared.db.models.llm import (
    LLMCredential,
    LLMModel,
    LLMRelCredentialModel,
)
from apps.shared.services.model_routing_global_profile_catalog import (
    canonical_model_routing_id,
    catalog_metadata_for_model_id,
    normalize_model_id as normalize_model_routing_id,
)
from apps.shared.services.llm_model_pricing import get_model_pricing
from apps.workflow_engine.services.llm_output_contract import (
    build_json_output_schema_instruction,
    response_format_requires_json_instruction,
)
from apps.workflow_engine.services.model_routing_judge_first_policy import (
    JUDGE_FIRST_STRATEGY_ID,
)
from apps.workflow_engine.services.model_routing_decision_cache import (
    accepted_decision,
)
from apps.workflow_engine.services.model_routing_local_classifier import (
    MultilingualE5TaskRequirementClassifier,
)
from apps.workflow_engine.services.model_routing_incremental_learning import (
    TASK_REQUIREMENT_FEATURE_SCHEMA_VERSION,
)


_routing_jinja_env = Environment(autoescape=False)

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


class ModelRoutingPromptRenderError(ValueError):
    """Routing feature용 prompt template을 안전하게 렌더링할 수 없다."""


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
        return float(sum(prices)) if prices else float("inf")

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
        return self.total_cost / self.run_count if self.run_count > 0 else None

    @property
    def avg_total_tokens(self) -> Optional[float]:
        return self.total_tokens / self.run_count if self.run_count > 0 else None

    @property
    def avg_latency_ms(self) -> Optional[float]:
        return self.total_latency_ms / self.run_count if self.run_count > 0 else None

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
    decision_source: str
    strategy_id: str
    decision_factors: dict[str, Any] = field(default_factory=dict)
    requires_runtime_judge: bool = False


class ModelRoutingUnavailableError(ValueError):
    pass


class ModelRouter:
    """Judge-first와 충분히 학습된 local-first 사이만 조정한다."""

    # Judge 입력에서 이번 요청은 매 실행 달라지는 핵심 신호다. 고정 노드 프롬프트가
    # 길어도 요청 원문이 잘리지 않도록 별도 예산을 둔다.
    _JUDGE_REQUEST_CHAR_BUDGET = 2_200
    _JUDGE_TASK_DESCRIPTION_CHAR_BUDGET = 600
    _JUDGE_PROMPT_SECTION_CHAR_BUDGET = 480
    _JUDGE_OUTPUT_CONTRACT_CHAR_BUDGET = 900
    _PRIMARY_LEARNING_VARIABLE_NAMES = {
        "input",
        "inputtext",
        "instruction",
        "message",
        "prompt",
        "query",
        "question",
        "request",
        "text",
        "userinput",
    }
    _CONTEXT_LEARNING_VARIABLE_NAMES = {
        "constraints",
        "content",
        "context",
        "conversation",
        "documents",
        "evidence",
        "history",
    }

    @classmethod
    def resolve_policy(
        cls,
        policy: dict[str, Any],
        *,
        inputs: dict[str, Any],
        node_data: Any,
        available_model_ids: Optional[Iterable[str]] = None,
        routing_feature_text: str | None = None,
        learning_feature_text: str | None = None,
        node_profile: NodeRunProfile | None = None,
    ) -> ModelRoutingPolicyDecision:
        del node_profile  # 운영 품질은 refresh에서 학습 모드 전환에만 사용한다.
        active_policy = policy.get("active_policy") if isinstance(policy, dict) else None
        active_policy = active_policy if isinstance(active_policy, dict) else {}
        if active_policy.get("strategy_id") != JUDGE_FIRST_STRATEGY_ID:
            raise ModelRoutingUnavailableError(
                "Only judge_bootstrap_incremental_v1 policies are executable."
            )

        default_model_id = cls._first_non_empty(
            active_policy.get("default_model_id"),
            cls._node_data_value(node_data, "model_id"),
        )
        fallback_model_id = cls._first_non_empty(
            active_policy.get("fallback_model_id"),
            cls._node_data_value(node_data, "fallback_model_id"),
        )
        if not default_model_id:
            raise ModelRoutingUnavailableError("default model is required.")

        availability_is_enforced = available_model_ids is not None
        executable_model_ids = cls._unique_model_ids(available_model_ids or [])
        configured_candidates = cls._unique_model_ids(
            active_policy.get("candidate_model_ids") or []
        )
        # policy에 저장된 후보는 정책 생성 당시의 snapshot이다. 이후 credential에
        # 새 모델이 연결되거나 예전 policy가 기본 모델 하나만 가진 경우에도 새 후보를
        # 평가할 수 있어야 검증 기회가 사라지는 순환을 피할 수 있다.
        candidates = cls._unique_model_ids(
            [*configured_candidates, *executable_model_ids]
        )
        if availability_is_enforced:
            executable_by_canonical_id: dict[str, str] = {}
            for model_id in executable_model_ids:
                normalized_model_id = cls.normalize_model_id(model_id)
                canonical_id = canonical_model_routing_id(model_id)
                existing = executable_by_canonical_id.get(canonical_id)
                # canonical ID와 별칭이 함께 있으면 canonical API ID를 우선한다.
                # 단, 별칭만 credential에 연결된 경우에는 그 별칭을 보존한다.
                if existing is None or normalized_model_id == canonical_id:
                    executable_by_canonical_id[canonical_id] = model_id

            def available_representative(model_id: str | None) -> str | None:
                if not model_id:
                    return model_id
                return executable_by_canonical_id.get(
                    canonical_model_routing_id(model_id), model_id
                )

            default_model_id = available_representative(default_model_id)
            fallback_model_id = available_representative(fallback_model_id)
            candidates = [
                executable_by_canonical_id[canonical_model_routing_id(model_id)]
                for model_id in candidates
                if canonical_model_routing_id(model_id) in executable_by_canonical_id
            ]
            if not candidates and executable_model_ids:
                candidates = executable_model_ids
            allowed_models: set[str] | None = {
                cls.normalize_model_id(model_id) for model_id in executable_model_ids
            }
        else:
            allowed_models = None

        runtime_context = cls.infer_runtime_context(inputs, node_data)
        default_selected = cls.first_available_model(
            [default_model_id, fallback_model_id, *candidates],
            allowed_models,
        )
        if not default_selected:
            raise ModelRoutingUnavailableError(
                "No Judge-first model is available to the execution subject."
            )
        resolved_fallback = cls.first_available_model(
            [fallback_model_id, default_model_id, *candidates],
            allowed_models,
            exclude=default_selected,
        )

        learning = active_policy.get("learning")
        learning = learning if isinstance(learning, dict) else {}
        cached_decision = accepted_decision(
            learning,
            feature_text=routing_feature_text or runtime_context.text,
            available_model_ids=candidates,
        )
        if cached_decision:
            cached_selected = cls.first_available_model(
                [cached_decision.get("selected_model_id")], allowed_models
            )
            if cached_selected:
                return ModelRoutingPolicyDecision(
                    selected_model_id=cached_selected,
                    fallback_model_id=resolved_fallback,
                    matched_rule_id="accepted-judge-decision-cache",
                    reason_code=str(cached_decision.get("reason_code") or "judge_selected"),
                    runtime_context=runtime_context,
                    decision_source="accepted_judge_cache",
                    strategy_id=JUDGE_FIRST_STRATEGY_ID,
                    decision_factors={
                        "learning_mode": str(learning.get("mode") or "judge_first"),
                        "cached_judge_confidence": cached_decision.get("confidence"),
                        "candidate_model_count": len(candidates),
                    },
                )
        artifact = learning.get("local_requirement_artifact")
        artifact_is_current = (
            isinstance(artifact, dict)
            and artifact.get("feature_schema_version")
            == TASK_REQUIREMENT_FEATURE_SCHEMA_VERSION
        )
        min_confidence = cls._confidence(
            learning.get("local_confidence_threshold"),
            default=0.78,
        )
        if learning.get("mode") == "local_first" and artifact_is_current:
            low_confidence: float | None = None
            try:
                prediction = MultilingualE5TaskRequirementClassifier.predict(
                    artifact,
                    text=learning_feature_text or cls.learning_feature_text(inputs, node_data),
                )
                selected = cls.select_candidate_for_requirements(
                    candidate_model_ids=candidates,
                    requirements=prediction.requirements,
                    default_model_id=default_selected,
                )
                if selected and prediction.confidence >= min_confidence:
                    return ModelRoutingPolicyDecision(
                        selected_model_id=selected,
                        fallback_model_id=resolved_fallback,
                        matched_rule_id="incremental-local-router",
                        reason_code="local_router_confident",
                        runtime_context=runtime_context,
                        decision_source="local_router",
                        strategy_id=JUDGE_FIRST_STRATEGY_ID,
                        decision_factors={
                            "learning_mode": "local_first",
                            "local_confidence": prediction.confidence,
                            "local_confidence_threshold": min_confidence,
                            "candidate_model_count": len(candidates),
                            "task_requirements": prediction.requirements,
                            "selection_method": "catalog_capability_then_price",
                        },
                    )
                low_confidence = prediction.confidence
            except (RuntimeError, ValueError):
                pass
            return ModelRoutingPolicyDecision(
                selected_model_id=default_selected,
                fallback_model_id=resolved_fallback,
                matched_rule_id=None,
                reason_code="local_router_uncertain",
                runtime_context=runtime_context,
                decision_source="local_router_uncertain",
                strategy_id=JUDGE_FIRST_STRATEGY_ID,
                decision_factors={
                    "learning_mode": "local_first",
                    "local_confidence": low_confidence,
                    "local_confidence_threshold": min_confidence,
                    "candidate_model_count": len(candidates),
                },
                requires_runtime_judge=True,
            )

        return ModelRoutingPolicyDecision(
            selected_model_id=default_selected,
            fallback_model_id=resolved_fallback,
            matched_rule_id=None,
            reason_code="judge_bootstrap_required",
            runtime_context=runtime_context,
            decision_source="runtime_judge_pending",
            strategy_id=JUDGE_FIRST_STRATEGY_ID,
            decision_factors={
                "learning_mode": "judge_first",
                "candidate_model_count": len(candidates),
                "judged_request_count": int(learning.get("judged_request_count") or 0),
            },
            requires_runtime_judge=True,
        )

    @classmethod
    def routing_feature_text(
        cls,
        inputs: dict[str, Any],
        node_data: Any,
        *,
        rendered_prompt_parts: Iterable[str] | None = None,
        rag_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Judge/local router에 노드 작업 계약과 이번 요청의 feature를 전달한다.

        세 프롬프트는 노드가 어떤 업무를 수행하는지 알려주는 최소 작업 계약이다.
        현재 요청과 RAG runtime 신호는 같은 노드 안에서도 매 실행 달라지는 판단 재료다.
        """

        if rendered_prompt_parts is None:
            rendered_prompt_parts = cls.render_prompt_parts(inputs, node_data)

        prompt_values = list(rendered_prompt_parts)[:3]
        prompt_values.extend([""] * (3 - len(prompt_values)))
        prompt_sections = (
            ("SYSTEM_PROMPT", prompt_values[0]),
            ("USER_PROMPT", prompt_values[1]),
            ("ASSISTANT_PROMPT", prompt_values[2]),
        )
        prompt_feature = "\n\n".join(
            f"{label}:\n{cls._judge_prompt_excerpt(value)}"
            for label, value in prompt_sections
        )
        task_description = cls._judge_task_description(node_data)
        node_title = str(cls._node_data_value(node_data, "title") or "").strip()
        task_contract_parts = []
        if node_title:
            task_contract_parts.append(f"NODE_TITLE: {node_title[:120]}")
        if task_description:
            task_contract_parts.append(f"TASK_DESCRIPTION:\n{task_description}")
        task_contract_parts.append(f"PROMPT_CONSTRAINTS:\n{prompt_feature}")
        output_contract = cls._judge_output_contract(node_data)
        if output_contract:
            task_contract_parts.append(f"OUTPUT_CONTRACT:\n{output_contract}")
        request_json = cls._judge_request_json(inputs)
        safe_rag_metadata = {
            key: value
            for key, value in (rag_metadata or {}).items()
            if key
            in {
                "used",
                "retrieved_context_token_estimate",
                "retrieved_context_chars",
                "retrieved_chunk_count",
                "source_count",
                "evidence_sufficient",
                "partial_result",
                "query_rewrite_applied",
                "insufficiency_reason",
                "source_tier_used",
            }
            and isinstance(value, (bool, int, float, str))
        }
        parts = [
            f"CURRENT_REQUEST_JSON:\n{request_json}" if request_json else "",
            "NODE_TASK_CONTRACT:\n" + "\n\n".join(task_contract_parts),
        ]
        if safe_rag_metadata:
            parts.append(
                "RAG_RUNTIME_SIGNALS:\n"
                + json.dumps(safe_rag_metadata, ensure_ascii=False, sort_keys=True)
            )
        return "\n\n".join(part for part in parts if part)

    @classmethod
    def learning_feature_text(
        cls,
        inputs: dict[str, Any],
        node_data: Any,
        *,
        rendered_prompt_parts: Iterable[str] | None = None,
        rag_metadata: dict[str, Any] | None = None,
    ) -> str:
        """요청 난이도 학습용 feature를 만든다.

        노드 제목과 prompt 같은 고정 계약은 같은 policy의 모든 실행에 반복되므로
        제외한다. referenced variable의 실행값과 RAG runtime 신호만 남겨 local
        router가 요청별 차이를 학습하게 한다. 변수 메타데이터가 없는 레거시
        노드는 전체 runtime input을 안전하게 축약해 사용한다.
        """

        del rendered_prompt_parts  # routing_feature_text만 고정 prompt 계약을 사용한다.
        runtime_variables = cls._learning_runtime_variables(inputs, node_data)
        feature_groups = cls._learning_feature_groups(runtime_variables)
        safe_rag_metadata = {
            key: value
            for key, value in (rag_metadata or {}).items()
            if key
            in {
                "used",
                "retrieved_context_token_estimate",
                "retrieved_context_chars",
                "retrieved_chunk_count",
                "source_count",
                "evidence_sufficient",
                "partial_result",
                "query_rewrite_applied",
                "insufficiency_reason",
                "source_tier_used",
            }
            and isinstance(value, (bool, int, float, str))
        }
        if safe_rag_metadata:
            feature_groups["structured_features"]["rag"] = safe_rag_metadata
        bounded_groups = {
            group_name: json.loads(cls._judge_request_json(group_values))
            for group_name, group_values in feature_groups.items()
        }
        return json.dumps(
            bounded_groups,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    @classmethod
    def _learning_feature_groups(
        cls,
        runtime_variables: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """실행 변수를 의미·문맥·구조 그룹으로 분리한다."""

        groups: dict[str, dict[str, Any]] = {
            "primary_request": {},
            "dynamic_context": {},
            "structured_features": {},
        }
        for name, value in runtime_variables.items():
            normalized_name = "".join(
                char for char in str(name).lower() if char.isalnum()
            )
            if normalized_name in cls._PRIMARY_LEARNING_VARIABLE_NAMES:
                groups["primary_request"][name] = value
            elif normalized_name in cls._CONTEXT_LEARNING_VARIABLE_NAMES:
                groups["dynamic_context"][name] = value
            elif isinstance(value, (dict, list, tuple, set)):
                groups["dynamic_context"][name] = value
            elif isinstance(value, str) and len(value.strip()) > 64:
                groups["dynamic_context"][name] = value
            else:
                groups["structured_features"][name] = value

        if not groups["primary_request"] and runtime_variables:
            # 이름이 낯선 사용자 정의 변수도 가장 정보량이 큰 실행값을 요청 본문으로
            # 사용할 수 있게 한다. 고정 prompt나 변수명별 제품 하드코딩은 사용하지 않는다.
            primary_name = max(
                runtime_variables,
                key=lambda key: len(cls._flatten_text(runtime_variables[key])),
            )
            groups["primary_request"][primary_name] = runtime_variables[primary_name]
            groups["dynamic_context"].pop(primary_name, None)
            groups["structured_features"].pop(primary_name, None)
        return groups

    @classmethod
    def _learning_runtime_variables(
        cls,
        inputs: dict[str, Any],
        node_data: Any,
    ) -> dict[str, Any]:
        """referenced variable의 실행값만 local learning 입력으로 투영한다."""

        referenced_variables = cls._node_data_value(
            node_data,
            "referenced_variables",
            default=[],
        )
        if not isinstance(referenced_variables, list):
            referenced_variables = []

        values: dict[str, Any] = {}
        for variable in referenced_variables:
            name = str(
                cls._node_data_value(variable, "name", default="") or ""
            ).strip()
            selector = cls._node_data_value(
                variable,
                "value_selector",
                default=[],
            )
            if not name:
                continue

            value = None
            if isinstance(selector, list) and selector:
                source = inputs.get(str(selector[0]))
                value = cls._nested_value(source, selector[1:])
            if value is None and name in inputs:
                value = inputs.get(name)
            if value is not None:
                values[name] = value

        return values or inputs

    @classmethod
    def select_candidate_for_requirements(
        cls,
        *,
        candidate_model_ids: Iterable[str],
        requirements: Mapping[str, Any],
        candidate_profiles: Iterable[Mapping[str, Any]] | None = None,
        default_model_id: str | None = None,
        structural_facts: Mapping[str, Any] | None = None,
    ) -> str | None:
        """현재 사용 가능한 후보 중 요구 수준을 충족하는 가장 경제적인 모델을 고른다.

        운영 성적은 정책 갱신과 local router 전환을 판단하는 데 사용한다. 새 후보를
        runtime에서 배제하면 검증할 기회 자체가 사라지므로, Judge가 평가한 현재 요청의
        요구 수준과 현재 credential/capability 경계 안에서는 전체 후보를 비교한다.
        """

        complexity = cls._requirement_score(requirements.get("task_complexity"))
        impact = cls._requirement_score(requirements.get("decision_impact"))
        evidence = cls._requirement_score(requirements.get("evidence_synthesis"))
        required_ceiling = max(complexity, impact, evidence)
        ceiling_rank = {"routine": 1, "multi_constraint": 2, "complex_professional": 3}
        reasoning_rank = {
            "non_reasoning": 0,
            "general_reasoning": 2,
            "frontier_reasoning": 3,
            "specialized_reasoning": 3,
        }
        profile_by_model = {
            cls.normalize_model_id(str(profile.get("model_id") or "")): profile
            for profile in (candidate_profiles or [])
            if isinstance(profile, Mapping) and profile.get("model_id")
        }
        normalized_default = cls.normalize_model_id(default_model_id or "")
        eligible: list[tuple[float, str]] = []
        for model_id in cls._unique_model_ids(candidate_model_ids):
            normalized_model_id = cls.normalize_model_id(model_id)
            profile = profile_by_model.get(normalized_model_id, {})
            is_default = bool(normalized_default) and normalized_model_id == normalized_default
            metadata = catalog_metadata_for_model_id(model_id)
            if not metadata:
                if is_default:
                    eligible.append((float("inf"), model_id))
                continue
            model_ceiling = ceiling_rank.get(str(metadata.get("complexity_ceiling")), 0)
            reasoning = reasoning_rank.get(str(metadata.get("reasoning_profile")), 0)
            if model_ceiling < required_ceiling:
                continue
            if evidence >= 2 and reasoning < 2:
                continue
            input_price = profile.get("input_price_per_1k")
            output_price = profile.get("output_price_per_1k")
            if isinstance(input_price, (int, float)) and isinstance(
                output_price, (int, float)
            ):
                price = float(input_price) + float(output_price)
            else:
                pricing = get_model_pricing(model_id)
                price = (
                    float(pricing.standard_input_per_1k + pricing.standard_output_per_1k)
                    if pricing is not None
                    else float("inf")
                )
            eligible.append((price, model_id))
        if not eligible:
            return cls.first_available_model(
                [default_model_id],
                {cls.normalize_model_id(model_id) for model_id in candidate_model_ids},
            )
        return min(eligible, key=lambda row: (row[0], row[1]))[1]

    @classmethod
    def runtime_requirement_facts(
        cls,
        *,
        inputs: Mapping[str, Any],
        node_data: Any,
        rag_metadata: Mapping[str, Any] | None = None,
        downstream_contract_required: bool = False,
    ) -> dict[str, Any]:
        """LLM이 추측할 필요가 없는 실행 구조 사실을 계산한다."""

        output_format = cls._node_data_value(node_data, "output_format", default={})
        output_format = output_format if isinstance(output_format, dict) else {}
        output_type = str(output_format.get("type") or "text").strip().lower()
        serialized_size = len(
            json.dumps(dict(inputs), ensure_ascii=False, default=str)
        )
        if serialized_size < 2_000:
            input_bucket = "short"
        elif serialized_size < 12_000:
            input_bucket = "medium"
        else:
            input_bucket = "long"
        knowledge_bases = cls._node_data_value(
            node_data, "knowledgeBases", default=[]
        ) or cls._node_data_value(node_data, "knowledge_bases", default=[])
        rag = rag_metadata if isinstance(rag_metadata, Mapping) else {}
        return {
            "input_token_bucket": input_bucket,
            "schema_required": bool(output_format.get("schema")),
            "knowledge_enabled": bool(knowledge_bases) or bool(rag.get("used")),
            "retrieved_source_count": max(
                0,
                int(rag.get("source_count") or rag.get("retrieved_chunk_count") or 0),
            ),
            "output_format": output_type,
            "downstream_contract_required": bool(downstream_contract_required),
            "file_input_present": cls._contains_file_like_value(inputs),
        }

    @classmethod
    def _contains_file_like_value(cls, value: Any) -> bool:
        if isinstance(value, Mapping):
            if any(
                str(key).lower() in {"file", "files", "filename", "mime_type"}
                for key in value
            ):
                return True
            return any(cls._contains_file_like_value(child) for child in value.values())
        if isinstance(value, (list, tuple)):
            return any(cls._contains_file_like_value(child) for child in value)
        return False

    @staticmethod
    def _requirement_score(value: Any) -> int:
        if isinstance(value, bool):
            return 0
        try:
            return max(0, min(3, int(value)))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _judge_request_json(cls, inputs: dict[str, Any]) -> str:
        """Preserve request keys and scalar types within the Judge budget."""

        for string_limit, item_limit in ((900, 24), (360, 16), (160, 10)):
            bounded = cls._bounded_judge_value(
                inputs,
                string_limit=string_limit,
                item_limit=item_limit,
            )
            serialized = json.dumps(
                bounded,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if len(serialized) <= cls._JUDGE_REQUEST_CHAR_BUDGET:
                return serialized

        preview_budget = max(cls._JUDGE_REQUEST_CHAR_BUDGET - 80, 0)
        return json.dumps(
            {
                "_truncated": True,
                "text_preview": cls._flatten_text(inputs)[:preview_budget],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @classmethod
    def _bounded_judge_value(
        cls,
        value: Any,
        *,
        string_limit: int,
        item_limit: int,
    ) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            if len(value) <= string_limit:
                return value
            return value[: string_limit - 1].rstrip() + "…"
        if isinstance(value, dict):
            items = list(value.items())
            result = {
                str(key): cls._bounded_judge_value(
                    child,
                    string_limit=string_limit,
                    item_limit=item_limit,
                )
                for key, child in items[:item_limit]
            }
            if len(items) > item_limit:
                result["_omitted_key_count"] = len(items) - item_limit
            return result
        if isinstance(value, (list, tuple, set)):
            items = list(value)
            result = [
                cls._bounded_judge_value(
                    child,
                    string_limit=string_limit,
                    item_limit=item_limit,
                )
                for child in items[:item_limit]
            ]
            if len(items) > item_limit:
                result.append({"_omitted_item_count": len(items) - item_limit})
            return result
        return str(value)[:string_limit]

    @classmethod
    def _judge_prompt_excerpt(cls, value: Any) -> str:
        text = str(value or "").strip()
        if len(text) <= cls._JUDGE_PROMPT_SECTION_CHAR_BUDGET:
            return text
        return text[: cls._JUDGE_PROMPT_SECTION_CHAR_BUDGET - 1].rstrip() + "…"

    @classmethod
    def _judge_output_contract(cls, node_data: Any) -> str:
        """구조화 출력 복잡도 신호를 prompt 예산과 독립적으로 보존한다."""

        parameters = cls._node_data_value(node_data, "parameters", default={})
        parameters = parameters if isinstance(parameters, Mapping) else {}
        output_format = cls._node_data_value(node_data, "output_format")
        force_json_object = response_format_requires_json_instruction(
            parameters.get("response_format")
        )
        schema_instruction = build_json_output_schema_instruction(
            output_format,
            force_json_object=force_json_object,
        )
        if not schema_instruction:
            return ""

        schema = (
            output_format.get("schema") if isinstance(output_format, dict) else None
        )
        properties = schema.get("properties") if isinstance(schema, dict) else None
        required = schema.get("required") if isinstance(schema, dict) else None
        summary = (
            "OUTPUT_MODE: json_object\n"
            "SCHEMA_PRESENT: "
            f"{str(isinstance(schema, dict) and bool(schema)).lower()}\n"
            "TOP_LEVEL_TYPE: "
            f"{schema.get('type', 'unspecified') if isinstance(schema, dict) else 'unspecified'}\n"
            "TOP_LEVEL_PROPERTY_COUNT: "
            f"{len(properties) if isinstance(properties, dict) else 0}\n"
            "REQUIRED_PROPERTY_COUNT: "
            f"{len(required) if isinstance(required, list) else 0}"
        )
        contract = f"{summary}\n\n{schema_instruction}"
        if len(contract) <= cls._JUDGE_OUTPUT_CONTRACT_CHAR_BUDGET:
            return contract
        return (
            contract[: cls._JUDGE_OUTPUT_CONTRACT_CHAR_BUDGET - 1].rstrip() + "…"
        )

    @classmethod
    def _judge_task_description(cls, node_data: Any) -> str:
        """사용자가 적은 작업 설명을 고정 작업 계약의 중심 정보로 사용한다."""

        value = str(
            cls._node_data_value(node_data, "model_routing_task_description") or ""
        ).strip()
        if len(value) <= cls._JUDGE_TASK_DESCRIPTION_CHAR_BUDGET:
            return value
        return value[: cls._JUDGE_TASK_DESCRIPTION_CHAR_BUDGET - 1].rstrip() + "…"

    @classmethod
    def infer_runtime_context(
        cls,
        inputs: dict[str, Any],
        node_data: Any,
    ) -> ModelRoutingRuntimeContext:
        text = cls._flatten_text(inputs)
        prompts = " ".join(
            prompt
            for prompt in (
                str(cls._node_data_value(node_data, field) or "").strip()
                for field in ("system_prompt", "user_prompt", "assistant_prompt")
            )
            if prompt
        )
        routing_context = cls._node_data_value(node_data, "model_routing_context")
        routing_context = routing_context if isinstance(routing_context, dict) else {}
        output_format_value = cls._node_data_value(node_data, "output_format")
        knowledge_enabled = bool(
            cls._node_data_value(node_data, "knowledgeBases")
            or cls._node_data_value(node_data, "knowledgeCollections")
        )
        node_task = cls._first_non_empty(
            routing_context.get("node_task"),
            routing_context.get("category"),
            cls._node_data_value(node_data, "task_type"),
        ) or "generate"
        return ModelRoutingRuntimeContext(
            text=text,
            intent=cls._first_non_empty(routing_context.get("intent"), node_task)
            or "generate",
            risk_level=cls._first_non_empty(routing_context.get("risk_level"))
            or "medium",
            customer_facing=bool(routing_context.get("customer_facing", False)),
            knowledge_enabled=knowledge_enabled,
            output_format=cls._output_format_name(output_format_value),
            schema_required=cls._schema_required(output_format_value),
            has_file_input=cls._has_file_input(inputs),
            input_length=len(text),
            input_length_bucket=cls._length_bucket(len(text)),
            prompt_length=len(prompts),
            prompt_length_bucket=cls._length_bucket(len(prompts)),
            node_task=node_task,
        )

    @classmethod
    def collect_candidates(
        cls,
        db: Session,
        *,
        organization_id: uuid.UUID,
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
            if cls.is_workflow_chat_model(model):
                candidate = ModelCandidate.from_model(model)
                by_model_id[candidate.model_id] = candidate
        return list(by_model_id.values())

    @classmethod
    def is_workflow_chat_model(cls, model: Any) -> bool:
        raw_model_id = (
            model
            if isinstance(model, str)
            else getattr(model, "model_id_for_api_call", None)
            or getattr(model, "model_id", "")
        )
        model_id = cls.normalize_model_id(raw_model_id)
        model_name = str(getattr(model, "name", "") or "").lower()
        model_type = str(getattr(model, "type", "") or "").lower()
        if not bool(getattr(model, "is_active", True)):
            return False
        if model_type in BLOCKED_WORKFLOW_MODEL_TYPES:
            return False
        if any(keyword in model_id for keyword in BLOCKED_WORKFLOW_MODEL_KEYWORDS):
            return False
        if any(keyword in model_name for keyword in BLOCKED_WORKFLOW_MODEL_KEYWORDS):
            return False
        return model_id in WORKFLOW_CHAT_MODEL_ALIASES

    @staticmethod
    def normalize_model_id(model_id: Any) -> str:
        return normalize_model_routing_id(model_id)

    @classmethod
    def first_available_model(
        cls,
        model_ids: Iterable[Any],
        allowed_models: Optional[set[str]],
        *,
        exclude: Optional[str] = None,
    ) -> Optional[str]:
        normalized_exclude = cls.normalize_model_id(exclude)
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
    def render_prompt_parts(
        cls,
        inputs: dict[str, Any],
        node_data: Any,
    ) -> tuple[str, str, str]:
        """Preview와 runtime routing이 공유하는 side-effect 없는 prompt renderer."""

        values: dict[str, Any] = {}
        referenced_variables = cls._node_data_value(
            node_data,
            "referenced_variables",
            default=[],
        )
        if not isinstance(referenced_variables, list):
            referenced_variables = []
        for variable in referenced_variables:
            name = str(cls._node_data_value(variable, "name", default="") or "").strip()
            selector = cls._node_data_value(variable, "value_selector", default=[])
            if not name or not isinstance(selector, list) or not selector:
                continue
            source = inputs.get(str(selector[0]))
            value = cls._nested_value(source, selector[1:])
            values[name] = value if value is not None else ""
        rendered = {
            field: cls._render_template(
                cls._node_data_value(node_data, field, default=""), values
            )
            for field in ("system_prompt", "user_prompt", "assistant_prompt")
        }
        return (
            rendered["system_prompt"],
            rendered["user_prompt"],
            rendered["assistant_prompt"],
        )

    @staticmethod
    def _node_data_value(value: Any, field: str, *, default: Any = None) -> Any:
        if isinstance(value, Mapping):
            return value.get(field, default)
        return getattr(value, field, default)

    @staticmethod
    def _nested_value(value: Any, path: list[Any]) -> Any:
        current = value
        for key in path:
            if not isinstance(current, Mapping):
                return None
            current = current.get(str(key))
        return current

    @staticmethod
    def _render_template(template: Any, context: dict[str, Any]) -> str:
        source = str(template or "")
        if not source:
            return ""
        try:
            return _routing_jinja_env.from_string(source).render(**context)
        except Exception as exc:
            raise ModelRoutingPromptRenderError(
                "model_routing.prompt_render_failed"
            ) from exc

    @classmethod
    def _flatten_text(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, dict):
            return " ".join(
                f"{key}: {child_text}"
                for key, child in value.items()
                if (child_text := cls._flatten_text(child))
            )
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
        return str(output_format or "text").lower()

    @staticmethod
    def _schema_required(output_format: Any) -> bool:
        return (
            isinstance(output_format, dict)
            and str(output_format.get("type") or "").lower() == "json"
            and isinstance(output_format.get("schema"), dict)
            and bool(output_format.get("schema"))
        )

    @classmethod
    def _has_file_input(cls, value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).casefold() in {
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
        if isinstance(value, list):
            return any(cls._has_file_input(item) for item in value)
        return False

    @classmethod
    def _has_meaningful_value(cls, value: Any) -> bool:
        if value in (None, ""):
            return False
        if isinstance(value, dict):
            return any(cls._has_meaningful_value(item) for item in value.values())
        if isinstance(value, list):
            return any(cls._has_meaningful_value(item) for item in value)
        return True

    @staticmethod
    def _length_bucket(length: int) -> str:
        if length <= 500:
            return "short"
        if length <= 2_000:
            return "medium"
        return "long"

    @staticmethod
    def _confidence(value: Any, *, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _unique_model_ids(model_ids: Iterable[Any]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for model_id in model_ids:
            value = str(model_id or "").strip()
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    return numerator / denominator if denominator > 0 else None


def _float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
