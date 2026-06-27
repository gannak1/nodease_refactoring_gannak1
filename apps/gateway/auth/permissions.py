from typing import Any

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.shared.audit.actions import AuditAction
from apps.shared.audit.logger import record_audit
from apps.shared.db.models.llm import LLMCredential
from apps.shared.db.models.user import User
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.session import get_db
from apps.shared.services.permissions import (
    get_effective_llm_credential_auth_state,
    get_effective_workflow_auth_state,
    has_llm_credential_permission,
    has_workflow_permission,
)


def record_permission_denied(
    user: User,
    resource_type: str,
    resource_id: Any,
    action: str,
    effective_auth_state: str,
) -> None:
    record_audit(
        action=AuditAction.PERMISSION_DENIED,
        category="action",
        actor_id=user.id,
        actor_type="user",
        target_type=resource_type,
        target_id=resource_id,
        status="failure",
        metadata={
            "policy_result": "deny",
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "required_permission": action,
            "permission_action": action,
            "effective_auth_state": effective_auth_state,
        },
    )


def _permission_denied_exception() -> HTTPException:
    exc = HTTPException(status_code=403, detail="Forbidden")
    setattr(exc, "audit_recorded", True)
    return exc


def ensure_workflow_permission(
    db: Session,
    current_user: User,
    workflow_id: Any,
    action: str,
) -> Workflow:
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    effective_auth_state = get_effective_workflow_auth_state(
        db,
        current_user.id,
        workflow.id,
        organization_id=workflow.organization_id,
    )
    if not has_workflow_permission(
        db,
        current_user.id,
        workflow.id,
        action,
        organization_id=workflow.organization_id,
    ):
        record_permission_denied(
            current_user,
            "workflow",
            workflow.id,
            action,
            effective_auth_state,
        )
        raise _permission_denied_exception()
    return workflow


def ensure_llm_credential_permission(
    db: Session,
    current_user: User,
    credential_id: Any,
    action: str,
) -> LLMCredential:
    credential = (
        db.query(LLMCredential).filter(LLMCredential.id == credential_id).first()
    )
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    effective_auth_state = get_effective_llm_credential_auth_state(
        db,
        current_user.id,
        credential.id,
        organization_id=credential.organization_id,
    )
    if not has_llm_credential_permission(
        db,
        current_user.id,
        credential.id,
        action,
        organization_id=credential.organization_id,
    ):
        record_permission_denied(
            current_user,
            "llm_credential",
            credential.id,
            action,
            effective_auth_state,
        )
        raise _permission_denied_exception()
    return credential


def require_workflow_permission(action: str):
    def dependency(
        workflow_id: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> Workflow:
        return ensure_workflow_permission(db, current_user, workflow_id, action)

    return dependency


def require_llm_credential_permission(action: str):
    def dependency(
        credential_id: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> LLMCredential:
        return ensure_llm_credential_permission(
            db, current_user, credential_id, action
        )

    return dependency
