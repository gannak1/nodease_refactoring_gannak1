import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from apps.shared.db.models.llm import LLMModel

from apps.workflow_engine.services.llm_service import LLMService
from apps.workflow_engine.services.model_router import ModelCandidate, ModelRouter


POLICY_JUDGE_PROMPT_VERSION = "model-routing-policy-judge-v1"
ALLOWED_REFRESH_STATUSES = {"applied", "kept_current", "pending_review", "failed"}
STRUCTURED_OUTPUT_RISKY_MODEL_KEYWORDS = (
    "nano",
)


@dataclass(frozen=True)
class ModelRoutingPolicyRefreshRequest:
    workflow_id: str
    node_id: str
    user_id: uuid.UUID
    organization_id: uuid.UUID
    current_policy: Optional[dict[str, Any]]
    candidate_models: list[ModelCandidate]
    recent_runs: list[dict[str, Any]] = field(default_factory=list)
    node_summary: dict[str, Any] = field(default_factory=dict)
    trigger: str = "manual_refresh"
    judge_model_id: str = "gpt-4.1-mini"


@dataclass(frozen=True)
class ModelRoutingPolicyRefreshResult:
    status: str
    policy: dict[str, Any]
    reason: str
    judge_model_id: str
    judge_usage: dict[str, Any]
    metadata: dict[str, Any]
    judge_credential_id: Optional[uuid.UUID] = None
    judge_provider: Optional[str] = None


class ModelRoutingPolicyRefreshService:
    """Judge 결과를 검증된 runtime policy로 변환하는 서비스."""

    MIN_MODEL_QUALITY_SAMPLES = 5
    MIN_JUDGE_CONFIDENCE = 0.7

    @classmethod
    def refresh_policy(
        cls,
        db: Session,
        request: ModelRoutingPolicyRefreshRequest,
        *,
        judge_client: Any | None = None,
    ) -> ModelRoutingPolicyRefreshResult:
        candidates = cls._sanitize_candidates(request.candidate_models)
        if not candidates:
            current_policy = request.current_policy or {}
            return ModelRoutingPolicyRefreshResult(
                status="failed",
                policy=current_policy,
                reason="실행 가능한 모델 후보가 없습니다.",
                judge_model_id=request.judge_model_id,
                judge_usage={},
                metadata=cls._metadata(request, "failed", 0, None),
            )

        messages = cls._build_messages(request, candidates)
        selection = None
        judge_provider = None
        if judge_client is None:
            selection = LLMService.get_runtime_client_for_user(
                db,
                user_id=request.user_id,
                model_id=request.judge_model_id,
                organization_id=request.organization_id,
            )
            judge_client = selection.client
            judge_provider = cls._provider_for_model(db, selection.model_id)

        response = judge_client.invoke_sync(messages, temperature=0.0, max_tokens=1200)
        usage = cls._usage_from_response(response)
        try:
            generated = cls._parse_judge_response(cls._content_from_response(response))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            current_policy = request.current_policy or {}
            return ModelRoutingPolicyRefreshResult(
                status="failed",
                policy=cls._with_refresh_status(current_policy, "failed"),
                reason=f"judge 응답을 정책 JSON으로 해석하지 못했습니다: {type(exc).__name__}",
                judge_model_id=selection.model_id if selection is not None else request.judge_model_id,
                judge_usage=usage,
                metadata=cls._metadata(request, "failed", len(candidates), usage),
                judge_credential_id=selection.credential_id if selection else None,
                judge_provider=judge_provider,
            )
        policy, status, reason = cls._normalize_generated_policy(
            generated,
            current_policy=request.current_policy,
            candidates=candidates,
            recent_runs=request.recent_runs,
        )
        metadata = cls._metadata(
            request,
            status,
            len(candidates),
            usage,
            generated_policy_version=policy.get("policy_version"),
            confidence=cls._confidence(generated.get("confidence")),
        )
        return ModelRoutingPolicyRefreshResult(
            status=status,
            policy=policy,
            reason=reason,
            judge_model_id=selection.model_id if selection is not None else request.judge_model_id,
            judge_usage=usage,
            metadata=metadata,
            judge_credential_id=selection.credential_id if selection else None,
            judge_provider=judge_provider,
        )

    @staticmethod
    def _provider_for_model(db: Session | None, model_id: str) -> Optional[str]:
        if db is None:
            return None
        model = (
            db.query(LLMModel)
            .filter(LLMModel.model_id_for_api_call == model_id)
            .first()
        )
        provider = getattr(model, "provider", None) if model is not None else None
        return str(getattr(provider, "name", "") or "") or None

    @classmethod
    def default_rule_policy(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        candidate_models: list[ModelCandidate],
        refresh_every_runs: int = 20,
    ) -> dict[str, Any]:
        cheap, mid, high = cls._tier_models(candidate_models)
        structured_cheap = cls._structured_output_model(candidate_models, fallback=cheap)
        structured_fallback = cls._first_distinct_model(
            [mid, high, cheap],
            exclude=structured_cheap.model_id,
        )
        return {
            "status": "active",
            "policy_id": policy_id,
            "policy_version": policy_version,
            "active_policy": {
                "default_model_id": mid.model_id,
                "fallback_model_id": high.model_id,
                "rules": [
                    {
                        "id": "long-input-strong-model",
                        "priority": 10,
                        "when": {"input_length_bucket": "long"},
                        "selected_model_id": high.model_id,
                        "fallback_model_id": None,
                        "reason_code": "long_input_uses_strong_model",
                    },
                    {
                        "id": "customer-facing-balanced",
                        "priority": 20,
                        "when": {"customer_facing": True},
                        "selected_model_id": mid.model_id,
                        "fallback_model_id": high.model_id,
                        "reason_code": "customer_facing_uses_balanced_model",
                    },
                    {
                        "id": "knowledge-enabled-balanced",
                        "priority": 30,
                        "when": {"knowledge_enabled": True},
                        "selected_model_id": mid.model_id,
                        "fallback_model_id": high.model_id,
                        "reason_code": "rag_context_uses_balanced_model",
                    },
                    {
                        "id": "short-json-no-knowledge",
                        "priority": 40,
                        "when": {
                            "output_format": "json",
                            "knowledge_enabled": False,
                            "input_length_bucket": "short",
                        },
                        "selected_model_id": structured_cheap.model_id,
                        "fallback_model_id": (
                            structured_fallback.model_id
                            if structured_fallback is not None
                            else None
                        ),
                        "reason_code": "short_structured_input_uses_low_cost_model",
                    },
                ],
            },
            "refresh": {
                "refresh_every_runs": cls._normalize_refresh_every_runs(
                    refresh_every_runs
                ),
                "last_refresh_result": "bootstrap",
                "last_refresh_trigger": "bootstrap",
            },
        }

    @classmethod
    def _build_messages(
        cls,
        request: ModelRoutingPolicyRefreshRequest,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        payload = {
            "workflow_id": request.workflow_id,
            "node_id": request.node_id,
            "trigger": request.trigger,
            "node_summary": request.node_summary,
            "candidate_models": candidates,
            "current_policy": request.current_policy,
            "recent_runs": request.recent_runs[-40:],
            "required_schema": {
                "status": "applied | kept_current | pending_review",
                "confidence": "number from 0 to 1",
                "default_model_id": "model id",
                "fallback_model_id": "model id or null",
                "rules": [
                    {
                        "id": "stable short id",
                        "priority": 10,
                        "when": {
                            "intent": "optional explicit node intent",
                            "customer_facing": "optional boolean",
                            "knowledge_enabled": "optional boolean",
                            "output_format": "optional text/json",
                            "schema_required": "optional boolean",
                            "has_file_input": "optional boolean",
                            "input_length_bucket": "optional short/medium/long",
                            "prompt_length_bucket": "optional short/medium/long",
                            "node_task": "optional node task/category",
                            "keyword_any": "optional domain keyword array generated from recent runs",
                        },
                        "selected_model_id": "candidate model id",
                        "fallback_model_id": "candidate model id or null",
                        "reason_code": "snake_case reason",
                    }
                ],
            },
        }
        return [
            {
                "role": "system",
                "content": (
                    "You generate safe JSON model-routing policies for a workflow LLM node. "
                    "Use only candidate model ids. Return JSON only. "
                    "Do not include secrets or raw user payloads. "
                    "Runtime code has no domain keyword classifier. If domain terms matter, "
                    "put them explicitly in rules[].when.keyword_any. Prefer generic conditions "
                    "such as output_format, knowledge_enabled, schema_required, customer_facing, "
                    "node_task, and input_length_bucket when they are sufficient. "
                    "When using keyword_any, include exact source-language terms from recent run "
                    "summaries. Korean terms must remain Korean; do not replace them with "
                    "English-only translations."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            },
        ]

    @classmethod
    def _normalize_generated_policy(
        cls,
        generated: dict[str, Any],
        *,
        current_policy: Optional[dict[str, Any]],
        candidates: list[dict[str, Any]],
        recent_runs: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], str, str]:
        candidate_ids = {candidate["model_id"] for candidate in candidates}
        status = str(generated.get("status") or "pending_review")
        if status not in ALLOWED_REFRESH_STATUSES:
            status = "pending_review"

        # Judge가 명시적으로 현재 정책을 유지하라고 판단한 경우에는
        # 새 rule set을 만들지 않고 active snapshot/version을 그대로 보존한다.
        if status == "kept_current" and current_policy:
            return (
                cls._with_refresh_status(current_policy, "kept_current"),
                "kept_current",
                "검증된 변경 후보가 없어 기존 정책을 유지합니다.",
            )

        confidence = cls._confidence(generated.get("confidence"))
        if confidence < cls.MIN_JUDGE_CONFIDENCE:
            current = current_policy or {}
            return (
                cls._with_refresh_status(current, "pending_review"),
                "pending_review",
                "judge confidence가 정책 반영 기준보다 낮아 기존 정책을 유지합니다.",
            )

        raw_rules = [
            rule
            for rule in generated.get("rules", [])
            if isinstance(rule, dict)
            and str(rule.get("selected_model_id") or "") in candidate_ids
        ]
        sanitized_rules = cls._sanitize_rules(raw_rules, candidate_ids)
        if not sanitized_rules:
            fallback_policy = current_policy or {}
            return (
                cls._with_refresh_status(fallback_policy, "pending_review"),
                "pending_review",
                "judge가 실행 가능한 rule을 만들지 못해 기존 정책을 유지합니다.",
            )

        default_model = str(generated.get("default_model_id") or "").strip()
        fallback_model = str(generated.get("fallback_model_id") or "").strip() or None
        if default_model not in candidate_ids:
            default_model = sanitized_rules[0]["selected_model_id"]
        if fallback_model not in candidate_ids:
            fallback_model = None

        quality_metrics = cls._quality_metrics_by_model(recent_runs)
        changed_models = cls._changed_primary_models(
            current_policy,
            default_model=default_model,
            rules=sanitized_rules,
        )
        unverified_models = {
            model_id
            for model_id in changed_models
            if model_id
            and not cls._passes_model_quality_gate(quality_metrics.get(model_id))
        }
        if unverified_models:
            current = current_policy or {}
            return (
                cls._with_refresh_status(current, "pending_review"),
                "pending_review",
                "검증된 운영 표본이 없는 모델은 자동 정책에 반영하지 않습니다.",
            )

        if changed_models and not cls._has_efficiency_evidence(
            changed_models,
            current_policy=current_policy,
            candidates=candidates,
            quality_metrics=quality_metrics,
        ):
            current = current_policy or {}
            return (
                cls._with_refresh_status(current, "kept_current"),
                "kept_current",
                "비용 또는 latency 개선 근거가 부족해 기존 정책을 유지합니다.",
            )

        policy_id = str(
            (current_policy or {}).get("policy_id") or "model-router-policy"
        )
        previous_version = str((current_policy or {}).get("policy_version") or "v0")
        refresh_every_runs = cls._refresh_every_runs_from_policy(current_policy)
        policy = {
            "status": "active" if status in {"applied", "kept_current"} else status,
            "policy_id": policy_id,
            "policy_version": cls._next_policy_version(previous_version),
            "active_policy": {
                "default_model_id": default_model,
                "fallback_model_id": fallback_model,
                "rules": sanitized_rules,
            },
            "refresh": {
                "refresh_every_runs": refresh_every_runs,
                "last_refresh_result": status,
                "last_refresh_trigger": generated.get("trigger"),
            },
        }
        return policy, status, str(generated.get("reason") or "judge rule set applied")

    @staticmethod
    def _confidence(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _policy_model_ids(policy: Optional[dict[str, Any]]) -> set[str]:
        if not isinstance(policy, dict):
            return set()
        active = policy.get("active_policy")
        if not isinstance(active, dict):
            return set()
        model_ids = {
            str(active.get("default_model_id") or "").strip(),
            str(active.get("fallback_model_id") or "").strip(),
        }
        for rule in active.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            model_ids.update(
                {
                    str(rule.get("selected_model_id") or "").strip(),
                    str(rule.get("fallback_model_id") or "").strip(),
                }
            )
        return {model_id for model_id in model_ids if model_id}

    @classmethod
    def _changed_primary_models(
        cls,
        current_policy: Optional[dict[str, Any]],
        *,
        default_model: str,
        rules: list[dict[str, Any]],
    ) -> set[str]:
        """기존 policy에서 새 실행 경로로 승격되는 모델만 품질 gate 대상으로 잡는다."""
        active = (
            current_policy.get("active_policy")
            if isinstance(current_policy, dict)
            else None
        )
        active = active if isinstance(active, dict) else {}
        changed: set[str] = set()
        if default_model and default_model != str(active.get("default_model_id") or ""):
            changed.add(default_model)

        current_rules = {
            str(rule.get("id") or ""): rule
            for rule in active.get("rules") or []
            if isinstance(rule, dict) and str(rule.get("id") or "")
        }
        for rule in rules:
            model_id = str(rule.get("selected_model_id") or "")
            current_rule = current_rules.get(str(rule.get("id") or ""))
            if (
                model_id
                and (
                    current_rule is None
                    or str(current_rule.get("selected_model_id") or "") != model_id
                )
            ):
                changed.add(model_id)
        return changed

    @classmethod
    def _has_efficiency_evidence(
        cls,
        changed_models: set[str],
        *,
        current_policy: Optional[dict[str, Any]],
        candidates: list[dict[str, Any]],
        quality_metrics: dict[str, dict[str, Any]],
    ) -> bool:
        """새 primary routing 모델은 관측 비용/지연 또는 price 근거가 있어야 한다."""
        if not changed_models or not isinstance(current_policy, dict):
            return True

        current_models = cls._primary_model_ids(current_policy)
        if not current_models:
            return False
        candidates_by_id = {
            str(candidate.get("model_id") or ""): candidate
            for candidate in candidates
        }

        for changed_model in changed_models:
            changed_metrics = quality_metrics.get(changed_model) or {}
            changed_candidate = candidates_by_id.get(changed_model) or {}
            for current_model in current_models - {changed_model}:
                current_metrics = quality_metrics.get(current_model) or {}
                current_candidate = candidates_by_id.get(current_model) or {}
                observed_cost = cls._is_lower_metric(
                    changed_metrics.get("avg_cost"),
                    current_metrics.get("avg_cost"),
                )
                observed_latency = cls._is_lower_metric(
                    changed_metrics.get("avg_latency_ms"),
                    current_metrics.get("avg_latency_ms"),
                )
                if observed_cost or observed_latency:
                    return True

                has_observed_comparison = any(
                    cls._as_float(value) is not None
                    for value in (
                        changed_metrics.get("avg_cost"),
                        current_metrics.get("avg_cost"),
                        changed_metrics.get("avg_latency_ms"),
                        current_metrics.get("avg_latency_ms"),
                    )
                )
                if has_observed_comparison:
                    continue
                if cls._is_lower_metric(
                    changed_candidate.get("price_score"),
                    current_candidate.get("price_score"),
                ):
                    return True
        return False

    @staticmethod
    def _primary_model_ids(policy: dict[str, Any]) -> set[str]:
        active = policy.get("active_policy")
        active = active if isinstance(active, dict) else {}
        model_ids = {str(active.get("default_model_id") or "").strip()}
        for rule in active.get("rules") or []:
            if isinstance(rule, dict):
                model_ids.add(str(rule.get("selected_model_id") or "").strip())
        return {model_id for model_id in model_ids if model_id}

    @staticmethod
    def _as_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _is_lower_metric(cls, value: Any, reference: Any) -> bool:
        parsed = cls._as_float(value)
        baseline = cls._as_float(reference)
        return parsed is not None and baseline is not None and parsed < baseline

    @staticmethod
    def _quality_metrics_by_model(
        recent_runs: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        metrics: dict[str, dict[str, Any]] = {}
        for row in recent_runs:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("model_id") or row.get("model") or "").strip()
            if model_id:
                metrics[model_id] = row
        return metrics

    @classmethod
    def _passes_model_quality_gate(cls, metrics: Optional[dict[str, Any]]) -> bool:
        if not isinstance(metrics, dict):
            return False
        try:
            run_count = int(metrics.get("run_count") or 0)
        except (TypeError, ValueError):
            return False
        if run_count < cls.MIN_MODEL_QUALITY_SAMPLES:
            return False

        def below(key: str, minimum: float) -> bool:
            value = metrics.get(key)
            return value is not None and float(value) < minimum

        if below("success_rate", ModelRouter.SCHEMA_PASS_RATE_MIN):
            return False
        if below("schema_pass_rate", ModelRouter.SCHEMA_PASS_RATE_MIN):
            return False
        if below("downstream_success_rate", ModelRouter.DOWNSTREAM_SUCCESS_RATE_MIN):
            return False
        fallback_rate = metrics.get("fallback_rate")
        if fallback_rate is not None and float(fallback_rate) > ModelRouter.FALLBACK_RATE_MAX:
            return False
        return True

    @staticmethod
    def _sanitize_rules(
        rules: list[dict[str, Any]], candidate_ids: set[str]
    ) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        for index, rule in enumerate(rules, start=1):
            selected_model = str(rule.get("selected_model_id") or "").strip()
            if selected_model not in candidate_ids:
                continue
            when = rule.get("when") if isinstance(rule.get("when"), dict) else {}
            if any(key not in ModelRouter.POLICY_CONDITION_KEYS for key in when):
                continue
            fallback_model = str(rule.get("fallback_model_id") or "").strip() or None
            if fallback_model not in candidate_ids:
                fallback_model = None
            sanitized.append(
                {
                    "id": str(rule.get("id") or f"judge-rule-{index}"),
                    "priority": int(rule.get("priority") or index * 10),
                    "when": when,
                    "selected_model_id": selected_model,
                    "fallback_model_id": fallback_model,
                    "reason_code": str(rule.get("reason_code") or "judge_generated_rule"),
                }
            )
        return sorted(sanitized, key=lambda item: item["priority"])

    @staticmethod
    def _parse_judge_response(content: str) -> dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start : end + 1])
            raise

    @staticmethod
    def _content_from_response(response: Any) -> str:
        if isinstance(response, dict):
            choices = response.get("choices") or []
            if choices:
                message = choices[0].get("message") or {}
                return str(message.get("content") or "")
            return str(response.get("content") or "")
        return str(response)

    @staticmethod
    def _usage_from_response(response: Any) -> dict[str, Any]:
        if not isinstance(response, dict):
            return {}
        usage = response.get("usage") or {}
        if not isinstance(usage, dict):
            return {}
        return {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0)
            or int(usage.get("prompt_tokens") or 0)
            + int(usage.get("completion_tokens") or 0),
        }

    @classmethod
    def _sanitize_candidates(
        cls, candidates: list[ModelCandidate]
    ) -> list[dict[str, Any]]:
        return [
            {
                "model_id": candidate.model_id,
                "display_name": candidate.display_name,
                "price_score": candidate.price_score,
                "input_price_1k": candidate.input_price_1k,
                "output_price_1k": candidate.output_price_1k,
            }
            for candidate in candidates
        ]

    @classmethod
    def _tier_models(
        cls, candidates: list[ModelCandidate]
    ) -> tuple[ModelCandidate, ModelCandidate, ModelCandidate]:
        sorted_candidates = sorted(candidates, key=lambda candidate: candidate.price_score)
        cheap = sorted_candidates[0]
        high = sorted_candidates[-1]
        mid = sorted_candidates[len(sorted_candidates) // 2]
        return cheap, mid, high

    @classmethod
    def _structured_output_model(
        cls,
        candidates: list[ModelCandidate],
        *,
        fallback: ModelCandidate,
    ) -> ModelCandidate:
        """JSON schema 출력은 최저가보다 안정적인 텍스트 생성 가능성을 우선한다."""
        for candidate in sorted(candidates, key=lambda item: item.price_score):
            normalized_id = candidate.model_id.lower()
            if any(
                keyword in normalized_id
                for keyword in STRUCTURED_OUTPUT_RISKY_MODEL_KEYWORDS
            ):
                continue
            return candidate
        return fallback

    @staticmethod
    def _first_distinct_model(
        candidates: list[ModelCandidate],
        *,
        exclude: str,
    ) -> Optional[ModelCandidate]:
        for candidate in candidates:
            if candidate.model_id != exclude:
                return candidate
        return None

    @staticmethod
    def _next_policy_version(previous_version: str) -> str:
        digits = ""
        for char in reversed(previous_version):
            if not char.isdigit():
                break
            digits = char + digits
        if not digits:
            return "router-policy-v1"
        return f"{previous_version[: -len(digits)]}{int(digits) + 1}"

    @staticmethod
    def _with_refresh_status(policy: dict[str, Any], status: str) -> dict[str, Any]:
        if not policy:
            return {"status": status, "refresh": {"last_refresh_result": status}}
        copied = json.loads(json.dumps(policy, ensure_ascii=False, default=str))
        copied.setdefault("refresh", {})["last_refresh_result"] = status
        return copied

    @classmethod
    def _refresh_every_runs_from_policy(
        cls, policy: Optional[dict[str, Any]]
    ) -> int:
        if not isinstance(policy, dict):
            return 20
        refresh = policy.get("refresh")
        if not isinstance(refresh, dict):
            return 20
        return cls._normalize_refresh_every_runs(refresh.get("refresh_every_runs"))

    @staticmethod
    def _normalize_refresh_every_runs(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 20
        return max(5, min(100, parsed))

    @staticmethod
    def _metadata(
        request: ModelRoutingPolicyRefreshRequest,
        status: str,
        candidate_count: int,
        usage: Optional[dict[str, Any]],
        *,
        generated_policy_version: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> dict[str, Any]:
        return {
            "trigger": request.trigger,
            "judge_model": request.judge_model_id,
            "prompt_version": POLICY_JUDGE_PROMPT_VERSION,
            "eligible_run_count": len(request.recent_runs),
            "candidate_count": candidate_count,
            "result": status,
            "confidence": confidence,
            "judge_usage": usage or {},
            "generated_policy_version": generated_policy_version,
        }
