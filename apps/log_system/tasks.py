"""
Log System Celery 태스크

워크플로우 실행 로그를 DB에 저장하는 Celery 태스크들입니다.
기존 LogWorkerPool의 역할을 Celery 태스크로 대체합니다.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from apps.shared.audit.actions import AuditAction
from apps.shared.audit.logger import record_audit
from apps.shared.celery_app import celery_app
from apps.shared.db.models.app import App  # noqa: F401
from apps.shared.db.models.connection import Connection  # noqa: F401
from apps.shared.db.models.knowledge import (  # noqa: F401
    Document,
    DocumentChunk,
    KnowledgeBase,
    RAGAnswerRun,
)
from apps.shared.db.models.llm import (  # noqa: F401
    LLMCredential,
    LLMModel,
    LLMProvider,
    LLMRelCredentialModel,
    LLMUsageLog,
)
from apps.shared.db.models.schedule import Schedule  # noqa: F401

# SQLAlchemy 모델 relationship 초기화를 위해 모든 모델을 명시적으로 import
# 순서 중요: 의존성 순서대로 import해야 관계가 올바르게 초기화됨
from apps.shared.db.models.user import User  # noqa: F401
from apps.shared.db.models.workflow import Workflow  # noqa: F401
from apps.shared.db.models.workflow_deployment import WorkflowDeployment  # noqa: F401
from apps.shared.db.models.workflow_run import (
    NodeRunStatus,
    RunStatus,
    RunTriggerMode,
    TracePayload,
    WorkflowNodeRun,
    WorkflowRun,
)
from apps.shared.db.session import SessionLocal
from apps.shared.services.tracing.metadata import TraceMetadataSanitizer
from celery.exceptions import Retry
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


def _schedule_model_routing_run_record(node_run: WorkflowNodeRun) -> None:
    """LLM node 로그가 확정된 뒤에만 정책 run 집계를 별도 task로 넘긴다."""
    status = getattr(node_run.status, "value", node_run.status)
    if node_run.node_type != "llmNode" or status != NodeRunStatus.SUCCESS.value:
        return
    celery_app.send_task(
        "workflow.model_routing.record_run",
        args=[str(node_run.workflow_run_id)],
    )


def _serialize_uuid(obj):
    """UUID를 문자열로 변환 (JSON 직렬화용)"""
    if isinstance(obj, uuid.UUID):
        return str(obj)
    return obj


def _deserialize_uuid(value):
    """문자열을 UUID로 변환"""
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return value
    return value


def _deserialize_datetime(value):
    """ISO 문자열을 datetime으로 변환"""
    from datetime import datetime

    if isinstance(value, str):
        try:
            # ISO 형식 문자열을 datetime으로 변환
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def _resolve_app_id(session, workflow_id, deployment_id=None):
    if deployment_id:
        deployment = (
            session.query(WorkflowDeployment)
            .filter(WorkflowDeployment.id == deployment_id)
            .first()
        )
        if deployment and deployment.app_id:
            return deployment.app_id

    workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
    if workflow and workflow.app_id:
        return workflow.app_id
    return None


def _record_workflow_execute_audit(run_log, status, reason_code=None):
    metadata = {
        "policy_result": "allow",
        "workflow_run_id": str(run_log.id),
        "trigger_mode": run_log.trigger_mode.value
        if hasattr(run_log.trigger_mode, "value")
        else str(run_log.trigger_mode),
        "request_id": run_log.request_id,
        "correlation_id": run_log.correlation_id,
    }
    if reason_code:
        metadata["reason_code"] = reason_code
        metadata["error_present"] = bool(run_log.error_message)

    record_audit(
        action=AuditAction.WORKFLOW_EXECUTE,
        category="action",
        actor_id=run_log.user_id,
        actor_type="user",
        target_type="workflow",
        target_id=run_log.workflow_id,
        status=status,
        metadata=metadata,
    )


def _insert_trace_payloads(session, workflow_run_id, payload_records):
    for record in payload_records or []:
        payload_id = _deserialize_uuid(record.get("id"))
        if not payload_id:
            continue
        exists = session.query(TracePayload.id).filter(TracePayload.id == payload_id).first()
        if exists:
            continue
        # 페이로드 레코드는 마스킹/보관 정책이 적용된 봉투 구조만 저장합니다.
        payload = TracePayload(
            id=payload_id,
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=_deserialize_uuid(record.get("workflow_node_run_id"))
            if record.get("workflow_node_run_id")
            else None,
            scope=record.get("scope") or "trace",
            payload_kind=record.get("payload_kind") or "input",
            sequence=record.get("sequence"),
            attempt=record.get("attempt") or 1,
            redacted_payload=record.get("redacted_payload"),
            raw_payload_encrypted=record.get("raw_payload_encrypted"),
            redaction_applied=bool(record.get("redaction_applied")),
            pii_detected=bool(record.get("pii_detected")),
            secret_detected=bool(record.get("secret_detected")),
            redaction_metadata=record.get("redaction_metadata"),
            storage_mode=record.get("storage_mode") or "redacted_only",
            retention_expires_at=_deserialize_datetime(record.get("retention_expires_at"))
            if record.get("retention_expires_at")
            else None,
            created_at=_deserialize_datetime(record.get("created_at"))
            if record.get("created_at")
            else datetime.now(timezone.utc),
        )
        session.add(payload)


def _retry_waiting_for_workflow_run(task, workflow_run_id):
    raise task.retry(
        exc=Exception(f"Waiting for WorkflowRun: {workflow_run_id}"),
        countdown=1,
    )


@celery_app.task(name="log.create_run", bind=True, max_retries=3)
def create_run_log(self, data: Dict[str, Any]):
    """워크플로우 실행 로그 생성"""
    session = SessionLocal()
    run_id = None
    try:
        # 트리거 모드 정규화
        trigger_mode = data.get("trigger_mode")
        if isinstance(trigger_mode, str):
            trigger_mode = trigger_mode.strip().lower()

        trigger_mode_map = {
            "manual": RunTriggerMode.MANUAL,
            "api": RunTriggerMode.API,
            "app": RunTriggerMode.API,
            "deployed": RunTriggerMode.API,
        }

        normalized_trigger = None
        if isinstance(trigger_mode, RunTriggerMode):
            normalized_trigger = trigger_mode
        elif isinstance(trigger_mode, str):
            normalized_trigger = trigger_mode_map.get(trigger_mode)

        if normalized_trigger is None:
            normalized_trigger = (
                RunTriggerMode.API if data.get("is_deployed") else RunTriggerMode.MANUAL
            )

        # UUID 변환
        run_id = _deserialize_uuid(data["run_id"])
        workflow_id = _deserialize_uuid(data["workflow_id"])
        user_id = _deserialize_uuid(data["user_id"])
        deployment_id = (
            _deserialize_uuid(data.get("deployment_id"))
            if data.get("deployment_id")
            else None
        )
        app_id = (
            _deserialize_uuid(data.get("app_id"))
            if data.get("app_id")
            else _resolve_app_id(session, workflow_id, deployment_id)
        )

        run_log = WorkflowRun(
            id=run_id,
            workflow_id=workflow_id,
            app_id=app_id,
            user_id=user_id,
            status=RunStatus.RUNNING,
            trigger_mode=normalized_trigger,
            inputs=data.get("user_input") or {},
            started_at=_deserialize_datetime(data["started_at"]),
            deployment_id=deployment_id,
            workflow_version=data.get("workflow_version"),
            correlation_id=data.get("correlation_id"),
            conversation_id=data.get("conversation_id"),
            request_id=data.get("request_id"),
            workflow_task_id=data.get("workflow_task_id"),
            trace_metadata=TraceMetadataSanitizer.sanitize_run_metadata(
                data.get("trace_metadata") or {}
            ),
            redaction_applied=bool(data.get("redaction_applied")),
            pii_detected=bool(data.get("pii_detected")),
            redaction_policy_id=_deserialize_uuid(data.get("redaction_policy_id"))
            if data.get("redaction_policy_id")
            else None,
            retention_policy_id=_deserialize_uuid(data.get("retention_policy_id"))
            if data.get("retention_policy_id")
            else None,
            visibility_policy_id=_deserialize_uuid(data.get("visibility_policy_id"))
            if data.get("visibility_policy_id")
            else None,
            payload_storage_mode=data.get("payload_storage_mode") or "redacted_only",
        )
        session.add(run_log)
        session.flush()
        _insert_trace_payloads(session, run_id, data.get("trace_payloads") or [])
        session.commit()

        return {"status": "success", "run_id": str(run_id)}

    except IntegrityError as e:
        session.rollback()
        if run_id is not None:
            existing = (
                session.query(WorkflowRun.id).filter(WorkflowRun.id == run_id).first()
            )
            if existing:
                # 동일 run_id 재시도 시 중복 insert는 정상으로 간주합니다.
                return {"status": "success", "run_id": str(run_id)}
        raise self.retry(exc=e, countdown=2**self.request.retries)
    except Exception as e:
        session.rollback()
        logger.error(f"[Log-System] create_run_log 실패: {e}")
        raise self.retry(exc=e, countdown=2**self.request.retries)
    finally:
        session.close()


@celery_app.task(name="log.update_run_finish", bind=True, max_retries=3)
def update_run_log_finish(self, data: Dict[str, Any]):
    """워크플로우 실행 완료 로그 업데이트"""
    session = SessionLocal()
    try:
        run_id = _deserialize_uuid(data["run_id"])

        run_log = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()

        if not run_log:
            # 아직 생성되지 않은 경우 재시도
            raise Exception(f"WorkflowRun not found: {run_id}")

        run_log.status = RunStatus.SUCCESS
        run_log.outputs = data["outputs"]
        run_log.error_message = None
        run_log.redaction_applied = run_log.redaction_applied or bool(
            data.get("redaction_applied")
        )
        run_log.pii_detected = run_log.pii_detected or bool(data.get("pii_detected"))
        run_log.payload_storage_mode = (
            data.get("payload_storage_mode") or run_log.payload_storage_mode
        )
        finished_at = _deserialize_datetime(data["finished_at"])
        run_log.finished_at = finished_at

        if run_log.started_at and finished_at:
            run_log.duration = (finished_at - run_log.started_at).total_seconds()

        # 비용 및 토큰 집계
        stats = (
            session.query(
                func.sum(
                    LLMUsageLog.prompt_tokens + LLMUsageLog.completion_tokens
                ).label("total_tokens"),
                func.sum(LLMUsageLog.total_cost).label("total_cost"),
            )
            .filter(LLMUsageLog.workflow_run_id == run_id)
            .first()
        )

        if stats:
            run_log.total_tokens = stats.total_tokens or 0
            run_log.total_cost = stats.total_cost or 0.0

        _insert_trace_payloads(session, run_id, data.get("trace_payloads") or [])
        session.commit()
        _record_workflow_execute_audit(run_log, "success")

        return {"status": "success", "run_id": str(run_id)}

    except Exception as e:
        session.rollback()
        logger.error(f"[Log-System] update_run_log_finish 실패: {e}")
        raise self.retry(exc=e, countdown=2**self.request.retries)
    finally:
        session.close()


@celery_app.task(name="log.update_run_error", bind=True, max_retries=3)
def update_run_log_error(self, data: Dict[str, Any]):
    """워크플로우 실행 에러 로그 업데이트"""
    session = SessionLocal()
    try:
        run_id = _deserialize_uuid(data["run_id"])

        run_log = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()

        if not run_log:
            raise Exception(f"WorkflowRun not found: {run_id}")

        run_log.status = RunStatus.FAILED
        run_log.error_message = data["error_message"]
        finished_at = _deserialize_datetime(data["finished_at"])
        run_log.finished_at = finished_at

        if run_log.started_at and finished_at:
            run_log.duration = (finished_at - run_log.started_at).total_seconds()

        session.commit()
        _record_workflow_execute_audit(
            run_log, "failure", reason_code="workflow.execute_failed"
        )

        return {"status": "success", "run_id": str(run_id)}

    except Exception as e:
        session.rollback()
        logger.error(f"[Log-System] update_run_log_error 실패: {e}")
        raise self.retry(exc=e, countdown=2**self.request.retries)
    finally:
        session.close()


@celery_app.task(name="log.create_node", bind=True, max_retries=5)
def create_node_log(self, data: Dict[str, Any]):
    """노드 실행 로그 생성"""
    session = SessionLocal()
    try:
        workflow_run_id = _deserialize_uuid(data["workflow_run_id"])
        # 전달받은 ID 사용
        node_run_id = _deserialize_uuid(data.get("id"))

        # 세션 캐시 무효화 - 다른 Worker의 커밋 반영
        session.expire_all()

        # 부모 WorkflowRun이 존재하는지 확인
        run_exists = (
            session.query(WorkflowRun.id)
            .filter(WorkflowRun.id == workflow_run_id)
            .first()
        )

        if not run_exists:
            # [FIX] Race Condition: 부모(WorkflowRun)가 아직 생성되지 않음
            # 에러 로그 없이 조용히 재시도 (Quiet Retry)
            _retry_waiting_for_workflow_run(self, workflow_run_id)

        node_run = WorkflowNodeRun(
            id=node_run_id,  # [NEW] PK 지정
            workflow_run_id=workflow_run_id,
            node_id=data["node_id"],
            node_type=data["node_type"],
            status=NodeRunStatus.RUNNING,
            inputs=data.get("inputs") or {},
            process_data=data.get("process_data") or {},
            started_at=_deserialize_datetime(data["started_at"]),
            redaction_applied=bool(data.get("redaction_applied")),
            pii_detected=bool(data.get("pii_detected")),
            redaction_policy_id=_deserialize_uuid(data.get("redaction_policy_id"))
            if data.get("redaction_policy_id")
            else None,
            sequence=data.get("sequence"),
            retry_count=data.get("retry_count") or 0,
        )
        session.add(node_run)
        session.flush()
        _insert_trace_payloads(session, workflow_run_id, data.get("trace_payloads") or [])
        session.commit()

        return {"status": "success", "node_id": data["node_id"]}

    except IntegrityError as e:
        session.rollback()
        # [NEW] 중복 키 오류(이미 존재함)는 성공으로 간주 (Idempotency)
        # 이미 생성되었다면 생성 작업이 가진 입력 페이로드만 보존
        try:
            workflow_run_id = _deserialize_uuid(data["workflow_run_id"])
            node_run_id = _deserialize_uuid(data.get("id"))
            existing_node = (
                session.query(WorkflowNodeRun.id)
                .filter(WorkflowNodeRun.id == node_run_id)
                .first()
            )
            if not existing_node:
                raise e
            _insert_trace_payloads(
                session, workflow_run_id, data.get("trace_payloads") or []
            )
            session.commit()
        except Exception as payload_error:
            session.rollback()
            logger.error("[Log-System] create_node_log duplicate payload 보존 실패")
            raise self.retry(
                exc=payload_error, countdown=min(2 ** (self.request.retries + 1), 30)
            )
        return {"status": "success", "node_id": data["node_id"], "duplicated": True}
    except Retry:
        raise
    except Exception as e:
        session.rollback()
        logger.error(f"[Log-System] create_node_log 실패: {e}")
        # Retry 간격 최대 30초
        raise self.retry(exc=e, countdown=min(2 ** (self.request.retries + 1), 30))
    finally:
        session.close()


@celery_app.task(name="log.update_node_finish", bind=True, max_retries=5)
def update_node_log_finish(self, data: Dict[str, Any]):
    """노드 실행 완료 로그 업데이트 (Upsert 패턴 적용)"""
    session = SessionLocal()
    try:
        log_id = _deserialize_uuid(data.get("log_id"))
        workflow_run_id = _deserialize_uuid(data["workflow_run_id"])
        finished_at = _deserialize_datetime(data["finished_at"])

        # 세션 캐시 무효화 - 다른 Worker의 커밋 반영
        session.expire_all()

        # outputs 정규화
        outputs = data["outputs"]
        if not isinstance(outputs, dict):
            outputs = {"result": outputs}

        node_run = None
        if log_id:
            node_run = (
                session.query(WorkflowNodeRun)
                .filter(WorkflowNodeRun.id == log_id)
                .first()
            )

        if not node_run:
            # [FIX] Upsert: 레코드가 없으면 직접 생성 (Race Condition 해결)
            # finish가 create보다 먼저 도착한 경우
            started_at = _deserialize_datetime(data.get("started_at")) or finished_at

            # [FIX] 부모 WorkflowRun 존재 확인 - 없으면 Quiet Retry
            # NodeRun을 생성하려면 부모가 반드시 있어야 함 (FK 제약)
            run_exists = (
                session.query(WorkflowRun.id)
                .filter(WorkflowRun.id == workflow_run_id)
                .first()
            )
            if not run_exists:
                _retry_waiting_for_workflow_run(self, workflow_run_id)

            node_run = WorkflowNodeRun(
                id=log_id,
                workflow_run_id=workflow_run_id,
                node_id=data["node_id"],
                node_type=data.get("node_type", "unknown"),
                status=NodeRunStatus.SUCCESS,
                inputs=data.get("inputs") or {},
                process_data=data.get("process_data") or {},
                outputs=outputs,
                started_at=started_at,
                finished_at=finished_at,
                duration=data.get("duration")
                if data.get("duration") is not None
                else (finished_at - started_at).total_seconds()
                if started_at and finished_at
                else None,
                trace_metadata=TraceMetadataSanitizer.sanitize_span_metadata(
                    data.get("node_type", "unknown"),
                    data.get("trace_metadata") or {},
                ),
                redaction_applied=bool(data.get("redaction_applied")),
                pii_detected=bool(data.get("pii_detected")),
                sequence=data.get("sequence"),
                retry_count=data.get("retry_count") or 0,
            )
            session.add(node_run)
            logger.info(f"[Log-System] Upsert: 노드 로그 직접 생성 (log_id={log_id})")
        else:
            # 레코드가 있으면 업데이트
            node_run.status = NodeRunStatus.SUCCESS
            node_run.outputs = outputs
            node_run.finished_at = finished_at
            node_run.duration = data.get("duration") or (
                (finished_at - node_run.started_at).total_seconds()
                if node_run.started_at and finished_at
                else node_run.duration
            )
            sanitized_metadata = TraceMetadataSanitizer.sanitize_span_metadata(
                data.get("node_type") or node_run.node_type,
                data.get("trace_metadata") or {},
            )
            node_run.trace_metadata = sanitized_metadata or node_run.trace_metadata
            node_run.redaction_applied = node_run.redaction_applied or bool(
                data.get("redaction_applied")
            )
            node_run.pii_detected = node_run.pii_detected or bool(data.get("pii_detected"))
            node_run.sequence = node_run.sequence or data.get("sequence")
            node_run.retry_count = data.get("retry_count") or node_run.retry_count

        _insert_trace_payloads(session, workflow_run_id, data.get("trace_payloads") or [])
        session.commit()
        _schedule_model_routing_run_record(node_run)

        return {"status": "success", "node_id": data["node_id"]}

    except IntegrityError:
        session.rollback()
        # 중복 키 오류는 이미 처리됨을 의미 (Idempotency)
        logger.info(
            f"[Log-System] update_node_finish 중복 처리 무시: log_id={data.get('log_id')}"
        )
        return {"status": "success", "node_id": data["node_id"], "duplicated": True}
    except Retry:
        raise
    except Exception as e:
        session.rollback()
        logger.error(f"[Log-System] update_node_log_finish 실패: {e}")
        raise self.retry(exc=e, countdown=min(2**self.request.retries, 30))
    finally:
        session.close()


@celery_app.task(name="log.update_node_error", bind=True, max_retries=5)
def update_node_log_error(self, data: Dict[str, Any]):
    """노드 실행 에러 로그 업데이트 (Upsert 패턴 적용)"""
    session = SessionLocal()
    try:
        log_id = _deserialize_uuid(data.get("log_id"))
        workflow_run_id = _deserialize_uuid(data["workflow_run_id"])
        finished_at = _deserialize_datetime(data["finished_at"])

        # 세션 캐시 무효화 - 다른 Worker의 커밋 반영
        session.expire_all()

        node_run = None
        if log_id:
            node_run = (
                session.query(WorkflowNodeRun)
                .filter(WorkflowNodeRun.id == log_id)
                .first()
            )

        if not node_run:
            # [FIX] Upsert: 레코드가 없으면 직접 생성 (Race Condition 해결)
            # error가 create보다 먼저 도착한 경우
            started_at = _deserialize_datetime(data.get("started_at")) or finished_at

            # [FIX] 부모 WorkflowRun 존재 확인 - 없으면 Quiet Retry
            run_exists = (
                session.query(WorkflowRun.id)
                .filter(WorkflowRun.id == workflow_run_id)
                .first()
            )
            if not run_exists:
                _retry_waiting_for_workflow_run(self, workflow_run_id)

            node_run = WorkflowNodeRun(
                id=log_id,
                workflow_run_id=workflow_run_id,
                node_id=data["node_id"],
                node_type=data.get("node_type", "unknown"),
                status=NodeRunStatus.FAILED,
                inputs=data.get("inputs") or {},
                process_data=data.get("process_data") or {},
                error_message=data["error_message"],
                started_at=started_at,
                finished_at=finished_at,
                duration=data.get("duration")
                if data.get("duration") is not None
                else (finished_at - started_at).total_seconds()
                if started_at and finished_at
                else None,
                trace_metadata=TraceMetadataSanitizer.sanitize_span_metadata(
                    data.get("node_type", "unknown"),
                    data.get("trace_metadata") or {},
                ),
                sequence=data.get("sequence"),
                retry_count=data.get("retry_count") or 0,
            )
            session.add(node_run)
            logger.info(
                f"[Log-System] Upsert: 노드 에러 로그 직접 생성 (log_id={log_id})"
            )
        else:
            # 레코드가 있으면 업데이트
            node_run.status = NodeRunStatus.FAILED
            node_run.error_message = data["error_message"]
            node_run.finished_at = finished_at
            node_run.duration = data.get("duration") or (
                (finished_at - node_run.started_at).total_seconds()
                if node_run.started_at and finished_at
                else node_run.duration
            )
            sanitized_metadata = TraceMetadataSanitizer.sanitize_span_metadata(
                data.get("node_type") or node_run.node_type,
                data.get("trace_metadata") or {},
            )
            node_run.trace_metadata = sanitized_metadata or node_run.trace_metadata
            node_run.sequence = node_run.sequence or data.get("sequence")
            node_run.retry_count = data.get("retry_count") or node_run.retry_count

        session.commit()

        return {"status": "success", "node_id": data["node_id"]}

    except IntegrityError:
        session.rollback()
        # 중복 키 오류는 이미 처리됨을 의미 (Idempotency)
        logger.info(
            f"[Log-System] update_node_error 중복 처리 무시: log_id={data.get('log_id')}"
        )
        return {"status": "success", "node_id": data["node_id"], "duplicated": True}
    except Retry:
        raise
    except Exception as e:
        session.rollback()
        logger.error(f"[Log-System] update_node_log_error 실패: {e}")
        raise self.retry(exc=e, countdown=min(2**self.request.retries, 30))
    finally:
        session.close()


@celery_app.task(name="log.trace_retention_purge", bind=True, max_retries=3)
def trace_retention_purge(self, data: Dict[str, Any]):
    """보관 정책 기반 추적 정리 실행."""
    from apps.shared.services.tracing.retention import TraceRetentionService

    session = SessionLocal()
    try:
        result = TraceRetentionService.purge(
            session,
            scope_type=data.get("scope_type") or "global",
            scope_id=data.get("scope_id"),
            dry_run=bool(data.get("dry_run", True)),
            limit=int(data.get("limit") or 1000),
        )
        return {"status": "success", "result": result}
    except Exception as e:
        session.rollback()
        logger.error(f"[Log-System] trace_retention_purge 실패: {e}")
        raise self.retry(exc=e, countdown=2**self.request.retries)
    finally:
        session.close()


def _parse_rag_answer_purge_limit(data: Dict[str, Any]) -> int:
    from apps.shared.services.rag_answer_retention import (
        DEFAULT_RAG_ANSWER_PURGE_LIMIT,
        RAGAnswerRetentionService,
    )

    return RAGAnswerRetentionService.validate_limit(
        data.get("limit", DEFAULT_RAG_ANSWER_PURGE_LIMIT)
    )


@celery_app.task(name="log.rag_answer_retention_purge", bind=True, max_retries=3)
def rag_answer_retention_purge(self, data: Dict[str, Any]):
    """만료된 standalone RAG Agent answer run 정리 실행."""
    from apps.shared.services.rag_answer_retention import RAGAnswerRetentionService

    session = SessionLocal()
    try:
        organization_id = data.get("organization_id")
        limit = _parse_rag_answer_purge_limit(data)
        result = RAGAnswerRetentionService.purge(
            session,
            organization_id=uuid.UUID(organization_id) if organization_id else None,
            dry_run=bool(data.get("dry_run", False)),
            limit=limit,
        )
        return {"status": "success", "result": result}
    except ValueError:
        session.rollback()
        logger.warning("[Log-System] rag_answer_retention_purge invalid request")
        return {"status": "failed", "error": "invalid_rag_answer_purge_request"}
    except Exception as e:
        session.rollback()
        logger.error(f"[Log-System] rag_answer_retention_purge 실패: {e}")
        raise self.retry(exc=e, countdown=2**self.request.retries)
    finally:
        session.close()


@celery_app.task(name="log.knowledge_ingestion_outbox_process", bind=True, max_retries=3)
def knowledge_ingestion_outbox_process(self, data: Dict[str, Any]):
    """Knowledge ingestion outbox의 cleanup/recovery event를 idempotent하게 처리한다."""
    from apps.shared.services.knowledge_ingestion_outbox import (
        DEFAULT_OUTBOX_PROCESS_LIMIT,
        KnowledgeIngestionOutboxService,
    )
    from apps.shared.services.knowledge_ingestion_outbox_processor import (
        KnowledgeIngestionOutboxProcessor,
    )

    session = SessionLocal()
    owner_token = str(uuid.uuid4())
    try:
        processor = KnowledgeIngestionOutboxProcessor(session)
        result = processor.process_due_events(
            owner_token=owner_token,
            limit=KnowledgeIngestionOutboxService.validate_limit(
                data.get("limit") or DEFAULT_OUTBOX_PROCESS_LIMIT
            ),
        )
        session.commit()
        return {
            "status": "success",
            "processed_count": result.processed_count,
            "recovered_count": result.recovered_count,
        }
    except ValueError:
        session.rollback()
        logger.warning("[Log-System] knowledge_ingestion_outbox invalid request")
        return {"status": "failed", "error": "invalid_knowledge_outbox_request"}
    except Exception as e:
        session.rollback()
        logger.error(
            "[Log-System] knowledge_ingestion_outbox_process 실패: error_type=%s",
            type(e).__name__,
        )
        raise self.retry(exc=e, countdown=2**self.request.retries)
    finally:
        session.close()
