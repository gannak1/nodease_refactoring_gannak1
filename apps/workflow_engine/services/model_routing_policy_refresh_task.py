"""사전 지식 기반 model-routing policy 갱신 orchestration."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.shared.db.models.model_routing_policy import (
    LLMNodeModelRoutingPolicy,
    LLMNodeModelRoutingPolicyRunEvent,
    LLMNodeModelRoutingPolicyUpdate,
)
from apps.shared.db.models.workflow_deployment import WorkflowDeployment
from apps.shared.services.model_routing_model_filter import (
    filter_model_routing_available_model_ids,
)
from apps.workflow_engine.services.llm_service import LLMService
from apps.workflow_engine.services.model_router import ModelRouter, ModelRouterContext
from apps.workflow_engine.services.model_routing_policy_lifecycle import (
    ModelRoutingPolicyLifecycleService,
)
from apps.workflow_engine.services.model_routing_policy_refresh import (
    ModelRoutingPolicyRefreshService,
)
from apps.workflow_engine.services.model_routing_prior_guided_policy import (
    compile_prior_guided_policy_from_db,
)


logger = logging.getLogger(__name__)


class PersistedModelRoutingPolicyRefreshService:
    """모델 catalog prior와 운영 집계를 이용해 저장 정책을 갱신한다."""

    @classmethod
    def refresh(cls, db: Session, *, policy_id: str | uuid.UUID, trigger: str):
        policy = (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.id == uuid.UUID(str(policy_id)))
            .first()
        )
        if policy is None:
            return None

        requested_at = policy.refresh_requested_at or datetime.now(timezone.utc)
        update = LLMNodeModelRoutingPolicyUpdate(
            policy_id=policy.id,
            trigger=trigger,
            status="failed",
            input_summary={},
            output_summary={},
        )
        db.add(update)

        try:
            deployment = (
                db.query(WorkflowDeployment)
                .filter(WorkflowDeployment.id == policy.deployment_id)
                .first()
            )
            node_data = cls._node_data(
                deployment.graph_snapshot if deployment else {},
                policy.node_id,
            ) or {}

            if not bool(node_data.get("auto_model_routing")):
                ModelRoutingPolicyLifecycleService.apply_refresh_result(
                    policy,
                    status="kept_current",
                    proposed_policy=policy.active_policy or {},
                    policy_version=policy.policy_version,
                )
                ModelRoutingPolicyLifecycleService.complete_refresh_cycle(
                    policy,
                    eligible_runs_since_last_refresh=cls._remaining_event_count(
                        db,
                        policy,
                        requested_at,
                    ),
                )
                update.status = "kept_current"
                update.output_summary = {
                    "reason": "자동 모델 라우팅이 꺼져 있어 기존 정책을 유지했습니다."
                }
                db.flush()
                return update

            return cls._refresh_prior_guided_policy(
                db,
                policy=policy,
                update=update,
                node_data=node_data,
                requested_at=requested_at,
            )
        except Exception as exc:
            logger.exception(
                "[Model-Routing] prior-guided refresh failed: policy_id=%s trigger=%s error_type=%s",
                policy.id,
                trigger,
                type(exc).__name__,
            )
            ModelRoutingPolicyLifecycleService.apply_refresh_result(
                policy,
                status="failed",
                proposed_policy=policy.active_policy or {},
                policy_version=policy.policy_version,
            )
            policy.refresh_requested_at = None
            update.status = "failed"
            update.error_code = type(exc).__name__
            update.output_summary = {
                "reason": "사전 지식 기반 모델 라우팅 정책 갱신에 실패했습니다."
            }
            db.flush()
            return update

    @classmethod
    def _refresh_prior_guided_policy(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        update: LLMNodeModelRoutingPolicyUpdate,
        node_data: dict[str, Any],
        requested_at: datetime,
    ) -> LLMNodeModelRoutingPolicyUpdate:
        execution_subject_id = (
            getattr(policy, "execution_subject_user_id", None)
            or getattr(policy, "judge_user_id", None)
        )
        if execution_subject_id is None or policy.organization_id is None:
            raise ValueError("model routing execution subject is unavailable")

        available_model_ids = set(
            LLMService.get_runtime_available_model_ids_for_user(
                db,
                user_id=execution_subject_id,
                organization_id=policy.organization_id,
            )
        )
        available_model_ids = set(
            filter_model_routing_available_model_ids(
                available_model_ids,
                node_data=node_data,
            )
        )
        if not available_model_ids:
            raise ValueError("model routing candidate is unavailable")

        configured_model_id = str(node_data.get("model_id") or "").strip()
        active_policy = policy.active_policy if isinstance(policy.active_policy, dict) else {}
        current_default_model_id = str(active_policy.get("default_model_id") or "").strip()
        safe_default_model_id = next(
            (
                model_id
                for model_id in (configured_model_id, current_default_model_id)
                if model_id in available_model_ids
            ),
            sorted(available_model_ids)[0],
        )

        profile = ModelRouter.collect_profile(
            db,
            ModelRouterContext(
                workflow_id=str(policy.workflow_id),
                node_id=policy.node_id,
                current_model_id=safe_default_model_id,
                deployment_id=str(policy.deployment_id),
            ),
        )
        compiled = compile_prior_guided_policy_from_db(
            db,
            node_data=node_data,
            available_model_ids=available_model_ids,
            safe_default_model_id=safe_default_model_id,
            profile=profile,
        )
        next_version = ModelRoutingPolicyRefreshService._next_policy_version(
            str(policy.policy_version or "v0")
        )
        ModelRoutingPolicyLifecycleService.apply_refresh_result(
            policy,
            status="applied",
            proposed_policy=compiled.active_policy,
            policy_version=next_version,
        )
        policy.last_refreshed_at = requested_at
        ModelRoutingPolicyLifecycleService.complete_refresh_cycle(
            policy,
            eligible_runs_since_last_refresh=cls._remaining_event_count(
                db,
                policy,
                requested_at,
            ),
        )

        excluded_count = cls._excluded_run_count(db, policy, requested_at)
        update.status = "applied"
        update.eligible_run_count = profile.operational_usable_runs
        update.excluded_run_count = excluded_count
        update.excluded_reason_summary = {
            "missing_usage_or_output": excluded_count,
        }
        update.input_summary = {
            "node_summary": cls._safe_node_summary(node_data),
            "model_profile": profile.as_snapshot(),
            "available_model_count": len(available_model_ids),
        }
        update.output_summary = {
            "reason": "사전 지식과 운영 증거로 제약 기반 모델 정책을 갱신했습니다.",
            "prior_guided": compiled.summary,
        }
        update.error_code = None
        update.judge_model = None
        update.judge_provider = None
        update.prompt_version = None
        update.new_policy_version = next_version
        db.flush()
        return update

    @staticmethod
    def _node_data(graph: dict[str, Any], node_id: str) -> dict[str, Any] | None:
        for node in graph.get("nodes") or []:
            if isinstance(node, dict) and str(node.get("id")) == node_id:
                data = node.get("data")
                return data if isinstance(data, dict) else None
        return None

    @staticmethod
    def _safe_node_summary(node_data: dict[str, Any]) -> dict[str, Any]:
        output_format = node_data.get("output_format")
        output_format = output_format if isinstance(output_format, dict) else {}
        return {
            "output_format": output_format.get("type") or "text",
            "schema_required": bool(output_format.get("schema")),
            "knowledge_enabled": bool(
                node_data.get("knowledgeBases")
                or node_data.get("knowledgeCollections")
            ),
            "has_fallback_model": bool(node_data.get("fallback_model_id")),
        }

    @staticmethod
    def _remaining_event_count(
        db: Session,
        policy: LLMNodeModelRoutingPolicy,
        cutoff: datetime,
    ) -> int:
        return (
            db.query(LLMNodeModelRoutingPolicyRunEvent)
            .filter(LLMNodeModelRoutingPolicyRunEvent.policy_id == policy.id)
            .filter(LLMNodeModelRoutingPolicyRunEvent.created_at > cutoff)
            .count()
        )

    @staticmethod
    def _excluded_run_count(
        db: Session,
        policy: LLMNodeModelRoutingPolicy,
        cutoff: datetime,
    ) -> int:
        total = (
            db.query(LLMNodeModelRoutingPolicyRunEvent)
            .filter(LLMNodeModelRoutingPolicyRunEvent.policy_id == policy.id)
            .filter(LLMNodeModelRoutingPolicyRunEvent.created_at <= cutoff)
            .count()
        )
        profile = ModelRouter.collect_profile(
            db,
            ModelRouterContext(
                workflow_id=str(policy.workflow_id),
                node_id=policy.node_id,
                current_model_id=None,
                deployment_id=str(policy.deployment_id),
            ),
        )
        return max(0, total - profile.operational_usable_runs)
