"""모델 라우팅 policy의 DB persistence와 배포 run 완료 훅을 담당한다."""

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.shared.db.models.model_routing_policy import (
    LLMNodeModelRoutingPolicy,
    LLMNodeModelRoutingPolicyRunEvent,
)
from apps.shared.db.models.app import App
from apps.shared.db.models.workflow_deployment import WorkflowDeployment
from apps.shared.db.models.workflow_run import NodeRunStatus, WorkflowNodeRun, WorkflowRun
from apps.workflow_engine.services.model_routing_policy_lifecycle import (
    ModelRoutingPolicyLifecycleService,
)
from apps.workflow_engine.services.model_routing_policy_refresh import (
    ModelRoutingPolicyRefreshService,
)


class ModelRoutingPolicyStore:
    """정책 row 조회와 운영 run 누적을 한 곳에서 일관되게 처리한다."""

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
    def _legacy_active_policy(node_data: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        policy = node_data.get("model_routing_policy")
        if not isinstance(policy, dict):
            return {}, None
        active_policy = policy.get("active_policy")
        if not isinstance(active_policy, dict):
            return {}, None
        return active_policy, str(policy.get("policy_version") or "") or None

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
            return policy

        policy_id = uuid.uuid4()
        organization_id = cls._organization_id_for_run(db, workflow_run)
        active_policy, policy_version = cls._legacy_active_policy(node_data)
        refresh_every_runs = cls._refresh_every_runs(node_data)
        if not active_policy:
            configured_model_id = str(node_data.get("model_id") or "").strip()
            if not configured_model_id:
                # 실행 모델이 없는 잘못된 deployment snapshot은 policy를 만들지 않는다.
                # 이후 runtime도 저장 모델을 임의로 추정하지 않고 기존 validation 경로에서 막는다.
                return None
            bootstrap = ModelRoutingPolicyRefreshService.default_rule_policy(
                policy_id=str(policy_id),
                policy_version="bootstrap-preserve-config-v1",
                default_model_id=configured_model_id,
                fallback_model_id=node_data.get("fallback_model_id"),
                refresh_every_runs=refresh_every_runs,
            )
            active_policy = bootstrap["active_policy"]
            policy_version = bootstrap["policy_version"]

        policy = LLMNodeModelRoutingPolicy(
            id=policy_id,
            organization_id=organization_id,
            workflow_id=workflow_run.workflow_id,
            deployment_id=workflow_run.deployment_id,
            node_id=node_id,
            enabled=True,
            status="collecting",
            policy_version=policy_version,
            active_policy=active_policy,
            refresh_every_runs=refresh_every_runs,
            judge_user_id=workflow_run.user_id,
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
        node_runs = (
            db.query(WorkflowNodeRun)
            .filter(WorkflowNodeRun.workflow_run_id == workflow_run.id)
            .filter(WorkflowNodeRun.node_type == "llmNode")
            .filter(WorkflowNodeRun.status == NodeRunStatus.SUCCESS)
            .all()
        )
        scheduled: list[uuid.UUID] = []
        for node_run in node_runs:
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
            event_was_created = cls._record_policy_event(
                db,
                policy_id=policy.id,
                workflow_run_id=workflow_run.id,
            )
            outcome = ModelRoutingPolicyLifecycleService.apply_run_event(
                policy,
                event_was_created=event_was_created,
            )
            if outcome.should_enqueue_refresh:
                scheduled.append(policy.id)
        db.flush()
        return scheduled

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
