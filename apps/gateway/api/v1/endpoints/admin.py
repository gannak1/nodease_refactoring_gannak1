from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.services.organization_context import resolve_active_organization_id
from apps.gateway.services.permission_request_service import PermissionRequestService
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db
from apps.shared.schemas.permission_request import (
    PermissionRequestListResponse,
    PermissionRequestResponse,
    PermissionRequestUserSchema,
)
from apps.shared.services import permissions as shared_permissions

router = APIRouter()


def _require_org_manager(db: Session, user: User, organization_id) -> None:
    if not shared_permissions.has_organization_manager_permission(
        db, user.id, organization_id
    ):
        raise HTTPException(status_code=403, detail="Forbidden")


def _serialize_request(db: Session, item) -> PermissionRequestResponse:
    requester = db.query(User).filter(User.id == item.user_id).first()
    return PermissionRequestResponse(
        id=item.id,
        user=(
            PermissionRequestUserSchema.model_validate(requester)
            if requester is not None
            else None
        ),
        requested_permission=item.requested_permission,
        reason=item.reason,
        status=item.status,
        created_at=item.created_at,
        decided_by=item.decided_by,
        decided_at=item.decided_at,
    )


@router.get(
    "/permission-requests",
    response_model=PermissionRequestListResponse,
)
def list_permission_requests(
    request: Request,
    status: Literal["pending", "approved", "rejected"] = Query(default="pending"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """권한 신청 목록 조회 (FR-014)."""
    organization_id = resolve_active_organization_id(
        db, request, x_organization_id, current_user.id
    )
    _require_org_manager(db, current_user, organization_id)
    total, items = PermissionRequestService.list_requests(
        db, organization_id, status=status, page=page, limit=limit
    )
    return PermissionRequestListResponse(
        total=total,
        items=[_serialize_request(db, item) for item in items],
    )


@router.post(
    "/permission-requests/{request_id}/approve",
    response_model=PermissionRequestResponse,
)
def approve_permission_request(
    request: Request,
    request_id: UUID,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """권한 신청 승인 (FR-014, ADR-0014)."""
    organization_id = resolve_active_organization_id(
        db, request, x_organization_id, current_user.id
    )
    _require_org_manager(db, current_user, organization_id)
    approved = PermissionRequestService.approve_request(
        db,
        request_id=request_id,
        organization_id=organization_id,
        decided_by=current_user.id,
    )
    return _serialize_request(db, approved)


@router.post(
    "/permission-requests/{request_id}/reject",
    response_model=PermissionRequestResponse,
)
def reject_permission_request(
    request: Request,
    request_id: UUID,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """권한 신청 거절 (FR-014, ADR-0014)."""
    organization_id = resolve_active_organization_id(
        db, request, x_organization_id, current_user.id
    )
    _require_org_manager(db, current_user, organization_id)
    rejected = PermissionRequestService.reject_request(
        db,
        request_id=request_id,
        organization_id=organization_id,
        decided_by=current_user.id,
    )
    return _serialize_request(db, rejected)
