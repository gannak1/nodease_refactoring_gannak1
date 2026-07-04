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


def _resolve_managed_organization(
    db: Session,
    request: Request,
    x_organization_id: str | None,
    current_user: User,
):
    """active organization을 해석하고 owner/manager가 아니면 403으로 닫는다."""
    organization_id = resolve_active_organization_id(
        db, request, x_organization_id, current_user.id
    )
    if not shared_permissions.has_organization_manager_permission(
        db, current_user.id, organization_id
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    return organization_id


def _requesters_by_id(db: Session, items) -> dict:
    user_ids = {item.user_id for item in items}
    if not user_ids:
        return {}
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    return {user.id: user for user in users}


def _serialize_request(item, requester) -> PermissionRequestResponse:
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


def _serialize_requests(db: Session, items) -> list[PermissionRequestResponse]:
    requesters = _requesters_by_id(db, items)
    return [
        _serialize_request(item, requesters.get(item.user_id)) for item in items
    ]


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
    organization_id = _resolve_managed_organization(
        db, request, x_organization_id, current_user
    )
    total, items = PermissionRequestService.list_requests(
        db, organization_id, status=status, page=page, limit=limit
    )
    return PermissionRequestListResponse(
        total=total,
        items=_serialize_requests(db, items),
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
    organization_id = _resolve_managed_organization(
        db, request, x_organization_id, current_user
    )
    approved = PermissionRequestService.approve_request(
        db,
        request_id=request_id,
        organization_id=organization_id,
        decided_by=current_user.id,
    )
    return _serialize_requests(db, [approved])[0]


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
    organization_id = _resolve_managed_organization(
        db, request, x_organization_id, current_user
    )
    rejected = PermissionRequestService.reject_request(
        db,
        request_id=request_id,
        organization_id=organization_id,
        decided_by=current_user.id,
    )
    return _serialize_requests(db, [rejected])[0]
