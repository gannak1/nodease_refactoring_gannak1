import json
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Optional

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


OPERATIONAL_TRIGGER_MODES = {
    RunTriggerMode.API,
    RunTriggerMode.WEBHOOK,
    RunTriggerMode.SCHEDULER,
    RunTriggerMode.APP,
}

WORKFLOW_CHAT_MODEL_ALIASES = {
    "gpt-5.5",
    "gpt-5.5-pro",
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
        rules = active_policy.get("rules")
        normalized_rules = [
            rule
            for rule in (rules if isinstance(rules, list) else [])
            if isinstance(rule, dict)
        ]
        normalized_rules.sort(key=cls._rule_sort_key)

        for rule in normalized_rules:
            if not cls._matches_rule(rule.get("when"), runtime_context):
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
        )

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
        knowledge_enabled = bool(getattr(node_data, "knowledgeBases", None))
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
            .order_by(WorkflowNodeRun.started_at.desc())
            .limit(200)
        )
        if context.deployment_id:
            try:
                deployment_uuid = uuid.UUID(str(context.deployment_id))
            except (TypeError, ValueError):
                return NodeRunProfile()
            query = query.filter(WorkflowRun.deployment_id == deployment_uuid)
        rows = query.all()

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
        return {
            key: llm_metadata[key]
            for key in allowed
            if key in llm_metadata and llm_metadata[key] is not None
        }

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
        model_id = cls.normalize_model_id(getattr(model, "model_id_for_api_call", ""))
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
        cls, when: Any, runtime_context: ModelRoutingRuntimeContext
    ) -> bool:
        if when in (None, {}, []):
            return True
        if not isinstance(when, dict):
            return False
        if any(key not in cls.POLICY_CONDITION_KEYS for key in when):
            return False
        context = runtime_context.as_metadata()
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
        keywords = when.get("keyword_any")
        if keywords is not None:
            if not isinstance(keywords, list):
                return False
            normalized_keywords = [
                str(keyword).strip().casefold()
                for keyword in keywords
                if str(keyword).strip()
            ]
            if not normalized_keywords:
                return False
            text = runtime_context.text.casefold()
            if not any(keyword in text for keyword in normalized_keywords):
                return False
        return True

    @staticmethod
    def _rule_sort_key(rule: dict[str, Any]) -> tuple[int, int, int]:
        when = rule.get("when") if isinstance(rule.get("when"), dict) else {}
        keyword_weight = 0 if when.get("keyword_any") else 1
        specificity = -len(when)
        return (keyword_weight, int(rule.get("priority") or 1000), specificity)

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
                if key_text in {"file", "files", "filename", "attachment", "attachments"}:
                    return True
                if cls._has_file_input(item):
                    return True
            return False
        if isinstance(value, list):
            return any(cls._has_file_input(item) for item in value)
        return False

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
