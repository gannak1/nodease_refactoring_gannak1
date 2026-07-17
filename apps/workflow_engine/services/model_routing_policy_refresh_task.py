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
from apps.workflow_engine.services.model_routing_operational_performance import (
    ModelRoutingOperationalPerformanceService,
)
from apps.workflow_engine.services.model_routing_policy_change_guard import (
    ModelRoutingPolicyChangeGuard,
)
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
            node_data = (
                cls._node_data(
                    deployment.graph_snapshot if deployment else {},
                    policy.node_id,
                )
                or {}
            )

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

            active_policy = (
                policy.active_policy
                if isinstance(policy.active_policy, dict)
                else {}
            )
            if active_policy.get("strategy_id") == "judge_bootstrap_incremental_v1":
                return cls._refresh_judge_bootstrap_incremental_policy(
                    db,
                    policy=policy,
                    update=update,
                    requested_at=requested_at,
                )
            if active_policy.get("strategy_id") in {
                "bootstrap_request_complexity_regression_v4",
                "bootstrap_request_complexity_v3",
                "bootstrap_task_complexity_v2",
                # 이전 snapshot은 신규 profile로 다시 만들기 전까지 current policy를
                # 유지한다. refresh가 prior-guided 정책으로 덮어쓰지 않게 한다.
                "bootstrap_mdeberta_difficulty_v1",
            }:
                return cls._refresh_bootstrap_policy(
                    db,
                    policy=policy,
                    update=update,
                    requested_at=requested_at,
                )

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
    def _refresh_judge_bootstrap_incremental_policy(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        update: LLMNodeModelRoutingPolicyUpdate,
        requested_at: datetime,
    ) -> LLMNodeModelRoutingPolicyUpdate:
        """Judge label과 완료된 운영 결과를 반영해 local-first 전환만 재평가한다."""
        from apps.workflow_engine.services.model_routing_policy_store import (
            ModelRoutingPolicyStore,
        )

        ModelRoutingPolicyStore.reconcile_incremental_learning_mode(db, policy=policy)
        active_policy = (
            dict(policy.active_policy) if isinstance(policy.active_policy, dict) else {}
        )
        learning = (
            dict(active_policy.get("learning"))
            if isinstance(active_policy.get("learning"), dict)
            else {}
        )
        profile = ModelRoutingOperationalPerformanceService.profile_for_policy(
            db,
            policy_id=policy.id,
        )
        ModelRoutingPolicyLifecycleService.apply_refresh_result(
            policy,
            status="kept_current",
            proposed_policy=active_policy,
            policy_version=policy.policy_version,
        )
        policy.last_refreshed_at = requested_at
        policy.performance_checkpoint = (
            ModelRoutingOperationalPerformanceService.checkpoint_snapshot(
                db,
                policy_id=policy.id,
            )
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
        update.eligible_run_count = profile.operational_usable_runs
        update.excluded_run_count = cls._excluded_run_count(
            db,
            policy,
            requested_at,
            usable_run_count=profile.operational_usable_runs,
        )
        update.input_summary = {
            "strategy_id": "judge_bootstrap_incremental_v1",
            "judged_request_count": int(learning.get("judged_request_count") or 0),
            "selected_model_count": len(learning.get("selected_model_ids") or []),
        }
        update.output_summary = {
            "reason": "Judge 선택과 운영 품질을 다시 확인했습니다. 모델은 이 갱신에서 임의로 바꾸지 않습니다.",
            "learning_mode": learning.get("mode") or "judge_first",
            "local_router_ready": learning.get("mode") == "local_first",
        }
        update.error_code = None
        update.judge_model = None
        update.judge_provider = None
        update.prompt_version = None
        update.new_policy_version = None
        db.flush()
        return update

    @classmethod
    def _refresh_bootstrap_policy(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        update: LLMNodeModelRoutingPolicyUpdate,
        requested_at: datetime,
    ) -> LLMNodeModelRoutingPolicyUpdate:
        """Bootstrap 분류기를 prior-guided refresh로 덮어쓰지 않는다.

        Bootstrap 이후의 모델 교체는 난이도별 candidate replay evidence가 준비된
        경우에만 허용한다. 그 실행 경로가 없을 때는 운영 성적만 checkpoint로
        저장하고 현재 난이도별 모델을 유지한다.
        """
        profile = ModelRoutingOperationalPerformanceService.profile_for_policy(
            db,
            policy_id=policy.id,
        )
        ModelRoutingPolicyLifecycleService.apply_refresh_result(
            policy,
            status="kept_current",
            proposed_policy=policy.active_policy or {},
            policy_version=policy.policy_version,
        )
        policy.last_refreshed_at = requested_at
        policy.performance_checkpoint = (
            ModelRoutingOperationalPerformanceService.checkpoint_snapshot(
                db,
                policy_id=policy.id,
            )
        )
        ModelRoutingPolicyLifecycleService.complete_refresh_cycle(
            policy,
            eligible_runs_since_last_refresh=cls._remaining_event_count(
                db,
                policy,
                requested_at,
            ),
        )
        excluded_count = cls._excluded_run_count(
            db,
            policy,
            requested_at,
            usable_run_count=profile.operational_usable_runs,
        )
        update.status = "kept_current"
        update.eligible_run_count = profile.operational_usable_runs
        update.excluded_run_count = excluded_count
        update.excluded_reason_summary = {
            "missing_usage_or_output": excluded_count,
        }
        update.input_summary = {
            "model_profile": profile.as_snapshot(),
            "strategy_id": str(
                (policy.active_policy or {}).get("strategy_id")
                or "bootstrap_request_complexity_regression_v4"
            ),
        }
        update.output_summary = {
            "reason": "후보 replay 증거가 없어 기존 요청 난이도 bootstrap 정책을 유지했습니다.",
            "replay_required": True,
        }
        update.error_code = None
        update.judge_model = None
        update.judge_provider = None
        update.prompt_version = None
        update.new_policy_version = None
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
        execution_subject_id = getattr(
            policy, "execution_subject_user_id", None
        ) or getattr(policy, "judge_user_id", None)
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
        active_policy = (
            policy.active_policy if isinstance(policy.active_policy, dict) else {}
        )
        current_default_model_id = str(
            active_policy.get("default_model_id") or ""
        ).strip()
        safe_default_model_id = next(
            (
                model_id
                for model_id in (configured_model_id, current_default_model_id)
                if model_id in available_model_ids
            ),
            sorted(available_model_ids)[0],
        )

        profile = ModelRoutingOperationalPerformanceService.profile_for_policy(
            db,
            policy_id=policy.id,
        )
        compiled = compile_prior_guided_policy_from_db(
            db,
            node_data=node_data,
            available_model_ids=available_model_ids,
            safe_default_model_id=safe_default_model_id,
            profile=profile,
        )
        decision = ModelRoutingPolicyChangeGuard.evaluate(
            policy.active_policy,
            compiled.active_policy,
        )
        next_version = (
            ModelRoutingPolicyRefreshService._next_policy_version(
                str(policy.policy_version or "v0")
            )
            if decision.status == "applied"
            else policy.policy_version
        )
        ModelRoutingPolicyLifecycleService.apply_refresh_result(
            policy,
            status=decision.status,
            proposed_policy=compiled.active_policy,
            policy_version=next_version,
        )
        policy.last_refreshed_at = requested_at
        policy.performance_checkpoint = (
            ModelRoutingOperationalPerformanceService.checkpoint_snapshot(
                db,
                policy_id=policy.id,
            )
        )
        ModelRoutingPolicyLifecycleService.complete_refresh_cycle(
            policy,
            eligible_runs_since_last_refresh=cls._remaining_event_count(
                db,
                policy,
                requested_at,
            ),
        )

        excluded_count = cls._excluded_run_count(
            db,
            policy,
            requested_at,
            usable_run_count=profile.operational_usable_runs,
        )
        update.status = decision.status
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
            "reason": decision.reason_code,
            "prior_guided": compiled.summary,
            "change_guard": {
                "max_cost_improvement": decision.max_cost_improvement,
                "max_latency_improvement": decision.max_latency_improvement,
            },
        }
        update.error_code = None
        update.judge_model = None
        update.judge_provider = None
        update.prompt_version = None
        update.new_policy_version = (
            next_version if decision.status == "applied" else None
        )
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
                node_data.get("knowledgeBases") or node_data.get("knowledgeCollections")
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
        *,
        usable_run_count: int,
    ) -> int:
        total = (
            db.query(LLMNodeModelRoutingPolicyRunEvent)
            .filter(LLMNodeModelRoutingPolicyRunEvent.policy_id == policy.id)
            .filter(LLMNodeModelRoutingPolicyRunEvent.created_at <= cutoff)
            .count()
        )
        return max(0, total - usable_run_count)
