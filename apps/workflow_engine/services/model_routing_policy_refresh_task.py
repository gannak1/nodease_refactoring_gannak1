"""Celery task가 사용할 persisted model-routing policy refresh orchestration."""

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
from apps.workflow_engine.services.llm_service import LLMService
from apps.workflow_engine.services.model_router import ModelRouter, ModelRouterContext
from apps.workflow_engine.services.model_routing_policy_lifecycle import (
    ModelRoutingPolicyLifecycleService,
)
from apps.workflow_engine.services.model_routing_policy_refresh import (
    POLICY_JUDGE_PROMPT_VERSION,
    ModelRoutingPolicyRefreshRequest,
    ModelRoutingPolicyRefreshService,
)


class PersistedModelRoutingPolicyRefreshService:
    """저장된 policy를 읽고 judge refresh 결과를 policy/update row에 반영한다."""

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
        current_policy = cls._as_router_policy(policy)
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
            node_data = cls._node_data(deployment.graph_snapshot if deployment else {}, policy.node_id)
            candidates = (
                ModelRouter.collect_candidates(db, organization_id=policy.organization_id)
                if policy.organization_id is not None
                else []
            )
            if policy.judge_user_id is not None and policy.organization_id is not None:
                available_model_ids = set(
                    LLMService.get_runtime_available_model_ids_for_user(
                        db,
                        user_id=policy.judge_user_id,
                        organization_id=policy.organization_id,
                    )
                )
                candidates = [
                    candidate
                    for candidate in candidates
                    if candidate.model_id in available_model_ids
                ]
            profile = ModelRouter.collect_profile(
                db,
                ModelRouterContext(
                    workflow_id=str(policy.workflow_id),
                    node_id=policy.node_id,
                    current_model_id=(node_data or {}).get("model_id"),
                    deployment_id=str(policy.deployment_id),
                ),
            )
            recent_runs = cls._safe_recent_runs(profile)
            segment_profiles = cls._safe_segment_profiles(profile)
            excluded_count = cls._excluded_run_count(db, policy, requested_at)
            update.eligible_run_count = profile.operational_usable_runs
            update.excluded_run_count = excluded_count
            update.excluded_reason_summary = {
                "missing_usage_or_output": excluded_count,
            }
            update.input_summary = {
                "node_summary": cls._safe_node_summary(node_data or {}),
                "model_profile": profile.as_snapshot(),
                "segment_profile_count": len(segment_profiles),
                "candidate_count": len(candidates),
            }

            if policy.judge_user_id is None or not candidates:
                result_status = "failed"
                proposed_active_policy = policy.active_policy or {}
                policy_version = policy.policy_version
                update.error_code = "judge_context_unavailable"
                update.output_summary = {"reason": "judge user 또는 실행 가능 모델이 없습니다."}
                judge_model_id = None
                judge_usage = {}
            else:
                judge_model_id = cls._select_judge_model(
                    candidates,
                    current_model_id=(node_data or {}).get("model_id"),
                )
                result = ModelRoutingPolicyRefreshService.refresh_policy(
                    db,
                    ModelRoutingPolicyRefreshRequest(
                        workflow_id=str(policy.workflow_id),
                        node_id=policy.node_id,
                        user_id=policy.judge_user_id,
                        organization_id=policy.organization_id,
                        current_policy=current_policy,
                        candidate_models=candidates,
                        recent_runs=recent_runs,
                        segment_profiles=segment_profiles,
                        node_summary=cls._safe_node_summary(node_data or {}),
                        trigger=trigger,
                        judge_model_id=judge_model_id,
                    ),
                )
                result_status = result.status
                proposed_active_policy = result.policy.get("active_policy") or policy.active_policy or {}
                policy_version = result.policy.get("policy_version")
                judge_model_id = result.judge_model_id
                judge_usage = result.judge_usage
                update.output_summary = {
                    "reason": result.reason,
                    "judge_usage": judge_usage,
                    "result": result.metadata,
                }
                update.judge_provider = result.judge_provider
                judge_usage_log = cls._record_judge_usage(
                    db,
                    policy=policy,
                    result=result,
                )
                if judge_usage_log is not None:
                    update.judge_usage_log_id = judge_usage_log.id
                    update.output_summary["judge_cost"] = float(
                        judge_usage_log.total_cost or 0
                    )

            ModelRoutingPolicyLifecycleService.apply_refresh_result(
                policy,
                status=result_status,
                proposed_policy=proposed_active_policy,
                policy_version=policy_version,
            )
            policy.last_refreshed_at = requested_at
            policy.refresh_requested_at = None
            policy.eligible_runs_since_last_refresh = cls._remaining_event_count(
                db, policy, requested_at
            )
            update.status = result_status
            update.judge_model = judge_model_id
            update.prompt_version = POLICY_JUDGE_PROMPT_VERSION if judge_model_id else None
            update.new_policy_version = policy_version if result_status == "applied" else None
            db.flush()
            return update
        except Exception as exc:
            ModelRoutingPolicyLifecycleService.apply_refresh_result(
                policy,
                status="failed",
                proposed_policy=policy.active_policy or {},
                policy_version=policy.policy_version,
            )
            policy.refresh_requested_at = None
            update.status = "failed"
            update.error_code = type(exc).__name__
            update.output_summary = {"reason": "judge policy refresh failed"}
            db.flush()
            return update

    @staticmethod
    def _record_judge_usage(db: Session, *, policy, result):
        """judge 호출 비용을 usage log로 남기되 운영 node profile에는 섞지 않는다."""
        credential_id = getattr(result, "judge_credential_id", None)
        model_id = getattr(result, "judge_model_id", None)
        usage = result.judge_usage if isinstance(result.judge_usage, dict) else {}
        if not credential_id or not model_id or not usage:
            return None

        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        cost = LLMService.calculate_cost(
            db,
            model_id,
            prompt_tokens,
            completion_tokens,
        )
        return LLMService.log_usage(
            db,
            user_id=policy.judge_user_id,
            model_id=model_id,
            usage=usage,
            cost=cost,
            organization_id=policy.organization_id,
            workflow_id=policy.workflow_id,
            node_id=f"{policy.node_id}:model-routing-judge",
            credential_id=credential_id,
        )

    @staticmethod
    def _as_router_policy(policy: LLMNodeModelRoutingPolicy) -> dict[str, Any]:
        return {
            "policy_id": str(policy.id),
            "policy_version": policy.policy_version,
            "active_policy": policy.active_policy or {},
            "refresh": {"refresh_every_runs": policy.refresh_every_runs},
        }

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
        if not isinstance(output_format, dict):
            output_format = {}
        return {
            "output_format": output_format.get("type") or "text",
            "schema_required": bool(output_format.get("schema")),
            "knowledge_enabled": bool(
                node_data.get("knowledgeBases")
                or node_data.get("knowledgeCollections")
            ),
            "has_fallback_model": bool(node_data.get("fallback_model_id")),
            "model_routing_context": node_data.get("model_routing_context") or {},
        }

    @staticmethod
    def _safe_recent_runs(profile) -> list[dict[str, Any]]:
        return [
            {"model_id": model_id, **summary}
            for model_id, summary in profile.as_snapshot()["model_performance"].items()
        ]

    @staticmethod
    def _safe_segment_profiles(profile) -> list[dict[str, Any]]:
        snapshot = profile.as_snapshot()
        segments = snapshot.get("segment_performance")
        return segments if isinstance(segments, list) else []

    @staticmethod
    def _select_judge_model(candidates, *, current_model_id: Any) -> str:
        """현재 운영 모델을 우선하고, 없으면 안정적인 순서로 judge 모델을 고른다."""
        current_model_id = str(current_model_id or "").strip()
        for candidate in candidates:
            if candidate.model_id == current_model_id:
                return candidate.model_id
        ordered = sorted(
            candidates,
            key=lambda candidate: (candidate.price_score, candidate.model_id),
        )
        return ordered[len(ordered) // 2].model_id

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
