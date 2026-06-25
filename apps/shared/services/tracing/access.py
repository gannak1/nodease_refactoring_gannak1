import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from apps.shared.db.models.app import App
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_deployment import WorkflowDeployment
from apps.shared.db.models.workflow_run import (
    TracePayloadAccessEvent,
    WorkflowRun,
)
from apps.shared.db.session import SessionLocal
from apps.shared.services.tracing.policy import TracePolicyService
from apps.shared.services.tracing.rbac import TraceRbacService
from sqlalchemy.orm import Session

VIEW_METADATA = "metadata"
VIEW_REDACTED = "redacted"
VIEW_RAW = "raw"
VALID_VIEW_LEVELS = {VIEW_METADATA, VIEW_REDACTED, VIEW_RAW}
PROMPT_COMPLETION_KINDS = {"prompt", "completion"}


def _same_uuid(left: Any, right: Any) -> bool:
    try:
        return uuid.UUID(str(left)) == uuid.UUID(str(right))
    except (TypeError, ValueError):
        return False


def _actor_user_ref(actor_user_id: Any) -> Optional[str]:
    try:
        value = str(uuid.UUID(str(actor_user_id)))
    except (TypeError, ValueError):
        return None
    # 사용자 삭제 후에도 감사 이벤트를 상관분석할 수 있도록 단방향 참조만 남깁니다.
    return hashlib.sha256(f"trace-actor:{value}".encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TraceAccessDecision:
    allowed: bool
    reason_code: str
    app_id: Optional[uuid.UUID] = None
    is_system_admin: bool = False
    is_app_owner: bool = False


class TraceAccessService:
    """향후 RBAC 연동을 위한 추적 접근 제어 경계."""

    @staticmethod
    def is_system_admin(db: Session, user: Any) -> bool:
        return TraceRbacService.is_system_admin(db, user)

    @staticmethod
    def resolve_trace_app_id(db: Session, run: WorkflowRun) -> Optional[uuid.UUID]:
        if run.app_id:
            return run.app_id

        workflow = db.query(Workflow).filter(Workflow.id == run.workflow_id).first()
        if workflow and workflow.app_id:
            return workflow.app_id

        if run.deployment_id:
            deployment = (
                db.query(WorkflowDeployment)
                .filter(WorkflowDeployment.id == run.deployment_id)
                .first()
            )
            if deployment and deployment.app_id:
                return deployment.app_id

        return None

    @staticmethod
    def is_app_owner(db: Session, app_id: Optional[uuid.UUID], user: Any) -> bool:
        if app_id is None or user is None:
            return False
        app = db.query(App).filter(App.id == app_id).first()
        return bool(app and _same_uuid(app.created_by, getattr(user, "id", None)))

    @staticmethod
    def check_trace_access(
        db: Session,
        run: WorkflowRun,
        user: Any,
        view_level: str = VIEW_METADATA,
        payload_kind: Optional[str] = None,
    ) -> TraceAccessDecision:
        if view_level not in VALID_VIEW_LEVELS:
            return TraceAccessDecision(False, "invalid_view_level")

        app_id = TraceAccessService.resolve_trace_app_id(db, run)
        visibility = TracePolicyService.resolve_visibility_policy(db, app_id=app_id)
        is_admin = TraceAccessService.is_system_admin(db, user)
        is_owner = TraceAccessService.is_app_owner(db, app_id, user)
        is_prompt_completion = payload_kind in PROMPT_COMPLETION_KINDS

        if is_admin:
            if view_level in {VIEW_METADATA, VIEW_REDACTED}:
                return TraceAccessDecision(True, "system_admin", app_id, True, is_owner)
            if not visibility.admin_raw_payload_access_enabled:
                return TraceAccessDecision(
                    False, "admin_raw_payload_access_disabled", app_id, True, is_owner
                )
            if is_prompt_completion and not visibility.admin_prompt_completion_access_enabled:
                return TraceAccessDecision(
                    False,
                    "admin_prompt_completion_access_disabled",
                    app_id,
                    True,
                    is_owner,
                )
            return TraceAccessDecision(True, "system_admin_raw", app_id, True, is_owner)

        if is_owner:
            if visibility.deny_owner_trace_access:
                return TraceAccessDecision(
                    False, "owner_trace_access_denied", app_id, False, True
                )
            if view_level == VIEW_METADATA:
                return TraceAccessDecision(
                    visibility.owner_trace_access_enabled,
                    "app_owner" if visibility.owner_trace_access_enabled else "owner_metadata_disabled",
                    app_id,
                    False,
                    True,
                )
            if view_level == VIEW_REDACTED:
                if is_prompt_completion and not visibility.owner_prompt_completion_access_enabled:
                    return TraceAccessDecision(
                        False,
                        "owner_prompt_completion_access_disabled",
                        app_id,
                        False,
                        True,
                    )
                return TraceAccessDecision(
                    visibility.owner_redacted_payload_access_enabled,
                    "app_owner_redacted"
                    if visibility.owner_redacted_payload_access_enabled
                    else "owner_redacted_payload_access_disabled",
                    app_id,
                    False,
                    True,
                )
            if is_prompt_completion and not visibility.owner_prompt_completion_access_enabled:
                return TraceAccessDecision(
                    False,
                    "owner_prompt_completion_access_disabled",
                    app_id,
                    False,
                    True,
                )
            return TraceAccessDecision(
                visibility.owner_raw_payload_access_enabled,
                "app_owner_raw"
                if visibility.owner_raw_payload_access_enabled
                else "owner_raw_payload_access_disabled",
                app_id,
                False,
                True,
            )

        return TraceAccessDecision(False, "regular_user_trace_access_denied", app_id)

    @staticmethod
    def record_payload_access_event(
        db: Session,
        workflow_run_id: Any,
        actor_user_id: Any,
        view_level: str,
        allowed: bool,
        reason_code: str,
        payload_id: Any = None,
    ) -> None:
        if view_level != VIEW_RAW:
            return
        # 원문 응답은 감사 기록과 분리될 수 없도록 독립 트랜잭션에 먼저 기록합니다.
        audit_db = SessionLocal()
        try:
            event = TracePayloadAccessEvent(
                payload_id=payload_id,
                workflow_run_id=workflow_run_id,
                actor_user_id=actor_user_id,
                actor_user_ref=_actor_user_ref(actor_user_id),
                view_level=view_level,
                allowed=allowed,
                reason_code=reason_code,
            )
            audit_db.add(event)
            audit_db.commit()
        except Exception:
            audit_db.rollback()
            raise
        finally:
            audit_db.close()
