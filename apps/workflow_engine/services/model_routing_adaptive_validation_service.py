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


class AdaptiveModelRoutingValidationService:
    """검증 batch를 계획하고 실제 provider Replay 결과를 policy evidence로 반영한다."""

    MAX_CANDIDATES_PER_COHORT = 2
    MAX_VALIDATING_COHORTS = 4
    QUALITY_JUDGE_MAX_TOKENS = 700
    RUNNING_ITEM_LEASE = timedelta(minutes=5)
    _TERMINAL_BATCH_STATUSES = {"completed", "failed", "cancelled"}
    _TERMINAL_ITEM_STATUSES = {"completed", "failed", "skipped_unavailable"}

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
    ) -> LLMNodeModelRoutingValidationBatch | None:
        policy = cls._locked_policy(db, policy_id)
        if policy is None or not policy.enabled:
            return None
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
        cohorts = cls._candidate_cohorts(db, policy_id=policy.id, fingerprint=fingerprint)
        if not cohorts:
            return None
        available_model_ids = set(
            LLMService.get_runtime_available_model_ids_for_user(
                db,
                user_id=subject_id,
                organization_id=policy.organization_id,
            )
        )
        if not available_model_ids:
            return None
        baseline_model_id = cls._baseline_model(policy, node_data)
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
        estimated_items: dict[tuple[str, str], Decimal] = {}
        for cohort in cohorts:
            candidate_models = cls._candidate_models(
                db,
                policy=policy,
                cohort_id=cohort.id,
                fingerprint=fingerprint,
                baseline_model_id=baseline_model_id,
                available_model_ids=available_model_ids,
            )
            if not candidate_models:
                continue
            observations = cls._cohort_observations(db, cohort_id=cohort.id)
            if len(observations) < ModelRoutingValidationPlanner.REPLAYS_PER_CANDIDATE:
                continue
            estimated_candidates: list[CandidateValidationRequest] = []
            for model_id in candidate_models:
                estimate = cls._estimate_candidate_replay_cost(
                    db,
                    observations=observations,
                    candidate_model_id=model_id,
                    judge_model_id=judge_model_id,
                )
                if estimate is None:
                    continue
                estimated_candidates.append(
                    CandidateValidationRequest(
                        model_id=model_id,
                        estimated_item_cost=float(estimate),
                    )
                )
                estimated_items[(str(cohort.id), model_id)] = estimate
            if estimated_candidates:
                cohort_inputs.append(
                    CohortValidationInput(
                        cohort_id=str(cohort.id),
                        observation_ids=tuple(str(item.id) for item in observations),
                        candidates=tuple(estimated_candidates),
                    )
                )

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
                    observation_id=uuid.UUID(planned.observation_id),
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
            result = cls._execute_validation_item(
                db,
                policy=policy,
                deployment=deployment,
                node_data=node_data,
                item=item,
                execution_subject_id=subject_id,
            )
            item.status = result["status"]
            item.candidate_workflow_run_id = result.get("workflow_run_id")
            item.execution_summary = result["execution_summary"]
            item.quality_summary = result["quality_summary"]
            item.actual_cost_usd = result.get("actual_cost_usd")
            item.completed_at = datetime.now(timezone.utc)
            batch.completed_items = int(batch.completed_items or 0) + 1
            spent = Decimal(str(result.get("actual_cost_usd") or 0))
            batch.spent_cost = Decimal(str(batch.spent_cost or 0)) + spent
            if spent > 0:
                db.add(
                    LLMNodeModelRoutingValidationCostEvent(
                        batch_id=batch.id,
                        event_type="candidate_replay_and_judge",
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
    def _execute_validation_item(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        deployment: WorkflowDeployment,
        node_data: dict[str, Any],
        item: LLMNodeModelRoutingValidationItem,
        execution_subject_id: uuid.UUID,
    ) -> dict[str, Any]:
        observation = db.query(LLMNodeModelRoutingObservation).filter(
            LLMNodeModelRoutingObservation.id == item.observation_id
        ).first()
        baseline_node_run = (
            db.query(WorkflowNodeRun)
            .filter(WorkflowNodeRun.id == observation.workflow_node_run_id)
            .first()
            if observation is not None
            else None
        )
        if observation is None or baseline_node_run is None:
            return cls._failed_item("baseline_observation_unavailable")
        baseline_input = copy.deepcopy(
            baseline_node_run.inputs if isinstance(baseline_node_run.inputs, dict) else {}
        )
        baseline_output = copy.deepcopy(
            baseline_node_run.outputs if isinstance(baseline_node_run.outputs, dict) else {}
        )
        # observation/item lock과 이전 item의 결과 commit을 provider 호출 전 확정한다.
        # 이 지점 이후 DB transaction을 길게 잡아 운영 입력 기록을 막지 않는다.
        db.commit()
        started = time.perf_counter()
        try:
            candidate_output, candidate_run_id = cls._run_candidate_replay(
                db,
                policy=policy,
                deployment=deployment,
                node_data=node_data,
                baseline_node_run=baseline_node_run,
                candidate_model_id=item.model_id,
                execution_subject_id=execution_subject_id,
            )
        except Exception as exc:
            code = cls._safe_error_code(exc)
            return cls._failed_item(
                code,
                workflow_run_id=None,
                model_unavailable=code in {"credential_not_available", "model_relation_not_verified", "model_inactive"},
            )
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
        )
        candidate_cost = cls._cost(candidate_output)
        baseline_cost = cls._cost(baseline_output)
        actual_cost = Decimal(str(candidate_cost or 0)) + Decimal(
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
            baseline_latency_ms=cls._duration_ms(baseline_node_run),
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
                "baseline_latency_ms": cls._duration_ms(baseline_node_run),
                "requested_model_id": item.model_id,
                "actual_model_id": actual_model_id,
                "fallback_used": fallback_used,
            },
            # quality_summary는 JSONB에 저장된다. Judge usage FK는 위의 별도
            # relational column으로 UUID를 유지하고, summary에는 JSON-safe 값만 둔다.
            "quality_summary": cls._json_safe_quality_summary(quality),
            "outcome": outcome,
        }

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
    def _run_candidate_replay(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        deployment: WorkflowDeployment,
        node_data: dict[str, Any],
        baseline_node_run: WorkflowNodeRun,
        candidate_model_id: str,
        execution_subject_id: uuid.UUID,
    ) -> tuple[dict[str, Any], uuid.UUID]:
        run_id = uuid.uuid4()
        graph = cls._candidate_graph(
            deployment.graph_snapshot,
            node_id=policy.node_id,
            candidate_model_id=candidate_model_id,
            fallback_model_id=cls._baseline_model(policy, node_data),
            baseline_input=baseline_node_run.inputs,
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
            user_input=baseline_node_run.inputs if isinstance(baseline_node_run.inputs, dict) else {},
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
    ) -> dict[str, Any]:
        target = cls._find_node(graph, node_id)
        if target is None:
            raise ValueError("target_llm_node_not_found")
        target = copy.deepcopy(target)
        data = target.get("data") if isinstance(target.get("data"), dict) else {}
        data = copy.deepcopy(data)
        data["model_id"] = candidate_model_id
        data["fallback_model_id"] = fallback_model_id or None
        data["auto_model_routing"] = False
        data["referenced_variables"] = cls._retarget_references(
            data.get("referenced_variables") or []
        )
        target["data"] = data
        values = baseline_input if isinstance(baseline_input, dict) else {}
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
                            for key in values
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
        }

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
            payload = {
                "task": "Score two anonymized outputs for the same workflow input.",
                "input": cls._judge_visible(baseline_input),
                "variant_a": cls._judge_visible(baseline_output),
                "variant_b": cls._judge_visible(candidate_output),
                "response_schema": {
                    "variant_a_score": "0..100",
                    "variant_b_score": "0..100",
                    "confidence": "0..1",
                },
            }
            started = time.perf_counter()
            response = selection.client.invoke_sync(
                [
                    {
                        "role": "system",
                        "content": "Return JSON only. Judge instruction fulfillment, correctness, clarity, and output contract suitability. Do not disclose sensitive content.",
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.0,
                max_tokens=cls.QUALITY_JUDGE_MAX_TOKENS,
            )
            usage = cls._usage(response)
            usage["latency_ms"] = int((time.perf_counter() - started) * 1000)
            parsed = json.loads(cls._content(response))
            baseline_score = cls._score(parsed.get("variant_a_score"))
            candidate_score = cls._score(parsed.get("variant_b_score"))
            confidence = cls._score(parsed.get("confidence"), upper=1)
            if baseline_score is None or candidate_score is None or confidence is None:
                return cls._judge_unavailable("judge_response_invalid")
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
            }
        except Exception as exc:
            logger.warning("[Model-Routing] quality judge skipped: error_type=%s", type(exc).__name__)
            return cls._judge_unavailable("judge_execution_failed")

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
        for (cohort_id, model_id), rows in grouped.items():
            outcomes = [cls._outcome_from_item(item) for item in rows]
            result = AdaptiveValidationResultService.evaluate(
                outcomes,
                expected_samples=ModelRoutingValidationPlanner.REPLAYS_PER_CANDIDATE,
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
            if evidence.status == "validated":
                cohort = (
                    db.query(LLMNodeModelRoutingCohort)
                    .filter(LLMNodeModelRoutingCohort.id == cohort_id)
                    .first()
                )
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
                    }
                )

        selected: dict[uuid.UUID, dict[str, Any]] = {}
        for route in sorted(routes, key=lambda item: (item["candidate_cost"], item["model_id"])):
            selected.setdefault(uuid.UUID(str(route["cohort_row_id"])), route)
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
        if catalog is not None and selected:
            policy.active_policy = AdaptiveValidationResultService.project_active_policy(
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
            )
            policy.policy_version = cls._next_policy_version(policy.policy_version)
            policy.status = "active"
            policy.last_refresh_result = "applied"
        else:
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
        batch.error_summary = {
            "validated_route_count": len(selected),
            "rejected_or_waiting_cohort_count": max(0, len(grouped) - len(selected)),
        }
        db.flush()

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
            "quality_summary": {**result.quality_summary, "reason_code": result.reason_code},
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
    def _candidate_cohorts(cls, db: Session, *, policy_id: uuid.UUID, fingerprint: str):
        return (
            db.query(LLMNodeModelRoutingCohort)
            .filter(LLMNodeModelRoutingCohort.policy_id == policy_id)
            .filter(LLMNodeModelRoutingCohort.status.in_(["proposed", "validated_waiting"]))
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
    ) -> list[str]:
        candidates = [
            AdaptiveCandidate(
                model_id=candidate.model_id,
                estimated_cost=candidate.price_score,
                validated=cls._model_has_any_evidence(
                    db,
                    cohort_id=cohort_id,
                    model_id=candidate.model_id,
                    fingerprint=fingerprint,
                ),
            )
            for candidate in ModelRouter.collect_candidates(
                db, organization_id=policy.organization_id
            )
            if candidate.model_id != baseline_model_id
        ]
        baseline_price = next(
            (
                candidate.price_score
                for candidate in ModelRouter.collect_candidates(db, organization_id=policy.organization_id)
                if candidate.model_id == baseline_model_id
            ),
            float("inf"),
        )
        lower_cost = [item for item in candidates if item.estimated_cost < baseline_price]
        planned = AdaptiveModelRoutingPolicyService.plan_candidates(
            candidates=lower_cost or candidates,
            available_model_ids=available_model_ids,
            maximum_candidates=cls.MAX_CANDIDATES_PER_COHORT,
        )
        return [item.model_id for item in planned]

    @staticmethod
    def _model_has_any_evidence(db: Session, *, cohort_id: uuid.UUID, model_id: str, fingerprint: str) -> bool:
        return (
            db.query(LLMNodeModelRoutingModelEvidence)
            .filter(LLMNodeModelRoutingModelEvidence.cohort_id == cohort_id)
            .filter(LLMNodeModelRoutingModelEvidence.model_id == model_id)
            .filter(LLMNodeModelRoutingModelEvidence.node_config_fingerprint == fingerprint)
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
                (item.cohort_id, item.observation_id, item.model_id)
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
