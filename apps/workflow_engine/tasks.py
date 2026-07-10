"""
Workflow-Engine Celery 태스크 정의
워크플로우 실행을 비동기적으로 처리

[GEVENT] WorkflowEngine이 동기화되어 asyncio가 더 이상 필요하지 않음.
"""

import logging
import uuid
from typing import Any, Dict

from apps.shared.celery_app import celery_app
from apps.shared.db.session import SessionLocal
from apps.shared.domain.deployment_runtime_policy import (
    DeploymentRuntimePolicy,
    is_deployment_type_allowed_for_trigger,
)
from apps.workflow_engine.runtime_policy import get_deployment_runtime_policy
from apps.workflow_engine.workflow.errors import NonRetryableWorkflowError

logger = logging.getLogger(__name__)

_DEPLOYMENT_CONTEXT_PASSTHROUGH_KEYS = frozenset(
    {
        "conversation_id",
        "correlation_id",
        "request_id",
        "trace_metadata",
        "trigger_mode",
        "workflow_task_id",
    }
)


@celery_app.task(name="workflow.model_routing.record_run", bind=True, max_retries=3)
def record_model_routing_operational_run(self, workflow_run_id: str):
    """완료된 LLM node run을 정책 갱신 카운터에 반영하고 필요할 때만 refresh task를 예약한다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    session = SessionLocal()
    try:
        policy_ids = ModelRoutingPolicyStore.record_completed_deployed_run(
            session,
            workflow_run_id=workflow_run_id,
        )
        session.commit()
        for policy_id in policy_ids:
            celery_app.send_task(
                "workflow.model_routing.refresh_policy",
                args=[str(policy_id), "auto_n_runs"],
            )
        return {"status": "success", "scheduled_policy_ids": [str(item) for item in policy_ids]}
    except Exception as exc:
        session.rollback()
        logger.error("[Model-Routing] run event record failed: %s", exc)
        raise self.retry(exc=exc, countdown=min(2 ** (self.request.retries + 1), 30))
    finally:
        session.close()


@celery_app.task(name="workflow.model_routing.refresh_policy", bind=True, max_retries=2)
def refresh_model_routing_policy(self, policy_id: str, trigger: str = "manual_refresh"):
    """Judge를 한 번 호출해 persisted policy rule set만 갱신한다. runtime에서는 호출하지 않는다."""
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    session = SessionLocal()
    try:
        if trigger == "auto_n_runs":
            from apps.workflow_engine.services.model_routing_policy_store import (
                ModelRoutingPolicyStore,
            )

            if (
                ModelRoutingPolicyStore.claim_pending_auto_refresh(
                    session,
                    policy_id=policy_id,
                )
                is None
            ):
                session.rollback()
                return {"status": "skipped", "update_id": None, "result": None}
        update = PersistedModelRoutingPolicyRefreshService.refresh(
            session,
            policy_id=policy_id,
            trigger=trigger,
        )
        session.commit()
        return {
            "status": "success" if update is not None else "not_found",
            "update_id": str(update.id) if update is not None else None,
            "result": update.status if update is not None else None,
        }
    except Exception as exc:
        session.rollback()
        logger.error("[Model-Routing] policy refresh failed: %s", exc)
        raise self.retry(exc=exc, countdown=min(2 ** (self.request.retries + 1), 30))
    finally:
        session.close()


def _sync_skipped_result(reason: str) -> Dict[str, Any]:
    """Knowledge sync를 실행하지 않았음을 task 응답에 안전하게 표시한다."""
    return {
        "synced_count": 0,
        "failed": [],
        "skipped": True,
        "reason": reason,
    }


def _resolve_user_execution_subject_id(
    execution_context: Dict[str, Any],
) -> uuid.UUID | None:
    """Private/source-backed Knowledge sync에 사용할 user execution_subject만 해석한다."""
    subject = execution_context.get("execution_subject")
    if not isinstance(subject, dict):
        return None

    subject_type = subject.get("subject_type") or subject.get("type") or "user"
    if subject_type != "user":
        return None

    subject_id = subject.get("subject_id") or subject.get("id")
    try:
        return uuid.UUID(str(subject_id))
    except (TypeError, ValueError):
        return None


def _sync_knowledge_bases_for_execution_subject(
    session,
    graph: Dict[str, Any],
    execution_context: Dict[str, Any],
) -> Dict[str, Any]:
    # Anonymous public-only RAG는 이미 색인된 public KB만 검색한다.
    # Private/source-backed sync에는 명시적인 user execution_subject가 필요하며,
    # workflow owner/app creator/user_id를 데이터 접근 주체로 대체하지 않는다.
    subject_id = _resolve_user_execution_subject_id(execution_context)
    if subject_id is None:
        return _sync_skipped_result("anonymous_public_only")

    from apps.workflow_engine.services.sync_service import SyncService

    syncer = SyncService(
        db=session,
        user_id=subject_id,
        organization_id=execution_context.get("organization_id"),
    )
    return syncer.sync_knowledge_bases(graph)


class PermanentDeploymentExecutionError(ValueError):
    """Non-retryable deployment runtime contract violation."""


def _deployment_type_allowed_for_trigger(
    deployment_type: Any,
    trigger_mode: Any,
    *,
    runtime_policy: DeploymentRuntimePolicy,
) -> bool:
    return is_deployment_type_allowed_for_trigger(
        deployment_type,
        trigger_mode,
        policy=runtime_policy,
    )


def _canonical_deployment_execution_context(
    queued_context: Dict[str, Any],
    *,
    deployment: Any,
    app: Any,
) -> Dict[str, Any]:
    """Rebuild tenant/resource identity from canonical deployment rows."""
    context = {
        key: queued_context[key]
        for key in _DEPLOYMENT_CONTEXT_PASSTHROUGH_KEYS
        if key in queued_context
    }
    canonical_user_id = getattr(app, "created_by", None) or getattr(
        deployment, "created_by", None
    )
    context.update(
        {
            "user_id": str(canonical_user_id) if canonical_user_id else None,
            "workflow_id": str(app.workflow_id) if app.workflow_id else None,
            "organization_id": (
                str(app.organization_id) if app.organization_id else None
            ),
            "app_id": str(deployment.app_id),
            "deployment_id": str(deployment.id),
            "workflow_version": deployment.version,
        }
    )
    return context


@celery_app.task(name="workflow.execute", bind=True, max_retries=3)
def execute_workflow(
    self,
    graph: Dict[str, Any],
    user_input: Dict[str, Any],
    execution_context: Dict[str, Any],
    is_deployed: bool = False,
):
    """
    워크플로우 비동기 실행

    [GEVENT] WorkflowEngine이 동기화되어 단순화됨.

    Args:
        graph: 워크플로우 그래프 데이터
        user_input: 사용자 입력
        execution_context: 실행 컨텍스트
        is_deployed: 배포 모드 여부

    Returns:
        워크플로우 실행 결과
    """
    from apps.workflow_engine.workflow.core.workflow_engine import WorkflowEngine

    session = SessionLocal()
    engine = None
    sync_result = {}

    try:
        # Knowledge Base 동기화
        try:
            sync_result = _sync_knowledge_bases_for_execution_subject(
                session,
                graph,
                execution_context,
            )
        except Exception as e:
            logger.error(f"[Workflow-Engine] 동기화 훅 실패: {e}")

        engine = WorkflowEngine(
            graph=graph,
            user_input=user_input,
            execution_context=execution_context,
            is_deployed=is_deployed,
            db=session,
        )

        # [GEVENT] 직접 동기 호출 - asyncio 불필요
        result = engine.execute()
        return {"status": "success", "result": result, "sync_status": sync_result}

    except NonRetryableWorkflowError as e:
        logger.error(f"[Workflow-Engine] execute_workflow 정책 차단: {e}")
        raise
    except Exception as e:
        logger.error(f"[Workflow-Engine] execute_workflow 실패: {e}")
        raise self.retry(exc=Exception(str(e)), countdown=2**self.request.retries)
    finally:
        if engine is not None:
            engine.cleanup()
        session.close()


@celery_app.task(name="workflow.execute_deployed", bind=True, max_retries=3)
def execute_deployed_workflow(
    self,
    workflow_id: str,
    user_input: Dict[str, Any],
    execution_context: Dict[str, Any],
):
    """
    배포된 워크플로우 실행

    [GEVENT] WorkflowEngine이 동기화되어 단순화됨.
    """
    from apps.shared.db.models.app import App
    from apps.shared.db.models.workflow_deployment import WorkflowDeployment
    from apps.workflow_engine.workflow.core.workflow_engine import WorkflowEngine

    session = SessionLocal()
    engine = None

    try:
        deployment = (
            session.query(WorkflowDeployment)
            .filter(WorkflowDeployment.workflow_id == workflow_id)
            .filter(WorkflowDeployment.is_active.is_(True))
            .first()
        )

        if not deployment:
            raise ValueError(f"배포된 워크플로우를 찾을 수 없습니다: {workflow_id}")

        graph = deployment.graph_data
        app = session.query(App).filter(App.id == deployment.app_id).first()
        execution_context["workflow_id"] = workflow_id
        execution_context["app_id"] = str(deployment.app_id)
        execution_context["deployment_id"] = str(deployment.id)
        execution_context["workflow_version"] = deployment.version
        if app and not execution_context.get("organization_id"):
            execution_context["organization_id"] = (
                str(app.organization_id) if app.organization_id else None
            )

        sync_result = {}
        try:
            sync_result = _sync_knowledge_bases_for_execution_subject(
                session,
                graph,
                execution_context,
            )
        except Exception as e:
            logger.error(f"[Workflow-Engine] 동기화 훅 실패: {e}")

        engine = WorkflowEngine(
            graph=graph,
            user_input=user_input,
            execution_context=execution_context,
            is_deployed=True,
            db=session,
        )

        # [GEVENT] 직접 동기 호출
        result = engine.execute()
        return {"status": "success", "result": result, "sync_status": sync_result}

    except NonRetryableWorkflowError as e:
        logger.error(f"[Workflow-Engine] execute_deployed_workflow 정책 차단: {e}")
        raise
    except Exception as e:
        logger.error(f"[Workflow-Engine] execute_deployed_workflow 실패: {e}")
        raise self.retry(exc=Exception(str(e)), countdown=2**self.request.retries)
    finally:
        if engine is not None:
            engine.cleanup()
        session.close()


@celery_app.task(name="workflow.execute_by_deployment", bind=True, max_retries=3)
def execute_by_deployment(
    self,
    deployment_id: str,
    user_input: Dict[str, Any],
    execution_context: Dict[str, Any],
):
    """
    배포 ID를 기반으로 워크플로우 실행 (Webhook 등에서 사용)

    [GEVENT] WorkflowEngine이 동기화되어 단순화됨.
    """
    from apps.shared.db.models.app import App
    from apps.shared.db.models.workflow_deployment import (
        DeploymentType,
        WorkflowDeployment,
    )
    from apps.workflow_engine.workflow.core.workflow_engine import WorkflowEngine

    session = SessionLocal()
    engine = None

    try:
        if not isinstance(execution_context, dict):
            raise PermanentDeploymentExecutionError("실행 컨텍스트 형식이 올바르지 않습니다")
        queued_context = dict(execution_context)

        deployment = (
            session.query(WorkflowDeployment)
            .filter(WorkflowDeployment.id == deployment_id)
            .first()
        )

        if not deployment:
            raise PermanentDeploymentExecutionError(
                f"배포를 찾을 수 없습니다: {deployment_id}"
            )

        if not deployment.graph_snapshot:
            raise PermanentDeploymentExecutionError(
                f"배포 그래프 데이터가 없습니다: {deployment_id}"
            )

        app = session.query(App).filter(App.id == deployment.app_id).first()
        if not app:
            raise PermanentDeploymentExecutionError(
                f"배포 앱을 찾을 수 없습니다: {deployment_id}"
            )
        if not getattr(deployment, "is_active", False):
            raise PermanentDeploymentExecutionError(
                f"비활성 배포는 실행할 수 없습니다: {deployment_id}"
            )
        if str(getattr(app, "active_deployment_id", "")) != str(deployment.id):
            raise PermanentDeploymentExecutionError(
                f"현재 활성 배포가 아닙니다: {deployment_id}"
            )
        if deployment.type == DeploymentType.WORKFLOW_NODE:
            raise PermanentDeploymentExecutionError(
                f"workflow_node 배포는 직접 실행할 수 없습니다: {deployment_id}"
            )
        if not _deployment_type_allowed_for_trigger(
            deployment.type,
            queued_context.get("trigger_mode"),
            runtime_policy=get_deployment_runtime_policy(),
        ):
            raise PermanentDeploymentExecutionError(
                f"배포 타입과 실행 트리거가 일치하지 않습니다: {deployment_id}"
            )

        execution_context = _canonical_deployment_execution_context(
            queued_context,
            deployment=deployment,
            app=app,
        )

        sync_result = {}
        try:
            sync_result = _sync_knowledge_bases_for_execution_subject(
                session,
                deployment.graph_snapshot,
                execution_context,
            )
        except Exception as e:
            logger.error(f"[Workflow-Engine] 동기화 훅 실패: {e}")

        engine = WorkflowEngine(
            graph=deployment.graph_snapshot,
            user_input=user_input,
            execution_context=execution_context,
            is_deployed=True,
            db=session,
        )

        # [GEVENT] 직접 동기 호출
        result = engine.execute()
        return {"status": "success", "result": result, "sync_status": sync_result}

    except (PermanentDeploymentExecutionError, NonRetryableWorkflowError) as e:
        logger.error(f"[Workflow-Engine] execute_by_deployment 정책 차단: {e}")
        raise
    except Exception as e:
        logger.error(f"[Workflow-Engine] execute_by_deployment 실패: {e}")
        raise self.retry(exc=Exception(str(e)), countdown=2**self.request.retries)
    finally:
        if engine is not None:
            engine.cleanup()
        session.close()


@celery_app.task(name="workflow.stream", bind=True, max_retries=3)
def stream_workflow(
    self,
    graph: Dict[str, Any],
    user_input: Dict[str, Any],
    execution_context: Dict[str, Any],
    external_run_id: str,
):
    """
    워크플로우 스트리밍 실행 (외부에서 run_id 전달)

    [GEVENT] WorkflowEngine.execute_stream()이 이제 동기 제너레이터.
    """
    from apps.workflow_engine.workflow.core.workflow_engine import WorkflowEngine

    session = SessionLocal()
    engine = None

    try:
        execution_context["workflow_run_id"] = external_run_id

        sync_result = {}
        try:
            sync_result = _sync_knowledge_bases_for_execution_subject(
                session,
                graph,
                execution_context,
            )

            if sync_result.get("failed"):
                from apps.shared.pubsub import publish_workflow_event

                publish_workflow_event(external_run_id, "sync_warning", sync_result)

        except Exception as e:
            logger.error(f"[Workflow-Engine] 동기화 훅 실패: {e}")

        engine = WorkflowEngine(
            graph=graph,
            user_input=user_input,
            execution_context=execution_context,
            is_deployed=False,
            db=session,
        )

        # [GEVENT] 동기 제너레이터 사용
        final_result = {}
        for event in engine.execute_stream():
            if event.get("type") == "workflow_finish":
                final_result = event.get("data", {})
            elif event.get("type") == "error":
                event_data = event.get("data", {})
                error_message = event_data.get("message", "Unknown error")
                if event_data.get("non_retryable"):
                    raise NonRetryableWorkflowError(error_message)
                raise ValueError(error_message)

        return {"status": "success", "result": final_result, "sync_status": sync_result}

    except NonRetryableWorkflowError as e:
        logger.error(f"[Workflow-Engine] stream_workflow 정책 차단: {e}")
        from apps.shared.pubsub import publish_workflow_event

        publish_workflow_event(external_run_id, "error", {"message": str(e)})
        raise
    except Exception as e:
        logger.error(f"[Workflow-Engine] stream_workflow 실패: {e}")
        from apps.shared.pubsub import publish_workflow_event

        publish_workflow_event(external_run_id, "error", {"message": str(e)})
        raise self.retry(exc=Exception(str(e)), countdown=2**self.request.retries)
    finally:
        if engine is not None:
            engine.cleanup()
        session.close()
