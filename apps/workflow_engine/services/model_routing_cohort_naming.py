"""자동 발견 입력군의 사용자 친화 이름과 영문 key를 생성한다.

운영 입력 원문은 이 서비스가 실행되는 동안에만 읽는다. 이름 생성 모델에는
가림 처리한 짧은 표본만 전달하고, DB에는 생성된 label/key만 저장한다.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import uuid
from typing import Any, Callable, Iterable

from sqlalchemy.orm import Session

from apps.shared.db.models.model_routing_cohort import (
    LLMNodeModelRoutingCohort,
    LLMNodeModelRoutingObservation,
)
from apps.shared.db.models.model_routing_policy import LLMNodeModelRoutingPolicy
from apps.shared.db.models.workflow_run import WorkflowNodeRun
from apps.shared.services.tracing.policy import TracePolicyService
from apps.shared.services.tracing.redaction import TraceRedactionService
from apps.workflow_engine.services.llm_service import LLMService
from apps.workflow_engine.services.model_routing_adaptive_store import (
    AdaptiveModelRoutingCohortStore,
)


logger = logging.getLogger(__name__)
NamingInvoker = Callable[[list[str]], Any]


class AdaptiveModelRoutingCohortNamingService:
    """순번뿐인 자동 입력군을 실제 업무 의미가 드러나는 이름으로 바꾼다."""

    MAX_SAMPLES = 5
    MAX_SAMPLE_CHARS = 600
    MAX_LABEL_CHARS = 40
    MAX_KEY_CHARS = 64

    @classmethod
    def name_pending_auto_cohorts(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        node_data: dict[str, Any],
        execution_subject_id: uuid.UUID | None = None,
        available_model_ids: Iterable[str] = (),
        preferred_model_id: str | None = None,
        invoke: NamingInvoker | None = None,
    ) -> list[LLMNodeModelRoutingCohort]:
        """아직 의미 이름이 없는 자동 입력군만 보정한다.

        ``invoke``는 테스트용 경계다. 운영에서는 실행 주체가 사용할 수 있는
        저비용 모델을 선택해 한 입력군당 한 번만 호출한다.
        """
        cohorts = (
            db.query(LLMNodeModelRoutingCohort)
            .filter(LLMNodeModelRoutingCohort.policy_id == policy.id)
            .all()
        )
        pending = [cohort for cohort in cohorts if cls._needs_naming(cohort)]
        if not pending:
            return []
        if invoke is None and (
            execution_subject_id is None
            or getattr(policy, "organization_id", None) is None
        ):
            return []

        existing_keys = {str(cohort.cohort_key) for cohort in cohorts}
        renamed: list[LLMNodeModelRoutingCohort] = []
        for cohort in pending:
            samples = cls._cohort_samples(
                db,
                cohort_id=cohort.id,
                node_data=node_data,
            )
            if not samples:
                continue
            try:
                response = (
                    invoke(samples)
                    if invoke is not None
                    else cls._invoke_model(
                        db,
                        policy=policy,
                        execution_subject_id=execution_subject_id,
                        available_model_ids=set(available_model_ids),
                        preferred_model_id=preferred_model_id,
                        samples=samples,
                    )
                )
                identity = cls._identity(response)
            except Exception as exc:
                logger.warning(
                    "[Model-Routing] automatic cohort naming skipped: error_type=%s",
                    type(exc).__name__,
                )
                continue
            if identity is None:
                continue

            old_key = str(cohort.cohort_key)
            existing_keys.discard(old_key)
            new_key = cls.unique_key(
                identity["key"],
                existing_keys=existing_keys,
                stable_source=old_key,
            )
            cohort.label = identity["label"]
            cohort.label_en = new_key
            cohort.cohort_key = new_key
            cls._replace_policy_reference(
                policy,
                old_key=old_key,
                new_key=new_key,
                new_label=identity["label"],
            )
            existing_keys.add(new_key)
            renamed.append(cohort)

        if renamed:
            db.flush()
        return renamed

    @classmethod
    def unique_key(
        cls,
        value: str,
        *,
        existing_keys: set[str],
        stable_source: str,
    ) -> str:
        """같은 주제명이 있어도 policy 내 key를 결정적으로 구분한다."""
        if value not in existing_keys:
            return value
        suffix = hashlib.sha256(stable_source.encode("utf-8")).hexdigest()[:8]
        prefix = value[: cls.MAX_KEY_CHARS - len(suffix) - 1].rstrip("_")
        return f"{prefix}_{suffix}"

    @staticmethod
    def _needs_naming(cohort: Any) -> bool:
        if str(getattr(cohort, "source", "")) != "auto":
            return False
        if str(getattr(cohort, "status", "")) == "retired":
            return False
        label = str(getattr(cohort, "label", ""))
        label_en = str(getattr(cohort, "label_en", ""))
        key = str(getattr(cohort, "cohort_key", ""))
        return (
            label.startswith("자동 발견 입력군")
            or label_en.startswith("auto_cohort_")
            or key.startswith("auto-")
        )

    @classmethod
    def _cohort_samples(
        cls,
        db: Session,
        *,
        cohort_id: uuid.UUID,
        node_data: dict[str, Any],
    ) -> list[str]:
        observations = (
            db.query(LLMNodeModelRoutingObservation)
            .filter(LLMNodeModelRoutingObservation.matched_cohort_id == cohort_id)
            .order_by(LLMNodeModelRoutingObservation.observed_at.desc())
            .limit(cls.MAX_SAMPLES)
            .all()
        )
        if not observations:
            return []
        node_run_ids = [item.workflow_node_run_id for item in observations]
        node_runs = (
            db.query(WorkflowNodeRun)
            .filter(WorkflowNodeRun.id.in_(node_run_ids))
            .all()
        )
        node_run_by_id = {row.id: row for row in node_runs}
        samples: list[str] = []
        for observation in observations:
            node_run = node_run_by_id.get(observation.workflow_node_run_id)
            if node_run is None:
                continue
            query = AdaptiveModelRoutingCohortStore._query_text(
                node_run.inputs if isinstance(node_run.inputs, dict) else {},
                node_data,
            )
            safe_query = cls._redacted_query(query)
            if safe_query and safe_query not in samples:
                samples.append(safe_query)
        return samples[: cls.MAX_SAMPLES]

    @classmethod
    def _redacted_query(cls, query: str) -> str:
        redaction = TraceRedactionService.redact_payload(
            {"query": query[: cls.MAX_SAMPLE_CHARS]},
            TracePolicyService.fail_closed_redaction_policy(),
            payload_kind="model_routing_cohort_naming",
        )
        if redaction.failed or not isinstance(redaction.redacted_payload, dict):
            return ""
        return " ".join(
            str(redaction.redacted_payload.get("query") or "").split()
        )[: cls.MAX_SAMPLE_CHARS]

    @classmethod
    def _invoke_model(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        execution_subject_id: uuid.UUID,
        available_model_ids: set[str],
        preferred_model_id: str | None,
        samples: list[str],
    ) -> Any:
        model_id = cls._naming_model(
            available_model_ids,
            preferred_model_id=preferred_model_id,
        )
        if not model_id:
            raise ValueError("cohort_naming_model_unavailable")
        selection = LLMService.get_runtime_client_for_user(
            db,
            user_id=execution_subject_id,
            model_id=model_id,
            organization_id=policy.organization_id,
        )
        response = selection.client.invoke_sync(
            [
                {
                    "role": "system",
                    "content": (
                        "같은 업무 목적을 가진 문의 묶음의 이름을 만듭니다. "
                        "반드시 JSON object 하나만 반환하세요. "
                        "label은 순번이나 '자동 입력군' 표현 없이 한국어 업무명 2~20자, "
                        "key는 같은 뜻의 영문 snake_case 2~40자로 작성하세요. "
                        "개인정보나 문의 원문을 이름에 포함하지 마세요. "
                        "형식: {\"label\": \"재무 결산·지급 승인\", "
                        "\"key\": \"finance_closing_approval\"}"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"queries": samples}, ensure_ascii=False),
                },
            ],
            temperature=0.1,
            max_tokens=160,
        )
        usage = cls._usage(response)
        cost = LLMService.calculate_cost(
            db,
            model_id,
            usage["prompt_tokens"],
            usage["completion_tokens"],
        )
        LLMService.log_usage(
            db,
            user_id=execution_subject_id,
            model_id=model_id,
            usage=usage,
            cost=float(cost or 0),
            organization_id=policy.organization_id,
            workflow_id=policy.workflow_id,
            node_id=f"{policy.node_id}:model-routing-cohort-naming",
            credential_id=selection.credential_id,
        )
        return response

    @staticmethod
    def _naming_model(
        available_model_ids: set[str],
        *,
        preferred_model_id: str | None,
    ) -> str:
        for model_id in LLMService.EFFICIENT_MODELS.values():
            if model_id in available_model_ids:
                return model_id
        if preferred_model_id and preferred_model_id in available_model_ids:
            return preferred_model_id
        return next(iter(sorted(available_model_ids)), "")

    @classmethod
    def _identity(cls, response: Any) -> dict[str, str] | None:
        payload = response if isinstance(response, dict) else {}
        if "label" not in payload or "key" not in payload:
            content = cls._response_text(response)
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if match is None:
                return None
            try:
                decoded = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
            payload = decoded if isinstance(decoded, dict) else {}

        label = " ".join(str(payload.get("label") or "").split())[
            : cls.MAX_LABEL_CHARS
        ]
        key = re.sub(
            r"[^a-z0-9]+",
            "_",
            str(payload.get("key") or "").lower(),
        ).strip("_")[: cls.MAX_KEY_CHARS]
        if (
            len(label) < 2
            or label.startswith("자동 발견 입력군")
            or len(key) < 2
            or not re.fullmatch(r"[a-z][a-z0-9_]*", key)
        ):
            return None
        return {"label": label, "key": key}

    @staticmethod
    def _response_text(response: Any) -> str:
        if not isinstance(response, dict):
            return ""
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first, dict) else {}
            if isinstance(message, dict):
                return str(message.get("content") or "")
        return str(response.get("content") or "")

    @staticmethod
    def _usage(response: Any) -> dict[str, int]:
        usage = response.get("usage") if isinstance(response, dict) else {}
        usage = usage if isinstance(usage, dict) else {}
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        )
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": int(usage.get("total_tokens") or prompt + completion),
        }

    @staticmethod
    def _replace_policy_reference(
        policy: LLMNodeModelRoutingPolicy,
        *,
        old_key: str,
        new_key: str,
        new_label: str,
    ) -> None:
        policy.active_policy = AdaptiveModelRoutingCohortNamingService._replace_snapshot_reference(
            policy.active_policy,
            old_key=old_key,
            new_key=new_key,
            new_label=new_label,
        )
        pending = getattr(policy, "pending_policy", None)
        if isinstance(pending, dict):
            policy.pending_policy = (
                AdaptiveModelRoutingCohortNamingService._replace_snapshot_reference(
                    pending,
                    old_key=old_key,
                    new_key=new_key,
                    new_label=new_label,
                )
            )

    @staticmethod
    def _replace_snapshot_reference(
        snapshot: Any,
        *,
        old_key: str,
        new_key: str,
        new_label: str,
    ) -> dict[str, Any]:
        updated = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
        for rule in updated.get("rules") if isinstance(updated.get("rules"), list) else []:
            if not isinstance(rule, dict):
                continue
            condition = rule.get("when")
            if (
                isinstance(condition, dict)
                and condition.get("semantic_cohort_id") == old_key
            ):
                condition["semantic_cohort_id"] = new_key
        semantic_router = updated.get("semantic_router")
        routes = (
            semantic_router.get("routes")
            if isinstance(semantic_router, dict)
            else []
        )
        for route in routes if isinstance(routes, list) else []:
            if not isinstance(route, dict) or route.get("cohort_id") != old_key:
                continue
            route["cohort_id"] = new_key
            route["label"] = new_label
        return updated
