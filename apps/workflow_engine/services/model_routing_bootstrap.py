"""자동 모델 라우팅의 초기 난이도 정책 생성.

이 모듈은 과거 실행이 없거나 적어도 첫 배포부터 모델을 선택할 수 있도록
운영 로그와 Planner 생성 예시를 같은 학습 표본 계약으로 정리한다.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Iterable, Literal, Protocol

from sqlalchemy.orm import Session

from apps.shared.db.models.model_routing_policy import (
    LLMNodeModelRoutingBootstrap,
    LLMNodeModelRoutingBootstrapSample,
    LLMNodeModelRoutingPolicy,
)
from apps.shared.db.models.workflow_deployment import WorkflowDeployment
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_run import (
    NodeRunStatus,
    RunStatus,
    RunTriggerMode,
    WorkflowNodeRun,
    WorkflowRun,
)
from apps.shared.services.tracing.policy import TracePolicyService
from apps.shared.services.tracing.redaction import TraceRedactionService
from apps.workflow_engine.services.model_router import (
    OPERATIONAL_TRIGGER_MODES,
    ModelCandidate,
    ModelRouter,
)
from apps.workflow_engine.services.model_routing_mdeberta_classifier import (
    MDebertaComplexityRegressor,
    MDebertaDifficultyClassifier,
    TextEmbedder,
)
from apps.workflow_engine.services.model_routing_global_profiles import (
    ModelRoutingDifficultyDistribution,
    ModelRoutingGlobalProfileScorer,
    ModelRoutingGlobalProfileStore,
)


BootstrapSource = Literal["history", "hybrid", "synthetic"]
DifficultyTier = Literal["economy", "balanced", "advanced"]
BootstrapSampleRole = Literal["training", "validation"]
DIFFICULTY_TIERS: tuple[DifficultyTier, ...] = (
    "economy",
    "balanced",
    "advanced",
)
MIN_HISTORY_FOR_HISTORY_ONLY = 12
MAX_HISTORY_SAMPLES = 24
COMPLEXITY_COVERAGE_TARGETS: tuple[float, ...] = (15.0, 30.0, 45.0, 60.0, 75.0, 90.0)
DEFAULT_SAMPLES_PER_COMPLEXITY_TARGET = 2
MIN_SAMPLES_PER_COMPLEXITY_TARGET = 1
MAX_SAMPLES_PER_COMPLEXITY_TARGET = 3


@dataclass(frozen=True)
class BootstrapHistoryRun:
    node_run_id: str
    safe_input_summary: dict[str, Any]
    feature_text: str
    input_length: int
    knowledge_enabled: bool
    output_format: str
    executed_at: str | None


@dataclass(frozen=True)
class BootstrapSample:
    source: Literal["history", "synthetic"]
    difficulty: DifficultyTier
    safe_input_summary: dict[str, Any]
    feature_text: str
    source_node_run_id: str | None
    reason: str | None
    input_length: int
    knowledge_enabled: bool
    output_format: str
    # v4 정책의 학습·실행 기준. difficulty는 이전 DB/API 호환용 표시값일 뿐,
    # 새 runtime은 이 연속 점수를 사용한다.
    complexity_score: float = 50.0
    # validation 표본은 artifact 학습에 넣지 않는다. 같은 정책이 본 적 없는
    # 표현을 분류할 수 있는지 확인하는 용도다.
    sample_role: BootstrapSampleRole = "training"


def _complexity_score_from_value(value: Any, *, fallback: float = 50.0) -> float:
    """신규 점수와 기존 tier 값을 모두 안전하게 읽는다."""

    if isinstance(value, str):
        legacy = {"economy": 20.0, "balanced": 55.0, "advanced": 85.0}
        if value in legacy:
            return legacy[value]
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = fallback
    return max(0.0, min(100.0, score))


def _display_difficulty_for_score(score: float) -> DifficultyTier:
    """기존 DB의 difficulty 문자열을 유지하기 위한 표시용 변환이다."""

    if score < 34:
        return "economy"
    if score < 67:
        return "balanced"
    return "advanced"


@dataclass(frozen=True)
class BootstrapPlan:
    source: BootstrapSource
    task_fingerprint: str
    task_complexity_profile: dict[str, Any]
    samples: list[BootstrapSample]
    validation_samples: list[BootstrapSample]
    difficulty_rules: list[dict[str, Any]]
    rule_generalization: dict[str, Any]
    history_sample_count: int
    synthetic_sample_count: int
    excluded_history_count: int
    planner_budget_usd: float
    sample_generation_budget_usd: float


class BootstrapPlanner(Protocol):
    def create_task_complexity_profile(
        self,
        *,
        task_summary: dict[str, Any],
    ) -> dict[str, Any]: ...

    def label_history(
        self,
        *,
        task_summary: dict[str, Any],
        history_runs: list[BootstrapHistoryRun],
    ) -> dict[str, tuple[float | DifficultyTier, str | None]]: ...

    def create_samples(
        self,
        *,
        task_summary: dict[str, Any],
        coverage_targets: list[float],
        count_per_target: int,
        sample_budget_usd: float,
        sample_role: BootstrapSampleRole = "training",
        reference_samples: list[BootstrapSample] | None = None,
    ) -> list[dict[str, Any]]: ...

    def create_difficulty_rules(
        self,
        *,
        task_summary: dict[str, Any],
        samples: list[BootstrapSample],
    ) -> list[dict[str, Any]]: ...


class LLMJsonBootstrapPlanner:
    """기존 LLM runtime client를 사용해 safe JSON bootstrap 표본을 생성한다."""

    PROMPT_VERSION = "model-routing-bootstrap-planner-v5"

    def __init__(self, client: Any):
        self.client = client
        self.usage: dict[str, float] = {
            "prompt_tokens": 0.0,
            "completion_tokens": 0.0,
            "total_tokens": 0.0,
            "cost": 0.0,
        }

    def create_task_complexity_profile(
        self,
        *,
        task_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """노드가 요구하는 능력 수준을 한 번만 분석한다.

        이 결과는 요청별 주제 분류가 아니다. 동일한 LLM 노드가 수행할 작업의
        prompt, 출력 계약, RAG, 후속 계약을 바탕으로 만드는 고정 프로필이다.
        """
        result = self._invoke(
            "Analyze the capability required by this one LLM node. This is not a "
            "classification of incoming request topics. Score the node task from 0 to 100 "
            "using its prompts, input/output contract, JSON schema precision, RAG/retrieval "
            "requirements, and downstream contract. Return a compact explanation and integer "
            "dimension scores from 0 to 5. Do not choose a model and do not use customer or "
            "document subject matter as a proxy for difficulty. Return JSON only.",
            {
                "task": task_summary,
                "response_schema": {
                    "score": "integer 0..100",
                    "reasoning_depth": "integer 0..5",
                    "instruction_complexity": "integer 0..5",
                    "schema_precision": "integer 0..5",
                    "context_synthesis": "integer 0..5",
                    "grounding_requirement": "integer 0..5",
                    "output_generation_demand": "integer 0..5",
                    "ambiguity": "integer 0..5",
                    "reason": "short safe Korean explanation",
                },
            },
        )
        return result

    def label_history(
        self,
        *,
        task_summary: dict[str, Any],
        history_runs: list[BootstrapHistoryRun],
    ) -> dict[str, tuple[float | DifficultyTier, str | None]]:
        payload = {
            "task": task_summary,
            "history_samples": [
                {
                    "node_run_id": run.node_run_id,
                    "input": run.safe_input_summary,
                    "input_length": run.input_length,
                    "knowledge_enabled": run.knowledge_enabled,
                    "output_format": run.output_format,
                }
                for run in history_runs
            ],
            "response_schema": {
                "labels": [
                    {
                        "node_run_id": "string",
                        "complexity_score": "integer 0..100",
                        "reason": "short safe reason",
                    }
                ]
            },
        }
        result = self._invoke(
            "Score each safe operational sample from 0 to 100 by the capability "
            "required to complete this node. This is continuous request complexity, "
            "not economy/balanced/advanced topic classification. Return JSON only. "
            "Do not infer model quality from the model that previously ran the sample.",
            payload,
        )
        labels: dict[str, tuple[float | DifficultyTier, str | None]] = {}
        for item in result.get("labels", []):
            if not isinstance(item, dict):
                continue
            node_run_id = str(item.get("node_run_id") or "")
            score = item.get("complexity_score")
            legacy_tier = str(item.get("difficulty") or "")
            if node_run_id and (score is not None or legacy_tier in DIFFICULTY_TIERS):
                labels[node_run_id] = (
                    _complexity_score_from_value(
                        score if score is not None else legacy_tier
                    ),
                    str(item.get("reason") or "") or None,
                )
        return labels

    def create_samples(
        self,
        *,
        task_summary: dict[str, Any],
        coverage_targets: list[float],
        count_per_target: int,
        sample_budget_usd: float,
        sample_role: BootstrapSampleRole = "training",
        reference_samples: list[BootstrapSample] | None = None,
    ) -> list[dict[str, Any]]:
        _ = sample_role, reference_samples
        payload = {
            "task": task_summary,
            "coverage_targets": coverage_targets,
            "count_per_target": count_per_target,
            "sample_budget_usd": round(sample_budget_usd, 4),
            "response_schema": {
                "samples": [
                    {
                        "complexity_score": "integer 0..100",
                        "payload": (
                            "JSON object in the LLM node input shape. Top-level keys "
                            "must match input_variables[].value_selector[0], and nested "
                            "values must follow the remaining selector path."
                        ),
                        "feature_text": "non-secret short explanation of the payload task",
                        "coverage_tag": "distinct request-shape tag",
                        "reason": "why this capability tier is needed",
                    }
                ]
            },
        }
        result = self._invoke(
            "Create executable representative JSON payloads across the requested "
            "continuous complexity range. These labeled examples train a per-request "
            "complexity regressor, not a topic or keyword router. "
            "Respect required input variables. Include RAG cases when knowledge is "
            "enabled: single source, synthesis, conflicting sources, and no evidence. "
            "Use different request shapes and Korean expressions. Do not merely replace a team "
            "name or noun. The node's prompt, output contract, RAG configuration, and downstream "
            "contract determine the tier; do not infer the tier from the input subject matter. "
            "Return JSON only and never invent credentials, secrets, or raw documents.",
            payload,
            max_tokens=min(6200, max(3200, 190 * count_per_target * len(coverage_targets))),
        )
        samples = result.get("samples")
        return samples if isinstance(samples, list) else []

    def create_difficulty_rules(
        self,
        *,
        task_summary: dict[str, Any],
        samples: list[BootstrapSample],
    ) -> list[dict[str, Any]]:
        """초기 예시를 실제 첫 실행 분기에 쓸 수 있는 안전한 규칙으로 요약한다."""
        payload = {
            "task": task_summary,
            "labeled_samples": [
                {
                    "difficulty": sample.difficulty,
                    "input": sample.safe_input_summary,
                    "reason": sample.reason,
                    "source": sample.source,
                }
                for sample in samples
            ],
            "response_schema": {
                "rules": [
                    {
                        "id": "stable-ascii-id",
                        "difficulty": "economy | balanced | advanced",
                        "keyword_any": ["short reusable input cues"],
                        "keyword_all": ["optional phrases that must all exist"],
                        "minimum_matches": 1,
                        "reason": "short explanation without customer data",
                    }
                ]
            },
        }
        result = self._invoke(
            "Create 1 to 3 deterministic and non-overlapping routing rules for each "
            "difficulty tier. The runtime only performs case-insensitive matching against "
            "the incoming workflow input; it will not call an LLM. Generate cues from "
            "the task and labeled samples, not from the subject nouns of one example. A cue must be "
            "either one compact meaning-bearing Korean word or a short phrase whose two "
            "or more meaning-bearing words must appear together. A multi-word phrase is "
            "not a single-word cue: the runtime treats it as strong only when the phrase "
            "is exact or at least two meaningful words match. Do not use broad constructions "
            "ending in words like 'method', 'guide', 'request', or polite endings. A direct "
            "lookup or navigation question must have at least one economy rule with 4 to 8 "
            "atomic lookup/action cues and minimum_matches=1, because short questions rarely "
            "contain two separate cues. Economy cues should describe lookup shapes such as a "
            "location, name, date, entry point, or one required item rather than a specific "
            "document subject. A balanced rule must capture comparison, ordered steps, or "
            "multiple related actions using compact comparison/process cues. An advanced rule "
            "must capture conflict, exception, risk, or a decision under multiple constraints "
            "and normally use keyword_all or minimum_matches=2. Include reusable Korean wording "
            "variants for each request shape, not only nouns from the generated payloads. "
            "Do not return whole example sentences, customer names, role titles, team names, "
            "or proper nouns copied from one sample. Never reuse the same cue in different "
            "difficulty tiers, and avoid broad words such as 'question', 'document', "
            "'request', 'policy', 'guide', or the workflow name. "
            "Return JSON only.",
            payload,
        )
        rules = result.get("rules")
        return rules if isinstance(rules, list) else []

    def repair_difficulty_rules(
        self,
        *,
        task_summary: dict[str, Any],
        samples: list[BootstrapSample],
        rules: list[dict[str, Any]],
        failures: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """합성 예문을 잘못 분류한 초기 규칙을 한 번만 보정한다.

        이 호출은 bootstrap 생성 과정에만 존재한다. 일반 workflow 실행 중에는
        호출되지 않으므로 매 요청마다 비용이 발생하지 않는다.
        """
        payload = {
            "task": task_summary,
            "labeled_samples": [
                {
                    "difficulty": sample.difficulty,
                    "input": sample.safe_input_summary,
                    "reason": sample.reason,
                }
                for sample in samples
            ],
            "existing_rules": rules,
            "misclassified_samples": failures,
            "response_schema": {
                "rules": [
                    {
                        "id": "stable-ascii-id",
                        "difficulty": "economy | balanced | advanced",
                        "keyword_any": ["short reusable input cues"],
                        "keyword_all": ["optional phrases that must all exist"],
                        "minimum_matches": 1,
                        "reason": "short explanation without customer data",
                    }
                ]
            },
        }
        result = self._invoke(
            "Repair the deterministic routing rules. The runtime will only match the "
            "saved phrases and will not call an LLM, so the repaired rules must correctly "
            "classify every labeled synthetic sample below. Remove a rule when it uses a "
            "role title, team name, or other broad subject noun as the only difficulty "
            "signal. Use compact, meaning-bearing request-shape cues instead: direct "
            "lookup for economy, comparison or ordered/multiple actions for balanced, and "
            "conflict/exception/risk/multiple constraints for advanced. A multi-word phrase "
            "does not match from one word alone, so provide atomic cues where one word is a "
            "reliable signal and require two independent cues when a single one is ambiguous. "
            "Never use polite endings or generic words such as method, guide, request, or "
            "document as cues. Cover wording variants that are likely for the same task "
            "without copying full example sentences. Do not reuse a cue across tiers. "
            "Return JSON only.",
            payload,
        )
        rules = result.get("rules")
        return rules if isinstance(rules, list) else []

    def _invoke(
        self,
        instruction: str,
        payload: dict[str, Any],
        *,
        max_tokens: int = 2200,
    ) -> dict[str, Any]:
        response = self.client.invoke_sync(
            [
                {
                    "role": "system",
                    "content": "You are a workflow routing bootstrap planner. "
                    "Return one valid JSON object only.",
                },
                {
                    "role": "user",
                    "content": f"{instruction}\n{json.dumps(payload, ensure_ascii=False)}",
                },
            ],
            temperature=0.0,
            max_tokens=max_tokens,
        )
        self._accumulate_usage(response)
        content = self._content(response)
        try:
            parsed = json.loads(self._strip_code_fence(content))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Planner 응답을 JSON으로 해석하지 못했습니다.") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Planner 응답은 JSON object여야 합니다.")
        return parsed

    def _accumulate_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        usage = usage if isinstance(usage, dict) else getattr(usage, "model_dump", lambda: {})()
        usage = usage if isinstance(usage, dict) else {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cost"):
            try:
                self.usage[key] += float(usage.get(key) or 0)
            except (TypeError, ValueError):
                continue

    @staticmethod
    def _content(response: Any) -> str:
        if isinstance(response, dict):
            if isinstance(response.get("content"), str):
                return response["content"]
            choices = response.get("choices")
        else:
            choices = getattr(response, "choices", None)
            content = getattr(response, "content", None)
            if isinstance(content, str):
                return content
        if isinstance(choices, list) and choices:
            first = choices[0]
            message = (
                first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
            )
            content = (
                message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
            )
            if isinstance(content, str):
                return content
        return ""

    @staticmethod
    def _strip_code_fence(value: str) -> str:
        stripped = str(value or "").strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1]
            if stripped.endswith("```"):
                stripped = stripped[:-3]
        return stripped.strip()


class ModelRoutingBootstrapPlanner:
    """History/synthetic/hybrid 선택 규칙과 안전한 task fingerprint를 소유한다."""

    @classmethod
    def plan(
        cls,
        *,
        node_data: Any,
        task_description: str,
        history_runs: Iterable[BootstrapHistoryRun],
        initial_budget_usd: float,
        planner: BootstrapPlanner,
        downstream_contract: dict[str, Any] | None = None,
        excluded_history_count: int = 0,
    ) -> BootstrapPlan:
        cls._validate_budget(initial_budget_usd)
        fingerprint = task_fingerprint(
            node_data,
            downstream_contract=downstream_contract,
            task_description=task_description,
        )
        selected_history = list(history_runs)[:MAX_HISTORY_SAMPLES]
        task_summary = safe_task_summary(
            node_data,
            task_description=task_description,
            downstream_contract=downstream_contract,
        )
        task_complexity_profile = cls._create_task_complexity_profile(
            planner,
            task_summary=task_summary,
        )
        task_tier = str(task_complexity_profile["tier"])
        task_complexity_score = _complexity_score_from_value(
            task_complexity_profile.get("score"),
            fallback=_complexity_score_from_value(task_tier),
        )
        try:
            history_labels = cls._label_history(
                planner,
                task_summary=task_summary,
                history_runs=selected_history,
            )
        except (RuntimeError, ValueError, TypeError):
            # Planner 문제가 bootstrap 전체를 막지 않도록, 라벨을 얻지 못한 표본은
            # display용 작업 프로필 등급으로만 최소 보완한다.
            history_labels = {}

        history_samples = []
        for run in selected_history:
            labeled_score, reason = history_labels.get(
                run.node_run_id,
                (
                    task_complexity_score,
                    str(task_complexity_profile.get("reason") or "") or None,
                ),
            )
            complexity_score = _complexity_score_from_value(
                labeled_score,
                fallback=task_complexity_score,
            )
            history_samples.append(
                BootstrapSample(
                    source="history",
                    difficulty=_display_difficulty_for_score(complexity_score),
                    safe_input_summary=run.safe_input_summary,
                    feature_text=ModelRouter.bootstrap_classifier_feature_text(
                        cls._classifier_inputs_for_node(
                            run.safe_input_summary,
                            node_data,
                        ),
                        node_data,
                    ),
                    source_node_run_id=run.node_run_id,
                    reason=reason,
                    input_length=run.input_length,
                    knowledge_enabled=run.knowledge_enabled,
                    output_format=run.output_format,
                    complexity_score=complexity_score,
                )
            )

        training_history, validation_history = cls._split_history_samples(history_samples)
        coverage_targets = cls._missing_complexity_coverage_targets(training_history)
        synthetic = cls._create_synthetic_samples(
            planner,
            node_data=node_data,
            task_summary=task_summary,
            coverage_targets=coverage_targets,
            count_per_target=cls._sample_count_per_complexity_target(
                initial_budget_usd
            ),
            sample_budget_usd=initial_budget_usd * 0.65,
            sample_role="training",
        )
        source: BootstrapSource = (
            "synthetic"
            if not history_samples
            else "hybrid"
            if synthetic
            else "history"
        )
        all_samples = [*training_history, *synthetic]
        return BootstrapPlan(
            source=source,
            task_fingerprint=fingerprint,
            task_complexity_profile=task_complexity_profile,
            samples=all_samples,
            validation_samples=validation_history,
            difficulty_rules=[],
            rule_generalization={"status": "not_used", "passed": False},
            history_sample_count=len(history_samples),
            synthetic_sample_count=len(synthetic),
            excluded_history_count=excluded_history_count,
            planner_budget_usd=round(initial_budget_usd * 0.15, 4),
            sample_generation_budget_usd=round(initial_budget_usd * 0.85, 4),
        )

    @staticmethod
    def _validate_budget(value: float) -> None:
        if not 0.5 <= float(value) <= 10.0:
            raise ValueError("초기 정책 생성 예산은 $0.50~$10 범위여야 합니다.")

    @classmethod
    def _create_task_complexity_profile(
        cls,
        planner: BootstrapPlanner,
        *,
        task_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """Planner 결과를 정규화하고, 테스트/장애 시 구조 기반 안전 기본값을 만든다."""
        creator = getattr(planner, "create_task_complexity_profile", None)
        raw_profile = creator(task_summary=task_summary) if callable(creator) else {}
        raw_profile = raw_profile if isinstance(raw_profile, dict) else {}

        def score(value: Any, default: int) -> int:
            try:
                return max(0, min(5, int(value)))
            except (TypeError, ValueError):
                return default

        prompts = task_summary.get("prompts")
        prompts = prompts if isinstance(prompts, dict) else {}
        input_variables = task_summary.get("input_variables")
        input_variables = input_variables if isinstance(input_variables, list) else []
        output_format = task_summary.get("output_format")
        output_format = output_format if isinstance(output_format, dict) else {}
        downstream_contract = task_summary.get("downstream_contract")
        downstream_contract = (
            downstream_contract if isinstance(downstream_contract, dict) else {}
        )
        knowledge_enabled = bool(task_summary.get("knowledge_enabled"))
        structural_defaults = {
            "reasoning_depth": 2 + int(bool(downstream_contract.get("consumers"))),
            "instruction_complexity": min(
                5, sum(bool(str(value).strip()) for value in prompts.values()) + int(len(input_variables) > 2)
            ),
            "schema_precision": 4 if str(output_format.get("type") or "").lower() == "json" else 1,
            "context_synthesis": 4 if knowledge_enabled else 1,
            "grounding_requirement": 4 if knowledge_enabled else 1,
            "output_generation_demand": 2,
            "ambiguity": 2,
        }
        dimensions = {
            key: score(raw_profile.get(key), default)
            for key, default in structural_defaults.items()
        }
        try:
            raw_score = int(raw_profile.get("score"))
        except (TypeError, ValueError):
            raw_score = round(
                100
                * (
                    dimensions["reasoning_depth"] * 0.24
                    + dimensions["instruction_complexity"] * 0.16
                    + dimensions["schema_precision"] * 0.16
                    + dimensions["context_synthesis"] * 0.16
                    + dimensions["grounding_requirement"] * 0.12
                    + dimensions["output_generation_demand"] * 0.08
                    + dimensions["ambiguity"] * 0.08
                )
                / 5
            )
        normalized_score = max(0, min(100, raw_score))
        tier: DifficultyTier = (
            "economy"
            if normalized_score <= 33
            else "balanced"
            if normalized_score <= 66
            else "advanced"
        )
        reason = str(raw_profile.get("reason") or "").strip()
        return {
            "kind": "planner_task_complexity_v1",
            "score": normalized_score,
            "tier": tier,
            **dimensions,
            "reason": reason or "노드의 prompt, 출력 계약, RAG와 후속 계약을 기준으로 난이도를 계산했습니다.",
            "source": "planner" if raw_profile else "structural_fallback",
        }

    @staticmethod
    def _sample_count_per_complexity_target(initial_budget_usd: float) -> int:
        """초기 예산에 맞는 복잡도 목표별 합성 표본 수를 계산한다."""

        # $1 기본값은 여섯 목표에 각 2개, 총 12개다. 점수 회귀기는 세 label에
        # 몰린 표본보다 복잡도 축 전체를 덮는 서로 다른 요청 형태가 필요하다.
        return max(
            MIN_SAMPLES_PER_COMPLEXITY_TARGET,
            min(
                MAX_SAMPLES_PER_COMPLEXITY_TARGET,
                round(DEFAULT_SAMPLES_PER_COMPLEXITY_TARGET * initial_budget_usd),
            ),
        )

    @staticmethod
    def _validation_sample_count_per_tier(initial_budget_usd: float) -> int:
        """학습 표본과 다른 표현을 확인할 최소 holdout 수를 계산한다."""
        training_count = ModelRoutingBootstrapPlanner._sample_count_per_complexity_target(
            initial_budget_usd
        )
        return max(3, min(5, round(training_count * 0.4)))

    @staticmethod
    def _split_history_samples(
        samples: list[BootstrapSample],
    ) -> tuple[list[BootstrapSample], list[BootstrapSample]]:
        """운영 이력도 일부를 holdout으로 남겨 같은 로그를 외우지 않게 한다."""
        by_tier: dict[str, list[BootstrapSample]] = {
            tier: [] for tier in DIFFICULTY_TIERS
        }
        for sample in samples:
            by_tier.setdefault(sample.difficulty, []).append(sample)

        training: list[BootstrapSample] = []
        validation: list[BootstrapSample] = []
        for tier_samples in by_tier.values():
            if len(tier_samples) < 4:
                training.extend(tier_samples)
                continue
            holdout_count = max(1, min(3, len(tier_samples) // 4))
            training.extend(tier_samples[:-holdout_count])
            validation.extend(
                BootstrapSample(
                    **{
                        **sample.__dict__,
                        "sample_role": "validation",
                    }
                )
                for sample in tier_samples[-holdout_count:]
            )
        return training, validation

    @classmethod
    def _label_history(
        cls,
        planner: BootstrapPlanner,
        *,
        task_summary: dict[str, Any],
        history_runs: list[BootstrapHistoryRun],
    ) -> dict[str, tuple[float, str | None]]:
        if not history_runs:
            return {}
        result = planner.label_history(
            task_summary=task_summary,
            history_runs=history_runs,
        )
        normalized: dict[str, tuple[float, str | None]] = {}
        for run in history_runs:
            tier_and_reason = result.get(run.node_run_id)
            if not tier_and_reason:
                continue
            score, reason = tier_and_reason
            normalized[run.node_run_id] = (
                _complexity_score_from_value(score),
                reason,
            )
        return normalized

    @classmethod
    def _create_synthetic_samples(
        cls,
        planner: BootstrapPlanner,
        *,
        node_data: Any,
        task_summary: dict[str, Any],
        coverage_targets: list[float],
        count_per_target: int,
        sample_budget_usd: float,
        sample_role: BootstrapSampleRole,
        reference_samples: list[BootstrapSample] | None = None,
    ) -> list[BootstrapSample]:
        if not coverage_targets:
            return []
        generated = planner.create_samples(
            task_summary=task_summary,
            coverage_targets=coverage_targets,
            count_per_target=count_per_target,
            sample_budget_usd=sample_budget_usd,
            sample_role=sample_role,
            reference_samples=reference_samples,
        )
        samples: list[BootstrapSample] = []
        for item in generated:
            if not isinstance(item, dict):
                continue
            score = item.get("complexity_score")
            tier = str(item.get("difficulty") or "")
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue
            complexity_score = _complexity_score_from_value(
                score if score is not None else tier
            )
            # 학습 입력은 실제 runtime과 같은 계약을 사용해야 한다. payload만
            # 직렬화하면 runtime의 prompt/출력 계약/RAG 구조 정보가 빠져 같은
            # 요청도 학습과 실행에서 다른 feature가 된다.
            feature_text = ModelRouter.bootstrap_classifier_feature_text(
                cls._classifier_inputs_for_node(payload, node_data),
                node_data,
            )
            if not feature_text:
                continue
            samples.append(
                BootstrapSample(
                    source="synthetic",
                    difficulty=_display_difficulty_for_score(complexity_score),
                    safe_input_summary=payload,
                    feature_text=feature_text,
                    source_node_run_id=None,
                    reason=str(item.get("reason") or "") or None,
                    input_length=len(
                        json.dumps(payload, ensure_ascii=False, sort_keys=True)
                    ),
                    knowledge_enabled=bool(task_summary.get("knowledge_enabled")),
                    output_format=str(task_summary.get("output_format") or "text"),
                    complexity_score=complexity_score,
                    sample_role=sample_role,
                )
            )
        return samples

    @staticmethod
    def _missing_complexity_coverage_targets(
        samples: list[BootstrapSample],
    ) -> list[float]:
        """학습 표본이 비어 있는 연속 복잡도 구간만 보강한다.

        각 목표는 이웃 목표의 중간값으로 만든 구간을 대표한다. 예를 들어 45점
        표본은 37.5~52.5 구간을 덮는다. 따라서 같은 legacy difficulty label 안에
        있더라도 35점과 60점의 학습 부족을 따로 감지할 수 있다.
        """

        scores = [sample.complexity_score for sample in samples]
        targets = COMPLEXITY_COVERAGE_TARGETS
        missing: list[float] = []
        for index, target in enumerate(targets):
            lower = 0.0 if index == 0 else (targets[index - 1] + target) / 2.0
            upper = 100.0 if index == len(targets) - 1 else (target + targets[index + 1]) / 2.0
            if not any(lower <= score < upper for score in scores):
                missing.append(target)
        return missing

    @staticmethod
    def _classifier_inputs_for_node(
        payload: dict[str, Any],
        node_data: Any,
    ) -> dict[str, Any]:
        """Planner payload를 LLM node의 실제 selector 입력 구조로 정규화한다.

        Planner는 workflow 외부에서 들어오는 JSON을 생성할 수 있지만, LLM node는
        ``referenced_variables[].value_selector``의 첫 값인 upstream node ID 아래에서
        값을 읽는다. source node ID가 하나이고 Planner가 평평한 payload를 만들면
        이를 source ID 아래에 감싸 runtime prompt와 같은 값을 렌더링한다. 여러
        source가 있는 경우에는 variable name을 대응 selector path에 채운다.
        """
        normalized = dict(payload)
        referenced_variables = _node_value(
            node_data,
            "referenced_variables",
            [],
        )
        if not isinstance(referenced_variables, list):
            return normalized

        bindings: list[tuple[str, list[Any], str]] = []
        source_ids: list[str] = []
        for variable in referenced_variables:
            selector = _node_value(variable, "value_selector", [])
            name = str(_node_value(variable, "name", "") or "").strip()
            if not isinstance(selector, list) or not selector:
                continue
            source_id = str(selector[0] or "").strip()
            if not source_id:
                continue
            bindings.append((source_id, list(selector[1:]), name))
            if source_id not in source_ids:
                source_ids.append(source_id)

        if not source_ids:
            return normalized
        if len(source_ids) == 1 and source_ids[0] not in normalized:
            return {source_ids[0]: normalized}

        for source_id, path, name in bindings:
            if source_id in normalized or not name or name not in payload:
                continue
            value = payload[name]
            if not path:
                normalized[source_id] = value
                continue
            source_value = normalized.get(source_id)
            source_mapping = (
                dict(source_value) if isinstance(source_value, dict) else {}
            )
            current = source_mapping
            for key in path[:-1]:
                key_text = str(key)
                nested = current.get(key_text)
                if not isinstance(nested, dict):
                    nested = {}
                    current[key_text] = nested
                current = nested
            current[str(path[-1])] = value
            normalized[source_id] = source_mapping
        return normalized

    @classmethod
    def _rule_generalization(
        cls,
        rules: list[dict[str, Any]],
        *,
        node_data: Any,
        validation_samples: list[BootstrapSample],
    ) -> dict[str, Any]:
        """학습에 포함되지 않은 표본에서 rule이 안전하게 분기되는지 요약한다."""
        if not validation_samples:
            return {
                "status": "not_available",
                "passed": False,
                "total_count": 0,
                "matched_count": 0,
                "correct_count": 0,
                "incorrect_count": 0,
                "accuracy": None,
            }
        evaluation = cls._evaluate_difficulty_rules(
            rules,
            node_data=node_data,
            samples=validation_samples,
        )
        total_count = int(evaluation["total_count"])
        accuracy = (
            int(evaluation["correct_count"]) / total_count if total_count else 0.0
        )
        # Planner가 만든 모든 rule을 한 묶음으로 합격/불합격 처리하면, 한 rule의
        # 과도한 매칭 때문에 안전한 다른 난이도 rule까지 runtime에서 못 쓴다.
        # 각 rule은 자기 난이도 holdout에서 충분히 맞고 다른 난이도에는 오탐이
        # 없을 때만 독립적으로 활성화한다.
        runtime_node_data = (
            SimpleNamespace(**node_data) if isinstance(node_data, dict) else node_data
        )
        per_rule: dict[str, dict[str, Any]] = {}
        validated_rule_ids: list[str] = []
        for index, rule in enumerate(rules, start=1):
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("id") or f"planner-rule-{index}").strip()
            difficulty = str(rule.get("difficulty") or "").strip()
            if not rule_id or difficulty not in DIFFICULTY_TIERS:
                continue
            expected_samples = [
                sample
                for sample in validation_samples
                if sample.difficulty == difficulty
            ]
            expected_total = len(expected_samples)
            expected_match_count = 0
            false_positive_count = 0
            matched_count = 0
            for sample in validation_samples:
                runtime_context = ModelRouter.infer_runtime_context(
                    sample.safe_input_summary,
                    runtime_node_data,
                )
                match = ModelRouter._match_bootstrap_difficulty_rule(
                    [rule],
                    runtime_context=runtime_context,
                )
                if match is None:
                    continue
                matched_count += 1
                if sample.difficulty == difficulty:
                    expected_match_count += 1
                else:
                    false_positive_count += 1
            minimum_expected_matches = max(1, (expected_total + 1) // 2)
            precision = (
                expected_match_count / matched_count if matched_count else 0.0
            )
            recall = (
                expected_match_count / expected_total if expected_total else 0.0
            )
            # 4개의 holdout이면 적어도 2개 이상을, 1개의 legacy test holdout이면
            # 그 1개를 맞혀야 한다. 오탐이 하나라도 있으면 해당 rule은 runtime에
            # 넣지 않는다.
            rule_passed = bool(
                expected_total
                and expected_match_count >= minimum_expected_matches
                and false_positive_count == 0
            )
            per_rule[rule_id] = {
                "difficulty": difficulty,
                "status": "ready" if rule_passed else "insufficient",
                "passed": rule_passed,
                "expected_total_count": expected_total,
                "minimum_expected_matches": minimum_expected_matches,
                "matched_count": matched_count,
                "correct_count": expected_match_count,
                "false_positive_count": false_positive_count,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
            }
            if rule_passed:
                validated_rule_ids.append(rule_id)
        all_rule_ids = set(per_rule)
        passed = bool(validated_rule_ids)
        status = (
            "ready"
            if all_rule_ids and set(validated_rule_ids) == all_rule_ids
            else "partial"
            if passed
            else "insufficient"
        )
        return {
            "status": status,
            "passed": passed,
            "total_count": total_count,
            "matched_count": int(evaluation["matched_count"]),
            "correct_count": int(evaluation["correct_count"]),
            "incorrect_count": int(evaluation["incorrect_count"]),
            "accuracy": round(accuracy, 4),
            "validated_rule_ids": validated_rule_ids,
            "per_rule": per_rule,
        }

    @classmethod
    def _create_difficulty_rules(
        cls,
        planner: BootstrapPlanner,
        *,
        task_summary: dict[str, Any],
        samples: list[BootstrapSample],
        node_data: Any,
        repair_samples: list[BootstrapSample] | None = None,
    ) -> list[dict[str, Any]]:
        """Planner가 실패해도 bootstrap 전체를 중단하지 않는 정책 규칙 경계다."""
        creator = getattr(planner, "create_difficulty_rules", None)
        if not callable(creator) or not samples:
            return []
        try:
            generated = creator(task_summary=task_summary, samples=samples)
        except (RuntimeError, ValueError, TypeError):
            return []
        rules = cls._normalize_difficulty_rules(generated)
        return cls._repair_difficulty_rules_if_needed(
            planner,
            task_summary=task_summary,
            node_data=node_data,
            rules=rules,
            samples=repair_samples or [],
        )

    @classmethod
    def _repair_difficulty_rules_if_needed(
        cls,
        planner: BootstrapPlanner,
        *,
        task_summary: dict[str, Any],
        node_data: Any,
        rules: list[dict[str, Any]],
        samples: list[BootstrapSample],
    ) -> list[dict[str, Any]]:
        """초기 생성 규칙이 자기 합성 표본을 틀리면 한 번만 보정한다.

        운영 history 표본은 redaction된 안전 요약이라 phrase rule의 정확도를
        검증하기에 적합하지 않다. 그래서 실제 입력 구조를 가진 synthetic 표본만
        대상으로 삼고, 보정 후보가 더 좋아질 때에만 교체한다.
        """
        if len(samples) < 3:
            return rules
        initial = cls._evaluate_difficulty_rules(
            rules,
            node_data=node_data,
            samples=samples,
        )
        if initial["correct_count"] == initial["total_count"]:
            return rules

        repairer = getattr(planner, "repair_difficulty_rules", None)
        if not callable(repairer):
            return rules
        try:
            generated = repairer(
                task_summary=task_summary,
                samples=samples,
                rules=rules,
                failures=initial["failures"],
            )
        except (RuntimeError, ValueError, TypeError):
            return rules
        repaired = cls._normalize_difficulty_rules(generated)
        if not repaired:
            return rules
        repaired_evaluation = cls._evaluate_difficulty_rules(
            repaired,
            node_data=node_data,
            samples=samples,
        )
        if cls._is_rule_evaluation_better(repaired_evaluation, initial):
            return repaired
        return rules

    @classmethod
    def _evaluate_difficulty_rules(
        cls,
        rules: list[dict[str, Any]],
        *,
        node_data: Any,
        samples: list[BootstrapSample],
    ) -> dict[str, Any]:
        runtime_node_data = (
            SimpleNamespace(**node_data) if isinstance(node_data, dict) else node_data
        )
        matched_count = 0
        correct_count = 0
        incorrect_count = 0
        failures: list[dict[str, Any]] = []
        for sample in samples:
            runtime_context = ModelRouter.infer_runtime_context(
                sample.safe_input_summary,
                runtime_node_data,
            )
            match = ModelRouter._match_bootstrap_difficulty_rule(
                rules,
                runtime_context=runtime_context,
            )
            actual_difficulty = str(match.get("difficulty") or "") if match else None
            if match:
                matched_count += 1
            if actual_difficulty == sample.difficulty:
                correct_count += 1
                continue
            if match:
                incorrect_count += 1
            failures.append(
                {
                    "expected_difficulty": sample.difficulty,
                    "actual_difficulty": actual_difficulty,
                    "input": sample.safe_input_summary,
                    "matched_terms": match.get("matched_terms", []) if match else [],
                }
            )
        return {
            "total_count": len(samples),
            "matched_count": matched_count,
            "correct_count": correct_count,
            "incorrect_count": incorrect_count,
            "failures": failures,
        }

    @classmethod
    def _sanitize_difficulty_rules_with_holdout(
        cls,
        rules: list[dict[str, Any]],
        *,
        node_data: Any,
        validation_samples: list[BootstrapSample],
    ) -> list[dict[str, Any]]:
        """Holdout에서 다른 난이도까지 잡는 단어만 policy 생성 단계에서 제거한다.

        Planner가 만든 규칙을 도메인 단어 목록으로 다시 해석하지 않는다. 대신 각
        ``keyword_any`` 항목을 holdout 표본에 단독 적용해, 자기 난이도에는 근거가
        있고 다른 난이도에는 오탐을 내지 않는 항목만 남긴다. 검증 표본에서 확인할
        수 없는 항목은 성급히 버리지 않고 보존한다.
        """
        if not rules or not validation_samples:
            return rules

        runtime_node_data = (
            SimpleNamespace(**node_data) if isinstance(node_data, dict) else node_data
        )

        def outcomes(rule: dict[str, Any]) -> tuple[int, int, int]:
            difficulty = str(rule.get("difficulty") or "")
            expected_total = 0
            correct_count = 0
            false_positive_count = 0
            for sample in validation_samples:
                if sample.difficulty == difficulty:
                    expected_total += 1
                context = ModelRouter.infer_runtime_context(
                    sample.safe_input_summary,
                    runtime_node_data,
                )
                match = ModelRouter._match_bootstrap_difficulty_rule(
                    [rule],
                    runtime_context=context,
                )
                if match is None:
                    continue
                if sample.difficulty == difficulty:
                    correct_count += 1
                else:
                    false_positive_count += 1
            return expected_total, correct_count, false_positive_count

        sanitized_rules: list[dict[str, Any]] = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            keyword_any = list(rule.get("keyword_any") or [])
            if len(keyword_any) <= 1:
                sanitized_rules.append(rule)
                continue

            safe_terms: list[str] = []
            for term in keyword_any:
                candidate = {**rule, "keyword_any": [term], "minimum_matches": 1}
                _expected_total, _correct_count, term_false_positives = outcomes(candidate)
                # 검증에서 다른 난이도에 걸린 term만 제거한다. holdout에 없던 term은
                # 새 표현에도 도움이 될 수 있으므로 보존한다.
                if term_false_positives == 0:
                    safe_terms.append(term)

            if not safe_terms:
                sanitized_rules.append(rule)
                continue

            candidate = {
                **rule,
                "keyword_any": safe_terms,
                "minimum_matches": min(
                    max(1, int(rule.get("minimum_matches") or 1)),
                    len(safe_terms),
                ),
            }
            expected_total, candidate_correct, candidate_false_positives = outcomes(candidate)
            _original_expected, _original_correct, original_false_positives = outcomes(rule)
            minimum_expected_matches = max(1, (expected_total + 1) // 2)
            if (
                candidate_false_positives < original_false_positives
                and candidate_correct >= minimum_expected_matches
            ):
                sanitized_rules.append(candidate)
            else:
                sanitized_rules.append(rule)
        return sanitized_rules

    @staticmethod
    def _is_rule_evaluation_better(
        candidate: dict[str, Any],
        baseline: dict[str, Any],
    ) -> bool:
        """동점 보정보다 실제로 더 많은 표본을 맞춘 규칙만 채택한다."""
        candidate_score = (
            int(candidate["correct_count"]),
            -int(candidate["incorrect_count"]),
            int(candidate["matched_count"]),
        )
        baseline_score = (
            int(baseline["correct_count"]),
            -int(baseline["incorrect_count"]),
            int(baseline["matched_count"]),
        )
        return candidate_score > baseline_score

    @staticmethod
    def _normalize_difficulty_rules(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        priorities = {"economy": 100, "balanced": 200, "advanced": 300}
        normalized: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict) or len(normalized) >= 9:
                continue
            difficulty = str(item.get("difficulty") or "").strip()
            if difficulty not in DIFFICULTY_TIERS:
                continue
            rule_id = str(item.get("id") or f"planner-{difficulty}-{index}").strip()
            if not rule_id or rule_id in seen_ids:
                rule_id = f"planner-{difficulty}-{index}"
            seen_ids.add(rule_id)
            keyword_any = ModelRoutingBootstrapPlanner._normalize_rule_terms(
                item.get("keyword_any")
            )
            keyword_all = ModelRoutingBootstrapPlanner._normalize_rule_terms(
                item.get("keyword_all")
            )
            if not keyword_any and not keyword_all:
                continue
            requested_minimum = item.get("minimum_matches")
            try:
                minimum_matches = int(requested_minimum)
            except (TypeError, ValueError):
                minimum_matches = 1
            minimum_matches = max(1, min(minimum_matches, len(keyword_any) or 1))
            normalized.append(
                {
                    "id": rule_id,
                    "difficulty": difficulty,
                    "keyword_any": keyword_any,
                    "keyword_all": keyword_all,
                    "minimum_matches": minimum_matches,
                    "priority": priorities[difficulty],
                    "reason": str(item.get("reason") or "").strip()[:300] or None,
                }
            )

        # 서로 다른 난이도에 같은 cue가 있으면 runtime은 단어 하나만 보고 임의의
        # tier를 선택하게 된다. 공통 신호는 정책 생성 시점에 제거하고, 남은 고유
        # 신호가 있는 rule만 보존한다.
        term_tiers: dict[str, set[str]] = {}
        for rule in normalized:
            for term in [*rule["keyword_any"], *rule["keyword_all"]]:
                term_tiers.setdefault(term.casefold(), set()).add(rule["difficulty"])
        ambiguous_terms = {
            term for term, tiers in term_tiers.items() if len(tiers) > 1
        }

        filtered: list[dict[str, Any]] = []
        for rule in normalized:
            keyword_any = [
                term
                for term in rule["keyword_any"]
                if term.casefold() not in ambiguous_terms
            ]
            keyword_all = [
                term
                for term in rule["keyword_all"]
                if term.casefold() not in ambiguous_terms
            ]
            if not keyword_any and not keyword_all:
                continue
            rule = dict(rule)
            rule["keyword_any"] = keyword_any
            rule["keyword_all"] = keyword_all
            rule["minimum_matches"] = max(
                1,
                min(int(rule["minimum_matches"]), len(keyword_any) or 1),
            )
            filtered.append(rule)
        return filtered

    @staticmethod
    def _normalize_rule_terms(value: Any) -> list[str]:
        terms = value if isinstance(value, list) else []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in terms:
            term = " ".join(str(item or "").split()).strip()
            key = term.casefold()
            # 문장 전체를 rule로 저장하면 실제 표현 변화에 전혀 대응하지 못한다.
            # 길이는 payload가 아니라 반복 가능한 짧은 신호 수준으로 제한한다.
            if (
                len(term) < 2
                or len(term) > 48
                or len(term.split()) > 6
                or key in seen
            ):
                continue
            seen.add(key)
            normalized.append(term)
            if len(normalized) >= 12:
                break
        return normalized


class PersistedModelRoutingBootstrapStore:
    """초안 bootstrap artifact와 배포 후 정책을 잇는 DB 경계.

    이 service는 workflow run 원문을 artifact에 저장하지 않는다. 분류기 학습에
    필요한 원문은 현재 transaction의 메모리에서만 사용하고, 표본 table에는
    redaction policy를 거친 safe summary와 one-way hash만 남긴다.
    """

    @classmethod
    def preview(
        cls,
        db: Session,
        *,
        workflow_id: uuid.UUID,
        organization_id: uuid.UUID | None,
        node_id: str,
        node_data: dict[str, Any],
        downstream_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fingerprint = task_fingerprint(node_data, downstream_contract=downstream_contract)
        history_runs, exclusions = cls._collect_history_runs(
            db,
            workflow_id=workflow_id,
            organization_id=organization_id,
            node_id=node_id,
            task_fingerprint_value=fingerprint,
        )
        existing = cls._find_exact_bootstrap(
            db,
            workflow_id=workflow_id,
            node_id=node_id,
            task_fingerprint_value=fingerprint,
        )
        return {
            "task_fingerprint": fingerprint,
            "history_mode": cls._history_mode(len(history_runs)),
            "available_history_count": len(history_runs),
            "excluded_history_count": sum(exclusions.values()),
            "excluded_reason_summary": exclusions,
            "bootstrap": cls.public_summary(existing, include_samples=True, db=db)
            if existing is not None
            else None,
        }

    @classmethod
    def create(
        cls,
        db: Session,
        *,
        workflow_id: uuid.UUID,
        organization_id: uuid.UUID | None,
        node_id: str,
        node_data: dict[str, Any],
        task_description: str,
        default_model_id: str,
        fallback_model_id: str | None,
        initial_budget_usd: float,
        created_by: uuid.UUID,
        planner: BootstrapPlanner,
        planner_model_id: str | None,
        available_candidates: list[ModelCandidate],
        downstream_contract: dict[str, Any] | None = None,
        embedder: TextEmbedder | None = None,
        defer_classifier: bool = False,
    ) -> tuple[LLMNodeModelRoutingBootstrap, dict[str, Any]]:
        if not task_description.strip():
            raise ValueError("자동 라우팅 작업 설명을 입력하세요.")
        normalized_default = str(default_model_id or "").strip()
        normalized_fallback = str(fallback_model_id or "").strip() or None
        candidate_ids = {candidate.model_id for candidate in available_candidates}
        if normalized_default not in candidate_ids:
            raise ValueError("기본 모델은 현재 실행 주체가 사용할 수 있는 모델이어야 합니다.")
        if normalized_fallback and normalized_fallback not in candidate_ids:
            raise ValueError("기본 대체 모델은 현재 실행 주체가 사용할 수 있는 모델이어야 합니다.")
        if normalized_default == normalized_fallback:
            raise ValueError("기본 모델과 기본 대체 모델은 서로 달라야 합니다.")

        fingerprint = task_fingerprint(
            node_data,
            downstream_contract=downstream_contract,
            task_description=task_description,
        )
        existing = cls._find_exact_bootstrap(
            db,
            workflow_id=workflow_id,
            node_id=node_id,
            task_fingerprint_value=fingerprint,
        )
        # POST는 사용자가 명시적으로 기준을 다시 만들겠다는 뜻이다. 동일한 작업
        # 지문이라도 작업 설명, 기본/대체 모델, 예산을 바꿨다면 기존 artifact를
        # 재사용하지 않고 같은 row를 새 결과로 갱신한다.
        if existing is not None:
            for previous_sample in (
                db.query(LLMNodeModelRoutingBootstrapSample)
                .filter(LLMNodeModelRoutingBootstrapSample.bootstrap_id == existing.id)
                .all()
            ):
                db.delete(previous_sample)

        history_runs, exclusions = cls._collect_history_runs(
            db,
            workflow_id=workflow_id,
            organization_id=organization_id,
            node_id=node_id,
            task_fingerprint_value=fingerprint,
        )
        plan = ModelRoutingBootstrapPlanner.plan(
            node_data=node_data,
            task_description=task_description,
            history_runs=history_runs,
            initial_budget_usd=initial_budget_usd,
            planner=planner,
            downstream_contract=downstream_contract,
            excluded_history_count=sum(exclusions.values()),
        )
        artifact, classifier_status = cls._classifier_artifact_for_plan(
            plan,
            defer_classifier=defer_classifier,
            embedder=embedder,
        )
        classifier_generalization = cls._classifier_generalization_for_samples(
            artifact,
            validation_samples=plan.validation_samples,
            embedder=embedder,
            pending=classifier_status == "pending",
        )
        (
            difficulty_models,
            global_profile_matches,
            global_profile_catalog,
        ) = cls._difficulty_model_selection(
            db,
            available_candidates,
            default_model_id=normalized_default,
            node_data=node_data,
        )
        planner_cost = cls._planner_cost(planner)
        for stale in (
            db.query(LLMNodeModelRoutingBootstrap)
            .filter(LLMNodeModelRoutingBootstrap.workflow_id == workflow_id)
            .filter(LLMNodeModelRoutingBootstrap.node_id == node_id)
            .filter(LLMNodeModelRoutingBootstrap.task_fingerprint != fingerprint)
            .filter(LLMNodeModelRoutingBootstrap.status == "ready")
            .all()
        ):
            stale.status = "stale"
            stale.stale_reason = "task_fingerprint_changed"

        bootstrap = existing or LLMNodeModelRoutingBootstrap(
            organization_id=organization_id,
            workflow_id=workflow_id,
            node_id=node_id,
            task_fingerprint=fingerprint,
        )
        bootstrap.organization_id = organization_id
        bootstrap.task_description = task_description.strip()
        bootstrap.status = "ready"
        bootstrap.source = plan.source
        bootstrap.default_model_id = normalized_default
        bootstrap.fallback_model_id = normalized_fallback
        bootstrap.initial_budget_usd = Decimal(str(initial_budget_usd))
        bootstrap.planner_model_id = planner_model_id
        bootstrap.planner_cost_usd = (
            Decimal(str(planner_cost)) if planner_cost else None
        )
        bootstrap.classifier_artifact = artifact
        bootstrap.generation_summary = {
            "source": plan.source,
            "history_sample_count": plan.history_sample_count,
            "synthetic_sample_count": plan.synthetic_sample_count,
            "excluded_history_count": plan.excluded_history_count,
            "excluded_reason_summary": exclusions,
            "planner_budget_usd": plan.planner_budget_usd,
            "sample_generation_budget_usd": plan.sample_generation_budget_usd,
            "difficulty_models": difficulty_models,
            "global_profile_matches": global_profile_matches,
            "global_profile_catalog": global_profile_catalog,
            "task_complexity_profile": plan.task_complexity_profile,
            "profile_status": "ready",
            "classifier_status": classifier_status,
            # v3는 keyword rule이 아니라 요청 난이도 분류기만 사용한다.
            "difficulty_rules": [],
            "generalization_validation": {"classifier": classifier_generalization},
            "validation_samples": cls._validation_sample_summaries(
                plan.validation_samples
            ),
            "planner_prompt_version": getattr(
                planner, "PROMPT_VERSION", "model-routing-bootstrap-planner-v1"
            ),
        }
        bootstrap.stale_reason = None
        bootstrap.created_by = created_by
        if existing is None:
            db.add(bootstrap)
        db.flush()
        for ordinal, sample in enumerate(plan.samples, start=1):
            source_node_run_id = _uuid_or_none(sample.source_node_run_id)
            db.add(
                LLMNodeModelRoutingBootstrapSample(
                    bootstrap_id=bootstrap.id,
                    source_node_run_id=source_node_run_id,
                    source=sample.source,
                    ordinal=ordinal,
                    difficulty=sample.difficulty,
                    complexity_score=Decimal(str(sample.complexity_score)),
                    safe_input_summary=sample.safe_input_summary,
                    feature_hash=hashlib.sha256(
                        sample.feature_text.encode("utf-8")
                    ).hexdigest(),
                    input_length=sample.input_length,
                    knowledge_enabled=sample.knowledge_enabled,
                    output_format=sample.output_format,
                    planner_reason=sample.reason,
                )
            )
        db.flush()
        return bootstrap, cls.active_policy_for_bootstrap(bootstrap)

    @classmethod
    def create_pending(
        cls,
        db: Session,
        *,
        workflow_id: uuid.UUID,
        organization_id: uuid.UUID | None,
        node_id: str,
        node_data: dict[str, Any],
        task_description: str,
        default_model_id: str,
        fallback_model_id: str | None,
        initial_budget_usd: float,
        created_by: uuid.UUID,
        planner_model_id: str | None,
        available_candidates: list[ModelCandidate],
        downstream_contract: dict[str, Any] | None = None,
    ) -> tuple[LLMNodeModelRoutingBootstrap, bool]:
        """Planner 호출 전, UI가 즉시 조회할 bootstrap 작업을 만든다.

        Planner는 예문/검증 예문/규칙을 차례로 생성하므로 한 HTTP 요청 안에서
        기다리면 reverse proxy timeout에 걸릴 수 있다. 이 메서드는 입력과 권한을
        먼저 검증하고 ``generating`` row만 저장한다. 실제 LLM 호출은 Worker가
        ``complete_pending`` 경로에서 수행한다.

        반환값의 두 번째 값은 새 Worker 작업을 발행해야 하는지 여부다. 이미 같은
        지문의 생성이 진행 중이면 중복 호출을 만들지 않는다.
        """
        if not task_description.strip():
            raise ValueError("자동 라우팅 작업 설명을 입력하세요.")
        normalized_default = str(default_model_id or "").strip()
        normalized_fallback = str(fallback_model_id or "").strip() or None
        candidate_ids = {candidate.model_id for candidate in available_candidates}
        if normalized_default not in candidate_ids:
            raise ValueError("기본 모델은 현재 실행 주체가 사용할 수 있는 모델이어야 합니다.")
        if normalized_fallback and normalized_fallback not in candidate_ids:
            raise ValueError("기본 대체 모델은 현재 실행 주체가 사용할 수 있는 모델이어야 합니다.")
        if normalized_default == normalized_fallback:
            raise ValueError("기본 모델과 기본 대체 모델은 서로 달라야 합니다.")

        fingerprint = task_fingerprint(
            node_data,
            downstream_contract=downstream_contract,
            task_description=task_description,
        )
        existing = cls._find_exact_bootstrap(
            db,
            workflow_id=workflow_id,
            node_id=node_id,
            task_fingerprint_value=fingerprint,
        )
        if existing is not None and existing.status == "generating":
            return existing, False

        history_runs, exclusions = cls._collect_history_runs(
            db,
            workflow_id=workflow_id,
            organization_id=organization_id,
            node_id=node_id,
            task_fingerprint_value=fingerprint,
        )
        for stale in (
            db.query(LLMNodeModelRoutingBootstrap)
            .filter(LLMNodeModelRoutingBootstrap.workflow_id == workflow_id)
            .filter(LLMNodeModelRoutingBootstrap.node_id == node_id)
            .filter(LLMNodeModelRoutingBootstrap.task_fingerprint != fingerprint)
            .filter(LLMNodeModelRoutingBootstrap.status.in_(("ready", "generating")))
            .all()
        ):
            stale.status = "stale"
            stale.stale_reason = "task_fingerprint_changed"

        bootstrap = existing or LLMNodeModelRoutingBootstrap(
            organization_id=organization_id,
            workflow_id=workflow_id,
            node_id=node_id,
            task_fingerprint=fingerprint,
        )
        if existing is not None:
            for previous_sample in (
                db.query(LLMNodeModelRoutingBootstrapSample)
                .filter(LLMNodeModelRoutingBootstrapSample.bootstrap_id == existing.id)
                .all()
            ):
                db.delete(previous_sample)

        bootstrap.organization_id = organization_id
        bootstrap.task_description = task_description.strip()
        bootstrap.status = "generating"
        bootstrap.source = cls._history_mode(len(history_runs))
        bootstrap.default_model_id = normalized_default
        bootstrap.fallback_model_id = normalized_fallback
        bootstrap.initial_budget_usd = Decimal(str(initial_budget_usd))
        bootstrap.planner_model_id = planner_model_id
        bootstrap.planner_cost_usd = None
        bootstrap.classifier_artifact = {}
        bootstrap.generation_summary = {
            "source": bootstrap.source,
            "history_sample_count": len(history_runs),
            "synthetic_sample_count": 0,
            "excluded_history_count": sum(exclusions.values()),
            "excluded_reason_summary": exclusions,
            "profile_status": "generating",
            "generation_status": "queued",
        }
        bootstrap.stale_reason = None
        bootstrap.created_by = created_by
        if existing is None:
            db.add(bootstrap)
        db.flush()
        return bootstrap, True

    @classmethod
    def complete_pending(
        cls,
        db: Session,
        *,
        bootstrap_id: uuid.UUID,
        planner: BootstrapPlanner,
        available_candidates: list[ModelCandidate],
        defer_classifier: bool = False,
    ) -> LLMNodeModelRoutingBootstrap | None:
        """Worker에서 generating bootstrap을 실제 Planner 결과로 완성한다.

        생성 대기 중 사용자가 프롬프트, RAG, schema를 바꾸면 처음 요청의 지문과
        달라진다. 그 경우 이전 요청의 결과를 새 초안에 붙이지 않고 stale로 끝낸다.
        """
        bootstrap = db.get(LLMNodeModelRoutingBootstrap, bootstrap_id)
        if bootstrap is None or bootstrap.status != "generating":
            return bootstrap
        workflow = db.get(Workflow, bootstrap.workflow_id)
        node = _graph_node(getattr(workflow, "graph", None), bootstrap.node_id)
        node_data = (
            node.get("data")
            if isinstance(node, dict) and isinstance(node.get("data"), dict)
            else None
        )
        if node_data is None:
            bootstrap.status = "stale"
            bootstrap.stale_reason = "node_removed_before_generation"
            return bootstrap
        downstream_contract = downstream_contract_from_graph(
            workflow.graph,
            bootstrap.node_id,
        )
        current_fingerprint = task_fingerprint(
            node_data,
            downstream_contract=downstream_contract,
            task_description=bootstrap.task_description,
        )
        if current_fingerprint != bootstrap.task_fingerprint:
            bootstrap.status = "stale"
            bootstrap.stale_reason = "task_fingerprint_changed_before_generation"
            return bootstrap
        if bootstrap.created_by is None:
            bootstrap.status = "failed"
            bootstrap.stale_reason = "bootstrap_creator_unavailable"
            return bootstrap

        completed, _ = cls.create(
            db,
            workflow_id=bootstrap.workflow_id,
            organization_id=bootstrap.organization_id,
            node_id=bootstrap.node_id,
            node_data=node_data,
            task_description=bootstrap.task_description,
            default_model_id=bootstrap.default_model_id,
            fallback_model_id=bootstrap.fallback_model_id,
            initial_budget_usd=float(bootstrap.initial_budget_usd),
            created_by=bootstrap.created_by,
            planner=planner,
            planner_model_id=bootstrap.planner_model_id,
            available_candidates=available_candidates,
            downstream_contract=downstream_contract,
            defer_classifier=defer_classifier,
        )
        return completed

    @classmethod
    def mark_pending_generation_failed(
        cls,
        db: Session,
        *,
        bootstrap_id: uuid.UUID,
        error_code: str,
    ) -> None:
        """Worker 오류를 polling UI가 읽을 수 있는 안전한 실패 상태로 남긴다."""
        bootstrap = db.get(LLMNodeModelRoutingBootstrap, bootstrap_id)
        if bootstrap is None:
            return
        bootstrap.status = "failed"
        bootstrap.stale_reason = error_code[:128]
        summary = (
            dict(bootstrap.generation_summary)
            if isinstance(bootstrap.generation_summary, dict)
            else {}
        )
        summary["generation_status"] = "failed"
        summary["generation_error"] = error_code[:80]
        bootstrap.generation_summary = summary

    @staticmethod
    def _classifier_artifact_for_plan(
        plan: BootstrapPlan,
        *,
        defer_classifier: bool,
        embedder: TextEmbedder | None = None,
    ) -> tuple[dict[str, Any], str]:
        """API 응답 경로에서는 무거운 encoder 준비를 뒤로 미룰 수 있다."""
        if defer_classifier:
            return {}, "pending"
        return (
            MDebertaComplexityRegressor.fit(
                [
                    (sample.feature_text, sample.complexity_score)
                    for sample in plan.samples
                ],
                embedder=embedder,
            ),
            "ready",
        )

    @staticmethod
    def _validation_sample_summaries(
        samples: list[BootstrapSample],
    ) -> list[dict[str, Any]]:
        return [
            {
                "difficulty": sample.difficulty,
                "complexity_score": sample.complexity_score,
                "safe_input_summary": sample.safe_input_summary,
                "input_length": sample.input_length,
                "knowledge_enabled": sample.knowledge_enabled,
                "output_format": sample.output_format,
                "planner_reason": sample.reason,
            }
            for sample in samples
        ]

    @classmethod
    def _classifier_generalization_for_samples(
        cls,
        artifact: dict[str, Any],
        *,
        validation_samples: list[BootstrapSample],
        embedder: TextEmbedder | None = None,
        pending: bool = False,
    ) -> dict[str, Any]:
        """holdout에서 검증된 artifact만 runtime semantic 분기에 사용한다."""
        if pending:
            return {
                "status": "pending",
                "passed": False,
                "total_count": len(validation_samples),
                "correct_count": 0,
                "accuracy": None,
                "minimum_confidence": None,
            }
        if not artifact or not validation_samples:
            return {
                "status": "not_available",
                "passed": False,
                "total_count": len(validation_samples),
                "correct_count": 0,
                "accuracy": None,
                "minimum_confidence": None,
            }

        if artifact.get("kind") == MDebertaComplexityRegressor.ARTIFACT_KIND:
            errors: list[float] = []
            confidences: list[float] = []
            for sample in validation_samples:
                try:
                    prediction = MDebertaComplexityRegressor.predict(
                        artifact,
                        sample.feature_text,
                        embedder=embedder,
                    )
                except (RuntimeError, ValueError):
                    return {
                        "status": "failed",
                        "passed": False,
                        "total_count": len(validation_samples),
                        "mean_absolute_error": None,
                        "minimum_confidence": None,
                    }
                errors.append(
                    abs(prediction.complexity_score - sample.complexity_score)
                )
                confidences.append(prediction.confidence)
            mae = sum(errors) / len(errors) if errors else None
            passed = bool(
                len(validation_samples) >= 4
                and mae is not None
                and mae <= 18.0
                and confidences
            )
            return {
                "status": "passed" if passed else "failed",
                "passed": passed,
                "total_count": len(validation_samples),
                "mean_absolute_error": round(mae, 4) if mae is not None else None,
                "minimum_confidence": round(min(confidences), 4) if passed else None,
            }

        correct_count = 0
        confidences: list[float] = []
        predictions_by_difficulty: dict[str, list[tuple[str, float]]] = {
            tier: [] for tier in DIFFICULTY_TIERS
        }
        expected_counts: dict[str, int] = {tier: 0 for tier in DIFFICULTY_TIERS}
        for sample in validation_samples:
            expected_counts[sample.difficulty] += 1
            try:
                prediction = MDebertaDifficultyClassifier.predict(
                    artifact,
                    sample.feature_text,
                    embedder=embedder,
                )
            except (RuntimeError, ValueError):
                return {
                    "status": "failed",
                    "passed": False,
                    "total_count": len(validation_samples),
                    "correct_count": correct_count,
                    "accuracy": None,
                    "minimum_confidence": None,
                }
            predicted_difficulty = str(prediction.difficulty or "")
            if predicted_difficulty in predictions_by_difficulty:
                predictions_by_difficulty[predicted_difficulty].append(
                    (sample.difficulty, float(prediction.confidence))
                )
            if predicted_difficulty == sample.difficulty:
                correct_count += 1
                confidences.append(float(prediction.confidence))

        total_count = len(validation_samples)
        accuracy = correct_count / total_count if total_count else 0.0
        # 생성 예문의 이름만 외운 분류기는 runtime에 쓰지 않는다. holdout 6건 이상,
        # 75% 이상일 때만 semantic 분기를 허용한다. 실제 threshold는 맞춘 holdout의
        # 가장 낮은 confidence를 사용해 E5의 0.3대 score를 0.55 같은 임의값으로
        # 막지 않는다.
        passed = bool(total_count >= 6 and accuracy >= 0.75 and confidences)
        per_difficulty: dict[str, dict[str, Any]] = {}
        validated_difficulties: list[str] = []
        for difficulty in DIFFICULTY_TIERS:
            expected_total = expected_counts[difficulty]
            predictions = predictions_by_difficulty[difficulty]
            correct_predictions = [
                confidence
                for expected_difficulty, confidence in predictions
                if expected_difficulty == difficulty
            ]
            predicted_count = len(predictions)
            correct_for_difficulty = len(correct_predictions)
            minimum_correct_matches = max(1, (expected_total + 1) // 2)
            precision = (
                correct_for_difficulty / predicted_count if predicted_count else 0.0
            )
            recall = (
                correct_for_difficulty / expected_total if expected_total else 0.0
            )
            difficulty_passed = bool(
                expected_total >= 2
                and correct_for_difficulty >= minimum_correct_matches
                and precision >= 0.75
                and recall >= 0.5
            )
            per_difficulty[difficulty] = {
                "status": "ready" if difficulty_passed else "insufficient",
                "passed": difficulty_passed,
                "expected_total_count": expected_total,
                "predicted_count": predicted_count,
                "correct_count": correct_for_difficulty,
                "minimum_correct_matches": minimum_correct_matches,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "minimum_confidence": (
                    round(min(correct_predictions), 4)
                    if difficulty_passed and correct_predictions
                    else None
                ),
            }
            if difficulty_passed:
                validated_difficulties.append(difficulty)
        return {
            "status": (
                "ready"
                if passed
                else "partial"
                if validated_difficulties
                else "insufficient"
            ),
            "passed": passed,
            "total_count": total_count,
            "correct_count": correct_count,
            "accuracy": round(accuracy, 4),
            "minimum_confidence": round(min(confidences), 4) if passed else None,
            "validated_difficulties": validated_difficulties,
            "per_difficulty": per_difficulty,
        }

    @staticmethod
    def _validation_samples_from_summary(
        summary: dict[str, Any],
        *,
        node_data: dict[str, Any],
    ) -> list[BootstrapSample]:
        values = summary.get("validation_samples")
        if not isinstance(values, list):
            return []
        runtime_node_data = SimpleNamespace(**node_data)
        samples: list[BootstrapSample] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            difficulty = str(item.get("difficulty") or "")
            payload = item.get("safe_input_summary")
            if difficulty not in DIFFICULTY_TIERS or not isinstance(payload, dict):
                continue
            feature_text = ModelRouter.bootstrap_classifier_feature_text(
                payload,
                runtime_node_data,
            )
            if not feature_text:
                continue
            samples.append(
                BootstrapSample(
                    source="synthetic",
                    difficulty=difficulty,  # type: ignore[arg-type]
                    safe_input_summary=payload,
                    feature_text=feature_text,
                    source_node_run_id=None,
                    reason=str(item.get("planner_reason") or "") or None,
                    input_length=int(item.get("input_length") or len(feature_text)),
                    knowledge_enabled=bool(item.get("knowledge_enabled")),
                    output_format=str(item.get("output_format") or "text"),
                    sample_role="validation",
                )
            )
        return samples

    @classmethod
    def finalize_request_complexity_classifier(
        cls,
        db: Session,
        *,
        bootstrap_id: uuid.UUID,
    ) -> LLMNodeModelRoutingBootstrap | None:
        """완성된 요청 난이도 분류기를 이미 배포된 정책에도 반영한다.

        bootstrap 생성 Worker가 학습한 artifact를 policy snapshot에 복사한다. 정책은
        요청별 classifier와 전역 모델 profile을 사용하고, task profile은 화면 설명과
        artifact 생성 근거로만 남긴다.
        """
        bootstrap = db.get(LLMNodeModelRoutingBootstrap, bootstrap_id)
        if bootstrap is None:
            return None
        summary = (
            dict(bootstrap.generation_summary)
            if isinstance(bootstrap.generation_summary, dict)
            else {}
        )
        artifact = bootstrap.classifier_artifact
        if not isinstance(artifact, dict) or not artifact:
            return bootstrap
        summary["profile_status"] = "ready"
        summary["classifier_status"] = "ready"
        bootstrap.generation_summary = summary
        profile = summary.get("task_complexity_profile")
        cls._sync_request_complexity_classifier_to_deployment_policies(
            db,
            bootstrap_id=bootstrap.id,
            artifact=artifact,
            classifier_generalization=cls._classifier_generalization_from_summary(summary),
            task_complexity_profile=profile if isinstance(profile, dict) else None,
        )
        return bootstrap

    @classmethod
    def build_deferred_classifier(
        cls,
        db: Session,
        *,
        bootstrap_id: uuid.UUID,
    ) -> LLMNodeModelRoutingBootstrap | None:
        """이미 발행된 queue 메시지가 준비된 artifact를 policy에 반영하는 호환 경로다."""
        return cls.finalize_request_complexity_classifier(
            db,
            bootstrap_id=bootstrap_id,
        )

    @staticmethod
    def _apply_request_complexity_classifier_to_policy(
        policy: LLMNodeModelRoutingPolicy,
        *,
        artifact: dict[str, Any],
        classifier_generalization: dict[str, Any] | None,
        task_complexity_profile: dict[str, Any] | None = None,
    ) -> None:
        active_policy = (
            dict(policy.active_policy)
            if isinstance(policy.active_policy, dict)
            else {}
        )
        if active_policy.get("strategy_id") == "judge_bootstrap_incremental_v1":
            # 새 전략은 Judge label을 local router artifact로 축적한다. 과거
            # complexity worker가 끝났다는 이유로 정책 전략을 되돌리지 않는다.
            return
        active_policy["strategy_id"] = "bootstrap_request_complexity_regression_v4"
        active_policy["classifier_artifact"] = dict(artifact)
        if task_complexity_profile is not None:
            active_policy["task_complexity_profile"] = dict(task_complexity_profile)
        active_policy.pop("difficulty_rules", None)
        active_policy["rules"] = []
        if classifier_generalization is not None:
            validations = (
                dict(active_policy.get("generalization_validation"))
                if isinstance(active_policy.get("generalization_validation"), dict)
                else {}
            )
            validations["classifier"] = dict(classifier_generalization)
            active_policy["generalization_validation"] = validations
        policy.active_policy = active_policy

    @classmethod
    def _sync_request_complexity_classifier_to_deployment_policies(
        cls,
        db: Session,
        *,
        bootstrap_id: uuid.UUID,
        artifact: dict[str, Any],
        classifier_generalization: dict[str, Any] | None,
        task_complexity_profile: dict[str, Any] | None = None,
    ) -> int:
        policies = (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.bootstrap_id == bootstrap_id)
            .all()
        )
        for policy in policies:
            cls._apply_request_complexity_classifier_to_policy(
                policy,
                artifact=artifact,
                classifier_generalization=classifier_generalization,
                task_complexity_profile=task_complexity_profile,
            )
        return len(policies)

    @classmethod
    def finalize_task_complexity_profile(
        cls,
        db: Session,
        *,
        bootstrap_id: uuid.UUID,
    ) -> LLMNodeModelRoutingBootstrap | None:
        """기존 Worker/테스트 호출명을 유지하는 v3 호환 별칭이다."""
        return cls.finalize_request_complexity_classifier(
            db,
            bootstrap_id=bootstrap_id,
        )

    @staticmethod
    def _apply_classifier_artifact_to_policy(
        policy: LLMNodeModelRoutingPolicy,
        *,
        artifact: dict[str, Any],
        classifier_generalization: dict[str, Any] | None = None,
    ) -> None:
        """이미 배포된 policy의 classifier snapshot을 안전하게 교체한다."""
        active_policy = (
            dict(policy.active_policy)
            if isinstance(policy.active_policy, dict)
            else {}
        )
        if active_policy.get("strategy_id") == "judge_bootstrap_incremental_v1":
            return
        active_policy["classifier_artifact"] = dict(artifact)
        active_policy["strategy_id"] = "bootstrap_request_complexity_regression_v4"
        active_policy.pop("difficulty_rules", None)
        active_policy["rules"] = []
        if classifier_generalization is not None:
            generalization_validation = (
                dict(active_policy.get("generalization_validation"))
                if isinstance(active_policy.get("generalization_validation"), dict)
                else {}
            )
            generalization_validation["classifier"] = dict(
                classifier_generalization
            )
            active_policy["generalization_validation"] = generalization_validation
        policy.active_policy = active_policy

    @classmethod
    def _sync_classifier_artifact_to_deployment_policies(
        cls,
        db: Session,
        *,
        bootstrap_id: uuid.UUID,
        artifact: dict[str, Any],
        classifier_generalization: dict[str, Any] | None = None,
    ) -> int:
        """같은 bootstrap을 참조하는 deployment snapshot을 갱신한다."""
        policies = (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.bootstrap_id == bootstrap_id)
            .all()
        )
        for policy in policies:
            cls._apply_classifier_artifact_to_policy(
                policy,
                artifact=artifact,
                classifier_generalization=classifier_generalization,
            )
        return len(policies)

    @staticmethod
    def _classifier_generalization_from_summary(
        summary: dict[str, Any],
    ) -> dict[str, Any] | None:
        generalization_validation = summary.get("generalization_validation")
        if not isinstance(generalization_validation, dict):
            return None
        classifier = generalization_validation.get("classifier")
        return dict(classifier) if isinstance(classifier, dict) else None

    @classmethod
    def mark_deferred_classifier_failed(
        cls,
        db: Session,
        *,
        bootstrap_id: uuid.UUID,
        error_code: str,
    ) -> None:
        bootstrap = db.get(LLMNodeModelRoutingBootstrap, bootstrap_id)
        if bootstrap is None:
            return
        summary = (
            dict(bootstrap.generation_summary)
            if isinstance(bootstrap.generation_summary, dict)
            else {}
        )
        summary["classifier_status"] = "failed"
        summary["classifier_error"] = error_code[:80]
        bootstrap.generation_summary = summary

    @classmethod
    def active_policy_for_bootstrap(
        cls, bootstrap: LLMNodeModelRoutingBootstrap
    ) -> dict[str, Any]:
        summary = bootstrap.generation_summary if isinstance(bootstrap.generation_summary, dict) else {}
        difficulty_models = summary.get("difficulty_models")
        difficulty_models = difficulty_models if isinstance(difficulty_models, dict) else {}
        task_complexity_profile = summary.get("task_complexity_profile")
        task_complexity_profile = (
            dict(task_complexity_profile)
            if isinstance(task_complexity_profile, dict)
            else {}
        )
        return {
            # bootstrap은 더 이상 정적 난이도 회귀 결과로 모델을 고정하지 않는다.
            # 첫 운영 요청은 Judge가 후보 중 하나를 고르고, 이후 local router가 그
            # 선택을 점진적으로 재현한다.
            "strategy": "judge_bootstrap_incremental",
            "strategy_id": "judge_bootstrap_incremental_v1",
            "policy_version": f"bootstrap-{str(bootstrap.id)[:8]}",
            "bootstrap_id": str(bootstrap.id),
            "task_fingerprint": bootstrap.task_fingerprint,
            "default_model_id": bootstrap.default_model_id,
            "fallback_model_id": bootstrap.fallback_model_id,
            "judge_model_id": bootstrap.default_model_id,
            "task_complexity_profile": task_complexity_profile,
            "classifier_artifact": (
                dict(bootstrap.classifier_artifact)
                if isinstance(bootstrap.classifier_artifact, dict)
                else {}
            ),
            "minimum_confidence": 0.45,
            "generalization_validation": (
                summary.get("generalization_validation")
                if isinstance(summary.get("generalization_validation"), dict)
                else {}
            ),
            "difficulty_models": difficulty_models,
            "global_profile_matches": (
                summary.get("global_profile_matches")
                if isinstance(summary.get("global_profile_matches"), dict)
                else {}
            ),
            "global_profile_catalog": (
                summary.get("global_profile_catalog")
                if isinstance(summary.get("global_profile_catalog"), dict)
                else {}
            ),
            "rules": [],
            "learning": {
                "mode": "judge_first",
                "local_confidence_threshold": 0.78,
                "judged_request_count": 0,
                "selected_model_ids": [],
                "local_router_artifact": {},
            },
        }

    @classmethod
    def public_summary(
        cls,
        bootstrap: LLMNodeModelRoutingBootstrap | None,
        *,
        include_samples: bool = False,
        db: Session | None = None,
    ) -> dict[str, Any] | None:
        if bootstrap is None:
            return None
        summary = bootstrap.generation_summary if isinstance(bootstrap.generation_summary, dict) else {}
        payload: dict[str, Any] = {
            "id": str(bootstrap.id),
            "status": bootstrap.status,
            "source": bootstrap.source,
            "task_fingerprint": bootstrap.task_fingerprint,
            "task_description": bootstrap.task_description,
            "default_model_id": bootstrap.default_model_id,
            "fallback_model_id": bootstrap.fallback_model_id,
            "initial_budget_usd": float(bootstrap.initial_budget_usd),
            "planner_model_id": bootstrap.planner_model_id,
            "planner_cost_usd": float(bootstrap.planner_cost_usd)
            if bootstrap.planner_cost_usd is not None
            else None,
            "generation_summary": summary,
            "stale_reason": bootstrap.stale_reason,
            "created_at": bootstrap.created_at.isoformat() if bootstrap.created_at else None,
        }
        if include_samples and db is not None:
            payload["samples"] = [
                {
                    "id": str(sample.id),
                    "source": sample.source,
                    "difficulty": sample.difficulty,
                    "complexity_score": float(sample.complexity_score),
                    "safe_input_summary": sample.safe_input_summary,
                    "input_length": sample.input_length,
                    "knowledge_enabled": sample.knowledge_enabled,
                    "output_format": sample.output_format,
                    "planner_reason": sample.planner_reason,
                }
                for sample in (
                    db.query(LLMNodeModelRoutingBootstrapSample)
                    .filter(LLMNodeModelRoutingBootstrapSample.bootstrap_id == bootstrap.id)
                    .order_by(LLMNodeModelRoutingBootstrapSample.ordinal.asc())
                    .all()
                )
            ]
        return payload

    @classmethod
    def _find_exact_bootstrap(
        cls,
        db: Session,
        *,
        workflow_id: uuid.UUID,
        node_id: str,
        task_fingerprint_value: str,
    ) -> LLMNodeModelRoutingBootstrap | None:
        return (
            db.query(LLMNodeModelRoutingBootstrap)
            .filter(LLMNodeModelRoutingBootstrap.workflow_id == workflow_id)
            .filter(LLMNodeModelRoutingBootstrap.node_id == node_id)
            .filter(
                LLMNodeModelRoutingBootstrap.task_fingerprint
                == task_fingerprint_value
            )
            .order_by(LLMNodeModelRoutingBootstrap.created_at.desc())
            .first()
        )

    @classmethod
    def _collect_history_runs(
        cls,
        db: Session,
        *,
        workflow_id: uuid.UUID,
        organization_id: uuid.UUID | None,
        node_id: str,
        task_fingerprint_value: str,
    ) -> tuple[list[BootstrapHistoryRun], dict[str, int]]:
        rows = (
            db.query(WorkflowRun, WorkflowNodeRun, WorkflowDeployment)
            .join(WorkflowNodeRun, WorkflowNodeRun.workflow_run_id == WorkflowRun.id)
            .join(WorkflowDeployment, WorkflowDeployment.id == WorkflowRun.deployment_id)
            .filter(WorkflowRun.workflow_id == workflow_id)
            .filter(WorkflowRun.deployment_id.is_not(None))
            .filter(WorkflowRun.status == RunStatus.SUCCESS)
            .filter(WorkflowRun.trigger_mode.in_(OPERATIONAL_TRIGGER_MODES))
            .filter(WorkflowNodeRun.node_id == node_id)
            .filter(WorkflowNodeRun.node_type == "llmNode")
            .filter(WorkflowNodeRun.status == NodeRunStatus.SUCCESS)
            .order_by(WorkflowRun.finished_at.desc(), WorkflowRun.id.desc())
            .limit(200)
            .all()
        )
        policy = TracePolicyService.resolve_redaction_policy(
            db, organization_id=organization_id
        )
        exclusions: dict[str, int] = {}
        selected: list[BootstrapHistoryRun] = []
        seen_feature_hashes: set[str] = set()
        for workflow_run, node_run, deployment in rows:
            snapshot_node = _graph_node(getattr(deployment, "graph_snapshot", None), node_id)
            snapshot_data = (
                snapshot_node.get("data")
                if isinstance(snapshot_node, dict)
                and isinstance(snapshot_node.get("data"), dict)
                else None
            )
            if snapshot_data is None:
                exclusions["snapshot_node_missing"] = exclusions.get("snapshot_node_missing", 0) + 1
                continue
            snapshot_contract = downstream_contract_from_graph(
                getattr(deployment, "graph_snapshot", None), node_id
            )
            if task_fingerprint(snapshot_data, downstream_contract=snapshot_contract) != task_fingerprint_value:
                exclusions["task_fingerprint_mismatch"] = exclusions.get("task_fingerprint_mismatch", 0) + 1
                continue
            redacted = TraceRedactionService.redact_payload(
                getattr(node_run, "inputs", {}) or {}, policy, payload_kind="input"
            )
            if redacted.failed:
                exclusions["redaction_failed"] = exclusions.get("redaction_failed", 0) + 1
                continue
            feature_text = ModelRouter.bootstrap_classifier_feature_text(
                getattr(node_run, "inputs", {}) or {},
                SimpleNamespace(**snapshot_data),
            )
            feature_hash = hashlib.sha256(feature_text.encode("utf-8")).hexdigest()
            if not feature_text or feature_hash in seen_feature_hashes:
                exclusions["duplicate_or_empty_input"] = exclusions.get("duplicate_or_empty_input", 0) + 1
                continue
            seen_feature_hashes.add(feature_hash)
            selected.append(
                BootstrapHistoryRun(
                    node_run_id=str(node_run.id),
                    safe_input_summary=_safe_summary(redacted.redacted_payload),
                    feature_text=feature_text,
                    input_length=len(feature_text),
                    knowledge_enabled=bool(
                        snapshot_data.get("knowledgeBases")
                        or snapshot_data.get("knowledgeCollections")
                    ),
                    output_format=_output_format(snapshot_data.get("output_format")),
                    executed_at=(
                        workflow_run.finished_at.isoformat()
                        if workflow_run.finished_at
                        else None
                    ),
                )
            )
            if len(selected) >= MAX_HISTORY_SAMPLES:
                break
        return selected, exclusions

    @staticmethod
    def _history_mode(history_count: int) -> BootstrapSource:
        if history_count >= MIN_HISTORY_FOR_HISTORY_ONLY:
            return "history"
        if history_count:
            return "hybrid"
        return "synthetic"

    @classmethod
    def _difficulty_model_selection(
        cls,
        db: Session,
        candidates: list[ModelCandidate],
        *,
        default_model_id: str,
        node_data: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]], dict[str, Any]]:
        """각 난이도에서 모든 catalog 후보를 전역 profile로 점수화한다.

        이전 구현은 가격순으로 첫·중간·마지막 모델만 골랐다. 이 경로는 전역
        profile의 난이도별 품질 하한, 예상 latency, fallback 위험과 catalog 가격을
        함께 비교한다. 실제 노드 운영 성적은 아직 없는 bootstrap 단계이므로
        `node_profile` 없이 global prior만 사용한다.
        """
        if not candidates:
            raise ValueError("자동 라우팅에 사용할 수 있는 채팅 모델이 없습니다.")
        normalized_default = str(default_model_id or "").strip().lower()
        profiles = ModelRoutingGlobalProfileStore.resolve_available_profiles(
            db,
            available_model_ids=[candidate.model_id for candidate in candidates],
            materialize_missing=True,
        )
        global_profile_catalog = ModelRoutingGlobalProfileScorer.catalog_snapshot(
            candidates=candidates,
            global_profiles=profiles,
        )
        if normalized_default not in profiles:
            normalized_default = str(candidates[0].model_id).strip().lower()
        estimated_input_tokens, estimated_output_tokens = cls._bootstrap_token_estimate(
            node_data
        )
        selected_models: dict[str, str] = {}
        matches: dict[str, dict[str, Any]] = {}
        for difficulty in DIFFICULTY_TIERS:
            result = ModelRoutingGlobalProfileScorer.rank_catalog_candidates(
                candidates=candidates,
                global_profiles=profiles,
                difficulty=ModelRoutingDifficultyDistribution.from_mapping(
                    {difficulty: 1.0}
                ),
                input_profile="medium",
                estimated_input_tokens=estimated_input_tokens,
                estimated_output_tokens=estimated_output_tokens,
                default_model_id=normalized_default,
            )
            selected_models[difficulty] = result.selected_model_id
            selected_score = result.by_model[result.selected_model_id]
            matches[difficulty] = {
                "selected_model_id": result.selected_model_id,
                "fallback_model_id": result.fallback_model_id,
                "compared_model_count": len(result.ranked_candidates),
                "quality_floor": result.quality_floor,
                "quality_lower_bound": selected_score.quality_lower_bound,
                "expected_cost_usd": selected_score.expected_cost_usd,
                "expected_latency_ms": selected_score.expected_latency_ms,
                "profile_source": selected_score.profile_source,
                "profile_version": selected_score.profile_version,
            }
        return selected_models, matches, global_profile_catalog

    @staticmethod
    def _bootstrap_token_estimate(node_data: dict[str, Any]) -> tuple[int, int]:
        """초기 policy 비교용 token 추정치. 실제 실행 token은 runtime에서 별도 기록한다."""
        prompts = (
            str(node_data.get("system_prompt") or "")
            + str(node_data.get("user_prompt") or "")
            + str(node_data.get("assistant_prompt") or "")
        )
        estimated_input = max(256, len(prompts) // 4)
        parameters = node_data.get("parameters")
        parameters = parameters if isinstance(parameters, dict) else {}
        try:
            configured_output = int(parameters.get("max_tokens") or 512)
        except (TypeError, ValueError):
            configured_output = 512
        return estimated_input, min(max(configured_output, 64), 8_192)

    @staticmethod
    def _planner_cost(planner: BootstrapPlanner) -> float:
        usage = getattr(planner, "usage", None)
        if not isinstance(usage, dict):
            return 0.0
        try:
            return max(0.0, float(usage.get("cost") or 0.0))
        except (TypeError, ValueError):
            return 0.0


def task_fingerprint(
    node_data: Any,
    *,
    downstream_contract: dict[str, Any] | None = None,
    task_description: str | None = None,
) -> str:
    """모델 선택값을 제외한 '무슨 작업인가'의 canonical fingerprint."""
    payload = safe_task_summary(
        node_data,
        task_description=(
            task_description
            if task_description is not None
            else str(_node_value(node_data, "model_routing_task_description", "") or "")
        ),
        downstream_contract=downstream_contract,
    )
    # 작업 설명은 Planner가 노드의 목적을 이해하기 위한 사용자 보조 정보다.
    # 자동 라우팅을 켜기 전 배포 snapshot에는 이 필드가 없으므로, 지문에 넣으면
    # 같은 프롬프트/Schema/RAG의 과거 운영 로그를 전부 다른 작업으로 오인한다.
    # 실제 작업 동일성은 노드 설정과 후속 계약만으로 판단한다.
    payload.pop("task_description", None)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def safe_task_summary(
    node_data: Any,
    *,
    task_description: str,
    downstream_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Planner가 작업을 이해할 최소 설정만 정규화한다.

    여기에는 workflow input 원문, credential, 현재/대체 모델, routing 상태가 없다.
    """
    return {
        "task_description": str(task_description or "").strip(),
        "prompts": {
            "system": str(_node_value(node_data, "system_prompt", "") or ""),
            "user": str(_node_value(node_data, "user_prompt", "") or ""),
            "assistant": str(_node_value(node_data, "assistant_prompt", "") or ""),
        },
        "input_variables": _json_safe(_node_value(node_data, "referenced_variables", []) or []),
        "output_format": _json_safe(_node_value(node_data, "output_format", None)),
        "knowledge_enabled": bool(
            _node_value(node_data, "knowledgeBases", None)
            or _node_value(node_data, "knowledgeCollections", None)
        ),
        "knowledge": {
            "knowledge_bases": _json_safe(
                _node_value(node_data, "knowledgeBases", []) or []
            ),
            "knowledge_collections": _json_safe(
                _node_value(node_data, "knowledgeCollections", []) or []
            ),
            "top_k": _node_value(node_data, "topK", None),
            "score_threshold": _node_value(node_data, "scoreThreshold", None),
            "retrieved_context_max_chars": _node_value(node_data, "retrievedContextMaxChars", None),
        },
        "downstream_contract": _json_safe(downstream_contract or {}),
    }


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(child) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _node_value(node_data: Any, key: str, default: Any = None) -> Any:
    if isinstance(node_data, dict):
        return node_data.get(key, default)
    return getattr(node_data, key, default)


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _graph_node(graph: Any, node_id: str) -> dict[str, Any] | None:
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    for node in nodes if isinstance(nodes, list) else []:
        if isinstance(node, dict) and str(node.get("id")) == str(node_id):
            return node
    return None


def downstream_contract_from_graph(graph: Any, node_id: str) -> dict[str, Any]:
    """후속 노드가 현재 LLM 출력에 요구하는 최소 계약만 fingerprint에 넣는다."""
    if not isinstance(graph, dict):
        return {"consumers": []}
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    consumers: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict) or str(edge.get("source")) != str(node_id):
            continue
        target = _graph_node(graph, str(edge.get("target") or ""))
        data = target.get("data") if isinstance(target, dict) else {}
        if not isinstance(data, dict):
            data = {}
        consumers.append(
            {
                "node_type": str(target.get("type") or "") if target else "",
                "node_id": str(target.get("id") or "") if target else "",
                "referenced_variables": _json_safe(data.get("referenced_variables") or []),
                "variable_mappings": _json_safe(
                    data.get("variableMappings") or data.get("mappings") or []
                ),
                "output_format": _json_safe(data.get("output_format")),
            }
        )
    return {"consumers": consumers}


def _feature_text(value: Any) -> str:
    """원문을 DB에 저장하지 않고 classifier 학습 중 메모리에서만 사용할 문자열."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(
            f"{key} {_feature_text(child)}" for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return " ".join(_feature_text(item) for item in value)
    return str(value)


def _safe_summary(value: Any, *, depth: int = 0) -> dict[str, Any]:
    """원문 문자열을 저장하지 않는 inspector/Planner용 input 구조 요약."""
    if depth >= 3:
        return {"kind": "nested", "truncated": True}
    if isinstance(value, dict):
        return {
            "kind": "object",
            "fields": {
                str(key): _safe_summary(child, depth=depth + 1)
                for key, child in value.items()
            },
        }
    if isinstance(value, list):
        return {
            "kind": "array",
            "length": len(value),
            "item": _safe_summary(value[0], depth=depth + 1) if value else None,
        }
    if isinstance(value, str):
        return {"kind": "string", "length": len(value)}
    if isinstance(value, bool):
        return {"kind": "boolean"}
    if isinstance(value, (int, float)):
        return {"kind": "number"}
    return {"kind": "null" if value is None else type(value).__name__}


def _output_format(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("type") or "text").lower()
    return str(value or "text").lower()
