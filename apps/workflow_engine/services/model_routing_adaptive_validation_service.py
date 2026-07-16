"""자동 발견 input cohort의 실제 Replay 검증과 policy activation.

후보 모델 검증은 runtime 요청마다 실행하지 않는다. policy refresh가 만든 batch에서만
기존 배포 node run의 입력을 일회성으로 replay하고, DB에는 원문 대신 결과 요약과
검증 evidence만 저장한다.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.shared.db.models.model_routing_cohort import (
    LLMNodeModelRoutingCohort,
    LLMNodeModelRoutingCohortExample,
    LLMNodeModelRoutingModelEvidence,
    LLMNodeModelRoutingObservation,
    LLMNodeModelRoutingValidationBatch,
    LLMNodeModelRoutingValidationBudgetMonth,
    LLMNodeModelRoutingValidationCostEvent,
    LLMNodeModelRoutingValidationItem,
)
from apps.shared.db.models.model_routing_policy import (
    LLMNodeModelRoutingPolicy,
    LLMNodeModelRoutingPolicyRunEvent,
)
from apps.shared.db.models.workflow_deployment import WorkflowDeployment
from apps.shared.db.models.workflow_run import WorkflowNodeRun, WorkflowRun
from apps.shared.services.model_routing_cohort_drafts import (
    filter_model_routing_available_model_ids,
)
from apps.shared.services.node_config_fingerprint import llm_node_config_fingerprint
from apps.shared.services.tracing.policy import TracePolicyService
from apps.shared.services.tracing.redaction import TraceRedactionService
from apps.workflow_engine.services.llm_service import LLMService
from apps.workflow_engine.services.model_router import ModelRouter
from apps.workflow_engine.services.model_routing_adaptive_policy import (
    AdaptiveCandidate,
    AdaptiveModelRoutingPolicyService,
)
from apps.workflow_engine.services.model_routing_adaptive_store import (
    AdaptiveModelRoutingCohortStore,
)
from apps.workflow_engine.services.model_routing_cohort_naming import (
    AdaptiveModelRoutingCohortNamingService,
)
from apps.workflow_engine.services.model_routing_adaptive_validation import (
    AdaptiveValidationOutcome,
    AdaptiveValidationResultService,
)
from apps.workflow_engine.services.model_routing_policy_lifecycle import (
    ModelRoutingPolicyLifecycleService,
)
from apps.workflow_engine.services.model_routing_validation_planner import (
    CandidateValidationRequest,
    CohortValidationInput,
    ModelRoutingValidationPlanner,
)
from apps.workflow_engine.workflow.core.workflow_engine import WorkflowEngine


logger = logging.getLogger(__name__)
_MISSING = object()


class AdaptiveModelRoutingValidationService:
    """검증 batch를 계획하고 실제 provider Replay 결과를 policy evidence로 반영한다."""

    MAX_CANDIDATES_PER_COHORT = 2
    MAX_VALIDATING_COHORTS = 4
    MAX_BOOTSTRAP_WAVES = 3
    QUALITY_JUDGE_MAX_TOKENS = 700
    QUALITY_JUDGE_MAX_ATTEMPTS_PER_PASS = 2
    # 여러 후보가 최소 gate를 통과해도 품질 하한 차이가 크면 더 싼 모델을
    # 고르지 않는다. 품질이 이 범위 안에서 비슷할 때만 비용을 우선한다.
    QUALITY_LOWER_BOUND_TOLERANCE = 3.0
    RUNNING_ITEM_LEASE = timedelta(minutes=5)
    _TERMINAL_BATCH_STATUSES = {"completed", "failed", "cancelled"}
    _TERMINAL_ITEM_STATUSES = {
        "completed",
        "failed",
        "baseline_failed",
        "skipped_unavailable",
    }

    @classmethod
    def prepare_deployment_bootstrap(
        cls,
        db: Session,
        *,
        policy_id: str | uuid.UUID,
    ) -> LLMNodeModelRoutingValidationBatch | None:
        """배포 직후 입력군을 만들고 첫 유료 검증 batch를 계획한다."""
        try:
            normalized_policy_id = uuid.UUID(str(policy_id))
        except (TypeError, ValueError):
            return None
        policy = db.query(LLMNodeModelRoutingPolicy).filter(
            LLMNodeModelRoutingPolicy.id == normalized_policy_id
        ).first()
        if policy is None or not policy.enabled:
            return None
        deployment = cls._deployment(db, policy)
        node_data = cls._node_data(
            deployment.graph_snapshot if deployment else {},
            policy.node_id,
        )
        if not isinstance(node_data, dict):
            return None

        from apps.workflow_engine.services.model_routing_policy_store import (
            ModelRoutingPolicyStore,
        )

        ModelRoutingPolicyStore.materialize_policy_cohorts(
            db,
            policy=policy,
            node_data=node_data,
        )
        db.flush()
        return cls.plan_batch(
            db,
            policy_id=policy.id,
            trigger="deployment_bootstrap",
        )

    @classmethod
    def complete_refresh_without_batch(
        cls,
        db: Session,
        *,
        policy_id: str | uuid.UUID,
    ) -> LLMNodeModelRoutingPolicy | None:
        """검증할 cohort가 아직 없을 때 refresh lease를 정상 종료한다.

        첫 observation window만 쌓인 시점처럼 candidate Replay batch가 비어 있는
        경우는 정상 상태다. 이 때 lease를 남기면 다음 window가 완성돼도 auto refresh가
        다시 예약되지 않아 입력군 발견 자체가 멈춘다.
        """
        policy = cls._locked_policy(db, policy_id)
        if policy is None:
            return None
        requested_at = policy.refresh_requested_at
        policy.status = (
            "active"
            if cls._has_validated_adaptive_rule(policy.active_policy)
            else "collecting"
        )
        policy.last_refresh_result = "kept_current"
        policy.last_refreshed_at = datetime.now(timezone.utc)
        if requested_at is not None:
            ModelRoutingPolicyLifecycleService.complete_refresh_cycle(
                policy,
                eligible_runs_since_last_refresh=cls._remaining_run_event_count(
                    db,
                    policy=policy,
                    requested_at=requested_at,
                ),
            )
        db.flush()
        return policy

    @classmethod
    def plan_batch(
        cls,
        db: Session,
        *,
        policy_id: str | uuid.UUID,
        trigger: str,
        policy_update_id: uuid.UUID | None = None,
        bootstrap_wave: int = 1,
    ) -> LLMNodeModelRoutingValidationBatch | None:
        policy = cls._locked_policy(db, policy_id)
        if policy is None or not policy.enabled:
            return None
        if trigger == "deployment_bootstrap":
            # task publish가 실패해 caller가 재시도하더라도 이미 예약한 후속 batch를
            # 다시 찾아 발행할 수 있어야 한다. 새 batch를 중복 생성하지 않는다.
            pending_bootstrap = (
                db.query(LLMNodeModelRoutingValidationBatch)
                .filter(LLMNodeModelRoutingValidationBatch.policy_id == policy.id)
                .filter(
                    LLMNodeModelRoutingValidationBatch.trigger
                    == "deployment_bootstrap"
                )
                .filter(
                    LLMNodeModelRoutingValidationBatch.status.in_(["pending", "running"])
                )
                .order_by(LLMNodeModelRoutingValidationBatch.created_at.asc())
                .first()
            )
            if pending_bootstrap is not None:
                return pending_bootstrap
        deployment = cls._deployment(db, policy)
        node_data = cls._node_data(deployment.graph_snapshot if deployment else {}, policy.node_id)
        if not isinstance(node_data, dict):
            return None
        subject_id = cls._execution_subject(policy)
        if subject_id is None or policy.organization_id is None:
            return None

        # 정책 갱신 시점에만 lifecycle을 전진시킨다. runtime은 이 함수를 호출하지 않는다.
        AdaptiveModelRoutingCohortStore.discover_and_advance(
            db, policy=policy, node_data=node_data
        )
        db.flush()
        fingerprint = llm_node_config_fingerprint(node_data)
        available_model_ids = cls._eligible_available_model_ids(
            LLMService.get_runtime_available_model_ids_for_user(
                db,
                user_id=subject_id,
                organization_id=policy.organization_id,
            ),
            node_data=node_data,
        )
        if not available_model_ids:
            return None
        baseline_model_id = cls._baseline_model(policy, node_data)
        AdaptiveModelRoutingCohortNamingService.name_pending_auto_cohorts(
            db,
            policy=policy,
            node_data=node_data,
            execution_subject_id=subject_id,
            available_model_ids=available_model_ids,
            preferred_model_id=baseline_model_id,
        )
        cohorts = cls._candidate_cohorts(
            db,
            policy_id=policy.id,
            fingerprint=fingerprint,
            trigger=trigger,
        )
        if not cohorts:
            return None
        if not baseline_model_id or baseline_model_id not in available_model_ids:
            return None
        budget = cls._locked_monthly_budget(db, policy)
        remaining_budget = max(
            Decimal("0"),
            Decimal(str(budget.limit_usd or 0))
            - Decimal(str(budget.spent_usd or 0))
            - Decimal(str(budget.reserved_usd or 0)),
        )
        judge_model_id = cls._judge_model_id(
            baseline_model_id=baseline_model_id,
            available_model_ids=available_model_ids,
        )
        cohort_inputs: list[CohortValidationInput] = []
        expected_samples_by_cohort: dict[str, int] = {}
        is_deployment_bootstrap = trigger == "deployment_bootstrap"
        for cohort in cohorts:
            active_model_id = (
                None
                if is_deployment_bootstrap
                else cls._active_model_for_cohort(
                    policy.active_policy,
                    cohort_key=str(cohort.cohort_key),
                )
            )
            candidate_models = cls._candidate_models(
                db,
                policy=policy,
                cohort_id=cohort.id,
                fingerprint=fingerprint,
                baseline_model_id=baseline_model_id,
                available_model_ids=available_model_ids,
                exclude_prior_rejections=is_deployment_bootstrap,
                active_model_id=active_model_id,
            )
            if not candidate_models:
                continue
            observations = [] if is_deployment_bootstrap else cls._cohort_observations(
                db,
                cohort_id=cohort.id,
            )
            examples = (
                cls._cohort_examples(db, cohort_id=cohort.id)
                if is_deployment_bootstrap
                else []
            )
            minimum_bootstrap_examples = 5 if bool(cohort.safety_protected) else 3
            if is_deployment_bootstrap and len(examples) < minimum_bootstrap_examples:
                continue
            if (
                not is_deployment_bootstrap
                and len(observations) < ModelRoutingValidationPlanner.REPLAYS_PER_CANDIDATE
            ):
                continue
            required_replays = (
                min(5, len(examples))
                if is_deployment_bootstrap
                else ModelRoutingValidationPlanner.REPLAYS_PER_CANDIDATE
            )
            estimated_candidates: list[CandidateValidationRequest] = []
            for model_id in candidate_models:
                estimate = (
                    cls._estimate_bootstrap_replay_cost(
                        db,
                        examples=examples,
                        node_data=node_data,
                        baseline_model_id=baseline_model_id,
                        candidate_model_id=model_id,
                        judge_model_id=judge_model_id,
                    )
                    if is_deployment_bootstrap
                    else cls._estimate_candidate_replay_cost(
                        db,
                        observations=observations,
                        candidate_model_id=model_id,
                        judge_model_id=judge_model_id,
                    )
                )
                if estimate is None:
                    continue
                estimated_candidates.append(
                    CandidateValidationRequest(
                        model_id=model_id,
                        estimated_item_cost=float(estimate),
                    )
                )
            if estimated_candidates:
                cohort_inputs.append(
                    CohortValidationInput(
                        cohort_id=str(cohort.id),
                        candidates=tuple(estimated_candidates),
                        observation_ids=tuple(str(item.id) for item in observations),
                        cohort_example_ids=tuple(str(item.id) for item in examples),
                        required_replays=required_replays,
                    )
                )
                expected_samples_by_cohort[str(cohort.id)] = required_replays

        plan = ModelRoutingValidationPlanner.plan(
            cohorts=cohort_inputs,
            remaining_budget_usd=float(remaining_budget),
        )
        if not plan.items:
            return None
        request_fingerprint = cls._request_fingerprint(
            policy=policy,
            fingerprint=fingerprint,
            plan=plan,
        )
        existing = (
            db.query(LLMNodeModelRoutingValidationBatch)
            .filter(LLMNodeModelRoutingValidationBatch.request_fingerprint == request_fingerprint)
            .first()
        )
        if existing is not None:
            # pending/running만 중복 task가 함께 처리하도록 재사용한다. 종료 batch는
            # 새 evidence가 없는 같은 refresh cycle에서 다시 실행하지 않고 caller가
            # refresh lease를 정상 종료하게 한다.
            return existing if cls._should_reuse_existing_batch(existing) else None

        planned_cohort_ids = {uuid.UUID(item.cohort_id) for item in plan.items}
        previous_cohort_statuses = {
            str(cohort.id): str(cohort.status)
            for cohort in cohorts
            if cohort.id in planned_cohort_ids
        }
        batch = LLMNodeModelRoutingValidationBatch(
            policy_id=policy.id,
            policy_update_id=policy_update_id,
            status="pending",
            trigger=trigger,
            request_fingerprint=request_fingerprint,
            candidate_plan={
                "baseline_model_id": baseline_model_id,
                "judge_model_id": judge_model_id,
                "node_config_fingerprint": fingerprint,
                "item_count": len(plan.items),
                "validation_stage": (
                    "bootstrap" if is_deployment_bootstrap else "production"
                ),
                "bootstrap_wave": (
                    max(1, int(bootstrap_wave)) if is_deployment_bootstrap else None
                ),
                "expected_samples_by_cohort": expected_samples_by_cohort,
                # batch 시작 뒤 실행 주체/배포가 일시적으로 불가능해져도 cohort가
                # validating 상태에 고착되지 않도록 원래 lifecycle 상태를 남긴다.
                "cohort_status_before_validation": previous_cohort_statuses,
            },
            total_items=len(plan.items),
            reserved_cost=Decimal(str(plan.reserved_cost_usd)),
        )
        db.add(batch)
        db.flush()
        for planned in plan.items:
            db.add(
                LLMNodeModelRoutingValidationItem(
                    batch_id=batch.id,
                    cohort_id=uuid.UUID(planned.cohort_id),
                    observation_id=(
                        uuid.UUID(planned.observation_id)
                        if planned.observation_id is not None
                        else None
                    ),
                    cohort_example_id=(
                        uuid.UUID(planned.cohort_example_id)
                        if planned.cohort_example_id is not None
                        else None
                    ),
                    model_id=planned.model_id,
                    baseline_model_id=baseline_model_id,
                    status="pending",
                )
            )
        for cohort in cohorts:
            if cohort.id in planned_cohort_ids:
                cohort.status = "validating"
        budget.reserved_usd = Decimal(str(budget.reserved_usd or 0)) + Decimal(
            str(plan.reserved_cost_usd)
        )
        db.flush()
        return batch

    @staticmethod
    def _eligible_available_model_ids(
        available_model_ids: list[str] | set[str] | tuple[str, ...],
        *,
        node_data: dict[str, Any],
    ) -> set[str]:
        """권한이 있어도 노드에서 제외한 모델은 검증 예산 후보에서 제거한다."""
        return set(
            filter_model_routing_available_model_ids(
                available_model_ids,
                node_data=node_data,
            )
        )

    @classmethod
    def execute_batch(
        cls,
        db: Session,
        *,
        batch_id: str | uuid.UUID,
    ) -> LLMNodeModelRoutingValidationBatch | None:
        batch = (
            db.query(LLMNodeModelRoutingValidationBatch)
            .filter(LLMNodeModelRoutingValidationBatch.id == uuid.UUID(str(batch_id)))
            .first()
        )
        if batch is None or batch.status in cls._TERMINAL_BATCH_STATUSES:
            return batch
        policy = (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.id == batch.policy_id)
            .first()
        )
        if policy is None:
            batch.status = "failed"
            batch.error_summary = {"reason_code": "policy_not_found"}
            return batch
        deployment = cls._deployment(db, policy)
        node_data = cls._node_data(deployment.graph_snapshot if deployment else {}, policy.node_id)
        subject_id = cls._execution_subject(policy)
        if not isinstance(node_data, dict) or subject_id is None:
            cls._fail_batch_and_release_refresh(
                db,
                batch=batch,
                policy=policy,
                reason_code="execution_subject_unavailable",
            )
            return batch

        batch.status = "running"
        unavailable_models: set[str] = set()
        # 같은 합성 대표 입력을 후보별로 검증할 때 기준 모델을 반복 호출하지 않는다.
        # 출력은 이 task 메모리 안에서만 공유하고 validation row에는 safe summary만 남긴다.
        validated_baselines: dict[
            tuple[uuid.UUID, uuid.UUID, str], dict[str, Any]
        ] = {}
        item_ids = [
            row.id
            for row in (
            db.query(LLMNodeModelRoutingValidationItem)
            .filter(LLMNodeModelRoutingValidationItem.batch_id == batch.id)
            .order_by(LLMNodeModelRoutingValidationItem.created_at.asc())
            .all()
            )
        ]
        # batch/policy 행 잠금은 네트워크 호출 전에 해제한다. 실제 provider Replay와
        # judge는 수 초 이상 걸릴 수 있으므로 이 상태를 유지하면 운영 run 기록이
        # 불필요하게 막힌다.
        db.commit()

        for item_id in item_ids:
            item = (
                db.query(LLMNodeModelRoutingValidationItem)
                .filter(LLMNodeModelRoutingValidationItem.id == item_id)
                .with_for_update()
                .first()
            )
            if item is None:
                continue
            if item.status == "running":
                if cls._is_stale_running_item(item):
                    item.status = "retry"
                    item.execution_summary = {
                        **(
                            item.execution_summary
                            if isinstance(item.execution_summary, dict)
                            else {}
                        ),
                        "reason_code": "stale_execution_lease_recovered",
                    }
                    db.commit()
                else:
                    continue
            if item.status not in {"pending", "retry"}:
                continue
            batch = (
                db.query(LLMNodeModelRoutingValidationBatch)
                .filter(LLMNodeModelRoutingValidationBatch.id == item.batch_id)
                .first()
            )
            policy = (
                db.query(LLMNodeModelRoutingPolicy)
                .filter(LLMNodeModelRoutingPolicy.id == batch.policy_id)
                .first()
                if batch is not None
                else None
            )
            deployment = cls._deployment(db, policy) if policy is not None else None
            node_data = cls._node_data(
                deployment.graph_snapshot if deployment else {},
                policy.node_id if policy is not None else "",
            )
            subject_id = cls._execution_subject(policy) if policy is not None else None
            if batch is None or policy is None or not isinstance(node_data, dict) or subject_id is None:
                if batch is not None:
                    batch.status = "failed"
                    batch.error_summary = {"reason_code": "execution_subject_unavailable"}
                item.status = "failed"
                item.execution_summary = {"reason_code": "execution_subject_unavailable"}
                item.completed_at = datetime.now(timezone.utc)
                db.commit()
                continue
            if item.model_id in unavailable_models:
                item.status = "skipped_unavailable"
                item.execution_summary = {"reason_code": "candidate_model_unavailable"}
                item.completed_at = datetime.now(timezone.utc)
                batch.completed_items = int(batch.completed_items or 0) + 1
                db.commit()
                continue
            # 이 item을 실행 중으로 먼저 확정해 worker retry/중복 delivery가 같은
            # provider Replay를 동시에 시작하지 않게 한다. 잠금은 바로 해제한다.
            item.status = "running"
            item.execution_summary = {
                **(
                    item.execution_summary
                    if isinstance(item.execution_summary, dict)
                    else {}
                ),
                "_lease_started_at": datetime.now(timezone.utc).isoformat(),
            }
            db.commit()
            baseline_cache_key = cls._bootstrap_baseline_cache_key(item)
            result = cls._execute_validation_item(
                db,
                policy=policy,
                deployment=deployment,
                node_data=node_data,
                item=item,
                execution_subject_id=subject_id,
                validated_baseline=(
                    validated_baselines.get(baseline_cache_key)
                    if baseline_cache_key is not None
                    else None
                ),
            )
            baseline_cache_entry = result.get("_baseline_cache_entry")
            if baseline_cache_key is not None and isinstance(
                baseline_cache_entry,
                dict,
            ):
                validated_baselines[baseline_cache_key] = baseline_cache_entry
            item.status = result["status"]
            # WorkflowEngine의 run log는 비동기로 저장된다. 아직 workflow_runs에
            # 없는 임시 UUID를 FK에 넣으면 검증 결과 commit이 실패하고 같은 유료
            # Replay가 lease 만료 뒤 중복 실행될 수 있으므로, 실제 저장된 run만 연결한다.
            item.candidate_workflow_run_id = cls._persisted_workflow_run_id(
                db,
                result.get("workflow_run_id"),
            )
            item.execution_summary = result["execution_summary"]
            item.quality_summary = result["quality_summary"]
            item.actual_cost_usd = result.get("actual_cost_usd")
            item.completed_at = datetime.now(timezone.utc)
            batch.completed_items = int(batch.completed_items or 0) + 1
            spent = Decimal(str(result.get("actual_cost_usd") or 0))
            batch.spent_cost = Decimal(str(batch.spent_cost or 0)) + spent
            if spent > 0:
                validation_stage = str(
                    (batch.candidate_plan or {}).get("validation_stage") or "production"
                )
                db.add(
                    LLMNodeModelRoutingValidationCostEvent(
                        batch_id=batch.id,
                        event_type=(
                            "bootstrap_replay_and_judge"
                            if validation_stage == "bootstrap"
                            else "candidate_replay_and_judge"
                        ),
                        amount_usd=spent,
                        usage_log_id=result.get("judge_usage_log_id"),
                    )
                )
            if result.get("model_unavailable"):
                unavailable_models.add(item.model_id)
            db.commit()

        batch = (
            db.query(LLMNodeModelRoutingValidationBatch)
            .filter(LLMNodeModelRoutingValidationBatch.id == uuid.UUID(str(batch_id)))
            .with_for_update()
            .first()
        )
        policy = cls._locked_policy(db, batch.policy_id) if batch is not None else None
        if batch is None or policy is None:
            return batch
        # 다른 worker가 같은 batch의 모든 item을 처리하고 완료했을 수 있다. 행
        # 잠금에서 깨어난 뒤 상태를 다시 확인하지 않으면 예산/active policy를
        # 같은 batch에 대해 두 번 확정하게 된다.
        if batch.status in cls._TERMINAL_BATCH_STATUSES:
            return batch
        deployment = cls._deployment(db, policy)
        node_data = cls._node_data(deployment.graph_snapshot if deployment else {}, policy.node_id)
        if not isinstance(node_data, dict):
            cls._fail_batch_and_release_refresh(
                db,
                batch=batch,
                policy=policy,
                reason_code="target_node_unavailable",
            )
            return batch
        if cls._batch_has_nonterminal_items(db, batch=batch):
            batch.status = "running"
            db.flush()
            return batch
        cls._finalize_batch(
            db,
            batch=batch,
            policy=policy,
            node_data=node_data,
        )
        return batch

    @classmethod
    def plan_deployment_bootstrap_follow_up(
        cls,
        db: Session,
        *,
        batch: LLMNodeModelRoutingValidationBatch,
    ) -> LLMNodeModelRoutingValidationBatch | None:
        """첫 후보 묶음 탈락 뒤 남은 후보를 같은 bootstrap에서 계속 검증한다."""
        if batch.status != "completed" or batch.trigger != "deployment_bootstrap":
            return None

        current_wave = max(
            1,
            int((getattr(batch, "candidate_plan", None) or {}).get("bootstrap_wave") or 1),
        )
        if current_wave >= cls.MAX_BOOTSTRAP_WAVES:
            summary = dict(batch.error_summary or {})
            summary.update(
                {
                    "bootstrap_search_state": "max_waves_reached",
                    "follow_up_batch_id": None,
                }
            )
            batch.error_summary = summary
            db.flush()
            return None

        follow_up = cls.plan_batch(
            db,
            policy_id=batch.policy_id,
            trigger="deployment_bootstrap",
            policy_update_id=batch.policy_update_id,
            bootstrap_wave=current_wave + 1,
        )
        summary = dict(batch.error_summary or {})
        if follow_up is not None:
            summary.update(
                {
                    "bootstrap_search_state": "continued",
                    "follow_up_batch_id": str(follow_up.id),
                }
            )
        else:
            summary.update(
                {
                    "bootstrap_search_state": (
                        "completed_with_routes"
                        if int(summary.get("validated_route_count") or 0) > 0
                        else "no_follow_up_batch"
                    ),
                    "follow_up_batch_id": None,
                }
            )
        batch.error_summary = summary
        db.flush()
        return follow_up

    @classmethod
    def _execute_validation_item(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        deployment: WorkflowDeployment,
        node_data: dict[str, Any],
        item: LLMNodeModelRoutingValidationItem,
        execution_subject_id: uuid.UUID,
        validated_baseline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        baseline_input, baseline_output, baseline_latency_ms = cls._validation_input(
            db,
            item=item,
            node_data=node_data,
        )
        if baseline_input is None:
            return cls._failed_item("baseline_observation_unavailable")
        # observation/item lock과 이전 item의 결과 commit을 provider 호출 전 확정한다.
        # 이 지점 이후 DB transaction을 길게 잡아 운영 입력 기록을 막지 않는다.
        db.commit()
        baseline_replay_cost = Decimal("0")
        baseline_cache_entry: dict[str, Any] | None = None
        if baseline_output is None:
            if validated_baseline is not None:
                if not bool(validated_baseline.get("passed")):
                    return cls._baseline_failed_item(
                        str(
                            validated_baseline.get("reason_code")
                            or "baseline_validation_failed"
                        ),
                        baseline_cost=0,
                    )
                baseline_output = validated_baseline.get("output")
                baseline_latency_ms = validated_baseline.get("latency_ms")
                if not isinstance(baseline_output, dict):
                    return cls._baseline_failed_item(
                        "baseline_cache_unavailable",
                        baseline_cost=0,
                    )
            else:
                baseline_started = time.perf_counter()
                try:
                    baseline_output, _baseline_run_id = cls._run_model_replay(
                        db,
                        policy=policy,
                        deployment=deployment,
                        node_data=node_data,
                        baseline_input=baseline_input,
                        replay_model_id=item.baseline_model_id,
                        fallback_model_id="",
                        execution_subject_id=execution_subject_id,
                    )
                except Exception as exc:
                    return cls._baseline_failure_with_cache(
                        cls._safe_error_code(exc),
                        baseline_cost=0,
                    )
                baseline_latency_ms = int((time.perf_counter() - baseline_started) * 1000)
                baseline_replay_cost = Decimal(str(cls._cost(baseline_output) or 0))
                baseline_actual_model, baseline_fallback = cls._candidate_execution_model(
                    baseline_output,
                    requested_model_id=item.baseline_model_id,
                )
                if baseline_fallback or baseline_actual_model != item.baseline_model_id:
                    return cls._baseline_failure_with_cache(
                        "baseline_model_mismatch",
                        baseline_cost=baseline_replay_cost,
                    )

        baseline_schema_passed = cls._schema_passed(baseline_output, node_data)
        if baseline_schema_passed is False:
            return cls._baseline_failure_with_cache(
                "baseline_schema_gate_failed",
                baseline_cost=baseline_replay_cost,
            )
        baseline_downstream_passed = cls._downstream_passed(
            deployment.graph_snapshot,
            policy.node_id,
            baseline_output,
        )
        if baseline_downstream_passed is False:
            return cls._baseline_failure_with_cache(
                "baseline_downstream_gate_failed",
                baseline_cost=baseline_replay_cost,
            )
        if item.cohort_example_id is not None and validated_baseline is None:
            baseline_cache_entry = {
                "passed": True,
                "output": baseline_output,
                "latency_ms": baseline_latency_ms,
            }

        started = time.perf_counter()
        try:
            candidate_output, candidate_run_id = cls._run_model_replay(
                db,
                policy=policy,
                deployment=deployment,
                node_data=node_data,
                baseline_input=baseline_input,
                replay_model_id=item.model_id,
                # 후보 실패를 기준 모델 성공으로 가리면 후보 품질 증거가 오염된다.
                # 검증 Replay는 요청한 후보 모델 자체만 실행한다.
                fallback_model_id="",
                execution_subject_id=execution_subject_id,
            )
        except Exception as exc:
            code = cls._safe_error_code(exc)
            result = cls._failed_item(
                code,
                workflow_run_id=None,
                model_unavailable=code in {"credential_not_available", "model_relation_not_verified", "model_inactive"},
            )
            result["_baseline_cache_entry"] = baseline_cache_entry
            return result
        latency_ms = int((time.perf_counter() - started) * 1000)
        schema_passed = cls._schema_passed(candidate_output, node_data)
        downstream_passed = cls._downstream_passed(
            deployment.graph_snapshot,
            policy.node_id,
            candidate_output,
        )
        # candidate Replay가 남긴 usage/trace를 먼저 짧게 commit하고, quality judge는
        # 별도의 다음 transaction에서 실행한다.
        db.commit()
        quality = cls._judge_quality(
            db,
            policy=policy,
            execution_subject_id=execution_subject_id,
            baseline_input=baseline_input,
            baseline_output=baseline_output,
            candidate_output=candidate_output,
            preferred_model_id=item.baseline_model_id,
            node_data=node_data,
        )
        candidate_cost = cls._cost(candidate_output)
        baseline_cost = cls._cost(baseline_output)
        actual_cost = baseline_replay_cost + Decimal(str(candidate_cost or 0)) + Decimal(
            str(quality.get("judge_cost") or 0)
        )
        actual_model_id, fallback_used = cls._candidate_execution_model(
            candidate_output,
            requested_model_id=item.model_id,
        )
        outcome = AdaptiveValidationOutcome(
            execution_succeeded=True,
            schema_passed=schema_passed,
            downstream_passed=downstream_passed,
            quality_score=quality.get("candidate_score"),
            baseline_quality_score=quality.get("baseline_score"),
            quality_confidence=quality.get("confidence"),
            candidate_cost=candidate_cost,
            baseline_cost=baseline_cost,
            candidate_latency_ms=float(latency_ms),
            baseline_latency_ms=baseline_latency_ms,
            fallback_used=fallback_used,
        )
        return {
            "status": "completed",
            "workflow_run_id": candidate_run_id,
            "actual_cost_usd": actual_cost,
            "judge_usage_log_id": quality.get("judge_usage_log_id"),
            "execution_summary": {
                "execution_succeeded": True,
                "schema_passed": schema_passed,
                "downstream_passed": downstream_passed,
                "candidate_cost": candidate_cost,
                "baseline_cost": baseline_cost,
                "candidate_latency_ms": latency_ms,
                "baseline_latency_ms": baseline_latency_ms,
                "baseline_validation_passed": True,
                "baseline_schema_passed": baseline_schema_passed,
                "baseline_downstream_passed": baseline_downstream_passed,
                "requested_model_id": item.model_id,
                "actual_model_id": actual_model_id,
                "fallback_used": fallback_used,
            },
            # quality_summary는 JSONB에 저장된다. Judge usage FK는 위의 별도
            # relational column으로 UUID를 유지하고, summary에는 JSON-safe 값만 둔다.
            "quality_summary": cls._json_safe_quality_summary(quality),
            "outcome": outcome,
            "_baseline_cache_entry": baseline_cache_entry,
        }

    @staticmethod
    def _bootstrap_baseline_cache_key(
        item: LLMNodeModelRoutingValidationItem,
    ) -> tuple[uuid.UUID, uuid.UUID, str] | None:
        if item.cohort_example_id is None:
            return None
        return (
            item.cohort_id,
            item.cohort_example_id,
            str(item.baseline_model_id),
        )

    @staticmethod
    def _json_safe_quality_summary(quality: dict[str, Any]) -> dict[str, Any]:
        """JSONB summary에 UUID 같은 Python 객체가 들어가지 않게 정규화한다."""
        summary = dict(quality)
        judge_usage_log_id = summary.get("judge_usage_log_id")
        if isinstance(judge_usage_log_id, uuid.UUID):
            summary["judge_usage_log_id"] = str(judge_usage_log_id)
        return summary

    @staticmethod
    def _candidate_execution_model(
        candidate_output: dict[str, Any],
        *,
        requested_model_id: str,
    ) -> tuple[str | None, bool]:
        """실제 provider 응답 모델을 기준으로 후보 Replay의 fallback 여부를 판정한다.

        후보 검증 Replay는 후보 모델을 강제로 호출하기 위해 auto routing을 끈다.
        따라서 일반 운영 실행과 달리 ``metadata.model_routing`` trace가 없을 수 있다.
        이 경우에도 LLM node가 돌려준 ``model`` 값이 요청 후보와 다르면, 해당 표본은
        후보 품질 증거가 아니라 fallback 실행이므로 승격 판단에서 제외해야 한다.
        """
        actual_model = candidate_output.get("model") if isinstance(candidate_output, dict) else None
        actual_model_id = str(actual_model).strip() if actual_model is not None else None
        if not actual_model_id:
            actual_model_id = None

        output_metadata = candidate_output.get("metadata") if isinstance(candidate_output, dict) else {}
        routing = output_metadata.get("model_routing") if isinstance(output_metadata, dict) else {}
        trace_fallback = bool(isinstance(routing, dict) and routing.get("fallback_used"))
        model_mismatch = bool(actual_model_id and actual_model_id != requested_model_id)
        return actual_model_id, trace_fallback or model_mismatch

    @classmethod
    def _validation_input(
        cls,
        db: Session,
        *,
        item: LLMNodeModelRoutingValidationItem,
        node_data: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, float | None]:
        """운영 관찰값 또는 입력군 대표 예시를 같은 Replay 입력 계약으로 바꾼다."""
        if item.observation_id is not None:
            observation = db.query(LLMNodeModelRoutingObservation).filter(
                LLMNodeModelRoutingObservation.id == item.observation_id
            ).first()
            node_run = (
                db.query(WorkflowNodeRun)
                .filter(WorkflowNodeRun.id == observation.workflow_node_run_id)
                .first()
                if observation is not None
                else None
            )
            if observation is None or node_run is None:
                return None, None, None
            inputs = copy.deepcopy(node_run.inputs) if isinstance(node_run.inputs, dict) else {}
            outputs = copy.deepcopy(node_run.outputs) if isinstance(node_run.outputs, dict) else {}
            return inputs, outputs, cls._duration_ms(node_run)

        if item.cohort_example_id is None:
            return None, None, None
        example = db.query(LLMNodeModelRoutingCohortExample).filter(
            LLMNodeModelRoutingCohortExample.id == item.cohort_example_id
        ).first()
        if example is None:
            return None, None, None
        return cls._synthetic_baseline_input(node_data, example.synthetic_text), None, None

    @staticmethod
    def _synthetic_baseline_input(
        node_data: dict[str, Any],
        synthetic_text: str,
    ) -> dict[str, Any]:
        """대표 문장을 실제 LLM 참조 selector가 읽는 입력 위치에 넣는다."""
        values: dict[str, Any] = {}
        references = node_data.get("referenced_variables")
        references = references if isinstance(references, list) else []
        for reference in references:
            if not isinstance(reference, dict):
                continue
            selector = reference.get("value_selector")
            if not isinstance(selector, list) or not selector:
                continue
            AdaptiveModelRoutingValidationService._set_nested_value(
                values,
                [str(item) for item in selector],
                "",
            )

        context = node_data.get("model_routing_context")
        context = context if isinstance(context, dict) else {}
        semantic_router = context.get("semantic_router")
        semantic_router = semantic_router if isinstance(semantic_router, dict) else {}
        input_paths = semantic_router.get("input_paths")
        input_paths = input_paths if isinstance(input_paths, list) else []
        path = next((str(item).strip() for item in input_paths if str(item).strip()), "")
        segments = [segment for segment in path.split(".") if segment]
        if not segments:
            selector = next(
                (
                    item.get("value_selector")
                    for item in references
                    if isinstance(item, dict)
                    and isinstance(item.get("value_selector"), list)
                    and item.get("value_selector")
                ),
                None,
            )
            segments = [str(item) for item in selector] if selector else ["input"]
        AdaptiveModelRoutingValidationService._set_nested_value(
            values,
            segments,
            synthetic_text,
        )
        return values

    @staticmethod
    def _set_nested_value(target: dict[str, Any], path: list[str], value: Any) -> None:
        current = target
        for segment in path[:-1]:
            existing = current.get(segment)
            if not isinstance(existing, dict):
                existing = {}
                current[segment] = existing
            current = existing
        if path:
            current[path[-1]] = value

    @classmethod
    def _run_model_replay(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        deployment: WorkflowDeployment,
        node_data: dict[str, Any],
        baseline_input: dict[str, Any],
        replay_model_id: str,
        fallback_model_id: str,
        execution_subject_id: uuid.UUID,
    ) -> tuple[dict[str, Any], uuid.UUID]:
        run_id = uuid.uuid4()
        graph, replay_input = cls._candidate_graph(
            deployment.graph_snapshot,
            node_id=policy.node_id,
            candidate_model_id=replay_model_id,
            fallback_model_id=fallback_model_id,
            baseline_input=baseline_input,
        )
        context = cls._candidate_execution_context(
            workflow_id=str(policy.workflow_id),
            organization_id=str(policy.organization_id),
            deployment_id=str(policy.deployment_id),
            workflow_run_id=str(run_id),
            execution_subject_id=str(execution_subject_id),
        )
        engine = WorkflowEngine(
            graph=graph,
            user_input=replay_input,
            execution_context=context,
            is_deployed=False,
            db=db,
        )
        try:
            results = engine.execute()
        finally:
            engine.cleanup()
        output = results.get(policy.node_id) if isinstance(results, dict) else None
        if not isinstance(output, dict):
            raise ValueError("candidate_output_unavailable")
        return output, run_id

    @staticmethod
    def _candidate_execution_context(
        *,
        workflow_id: str,
        organization_id: str,
        deployment_id: str,
        workflow_run_id: str,
        execution_subject_id: str,
    ) -> dict[str, Any]:
        """후보 Replay를 기존 workflow run trigger 계약 안에서 실행한다."""
        return {
            "workflow_id": workflow_id,
            "organization_id": organization_id,
            "deployment_id": deployment_id,
            "workflow_run_id": workflow_run_id,
            "user_id": execution_subject_id,
            "execution_subject": {
                "subject_type": "user",
                "subject_id": execution_subject_id,
            },
            "credential_principal": {
                "subject_type": "user",
                "subject_id": execution_subject_id,
            },
            # validation Replay는 운영 webhook가 아니라 비용 최적화의 수동 비교다.
            # canonical alias를 사용해야 WorkflowLogger가 run log를 거부하지 않는다.
            "trigger_mode": "cost_optimizer_compare",
            "trace_metadata": {"model_routing_validation": True},
        }

    @classmethod
    def _candidate_graph(
        cls,
        graph: dict[str, Any],
        *,
        node_id: str,
        candidate_model_id: str,
        fallback_model_id: str,
        baseline_input: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """원래 LLM 입력 selector를 검증용 단일 시작 노드 계약으로 옮긴다.

        운영 LLM node의 ``inputs``는 보통 ``{원본_노드_ID: {변수: 값}}`` 구조다.
        검증 graph에는 원본 upstream node가 없으므로, 그 구조를 그대로 넘기면
        StartNode가 변수 값을 찾지 못해 빈 prompt로 Replay하게 된다. 검증 전용
        start node에는 variable 이름별 평탄화된 값을 넣고 selector도 함께 바꾼다.
        """
        target = cls._find_node(graph, node_id)
        if target is None:
            raise ValueError("target_llm_node_not_found")
        target = copy.deepcopy(target)
        data = target.get("data") if isinstance(target.get("data"), dict) else {}
        data = copy.deepcopy(data)
        replay_input, replay_references = cls._candidate_replay_input(
            data,
            baseline_input,
        )
        data["model_id"] = candidate_model_id
        data["fallback_model_id"] = fallback_model_id or None
        data["auto_model_routing"] = False
        data["referenced_variables"] = replay_references
        target["data"] = data
        start_id = "model-routing-validation-input"
        return {
            "nodes": [
                {
                    "id": start_id,
                    "type": "startNode",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "title": "Model Routing Validation Input",
                        "trigger_type": "manual",
                        "variables": [
                            {"id": key, "name": key, "label": key, "type": "text", "required": False}
                            for key in replay_input
                            if isinstance(key, str) and key
                        ],
                    },
                },
                target,
            ],
            "edges": [
                {
                    "id": f"{start_id}-to-{node_id}",
                    "source": start_id,
                    "target": node_id,
                }
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }, replay_input

    @classmethod
    def _candidate_replay_input(
        cls,
        node_data: dict[str, Any],
        baseline_input: Any,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """운영 node input에서 LLM prompt 변수만 안전하게 추출한다."""
        source = baseline_input if isinstance(baseline_input, dict) else {}
        references = node_data.get("referenced_variables")
        references = references if isinstance(references, list) else []
        replay_input: dict[str, Any] = {}
        retargeted_references: list[dict[str, Any]] = []
        start_id = "model-routing-validation-input"

        for raw_reference in references:
            if not isinstance(raw_reference, dict):
                continue
            reference = copy.deepcopy(raw_reference)
            name = str(reference.get("name") or "").strip()
            selector = reference.get("value_selector")
            selector = selector if isinstance(selector, list) else []
            if not name:
                continue

            value = cls._value_at_selector(source, selector)
            if value is _MISSING:
                value = source.get(name, "")
            replay_input[name] = value
            reference["value_selector"] = [start_id, name]
            retargeted_references.append(reference)

        # referenced_variables가 없는 노드는 기존의 평탄화된 입력 계약을 유지한다.
        if not retargeted_references:
            replay_input = {
                str(key): copy.deepcopy(value)
                for key, value in source.items()
                if isinstance(key, str) and key
            }
        return replay_input, retargeted_references

    @staticmethod
    def _value_at_selector(source: dict[str, Any], selector: list[Any]) -> Any:
        current: Any = source
        for raw_segment in selector:
            if isinstance(current, dict):
                segment = str(raw_segment)
                if segment not in current:
                    return _MISSING
                current = current[segment]
                continue
            if isinstance(current, list):
                try:
                    current = current[int(raw_segment)]
                except (IndexError, TypeError, ValueError):
                    return _MISSING
                continue
            return _MISSING
        return copy.deepcopy(current)

    @classmethod
    def _judge_quality(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        execution_subject_id: uuid.UUID,
        baseline_input: Any,
        baseline_output: dict[str, Any],
        candidate_output: dict[str, Any],
        preferred_model_id: str,
        node_data: dict[str, Any],
    ) -> dict[str, Any]:
        if policy.organization_id is None:
            return cls._judge_unavailable("organization_unavailable")
        available = set(
            LLMService.get_runtime_available_model_ids_for_user(
                db,
                user_id=execution_subject_id,
                organization_id=policy.organization_id,
            )
        )
        judge_model_id = preferred_model_id if preferred_model_id in available else next(iter(sorted(available)), "")
        if not judge_model_id:
            return cls._judge_unavailable("judge_model_unavailable")
        try:
            selection = LLMService.get_runtime_client_for_user(
                db,
                user_id=execution_subject_id,
                model_id=judge_model_id,
                organization_id=policy.organization_id,
            )
            visible_contract = cls._judge_visible(
                cls._quality_evaluation_contract(node_data)
            )
            visible_input = cls._judge_visible(baseline_input)
            visible_baseline = cls._judge_visible(baseline_output)
            visible_candidate = cls._judge_visible(candidate_output)
            started = time.perf_counter()
            scored_passes: list[tuple[float, float, float]] = []
            usages: list[dict[str, int]] = []
            for swapped in (False, True):
                payload = {
                    "task": "Score two anonymized outputs for the same workflow input.",
                    "evaluation_contract": visible_contract,
                    "input": visible_input,
                    "variant_a": visible_candidate if swapped else visible_baseline,
                    "variant_b": visible_baseline if swapped else visible_candidate,
                    "response_schema": {
                        "variant_a_score": "0..100",
                        "variant_b_score": "0..100",
                        "confidence": "0..1",
                    },
                }
                response = None
                variant_a_score = None
                variant_b_score = None
                confidence = None
                for attempt in range(cls.QUALITY_JUDGE_MAX_ATTEMPTS_PER_PASS):
                    try:
                        response = selection.client.invoke_sync(
                            [
                                {
                                    "role": "system",
                                    "content": (
                                        "Return JSON only. Score each variant independently against "
                                        "evaluation_contract and the same input. Judge instruction "
                                        "fulfillment, correctness, clarity, and output contract suitability. "
                                        "When authoritative evidence is unavailable, penalize unsupported "
                                        "specific claims and do not penalize transparent uncertainty. "
                                        "Do not reward length by itself and do not disclose sensitive content."
                                    ),
                                },
                                {
                                    "role": "user",
                                    "content": json.dumps(payload, ensure_ascii=False),
                                },
                            ],
                            temperature=0.0,
                            max_tokens=cls.QUALITY_JUDGE_MAX_TOKENS,
                        )
                        parsed = json.loads(cls._content(response))
                        variant_a_score = cls._score(parsed.get("variant_a_score"))
                        variant_b_score = cls._score(parsed.get("variant_b_score"))
                        confidence = cls._score(parsed.get("confidence"), upper=1)
                        if (
                            variant_a_score is not None
                            and variant_b_score is not None
                            and confidence is not None
                        ):
                            break
                    except Exception:
                        if attempt + 1 >= cls.QUALITY_JUDGE_MAX_ATTEMPTS_PER_PASS:
                            raise
                if (
                    response is None
                    or variant_a_score is None
                    or variant_b_score is None
                    or confidence is None
                ):
                    return cls._judge_unavailable("judge_response_invalid")
                usages.append(cls._usage(response))
                scored_passes.append(
                    (
                        variant_b_score if swapped else variant_a_score,
                        variant_a_score if swapped else variant_b_score,
                        confidence,
                    )
                )
            usage = {
                key: sum(item.get(key, 0) for item in usages)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            }
            usage["latency_ms"] = int((time.perf_counter() - started) * 1000)
            baseline_score = round(
                sum(item[0] for item in scored_passes) / len(scored_passes), 6
            )
            candidate_score = round(
                sum(item[1] for item in scored_passes) / len(scored_passes), 6
            )
            confidence = round(
                sum(item[2] for item in scored_passes) / len(scored_passes), 6
            )
            judge_cost = LLMService.calculate_cost(
                db,
                judge_model_id,
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
            )
            usage_log = LLMService.log_usage(
                db,
                user_id=execution_subject_id,
                model_id=judge_model_id,
                usage=usage,
                cost=judge_cost,
                organization_id=policy.organization_id,
                workflow_id=policy.workflow_id,
                node_id=f"{policy.node_id}:model-routing-quality-judge",
                credential_id=selection.credential_id,
            )
            return {
                "status": "completed",
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
                "confidence": confidence,
                "judge_model_id": judge_model_id,
                "judge_cost": float(judge_cost or 0),
                "judge_usage_log_id": getattr(usage_log, "id", None),
                "judge_passes": len(scored_passes),
            }
        except Exception as exc:
            logger.warning("[Model-Routing] quality judge skipped: error_type=%s", type(exc).__name__)
            return cls._judge_unavailable("judge_execution_failed")

    @classmethod
    def _quality_evaluation_contract(cls, node_data: dict[str, Any]) -> dict[str, Any]:
        """품질 Judge가 실제 node 목적과 출력 계약을 기준으로 평가하게 한다."""
        data = node_data if isinstance(node_data, dict) else {}
        knowledge_enabled = bool(
            data.get("knowledgeBases")
            or data.get("knowledge_bases")
            or data.get("knowledge_base_ids")
        )
        return cls._bounded(
            {
                "system_prompt": data.get("system_prompt") or "",
                "user_prompt": data.get("user_prompt") or "",
                "assistant_prompt": data.get("assistant_prompt") or "",
                "output_format": data.get("output_format") or {"type": "text"},
                "knowledge_enabled": knowledge_enabled,
                "grounding_policy": {
                    "unsupported_specific_claims": "penalize",
                    "transparent_uncertainty": "do_not_penalize",
                },
            },
            depth=6,
            max_chars=4000,
        )

    @classmethod
    def _finalize_batch(
        cls,
        db: Session,
        *,
        batch: LLMNodeModelRoutingValidationBatch,
        policy: LLMNodeModelRoutingPolicy,
        node_data: dict[str, Any],
    ) -> None:
        fingerprint = str((batch.candidate_plan or {}).get("node_config_fingerprint") or "")
        grouped: dict[tuple[uuid.UUID, str], list[LLMNodeModelRoutingValidationItem]] = {}
        items = db.query(LLMNodeModelRoutingValidationItem).filter(
            LLMNodeModelRoutingValidationItem.batch_id == batch.id
        ).all()
        for item in items:
            grouped.setdefault((item.cohort_id, item.model_id), []).append(item)
        routes: list[dict[str, Any]] = []
        revoked_cohort_ids: set[str] = set()
        candidate_results: list[dict[str, Any]] = []
        validation_stage = str(
            (batch.candidate_plan or {}).get("validation_stage") or "production"
        )
        active_models_by_cohort = cls._active_models_by_cohort(policy.active_policy)
        expected_samples_by_cohort = (
            (batch.candidate_plan or {}).get("expected_samples_by_cohort") or {}
        )
        for (cohort_id, model_id), rows in grouped.items():
            cohort = (
                db.query(LLMNodeModelRoutingCohort)
                .filter(LLMNodeModelRoutingCohort.id == cohort_id)
                .first()
            )
            outcomes = [cls._outcome_from_item(item) for item in rows]
            expected_samples = int(
                expected_samples_by_cohort.get(
                    str(cohort_id),
                    ModelRoutingValidationPlanner.REPLAYS_PER_CANDIDATE,
                )
            )
            result = AdaptiveValidationResultService.evaluate(
                outcomes,
                expected_samples=expected_samples,
                safety_protected=bool(
                    cohort is not None and cohort.safety_protected
                ),
                validation_stage=validation_stage,
            )
            candidate_results.append(
                cls._candidate_result_summary(
                    cohort=cohort,
                    model_id=model_id,
                    result=result,
                    sample_count=len(rows),
                )
            )
            evidence = cls._upsert_evidence(
                db,
                cohort_id=cohort_id,
                model_id=model_id,
                fingerprint=fingerprint,
                batch=batch,
                result=result,
                rows=rows,
            )
            if (
                validation_stage == "production"
                and cohort is not None
                and active_models_by_cohort.get(str(cohort.cohort_key)) == model_id
                and evidence.status != "validated"
            ):
                revoked_cohort_ids.add(str(cohort.cohort_key))
            if evidence.status == "validated":
                if cohort is None:
                    continue
                routes.append(
                    {
                        # Runtime semantic matcher는 DB primary key가 아닌 catalog의
                        # cohort_key를 전달한다. 둘을 섞으면 rule은 저장돼도 절대
                        # 매칭되지 않아 항상 default model로 떨어진다.
                        "cohort_id": str(cohort.cohort_key),
                        "cohort_row_id": cohort_id,
                        "model_id": model_id,
                        "fallback_model_id": cls._baseline_model(policy, node_data),
                        "evidence_version": evidence.evidence_version,
                        "candidate_cost": float((evidence.efficiency_summary or {}).get("candidate_cost_average") or float("inf")),
                        "quality_score_lower_bound": (
                            (getattr(evidence, "quality_summary", None) or {}).get(
                                "quality_score_lower_bound"
                            )
                        ),
                    }
                )

        selected = cls._select_validated_routes(routes)
        for cohort_id, route in selected.items():
            cohort = db.query(LLMNodeModelRoutingCohort).filter(LLMNodeModelRoutingCohort.id == cohort_id).first()
            if cohort is not None:
                cohort.status = "active"
        for cohort_id, _model_id in grouped:
            if cohort_id in selected:
                continue
            cohort = db.query(LLMNodeModelRoutingCohort).filter(LLMNodeModelRoutingCohort.id == cohort_id).first()
            if cohort is not None and cohort.status == "validating":
                cohort.status = "validated_waiting"

        # SessionLocal은 autoflush=False다. 위에서 cohort를 active로 바꾼 직후
        # catalog를 조회하면 DB에는 여전히 validating으로 남아 있어 빈 catalog가
        # 반환된다. active 상태를 먼저 flush해야 검증 통과 route가 policy에 투영된다.
        db.flush()
        catalog = AdaptiveModelRoutingCohortStore.build_runtime_catalog(
            db,
            policy_id=policy.id,
            policy=policy,
            node_data=node_data,
        )
        current_active_policy = (
            policy.active_policy if isinstance(policy.active_policy, dict) else {}
        )
        projected_policy = current_active_policy
        if catalog is not None:
            projected_policy = AdaptiveValidationResultService.project_active_policy(
                current_policy=policy.active_policy if isinstance(policy.active_policy, dict) else {},
                semantic_router=catalog,
                validated_routes=[
                    {
                        key: value
                        for key, value in route.items()
                        if key != "cohort_row_id"
                    }
                    for route in selected.values()
                ],
                revoked_cohort_ids=revoked_cohort_ids,
            )
            policy.active_policy = projected_policy

        policy_changed = projected_policy != current_active_policy
        if selected or revoked_cohort_ids:
            policy.policy_version = cls._next_policy_version(policy.policy_version)
            policy.status = (
                "active"
                if cls._has_validated_adaptive_rule(policy.active_policy)
                else "collecting"
            )
            policy.last_refresh_result = "applied"
        else:
            # 특정 모델 승격이 없어도 필수 직접 입력군의 semantic catalog는 새
            # policy다. runtime은 입력군을 식별한 뒤 검증된 rule이 없으면 default
            # 모델을 사용하며, trace가 참조하는 version도 함께 전진시킨다.
            if policy_changed:
                policy.policy_version = cls._next_policy_version(policy.policy_version)
            # 이번 batch에서 새 candidate가 탈락했어도 이전 batch가 활성화한
            # cohort route가 있으면 runtime은 계속 그 검증된 route를 사용한다.
            policy.status = (
                "active"
                if cls._has_validated_adaptive_rule(policy.active_policy)
                else "collecting"
            )
            policy.last_refresh_result = "kept_current"
        policy.last_refreshed_at = datetime.now(timezone.utc)
        requested_at = policy.refresh_requested_at
        if requested_at is not None:
            ModelRoutingPolicyLifecycleService.complete_refresh_cycle(
                policy,
                eligible_runs_since_last_refresh=cls._remaining_run_event_count(
                    db,
                    policy=policy,
                    requested_at=requested_at,
                ),
            )
        budget = cls._locked_monthly_budget(db, policy)
        budget.reserved_usd = max(
            Decimal("0"),
            Decimal(str(budget.reserved_usd or 0)) - Decimal(str(batch.reserved_cost or 0)),
        )
        budget.spent_usd = Decimal(str(budget.spent_usd or 0)) + Decimal(str(batch.spent_cost or 0))
        batch.status = "completed"
        batch.completed_at = datetime.now(timezone.utc)
        grouped_cohort_ids = {cohort_id for cohort_id, _model_id in grouped}
        batch.error_summary = {
            "validated_route_count": len(selected),
            "revoked_route_count": len(revoked_cohort_ids),
            "rejected_or_waiting_cohort_count": len(
                grouped_cohort_ids - set(selected)
            ),
            "candidate_results": sorted(
                candidate_results,
                key=lambda item: (
                    str(item.get("cohort_key") or ""),
                    str(item.get("model_id") or ""),
                ),
            ),
        }
        db.flush()

    @classmethod
    def _select_validated_routes(
        cls,
        routes: Iterable[dict[str, Any]],
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """품질 하한이 비슷한 검증 후보 안에서만 최저비용 모델을 고른다."""

        grouped: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for route in routes:
            try:
                cohort_id = uuid.UUID(str(route["cohort_row_id"]))
            except (KeyError, TypeError, ValueError):
                continue
            grouped.setdefault(cohort_id, []).append(route)

        selected: dict[uuid.UUID, dict[str, Any]] = {}
        for cohort_id, candidates in grouped.items():
            scored: list[tuple[float, dict[str, Any]]] = []
            for candidate in candidates:
                try:
                    lower_bound = float(candidate["quality_score_lower_bound"])
                except (KeyError, TypeError, ValueError):
                    continue
                scored.append((lower_bound, candidate))

            quality_eligible = candidates
            if scored:
                best_lower_bound = max(score for score, _candidate in scored)
                quality_eligible = [
                    candidate
                    for score, candidate in scored
                    if score
                    >= best_lower_bound - cls.QUALITY_LOWER_BOUND_TOLERANCE
                ]

            selected[cohort_id] = min(
                quality_eligible,
                key=lambda item: (
                    float(item.get("candidate_cost", float("inf"))),
                    str(item.get("model_id") or ""),
                ),
            )
        return selected

    @staticmethod
    def _candidate_result_summary(
        *,
        cohort: Any,
        model_id: str,
        result: Any,
        sample_count: int,
    ) -> dict[str, Any]:
        """후보 탈락을 설명할 수 있는 비민감 집계값만 batch에 남긴다."""
        quality = result.quality_summary if isinstance(result.quality_summary, dict) else {}
        efficiency = (
            result.efficiency_summary
            if isinstance(result.efficiency_summary, dict)
            else {}
        )
        candidate_quality = quality.get(
            "candidate_quality_mean",
            quality.get("quality_score_average"),
        )
        baseline_quality = quality.get("baseline_quality_mean")
        quality_delta = quality.get("quality_delta_average")
        if baseline_quality is None and candidate_quality is not None and quality_delta is not None:
            baseline_quality = float(candidate_quality) - float(quality_delta)
        return {
            "cohort_id": str(getattr(cohort, "id", "")),
            "cohort_key": str(getattr(cohort, "cohort_key", "")),
            "model_id": str(model_id),
            "status": str(result.status),
            "reason_code": str(result.reason_code),
            "sample_count": int(sample_count),
            "baseline_quality_mean": baseline_quality,
            "candidate_quality_mean": candidate_quality,
            "net_savings_ratio": efficiency.get("net_savings_ratio"),
        }

    @staticmethod
    def _has_validated_adaptive_rule(active_policy: Any) -> bool:
        if not isinstance(active_policy, dict):
            return False
        return any(
            isinstance(rule, dict)
            and str(rule.get("reason_code") or "") == "validated_adaptive_cohort"
            and isinstance(rule.get("when"), dict)
            and bool(rule["when"].get("semantic_cohort_id"))
            for rule in active_policy.get("rules") or []
        )

    @staticmethod
    def _remaining_run_event_count(
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        requested_at: datetime,
    ) -> int:
        """검증 동안 완료된 운영 run을 다음 정책 갱신 카운터로 넘긴다."""
        return int(
            db.query(LLMNodeModelRoutingPolicyRunEvent)
            .filter(LLMNodeModelRoutingPolicyRunEvent.policy_id == policy.id)
            .filter(LLMNodeModelRoutingPolicyRunEvent.created_at > requested_at)
            .count()
        )

    @classmethod
    def _upsert_evidence(
        cls,
        db: Session,
        *,
        cohort_id: uuid.UUID,
        model_id: str,
        fingerprint: str,
        batch: LLMNodeModelRoutingValidationBatch,
        result: Any,
        rows: list[LLMNodeModelRoutingValidationItem],
    ) -> LLMNodeModelRoutingModelEvidence:
        evidence = (
            db.query(LLMNodeModelRoutingModelEvidence)
            .filter(LLMNodeModelRoutingModelEvidence.cohort_id == cohort_id)
            .filter(LLMNodeModelRoutingModelEvidence.model_id == model_id)
            .filter(LLMNodeModelRoutingModelEvidence.node_config_fingerprint == fingerprint)
            .first()
        )
        evidence_version = "adaptive-" + hashlib.sha256(
            f"{batch.id}:{cohort_id}:{model_id}:{fingerprint}".encode("utf-8")
        ).hexdigest()[:16]
        values = {
            "evidence_version": evidence_version,
            "status": result.status,
            "sample_count": len(rows),
            "quality_summary": {
                **result.quality_summary,
                "reason_code": result.reason_code,
                "validation_stage": str(
                    (batch.candidate_plan or {}).get("validation_stage") or "production"
                ),
            },
            "efficiency_summary": result.efficiency_summary,
            "source_candidate_ids": [str(row.id) for row in rows],
            "validated_at": datetime.now(timezone.utc) if result.status == "validated" else None,
        }
        if evidence is None:
            evidence = LLMNodeModelRoutingModelEvidence(
                cohort_id=cohort_id,
                model_id=model_id,
                node_config_fingerprint=fingerprint,
                **values,
            )
            db.add(evidence)
        else:
            for key, value in values.items():
                setattr(evidence, key, value)
        return evidence

    @classmethod
    def _candidate_cohorts(
        cls,
        db: Session,
        *,
        policy_id: uuid.UUID,
        fingerprint: str,
        trigger: str,
    ):
        return (
            db.query(LLMNodeModelRoutingCohort)
            .filter(LLMNodeModelRoutingCohort.policy_id == policy_id)
            .filter(
                LLMNodeModelRoutingCohort.status.in_(
                    cls._validation_cohort_statuses(trigger)
                )
            )
            # 고위험 route는 policy-owned safety override가 default 고성능 모델로
            # 처리한다. 새 저비용 모델을 자동으로 검증/승격하지 않는다.
            .filter(LLMNodeModelRoutingCohort.safety_protected.is_(False))
            .filter(LLMNodeModelRoutingCohort.node_config_fingerprint == fingerprint)
            .order_by(LLMNodeModelRoutingCohort.first_seen_at.asc())
            .limit(cls.MAX_VALIDATING_COHORTS)
            .all()
        )

    @classmethod
    def _candidate_models(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        cohort_id: uuid.UUID,
        fingerprint: str,
        baseline_model_id: str,
        available_model_ids: set[str],
        exclude_prior_rejections: bool,
        active_model_id: str | None = None,
    ) -> list[str]:
        evidence_checker = (
            cls._model_has_any_evidence
            if exclude_prior_rejections
            else cls._model_has_validated_evidence
        )
        catalog_candidates = ModelRouter.collect_candidates(
            db, organization_id=policy.organization_id
        )
        candidates = [
            AdaptiveCandidate(
                model_id=candidate.model_id,
                estimated_cost=candidate.price_score,
                validated=evidence_checker(
                    db,
                    cohort_id=cohort_id,
                    model_id=candidate.model_id,
                    fingerprint=fingerprint,
                ),
            )
            for candidate in catalog_candidates
            if candidate.model_id not in {baseline_model_id, active_model_id}
        ]
        baseline_price = next(
            (
                candidate.price_score
                for candidate in catalog_candidates
                if candidate.model_id == baseline_model_id
            ),
            float("inf"),
        )
        lower_cost = [item for item in candidates if item.estimated_cost < baseline_price]
        planned = AdaptiveModelRoutingPolicyService.plan_candidates(
            candidates=lower_cost or candidates,
            available_model_ids=available_model_ids,
            maximum_candidates=(
                cls.MAX_CANDIDATES_PER_COHORT
                - (1 if active_model_id and active_model_id != baseline_model_id else 0)
            ),
        )
        planned_model_ids = [item.model_id for item in planned]
        if (
            active_model_id
            and active_model_id != baseline_model_id
            and active_model_id in available_model_ids
            and any(item.model_id == active_model_id for item in catalog_candidates)
        ):
            return [active_model_id, *planned_model_ids]
        return planned_model_ids

    @staticmethod
    def _validation_cohort_statuses(trigger: str) -> tuple[str, ...]:
        if trigger == "deployment_bootstrap":
            return ("proposed", "validated_waiting")
        return ("proposed", "validated_waiting", "active")

    @staticmethod
    def _active_models_by_cohort(active_policy: Any) -> dict[str, str]:
        policy = active_policy if isinstance(active_policy, dict) else {}
        models: dict[str, str] = {}
        for rule in policy.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            when = rule.get("when")
            cohort_key = (
                str(when.get("semantic_cohort_id"))
                if isinstance(when, dict) and when.get("semantic_cohort_id")
                else None
            )
            model_id = rule.get("selected_model_id")
            if (
                cohort_key
                and model_id
                and str(rule.get("reason_code") or "")
                == "validated_adaptive_cohort"
            ):
                models[cohort_key] = str(model_id)
        return models

    @classmethod
    def _active_model_for_cohort(
        cls,
        active_policy: Any,
        *,
        cohort_key: str,
    ) -> str | None:
        return cls._active_models_by_cohort(active_policy).get(cohort_key)

    @staticmethod
    def _model_has_any_evidence(
        db: Session,
        *,
        cohort_id: uuid.UUID,
        model_id: str,
        fingerprint: str,
    ) -> bool:
        """같은 bootstrap에서 이미 시도한 후보를 다음 wave에서 제외한다."""
        return (
            db.query(LLMNodeModelRoutingModelEvidence)
            .filter(LLMNodeModelRoutingModelEvidence.cohort_id == cohort_id)
            .filter(LLMNodeModelRoutingModelEvidence.model_id == model_id)
            .filter(LLMNodeModelRoutingModelEvidence.node_config_fingerprint == fingerprint)
            .first()
            is not None
        )

    @staticmethod
    def _model_has_validated_evidence(
        db: Session,
        *,
        cohort_id: uuid.UUID,
        model_id: str,
        fingerprint: str,
    ) -> bool:
        """통과 evidence만 완료로 본다.

        탈락 evidence는 당시 합성 입력에 대한 결과다. 새로운 운영 입력 window가
        쌓였을 때도 이를 완료로 취급하면 후보가 영원히 재검증되지 않는다.
        """
        return (
            db.query(LLMNodeModelRoutingModelEvidence)
            .filter(LLMNodeModelRoutingModelEvidence.cohort_id == cohort_id)
            .filter(LLMNodeModelRoutingModelEvidence.model_id == model_id)
            .filter(LLMNodeModelRoutingModelEvidence.node_config_fingerprint == fingerprint)
            .filter(LLMNodeModelRoutingModelEvidence.status == "validated")
            .first()
            is not None
        )

    @staticmethod
    def _cohort_observations(db: Session, *, cohort_id: uuid.UUID):
        return (
            db.query(LLMNodeModelRoutingObservation)
            .filter(LLMNodeModelRoutingObservation.matched_cohort_id == cohort_id)
            .order_by(LLMNodeModelRoutingObservation.observed_at.desc())
            .limit(ModelRoutingValidationPlanner.REPLAYS_PER_CANDIDATE)
            .all()
        )

    @staticmethod
    def _cohort_examples(db: Session, *, cohort_id: uuid.UUID):
        return (
            db.query(LLMNodeModelRoutingCohortExample)
            .filter(LLMNodeModelRoutingCohortExample.cohort_id == cohort_id)
            .order_by(LLMNodeModelRoutingCohortExample.ordinal.asc())
            .limit(ModelRoutingValidationPlanner.REPLAYS_PER_CANDIDATE)
            .all()
        )

    @classmethod
    def _estimate_bootstrap_replay_cost(
        cls,
        db: Session,
        *,
        examples: list[LLMNodeModelRoutingCohortExample],
        node_data: dict[str, Any],
        baseline_model_id: str,
        candidate_model_id: str,
        judge_model_id: str,
    ) -> Decimal | None:
        """운영 usage가 없을 때 기준·후보·Judge 호출 비용을 보수적으로 예약한다."""
        prompt_chars = sum(
            len(str(node_data.get(key) or ""))
            for key in ("system_prompt", "user_prompt", "assistant_prompt")
        ) + max((len(item.synthetic_text) for item in examples), default=0)
        prompt_tokens = max(128, (prompt_chars + 3) // 4)
        parameters = (
            node_data.get("parameters")
            if isinstance(node_data.get("parameters"), dict)
            else {}
        )
        try:
            configured_max_tokens = int(parameters.get("max_tokens") or 1024)
        except (TypeError, ValueError):
            configured_max_tokens = 1024
        completion_tokens = max(64, min(4096, configured_max_tokens))
        costs = [
            LLMService.calculate_cost(
                db,
                baseline_model_id,
                prompt_tokens,
                completion_tokens,
            ),
            LLMService.calculate_cost(
                db,
                candidate_model_id,
                prompt_tokens,
                completion_tokens,
            ),
            LLMService.calculate_cost(
                db,
                judge_model_id,
                1000,
                cls.QUALITY_JUDGE_MAX_TOKENS,
            ),
        ]
        if any(value is None for value in costs):
            return None
        return sum(Decimal(str(value)) for value in costs if value is not None)

    @classmethod
    def _estimate_candidate_replay_cost(
        cls,
        db: Session,
        *,
        observations: list[LLMNodeModelRoutingObservation],
        candidate_model_id: str,
        judge_model_id: str,
    ) -> Decimal | None:
        node_runs = (
            db.query(WorkflowNodeRun)
            .filter(WorkflowNodeRun.id.in_([row.workflow_node_run_id for row in observations]))
            .all()
        )
        usages = [
            row.outputs.get("usage")
            for row in node_runs
            if isinstance(row.outputs, dict) and isinstance(row.outputs.get("usage"), dict)
        ]
        if not usages:
            return None
        estimated: list[Decimal] = []
        for usage in usages:
            prompt = cls._usage_int(usage, "prompt_tokens", "input_tokens")
            completion = cls._usage_int(usage, "completion_tokens", "output_tokens")
            candidate = LLMService.calculate_cost(db, candidate_model_id, prompt, completion)
            # Judge prompt/response는 output 길이에 따라 변하지만, budget reserve는
            # 일정 여유를 둔 1,000/700 token으로 계산한다.
            judge = LLMService.calculate_cost(db, judge_model_id, 1000, cls.QUALITY_JUDGE_MAX_TOKENS)
            if candidate is None or judge is None:
                return None
            estimated.append(Decimal(str(candidate)) + Decimal(str(judge)))
        return sum(estimated) / Decimal(len(estimated))

    @staticmethod
    def _usage_int(usage: dict[str, Any], *keys: str) -> int:
        for key in keys:
            try:
                return max(0, int(usage.get(key) or 0))
            except (TypeError, ValueError):
                continue
        return 0

    @staticmethod
    def _locked_monthly_budget(db: Session, policy: LLMNodeModelRoutingPolicy):
        month = date.today().replace(day=1)
        budget = (
            db.query(LLMNodeModelRoutingValidationBudgetMonth)
            .filter(LLMNodeModelRoutingValidationBudgetMonth.policy_id == policy.id)
            .filter(LLMNodeModelRoutingValidationBudgetMonth.month_start == month)
            .with_for_update()
            .first()
        )
        if budget is None:
            budget = LLMNodeModelRoutingValidationBudgetMonth(
                policy_id=policy.id,
                month_start=month,
                limit_usd=Decimal(str(policy.validation_budget_usd or 3)),
            )
            db.add(budget)
            db.flush()
        else:
            # 같은 달에도 정책 설정은 즉시 효력이 있어야 한다. 사용자가 예산을 낮춘
            # 경우 기존 monthly row의 예전 한도로 추가 Replay가 예약되면 안 된다.
            budget.limit_usd = Decimal(str(policy.validation_budget_usd or 3))
        return budget

    @classmethod
    def _fail_batch_and_release_refresh(
        cls,
        db: Session,
        *,
        batch: LLMNodeModelRoutingValidationBatch,
        policy: LLMNodeModelRoutingPolicy,
        reason_code: str,
    ) -> None:
        """실행 불가 batch가 refresh lease와 예약 예산을 남기지 않게 정리한다."""
        batch.status = "failed"
        batch.error_summary = {"reason_code": reason_code}
        batch.completed_at = datetime.now(timezone.utc)
        cls._restore_cohort_statuses_after_failed_batch(db, batch=batch)
        budget = cls._locked_monthly_budget(db, policy)
        budget.reserved_usd = max(
            Decimal("0"),
            Decimal(str(budget.reserved_usd or 0))
            - Decimal(str(batch.reserved_cost or 0)),
        )
        policy.last_refresh_result = "failed"
        policy.last_refreshed_at = datetime.now(timezone.utc)
        requested_at = policy.refresh_requested_at
        policy.status = "active" if policy.active_policy else "collecting"
        if requested_at is not None:
            ModelRoutingPolicyLifecycleService.complete_refresh_cycle(
                policy,
                eligible_runs_since_last_refresh=cls._remaining_run_event_count(
                    db,
                    policy=policy,
                    requested_at=requested_at,
                ),
            )
        db.flush()

    @classmethod
    def _restore_cohort_statuses_after_failed_batch(
        cls,
        db: Session,
        *,
        batch: LLMNodeModelRoutingValidationBatch,
    ) -> None:
        """실행 전 실패한 batch가 입력군을 validating에 남기지 않게 복구한다."""
        plan = batch.candidate_plan if isinstance(batch.candidate_plan, dict) else {}
        previous_by_id = plan.get("cohort_status_before_validation")
        previous_by_id = previous_by_id if isinstance(previous_by_id, dict) else {}
        cohort_ids: set[uuid.UUID] = set()
        for raw_id in previous_by_id:
            try:
                cohort_ids.add(uuid.UUID(str(raw_id)))
            except (TypeError, ValueError):
                continue
        if not cohort_ids:
            # 이전 버전에서 생성된 batch에는 lifecycle snapshot이 없으므로 item을
            # 기준으로 복구한다. 이 경우 재검증 가능 상태인 proposed로 되돌린다.
            cohort_ids = {
                row.cohort_id
                for row in (
                    db.query(LLMNodeModelRoutingValidationItem)
                    .filter(LLMNodeModelRoutingValidationItem.batch_id == batch.id)
                    .all()
                )
            }
        if not cohort_ids:
            return
        cohorts = (
            db.query(LLMNodeModelRoutingCohort)
            .filter(LLMNodeModelRoutingCohort.id.in_(cohort_ids))
            .all()
        )
        restorable_statuses = {"proposed", "validated_waiting"}
        for cohort in cohorts:
            if cohort.status != "validating":
                continue
            previous = str(previous_by_id.get(str(cohort.id)) or "proposed")
            cohort.status = previous if previous in restorable_statuses else "proposed"

    @classmethod
    def _batch_has_nonterminal_items(
        cls,
        db: Session,
        *,
        batch: LLMNodeModelRoutingValidationBatch,
    ) -> bool:
        return (
            db.query(LLMNodeModelRoutingValidationItem)
            .filter(LLMNodeModelRoutingValidationItem.batch_id == batch.id)
            .filter(
                ~LLMNodeModelRoutingValidationItem.status.in_(
                    cls._TERMINAL_ITEM_STATUSES
                )
            )
            .count()
            > 0
        )

    @staticmethod
    def _should_reuse_existing_batch(batch: Any) -> bool:
        return batch is not None and str(getattr(batch, "status", "")).lower() in {
            "pending",
            "running",
        }

    @classmethod
    def _is_stale_running_item(
        cls,
        item: LLMNodeModelRoutingValidationItem | Any,
        *,
        now: datetime | None = None,
    ) -> bool:
        summary = (
            item.execution_summary
            if isinstance(getattr(item, "execution_summary", None), dict)
            else {}
        )
        try:
            started = datetime.fromisoformat(str(summary.get("_lease_started_at")))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return True
        return (now or datetime.now(timezone.utc)) - started >= cls.RUNNING_ITEM_LEASE

    @staticmethod
    def _persisted_workflow_run_id(
        db: Session,
        workflow_run_id: str | uuid.UUID | None,
    ) -> uuid.UUID | None:
        """비동기 logger가 실제로 저장을 마친 workflow run만 FK로 연결한다."""
        try:
            value = uuid.UUID(str(workflow_run_id))
        except (TypeError, ValueError):
            return None
        run = db.query(WorkflowRun).filter(WorkflowRun.id == value).first()
        return value if run is not None else None

    @staticmethod
    def _locked_policy(db: Session, policy_id: str | uuid.UUID):
        try:
            value = uuid.UUID(str(policy_id))
        except (TypeError, ValueError):
            return None
        return (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.id == value)
            .with_for_update()
            .first()
        )

    @staticmethod
    def _deployment(db: Session, policy: LLMNodeModelRoutingPolicy):
        return db.query(WorkflowDeployment).filter(WorkflowDeployment.id == policy.deployment_id).first()

    @staticmethod
    def _execution_subject(policy: LLMNodeModelRoutingPolicy) -> uuid.UUID | None:
        return policy.execution_subject_user_id or policy.judge_user_id

    @staticmethod
    def _baseline_model(policy: LLMNodeModelRoutingPolicy, node_data: dict[str, Any]) -> str:
        active = policy.active_policy if isinstance(policy.active_policy, dict) else {}
        return str(active.get("default_model_id") or node_data.get("model_id") or "").strip()

    @staticmethod
    def _judge_model_id(*, baseline_model_id: str, available_model_ids: set[str]) -> str:
        return baseline_model_id if baseline_model_id in available_model_ids else sorted(available_model_ids)[0]

    @staticmethod
    def _request_fingerprint(*, policy: LLMNodeModelRoutingPolicy, fingerprint: str, plan: Any) -> str:
        payload = {
            "policy_id": str(policy.id),
            "fingerprint": fingerprint,
            "items": [
                (
                    item.cohort_id,
                    item.observation_id,
                    item.cohort_example_id,
                    item.model_id,
                )
                for item in plan.items
            ],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _node_data(graph: Any, node_id: str) -> dict[str, Any] | None:
        """배포 snapshot에서 검증 대상 LLM node의 data만 안전하게 꺼낸다."""
        node = AdaptiveModelRoutingValidationService._find_node(graph, node_id)
        if node is None:
            return None
        data = node.get("data")
        return data if isinstance(data, dict) else None

    @staticmethod
    def _find_node(graph: Any, node_id: str) -> dict[str, Any] | None:
        for node in graph.get("nodes") if isinstance(graph, dict) else []:
            if isinstance(node, dict) and str(node.get("id")) == node_id:
                return node
        return None

    @classmethod
    def _retarget_references(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [cls._retarget_references(item) for item in value]
        if isinstance(value, dict):
            copied = {key: cls._retarget_references(item) for key, item in value.items()}
            selector = copied.get("value_selector")
            if isinstance(selector, list) and selector:
                copied["value_selector"] = ["model-routing-validation-input", *selector]
            return copied
        return value

    @staticmethod
    def _schema_passed(output: dict[str, Any], node_data: dict[str, Any]) -> bool | None:
        output_format = node_data.get("output_format") if isinstance(node_data.get("output_format"), dict) else {}
        if str(output_format.get("type") or "").lower() != "json":
            return None
        schema = output_format.get("schema") if isinstance(output_format.get("schema"), dict) else {}
        if not schema:
            return True
        raw = output.get("text") if isinstance(output, dict) else None
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        return all(isinstance(key, str) and key in payload for key in required)

    @classmethod
    def _downstream_passed(cls, graph: dict[str, Any], node_id: str, output: dict[str, Any]) -> bool | None:
        consumers = [
            str(edge.get("target"))
            for edge in graph.get("edges", []) if isinstance(edge, dict) and str(edge.get("source")) == node_id
        ] if isinstance(graph, dict) else []
        if not consumers:
            return None
        nodes = {str(node.get("id")): node for node in graph.get("nodes", []) if isinstance(node, dict)}
        for consumer_id in consumers:
            node = nodes.get(consumer_id, {})
            for contract in cls._downstream_contracts_for_consumer(node_id, node):
                if not cls._downstream_contract_satisfied(output, contract):
                    return False
        return True

    @staticmethod
    def _downstream_contracts_for_consumer(
        target_node_id: str,
        consumer: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Cost Optimizer compare와 같은 direct consumer 계약만 검증한다."""
        consumer_type = str(consumer.get("type") or "")
        data = consumer.get("data") if isinstance(consumer.get("data"), dict) else {}
        contracts: list[dict[str, str]] = []
        if consumer_type == "variableExtractionNode":
            source_selector = data.get("source_selector") or []
            if not source_selector or source_selector[0] != target_node_id:
                return contracts
            selector = str(source_selector[1] if len(source_selector) > 1 else "text")
            for mapping in data.get("mappings") or []:
                path = str(mapping.get("json_path") or "").strip() if isinstance(mapping, dict) else ""
                if path:
                    contracts.append({"kind": "json_path", "selector": selector, "path": path})
            return contracts
        selectors_by_type = {
            "conditionNode": [
                condition.get("variable_selector") or []
                for case in data.get("cases") or []
                if isinstance(case, dict)
                for condition in case.get("conditions") or []
                if isinstance(condition, dict)
            ],
            "answerNode": [
                item.get("value_selector") or []
                for item in data.get("outputs") or []
                if isinstance(item, dict)
            ],
            "slackPostNode": [
                item.get("value_selector") or []
                for item in data.get("referenced_variables") or []
                if isinstance(item, dict)
            ],
        }
        for selector in selectors_by_type.get(consumer_type, []):
            if isinstance(selector, list) and len(selector) > 1 and selector[0] == target_node_id:
                contracts.append({"kind": "selector", "key": str(selector[1])})
        return contracts

    @classmethod
    def _downstream_contract_satisfied(
        cls,
        output: dict[str, Any],
        contract: dict[str, str],
    ) -> bool:
        if contract.get("kind") == "selector":
            return contract.get("key") in output
        value = output.get(contract.get("selector", "text"))
        try:
            payload = json.loads(value) if isinstance(value, str) else value
        except json.JSONDecodeError:
            return False
        return cls._json_path_exists(payload, str(contract.get("path") or ""))

    @staticmethod
    def _json_path_exists(payload: Any, path: str) -> bool:
        current = payload
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return False
        return True

    @staticmethod
    def _cost(output: dict[str, Any]) -> float | None:
        usage = output.get("usage") if isinstance(output, dict) else {}
        for source in (usage if isinstance(usage, dict) else {}, output):
            for key in ("cost", "total_cost"):
                try:
                    value = source.get(key)
                    if value is not None:
                        return float(value)
                except (AttributeError, TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _duration_ms(node_run: WorkflowNodeRun) -> float | None:
        try:
            return float(node_run.duration) * 1000 if node_run.duration is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_error_code(exc: Exception) -> str:
        code = str(getattr(exc, "code", "") or "").strip()
        return code if code else type(exc).__name__

    @staticmethod
    def _failed_item(reason_code: str, *, workflow_run_id=None, model_unavailable: bool = False) -> dict[str, Any]:
        return {
            "status": "failed",
            "workflow_run_id": workflow_run_id,
            "actual_cost_usd": Decimal("0"),
            "model_unavailable": model_unavailable,
            "execution_summary": {"execution_succeeded": False, "reason_code": reason_code},
            "quality_summary": {"status": "unavailable", "reason_code": reason_code},
        }

    @staticmethod
    def _baseline_failed_item(
        reason_code: str,
        *,
        baseline_cost: Decimal | float | int,
    ) -> dict[str, Any]:
        """기준 모델 검증 실패를 후보 실행 실패와 구분해 비용까지 기록한다."""
        return {
            "status": "baseline_failed",
            "workflow_run_id": None,
            "actual_cost_usd": Decimal(str(baseline_cost or 0)),
            "model_unavailable": False,
            "execution_summary": {
                "execution_succeeded": False,
                "baseline_validation_passed": False,
                "baseline_cost": float(baseline_cost or 0),
                "reason_code": reason_code,
            },
            "quality_summary": {
                "status": "unavailable",
                "reason_code": reason_code,
            },
        }

    @classmethod
    def _baseline_failure_with_cache(
        cls,
        reason_code: str,
        *,
        baseline_cost: Decimal | float | int,
    ) -> dict[str, Any]:
        result = cls._baseline_failed_item(
            reason_code,
            baseline_cost=baseline_cost,
        )
        result["_baseline_cache_entry"] = {
            "passed": False,
            "reason_code": reason_code,
        }
        return result

    @staticmethod
    def _outcome_from_item(item: LLMNodeModelRoutingValidationItem) -> AdaptiveValidationOutcome:
        execution = item.execution_summary if isinstance(item.execution_summary, dict) else {}
        quality = item.quality_summary if isinstance(item.quality_summary, dict) else {}
        return AdaptiveValidationOutcome(
            execution_succeeded=bool(execution.get("execution_succeeded")),
            schema_passed=execution.get("schema_passed"),
            downstream_passed=execution.get("downstream_passed"),
            quality_score=quality.get("candidate_score"),
            baseline_quality_score=quality.get("baseline_score"),
            quality_confidence=quality.get("confidence"),
            candidate_cost=execution.get("candidate_cost"),
            baseline_cost=execution.get("baseline_cost"),
            candidate_latency_ms=execution.get("candidate_latency_ms"),
            baseline_latency_ms=execution.get("baseline_latency_ms"),
            fallback_used=bool(execution.get("fallback_used")),
        )

    @staticmethod
    def _content(response: Any) -> str:
        if isinstance(response, dict):
            choices = response.get("choices") or []
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message") or {}
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
        return ""

    @staticmethod
    def _usage(response: Any) -> dict[str, int]:
        usage = response.get("usage") if isinstance(response, dict) else {}
        usage = usage if isinstance(usage, dict) else {}
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": int(usage.get("total_tokens") or prompt + completion)}

    @staticmethod
    def _score(value: Any, *, upper: float = 100) -> float | None:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return None
        return score if 0 <= score <= upper else None

    @classmethod
    def _judge_visible(cls, value: Any) -> Any:
        redaction = TraceRedactionService.redact_payload(
            cls._bounded(value),
            TracePolicyService.fail_closed_redaction_policy(),
            payload_kind="model_routing_quality_judge",
        )
        if redaction.failed:
            raise ValueError("quality_judge_redaction_failed")
        return cls._bounded(redaction.redacted_payload)

    @classmethod
    def _bounded(cls, value: Any, *, depth: int = 4, max_chars: int = 6000) -> Any:
        if depth <= 0:
            return "[TRUNCATED]"
        if isinstance(value, str):
            return value[:max_chars]
        if isinstance(value, dict):
            return {str(key): cls._bounded(item, depth=depth - 1, max_chars=max_chars) for key, item in list(value.items())[:30] if str(key) not in {"metadata", "usage"}}
        if isinstance(value, list):
            return [cls._bounded(item, depth=depth - 1, max_chars=max_chars) for item in value[:30]]
        return value

    @staticmethod
    def _judge_unavailable(reason_code: str) -> dict[str, Any]:
        return {"status": "unavailable", "reason_code": reason_code, "baseline_score": None, "candidate_score": None, "confidence": None, "judge_cost": 0, "judge_usage_log_id": None}

    @staticmethod
    def _next_policy_version(value: Any) -> str:
        current = str(value or "adaptive-v0")
        prefix, separator, number = current.rpartition("v")
        try:
            return f"{prefix}v{int(number) + 1}" if separator else "adaptive-v1"
        except ValueError:
            return f"{current}-next"
