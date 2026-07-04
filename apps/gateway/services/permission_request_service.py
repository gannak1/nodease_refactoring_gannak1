import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from apps.shared.audit.actions import AuditAction
from apps.shared.db.models.audit_log import AuditLog
from apps.shared.db.models.organization_membership import (
    ORGANIZATION_MEMBERSHIP_ACTIVE,
    OrganizationMembership,
)
from apps.shared.db.models.permission_request import (
    PERMISSION_REQUEST_APPROVED,
    PERMISSION_REQUEST_PENDING,
    PERMISSION_REQUEST_REJECTED,
    REQUESTED_PERMISSION_APP_CREATE,
    PermissionRequest,
)
from apps.shared.db.models.user import User
from apps.shared.db.models.user_app_creation_permission import (
    UserAppCreationPermission,
)
from apps.shared.services import permissions as shared_permissions


def _add_audit(
    db: Session,
    action: str,
    actor_id: Any,
    target_type: str,
    target_id: Any,
) -> None:
    db.add(
        AuditLog(
            action=action,
            category="action",
            actor_id=actor_id,
            actor_type="user",
            target_type=target_type,
            target_id=str(target_id),
            status="success",
            audit_metadata={},
        )
    )


class PermissionRequestService:
    """권한 신청 제출/조회/승인/거절 (FR-041/FR-014, ADR-0014)."""

    @staticmethod
    def _get_request(db: Session, request_id: Any) -> Optional[PermissionRequest]:
        return (
            db.query(PermissionRequest)
            .filter(PermissionRequest.id == request_id)
            .first()
        )

    @staticmethod
    def ensure_request_processable(
        request: Optional[PermissionRequest],
        organization_id: Any,
    ) -> None:
        # scope 밖 신청은 존재를 숨긴다 (ADR-0010).
        if request is None or str(request.organization_id) != str(organization_id):
            raise HTTPException(
                status_code=404, detail="Permission request not found"
            )
        if request.status != PERMISSION_REQUEST_PENDING:
            raise HTTPException(
                status_code=409, detail="Permission request already processed"
            )

    @staticmethod
    def ensure_requester_is_active_member(
        db: Session,
        request: PermissionRequest,
    ) -> None:
        membership = (
            db.query(OrganizationMembership)
            .filter(
                OrganizationMembership.organization_id == request.organization_id,
                OrganizationMembership.user_id == request.user_id,
            )
            .first()
        )
        if (
            membership is None
            or membership.membership_state != ORGANIZATION_MEMBERSHIP_ACTIVE
        ):
            raise HTTPException(
                status_code=409, detail="Requester is not an active member"
            )
        user = db.query(User).filter(User.id == request.user_id).first()
        if user is None or user.deactivated_at is not None:
            raise HTTPException(
                status_code=409, detail="Requester is not an active member"
            )

    @staticmethod
    def grant_app_creation_permission(
        db: Session,
        request: PermissionRequest,
        decided_by: Any,
    ) -> UserAppCreationPermission:
        if request.requested_permission != REQUESTED_PERMISSION_APP_CREATE:
            raise HTTPException(
                status_code=400, detail="Unsupported requested permission"
            )
        existing = (
            db.query(UserAppCreationPermission)
            .filter(
                UserAppCreationPermission.grantee_organization_id
                == request.organization_id,
                UserAppCreationPermission.user_id == request.user_id,
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=409, detail="App creation permission already granted"
            )
        permission = UserAppCreationPermission(
            id=uuid.uuid4(),
            grantee_organization_id=request.organization_id,
            user_id=request.user_id,
            assigned_by=decided_by,
            assigned_at=datetime.now(timezone.utc),
        )
        db.add(permission)
        return permission

    @staticmethod
    def approve_request(
        db: Session,
        request_id: Any,
        organization_id: Any,
        decided_by: Any,
    ) -> PermissionRequest:
        request = PermissionRequestService._get_request(db, request_id)
        PermissionRequestService.ensure_request_processable(request, organization_id)
        PermissionRequestService.ensure_requester_is_active_member(db, request)
        permission = PermissionRequestService.grant_app_creation_permission(
            db, request, decided_by=decided_by
        )
        request.status = PERMISSION_REQUEST_APPROVED
        request.decided_by = decided_by
        request.decided_at = datetime.now(timezone.utc)
        _add_audit(
            db,
            AuditAction.PERMISSION_REQUEST_APPROVED,
            decided_by,
            "permission_request",
            request.id,
        )
        _add_audit(
            db,
            AuditAction.USER_APP_CREATION_PERMISSION_CREATED,
            decided_by,
            "user_app_creation_permission",
            permission.id,
        )
        db.commit()
        return request

    @staticmethod
    def reject_request(
        db: Session,
        request_id: Any,
        organization_id: Any,
        decided_by: Any,
    ) -> PermissionRequest:
        request = PermissionRequestService._get_request(db, request_id)
        PermissionRequestService.ensure_request_processable(request, organization_id)
        request.status = PERMISSION_REQUEST_REJECTED
        request.decided_by = decided_by
        request.decided_at = datetime.now(timezone.utc)
        _add_audit(
            db,
            AuditAction.PERMISSION_REQUEST_REJECTED,
            decided_by,
            "permission_request",
            request.id,
        )
        db.commit()
        return request

    @staticmethod
    def submit_request(
        db: Session,
        user: User,
        organization_id: Any,
        requested_permission: str,
        reason: str,
    ) -> PermissionRequest:
        if shared_permissions.has_app_creation_permission(
            db, user.id, organization_id
        ):
            raise HTTPException(
                status_code=409, detail="App creation permission already granted"
            )
        pending = (
            db.query(PermissionRequest)
            .filter(
                PermissionRequest.organization_id == organization_id,
                PermissionRequest.user_id == user.id,
                PermissionRequest.status == PERMISSION_REQUEST_PENDING,
            )
            .first()
        )
        if pending is not None:
            raise HTTPException(
                status_code=409, detail="Pending permission request already exists"
            )
        request = PermissionRequest(
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=user.id,
            requested_permission=requested_permission,
            reason=reason,
            status=PERMISSION_REQUEST_PENDING,
            created_at=datetime.now(timezone.utc),
        )
        db.add(request)
        _add_audit(
            db,
            AuditAction.PERMISSION_REQUEST_CREATED,
            user.id,
            "permission_request",
            request.id,
        )
        db.commit()
        db.refresh(request)
        return request

    @staticmethod
    def list_requests(
        db: Session,
        organization_id: Any,
        status: str = PERMISSION_REQUEST_PENDING,
        page: int = 1,
        limit: int = 20,
    ):
        query = db.query(PermissionRequest).filter(
            PermissionRequest.organization_id == organization_id,
            PermissionRequest.status == status,
        )
        total = query.count()
        items = (
            query.order_by(PermissionRequest.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return total, items
