"""배포된 자동 모델 라우팅 정책을 기록 없이 평가하는 read-only service."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from apps.shared.db.models.model_routing_policy import LLMNodeModelRoutingPolicy
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_deployment import WorkflowDeployment
from apps.shared.services.node_config_fingerprint import llm_node_config_fingerprint
from apps.workflow_engine.services.llm_service import LLMService as WorkflowRuntimeLLMService
from apps.workflow_engine.services.model_router import (
    ModelRouter,
    ModelRoutingUnavailableError,
)
from apps.workflow_engine.workflow.nodes.llm.entities import LLMNodeData


class ModelRoutingPreviewBlockedError(ValueError):
    """미리보기는 요청을 처리했지만, 현재 정책으로 모델을 고를 수 없는 상태."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ModelRoutingPreviewService:
    """실제 deployment runtime과 같은 policy evaluator를 재사용한다.

    이 service는 policy/run/usage를 변경하거나 Celery task를 발행하지 않는다.
    semantic cohort가 있는 policy에 한해 input embedding을 한 번 계산할 수 있지만,
    LLM completion을 실행하거나 raw input을 저장하지 않는다.
    """

    @classmethod
    def preview(
        cls,
        db: Session,
        *,
        workflow: Workflow,
        deployment: WorkflowDeployment,
        node_id: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        deployed_node = cls._find_llm_node(deployment.graph_snapshot, node_id)
        deployed_node_data = cls._node_data(deployed_node)
        if not bool(deployed_node_data.get("auto_model_routing")):
            raise ModelRoutingPreviewBlockedError("model_routing.disabled")

        policy = cls._load_policy(
            db,
            workflow_id=workflow.id,
            deployment_id=deployment.id,
            node_id=node_id,
        )
        if (
            policy is None
            or not policy.enabled
            or not isinstance(policy.active_policy, dict)
            or not policy.active_policy
        ):
            raise ModelRoutingPreviewBlockedError("model_routing.policy_not_ready")

        subject_id = policy.execution_subject_user_id
        organization_id = policy.organization_id or getattr(workflow, "organization_id", None)
        if subject_id is None or organization_id is None:
            raise ModelRoutingPreviewBlockedError(
                "model_routing.execution_subject_unavailable"
            )

        # 배포 runtime과 같은 execution subject 권한으로 제한한다. 현재 로그인
        # 사용자의 권한을 쓰면 webhook/app 실행의 실제 결과와 달라질 수 있다.
        available_model_ids = (
            WorkflowRuntimeLLMService.get_runtime_available_model_ids_for_user(
                db,
                user_id=subject_id,
                organization_id=organization_id,
            )
        )
        node_data = LLMNodeData.model_validate(deployed_node_data)
        policy_payload = {
            "policy_id": str(policy.id),
            "policy_version": policy.policy_version,
            "active_policy": policy.active_policy,
        }
        semantic_query_vector, semantic_evaluation = cls._semantic_query_vector(
            db,
            policy=policy,
            policy_payload=policy_payload,
            inputs=inputs,
            organization_id=organization_id,
            subject_id=subject_id,
        )
        try:
            decision = ModelRouter.resolve_policy(
                policy_payload,
                inputs=inputs,
                node_data=node_data,
                available_model_ids=available_model_ids,
                semantic_query_vector=semantic_query_vector,
            )
        except ModelRoutingUnavailableError as exc:
            raise ModelRoutingPreviewBlockedError(
                "model_routing.no_available_model"
            ) from exc

        active_policy = policy.active_policy
        configured_default_model = cls._model_id(active_policy.get("default_model_id"))
        configured_fallback_model = cls._model_id(active_policy.get("fallback_model_id"))
        decision_source = "matched_rule" if decision.matched_rule_id else "default_model"
        availability = "available"
        if (
            decision.matched_rule_id is None
            and configured_default_model
            and ModelRouter.normalize_model_id(decision.selected_model_id)
            != ModelRouter.normalize_model_id(configured_default_model)
        ):
            decision_source = "fallback_model"
            availability = "fallback"

        semantic_match = decision.semantic_match
        matched_cohort = None
        if semantic_match is not None and semantic_match.status == "matched":
            matched_cohort = {
                "id": semantic_match.cohort_id,
                "label": semantic_match.label,
            }

        return {
            "deployment_version": deployment.version,
            "policy_version": policy.policy_version,
            "decision_source": decision_source,
            "selected_model_id": decision.selected_model_id,
            "fallback_model_id": decision.fallback_model_id,
            "default_model_id": configured_default_model,
            "configured_fallback_model_id": configured_fallback_model,
            "matched_cohort": matched_cohort,
            "matched_rule_id": decision.matched_rule_id,
            "reason_code": decision.reason_code,
            "availability": availability,
            "semantic_evaluation": semantic_evaluation,
            "draft_matches_deployment": cls._draft_matches_deployment(
                workflow, node_id, deployed_node_data
            ),
        }

    @staticmethod
    def _load_policy(
        db: Session,
        *,
        workflow_id: Any,
        deployment_id: Any,
        node_id: str,
    ) -> LLMNodeModelRoutingPolicy | None:
        return (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.workflow_id == workflow_id)
            .filter(LLMNodeModelRoutingPolicy.deployment_id == deployment_id)
            .filter(LLMNodeModelRoutingPolicy.node_id == node_id)
            .first()
        )

    @staticmethod
    def _find_llm_node(graph: Any, node_id: str) -> dict[str, Any]:
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        for node in nodes if isinstance(nodes, list) else []:
            if isinstance(node, dict) and node.get("id") == node_id:
                if node.get("type") != "llmNode":
                    break
                return node
        raise ModelRoutingPreviewBlockedError("model_routing.deployed_node_not_found")

    @staticmethod
    def _node_data(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data")
        if not isinstance(data, dict):
            raise ModelRoutingPreviewBlockedError("model_routing.deployed_node_invalid")
        return data

    @classmethod
    def _semantic_query_vector(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        policy_payload: dict[str, Any],
        inputs: dict[str, Any],
        organization_id: Any,
        subject_id: Any,
    ) -> tuple[tuple[float, ...] | None, str]:
        active_policy = policy_payload.get("active_policy")
        semantic_router = (
            active_policy.get("semantic_router")
            if isinstance(active_policy, dict)
            else None
        )
        if not isinstance(semantic_router, dict) or not semantic_router:
            return None, "not_required"

        encoder = semantic_router.get("encoder")
        encoder_model_id = semantic_router.get("encoder_model_id")
        if not encoder_model_id and isinstance(encoder, dict):
            encoder_model_id = encoder.get("model_id")
        encoder_model_id = cls._model_id(encoder_model_id)
        query_text = ModelRouter.semantic_query_text(inputs, semantic_router)
        if not encoder_model_id or not query_text:
            return None, "unavailable"

        try:
            runtime = WorkflowRuntimeLLMService.get_runtime_client_for_user(
                db,
                user_id=subject_id,
                model_id=encoder_model_id,
                organization_id=organization_id,
            )
            vector = runtime.client.embed_sync(query_text)
            if not isinstance(vector, (list, tuple)) or not vector:
                return None, "unavailable"
            return tuple(float(value) for value in vector), "embedding_used"
        except Exception:
            # embedding provider/credential 문제는 preview 자체를 실패시키지 않는다.
            # runtime과 같이 semantic route 없이 안전한 default rule을 평가한다.
            return None, "unavailable"

    @classmethod
    def _draft_matches_deployment(
        cls,
        workflow: Workflow,
        node_id: str,
        deployed_node_data: dict[str, Any],
    ) -> bool:
        draft_graph = getattr(workflow, "graph", None)
        try:
            draft_node = cls._find_llm_node(draft_graph, node_id)
            draft_node_data = cls._node_data(draft_node)
        except ModelRoutingPreviewBlockedError:
            return False
        return llm_node_config_fingerprint(
            draft_node_data
        ) == llm_node_config_fingerprint(deployed_node_data)

    @staticmethod
    def _model_id(value: Any) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None
