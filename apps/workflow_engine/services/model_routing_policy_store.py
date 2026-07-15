"""모델 라우팅 policy의 DB persistence와 배포 run 완료 훅을 담당한다."""

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.shared.db.models.model_routing_policy import (
    LLMNodeModelRoutingPolicy,
    LLMNodeModelRoutingPolicyRunEvent,
    LLMNodeModelRoutingPolicyUpdate,
)
from apps.shared.db.models.model_routing_cohort import LLMNodeModelRoutingCohort
from apps.shared.db.models.app import App
from apps.shared.db.models.workflow_deployment import WorkflowDeployment
from apps.shared.db.models.workflow_run import (
    NodeRunStatus,
    RunStatus,
    WorkflowNodeRun,
    WorkflowRun,
)
from apps.workflow_engine.services.model_routing_policy_lifecycle import (
    ModelRoutingPolicyLifecycleService,
)
from apps.workflow_engine.services.model_routing_policy_refresh import (
    ModelRoutingPolicyRefreshService,
)
from apps.workflow_engine.services.llm_service import LLMService
from apps.shared.services.model_routing_cohort_drafts import (
    model_routing_cohort_drafts,
    model_routing_excluded_model_ids,
)


logger = logging.getLogger(__name__)


class ModelRoutingRunLogPendingError(RuntimeError):
    """Workflow는 끝났지만 자동 라우팅 node 완료 로그가 아직 반영되지 않았다."""


class ModelRoutingPolicyStore:
    """정책 row 조회와 운영 run 누적을 한 곳에서 일관되게 처리한다."""

    @staticmethod
    def _max_cohorts(node_data: dict[str, Any]) -> int:
        """배포 snapshot에 저장된 활성 입력군 상한을 안전한 범위로 정규화한다."""
        policy = node_data.get("model_routing_policy")
        value = policy.get("max_cohorts") if isinstance(policy, dict) else 6
        try:
            return max(1, min(12, int(value)))
        except (TypeError, ValueError):
            return 6

    @staticmethod
    def _refresh_every_runs(node_data: dict[str, Any]) -> int:
        policy = node_data.get("model_routing_policy")
        refresh = policy.get("refresh") if isinstance(policy, dict) else None
        value = refresh.get("refresh_every_runs") if isinstance(refresh, dict) else 20
        try:
            return max(5, min(100, int(value)))
        except (TypeError, ValueError):
            return 20

    @staticmethod
    def _validation_budget_usd(node_data: dict[str, Any]) -> Decimal:
        """배포 snapshot에 저장된 월간 검증 예산을 안전한 범위로 정규화한다."""
        policy = node_data.get("model_routing_policy")
        raw_value = (
            policy.get("validation_budget_usd")
            if isinstance(policy, dict)
            else Decimal("3")
        )
        try:
            value = Decimal(str(raw_value))
        except (InvalidOperation, TypeError, ValueError):
            value = Decimal("3")
        return max(Decimal("0.5"), min(Decimal("10"), value))

    @classmethod
    def get_runtime_policy(
        cls,
        db: Session,
        *,
        workflow_id: str | uuid.UUID | None,
        deployment_id: str | uuid.UUID | None,
        node_id: str,
    ) -> LLMNodeModelRoutingPolicy | None:
        if not workflow_id or not deployment_id:
            return None
        try:
            workflow_uuid = uuid.UUID(str(workflow_id))
            deployment_uuid = uuid.UUID(str(deployment_id))
        except (TypeError, ValueError):
            return None
        return (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.workflow_id == workflow_uuid)
            .filter(LLMNodeModelRoutingPolicy.deployment_id == deployment_uuid)
            .filter(LLMNodeModelRoutingPolicy.node_id == node_id)
            .first()
        )

    @classmethod
    def ensure_policy_for_deployed_node(
        cls,
        db: Session,
        *,
        workflow_run: WorkflowRun,
        node_id: str,
        node_data: dict[str, Any],
    ) -> LLMNodeModelRoutingPolicy | None:
        if not bool(node_data.get("auto_model_routing")):
            return None
        if workflow_run.deployment_id is None:
            return None

        policy = cls.get_runtime_policy(
            db,
            workflow_id=workflow_run.workflow_id,
            deployment_id=workflow_run.deployment_id,
            node_id=node_id,
        )
        if policy is not None:
            cls._materialize_draft_cohorts(
                db,
                policy=policy,
                workflow_run=workflow_run,
                node_data=node_data,
            )
            return policy

        policy_id = uuid.uuid4()
        organization_id = cls._organization_id_for_run(db, workflow_run)
        refresh_every_runs = cls._refresh_every_runs(node_data)
        validation_budget_usd = cls._validation_budget_usd(node_data)
        max_cohorts = cls._max_cohorts(node_data)
        configured_model_id = str(node_data.get("model_id") or "").strip()
        if not configured_model_id:
            # 실행 모델이 없는 잘못된 deployment snapshot은 policy를 만들지 않는다.
            # 이후 runtime도 저장 모델을 임의로 추정하지 않고 기존 validation 경로에서 막는다.
            return None
        execution_user_id = getattr(workflow_run, "user_id", None)
        if organization_id is None or execution_user_id is None:
            return None
        available_model_ids = set(
            LLMService.get_runtime_available_model_ids_for_user(
                db,
                user_id=execution_user_id,
                organization_id=organization_id,
            )
        )
        available_model_ids -= model_routing_excluded_model_ids(node_data)
        if configured_model_id not in available_model_ids:
            # bootstrap policy가 실행 주체에게 사용할 수 없는 모델을 active로 만들면
            # policy runtime의 credential guard보다 먼저 잘못된 상태를 저장하게 된다.
            return None
        fallback_model_id = node_data.get("fallback_model_id")
        if fallback_model_id not in available_model_ids:
            fallback_model_id = None
        bootstrap = ModelRoutingPolicyRefreshService.default_rule_policy(
            policy_id=str(policy_id),
            policy_version="bootstrap-preserve-config-v1",
            default_model_id=configured_model_id,
            fallback_model_id=fallback_model_id,
            refresh_every_runs=refresh_every_runs,
        )

        policy = LLMNodeModelRoutingPolicy(
            id=policy_id,
            organization_id=organization_id,
            workflow_id=workflow_run.workflow_id,
            deployment_id=workflow_run.deployment_id,
            node_id=node_id,
            enabled=True,
            status="collecting",
            policy_version=bootstrap["policy_version"],
            active_policy=bootstrap["active_policy"],
            refresh_every_runs=refresh_every_runs,
            judge_user_id=workflow_run.user_id,
            execution_subject_user_id=workflow_run.user_id,
            validation_budget_usd=validation_budget_usd,
            max_cohorts=max_cohorts,
        )
        try:
            with db.begin_nested():
                db.add(policy)
                db.flush()
        except IntegrityError:
            return cls.get_runtime_policy(
                db,
                workflow_id=workflow_run.workflow_id,
                deployment_id=workflow_run.deployment_id,
                node_id=node_id,
            )
        cls._materialize_draft_cohorts(
            db,
            policy=policy,
            workflow_run=workflow_run,
            node_data=node_data,
        )
        return policy

    @classmethod
    def _materialize_draft_cohorts(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        workflow_run: WorkflowRun,
        node_data: dict[str, Any],
    ) -> int:
        """배포 snapshot의 초안을 실제 semantic cohort로 best-effort 승격한다."""
        drafts = model_routing_cohort_drafts(node_data)
        user_id = getattr(workflow_run, "user_id", None)
        if not drafts or user_id is None or policy.organization_id is None:
            return 0
        try:
            embedding_models = LLMService.get_runtime_available_embedding_model_ids_for_user(
                db,
                user_id=user_id,
                organization_id=policy.organization_id,
            )
            if not embedding_models:
                return 0
            encoder_model_id = cls._preferred_embedding_model(
                node_data,
                embedding_models,
            )
            selection = LLMService.get_runtime_client_for_user(
                db,
                user_id=user_id,
                model_id=encoder_model_id,
                organization_id=policy.organization_id,
            )
            from apps.workflow_engine.services.model_routing_adaptive_store import (
                AdaptiveModelRoutingCohortStore,
            )

            created = 0
            for draft in drafts:
                cohort_id = uuid.UUID(draft["id"])
                existing = (
                    db.query(LLMNodeModelRoutingCohort)
                    .filter(LLMNodeModelRoutingCohort.id == cohort_id)
                    .filter(LLMNodeModelRoutingCohort.policy_id == policy.id)
                    .first()
                )
                if existing is not None:
                    continue
                AdaptiveModelRoutingCohortStore.create_manual_cohort(
                    db,
                    policy=policy,
                    node_data=node_data,
                    cohort_id=cohort_id,
                    label=draft["label"],
                    cohort_key=draft["key"],
                    representative_query=draft["representative_query"],
                    fixed=draft["fixed"],
                    encoder_model_id=encoder_model_id,
                    embed=selection.client.embed_sync,
                )
                created += 1
            return created
        except Exception as exc:
            # 임베딩 공급자 장애가 고객의 본 workflow 실행을 실패시키면 안 된다.
            # 초안은 deployment snapshot에 남으므로 다음 정책 생성/복구에서 재시도한다.
            logger.warning(
                "[Model-Routing] cohort draft materialization skipped: error_type=%s",
                type(exc).__name__,
            )
            return 0

    @classmethod
    def _lock_policy_for_update(
        cls,
        db: Session,
        *,
        policy_id: uuid.UUID,
    ) -> LLMNodeModelRoutingPolicy | None:
        return (
            db.query(LLMNodeModelRoutingPolicy)
            .populate_existing()
            .filter(LLMNodeModelRoutingPolicy.id == policy_id)
            .with_for_update()
            .first()
        )

    @classmethod
    def claim_pending_auto_refresh(
        cls,
        db: Session,
        *,
        policy_id: str | uuid.UUID,
    ) -> LLMNodeModelRoutingPolicy | None:
        """동일 auto refresh 메시지 중 아직 처리할 요청 하나만 transaction 안에서 통과시킨다."""
        try:
            policy_uuid = uuid.UUID(str(policy_id))
        except (TypeError, ValueError):
            return None
        policy = cls._lock_policy_for_update(db, policy_id=policy_uuid)
        if not ModelRoutingPolicyLifecycleService.has_pending_refresh_request(policy):
            return None

        # 동일 refresh 요청은 task 재전달로 여러 번 들어올 수 있다. policy 행을
        # 잠근 뒤, 이 요청 시각 이후 생성된 update가 있으면 이미 다른 worker가
        # refresh를 시작한 것이므로 중복 Judge/Replay를 막는다. 첫 worker가 commit
        # 전에 실패하면 update도 남지 않아 Celery 재시도가 정상적으로 다시 claim한다.
        refresh_requested_at = policy.refresh_requested_at
        refresh_already_started = (
            db.query(LLMNodeModelRoutingPolicyUpdate.id)
            .filter(LLMNodeModelRoutingPolicyUpdate.policy_id == policy.id)
            .filter(LLMNodeModelRoutingPolicyUpdate.created_at >= refresh_requested_at)
            .first()
        )
        if refresh_already_started is not None:
            return None
        return policy

    @staticmethod
    def _organization_id_for_run(db: Session, workflow_run: WorkflowRun):
        deployment = (
            db.query(WorkflowDeployment)
            .filter(WorkflowDeployment.id == workflow_run.deployment_id)
            .first()
        )
        if deployment is None:
            return None
        app = db.query(App).filter(App.id == deployment.app_id).first()
        return app.organization_id if app is not None else None

    @classmethod
    def record_completed_deployed_run(
        cls,
        db: Session,
        *,
        workflow_run_id: str | uuid.UUID,
    ) -> list[uuid.UUID]:
        """완료된 배포 run의 auto-routing LLM node를 카운트하고 예약할 policy id를 반환한다."""
        workflow_run = (
            db.query(WorkflowRun)
            .filter(WorkflowRun.id == uuid.UUID(str(workflow_run_id)))
            .first()
        )
        if workflow_run is None or not ModelRoutingPolicyLifecycleService.is_eligible_operational_run(
            workflow_run
        ):
            return []

        deployment = (
            db.query(WorkflowDeployment)
            .filter(WorkflowDeployment.id == workflow_run.deployment_id)
            .first()
        )
        graph = deployment.graph_snapshot if deployment is not None else {}
        node_data_by_id = {
            str(node.get("id")): node.get("data")
            for node in (graph.get("nodes") or [])
            if isinstance(node, dict) and isinstance(node.get("data"), dict)
        }
        auto_routing_node_ids = {
            node_id
            for node_id, node_data in node_data_by_id.items()
            if bool(node_data.get("auto_model_routing"))
        }
        if not auto_routing_node_ids:
            return []
        node_runs = (
            db.query(WorkflowNodeRun)
            .filter(WorkflowNodeRun.workflow_run_id == workflow_run.id)
            .filter(WorkflowNodeRun.node_type == "llmNode")
            .filter(WorkflowNodeRun.node_id.in_(auto_routing_node_ids))
            .all()
        )
        node_runs_by_id = {str(node_run.node_id): node_run for node_run in node_runs}
        workflow_status = getattr(workflow_run.status, "value", workflow_run.status)
        if workflow_status == RunStatus.SUCCESS.value:
            pending_node_ids = {
                node_id
                for node_id in auto_routing_node_ids
                if node_id in node_runs_by_id
                and node_runs_by_id[node_id].status == NodeRunStatus.RUNNING
            }
            if pending_node_ids:
                raise ModelRoutingRunLogPendingError(
                    "auto-routing node completion logs are not ready"
                )

        successful_node_runs = [
            node_run
            for node_run in node_runs
            if node_run.status == NodeRunStatus.SUCCESS
        ]
        scheduled: list[uuid.UUID] = []
        for node_run in sorted(
            successful_node_runs,
            key=lambda item: str(item.node_id),
        ):
            node_data = node_data_by_id.get(node_run.node_id)
            if not isinstance(node_data, dict):
                continue
            if not bool(node_data.get("auto_model_routing")):
                # 현재 draft가 아니라 deployment snapshot을 기준으로 집계한다.
                # 자동 라우팅이 포함되지 않은 배포의 과거 run은 policy/event를 만들지 않는다.
                continue
            policy = cls.ensure_policy_for_deployed_node(
                db,
                workflow_run=workflow_run,
                node_id=node_run.node_id,
                node_data=node_data,
            )
            if policy is None:
                continue
            cls._record_adaptive_observation(
                db,
                policy=policy,
                workflow_run=workflow_run,
                node_run=node_run,
                node_data=node_data,
            )
            event_was_created = cls._record_policy_event(
                db,
                policy_id=policy.id,
                workflow_run_id=workflow_run.id,
            )
            # 동시 run은 event insert 뒤 같은 순서로 policy row를 잠근다. lock을
            # 얻은 시점의 최신 counter에만 event를 반영해 누락 갱신을 막는다.
            policy = cls._lock_policy_for_update(db, policy_id=policy.id)
            if policy is None:
                continue
            outcome = ModelRoutingPolicyLifecycleService.apply_run_event(
                policy,
                event_was_created=event_was_created,
            )
            if outcome.should_enqueue_refresh or (
                not event_was_created
                and ModelRoutingPolicyLifecycleService.has_pending_refresh_request(policy)
            ):
                scheduled.append(policy.id)
        db.flush()
        return scheduled

    @classmethod
    def _record_adaptive_observation(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        workflow_run: WorkflowRun,
        node_run: WorkflowNodeRun,
        node_data: dict[str, Any],
    ) -> None:
        """Embedding 실패가 운영 run 집계를 막지 않도록 관찰만 best-effort로 기록한다."""
        # 팀별 RAG 권한이 다른 배포에서는 정책 소유자가 아니라 이 요청을 실제로
        # 실행한 사용자의 권한으로 입력을 임베딩해야 관찰·Replay 경계가 일치한다.
        user_id = getattr(workflow_run, "user_id", None)
        if user_id is None or policy.organization_id is None:
            return
        try:
            embedding_models = LLMService.get_runtime_available_embedding_model_ids_for_user(
                db,
                user_id=user_id,
                organization_id=policy.organization_id,
            )
            if not embedding_models:
                return
            encoder_model_id = cls._preferred_embedding_model(
                node_data,
                embedding_models,
            )
            selection = LLMService.get_runtime_client_for_user(
                db,
                user_id=user_id,
                model_id=encoder_model_id,
                organization_id=policy.organization_id,
            )
            from apps.workflow_engine.services.model_routing_adaptive_store import (
                AdaptiveModelRoutingCohortStore,
            )

            AdaptiveModelRoutingCohortStore.record_observation(
                db,
                policy=policy,
                workflow_run=workflow_run,
                node_run=node_run,
                node_data=node_data,
                encoder_model_id=encoder_model_id,
                embed=selection.client.embed_sync,
            )
        except Exception as exc:
            logger.warning(
                "[Model-Routing] adaptive cohort observation skipped: error_type=%s",
                type(exc).__name__,
            )

    @staticmethod
    def _preferred_embedding_model(
        node_data: dict[str, Any],
        available_model_ids: list[str],
    ) -> str:
        context = node_data.get("model_routing_context")
        context = context if isinstance(context, dict) else {}
        semantic = context.get("semantic_router")
        semantic = semantic if isinstance(semantic, dict) else {}
        configured = str(semantic.get("encoder_model_id") or "").strip()
        if configured in available_model_ids:
            return configured
        return sorted(available_model_ids)[0]

    @staticmethod
    def _record_policy_event(
        db: Session,
        *,
        policy_id: uuid.UUID,
        workflow_run_id: uuid.UUID,
    ) -> bool:
        try:
            with db.begin_nested():
                db.add(
                    LLMNodeModelRoutingPolicyRunEvent(
                        policy_id=policy_id,
                        workflow_run_id=workflow_run_id,
                    )
                )
                db.flush()
            return True
        except IntegrityError:
            return False
