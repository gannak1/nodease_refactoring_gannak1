from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.utils.audit import audit
from apps.shared.audit.actions import AuditAction
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.team import Team, TeamMembership
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db
from apps.shared.schemas.organization import (
    OrganizationPatchRequest,
    OrganizationResponse,
)

router = APIRouter()


def _error_detail(
    request: Request,
    code: str,
    message: str,
    details: dict | None = None,
) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
            "details": details or {},
        }
    }


def _raise_error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail=_error_detail(request, code, message, details),
    )


def _parse_organization_id(
    request: Request,
    raw_organization_id: str | None,
) -> UUID:
    if raw_organization_id is None:
        _raise_error(
            request,
            400,
            "organization.required",
            "X-Organization-Id header is required.",
        )

    try:
        return UUID(raw_organization_id)
    except ValueError:
        _raise_error(
            request,
            422,
            "validation.failed",
            "X-Organization-Id must be a valid UUID.",
            {"field": "X-Organization-Id"},
        )


# 인증된 사용자가 속한 active organization 목록을 조회하는 API.
@router.get("", response_model=list[OrganizationResponse])
def list_organizations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organizations = (
        db.query(Organization)
        .join(
            TeamMembership,
            TeamMembership.grantee_organization_id == Organization.id,
        )
        .join(Team, Team.id == TeamMembership.team_id)
        .filter(
            TeamMembership.user_id == current_user.id,
            TeamMembership.grantee_organization_id == Team.organization_id,
            Team.is_active.is_(True),
            Organization.is_active.is_(True),
        )
        .distinct()
        .order_by(Organization.created_at.asc(), Organization.id.asc())
        .all()
    )

    return organizations


# 인증된 사용자가 접근 가능한 특정 active organization 상세를 조회하는 API.
@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(
    request: Request,
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization = (
        db.query(Organization)
        .join(
            TeamMembership,
            TeamMembership.grantee_organization_id == Organization.id,
        )
        .join(Team, Team.id == TeamMembership.team_id)
        .filter(
            Organization.id == organization_id,
            TeamMembership.user_id == current_user.id,
            TeamMembership.grantee_organization_id == Organization.id,
            TeamMembership.grantee_organization_id == Team.organization_id,
            Team.is_active.is_(True),
            Organization.is_active.is_(True),
        )
        .first()
    )

    if organization is None:
        _raise_error(
            request,
            404,
            "resource.not_found",
            "Organization not found.",
        )

    return organization


@router.patch("/{organization_id}", response_model=OrganizationResponse)
@audit(AuditAction.ORGANIZATION_UPDATE, target_param="organization_id")
def update_organization(
    request: Request,
    organization_id: UUID,
    payload: OrganizationPatchRequest,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    parsed_organization_id = _parse_organization_id(request, x_organization_id)

    if parsed_organization_id != organization_id:
        _raise_error(
            request,
            404,
            "resource.not_found",
            "Organization not found.",
        )

    fields = payload.model_fields_set
    if not fields:
        _raise_error(
            request,
            400,
            "validation.failed",
            "No organization fields to update.",
        )

    if "name" in fields and (
        payload.name is None or payload.name.strip() == ""
    ):
        _raise_error(
            request,
            400,
            "validation.failed",
            "Organization name is required.",
            {"field": "name"},
        )

    if "options" in fields and payload.options is None:
        _raise_error(
            request,
            400,
            "validation.failed",
            "Organization options are required.",
            {"field": "options"},
        )

    organization = (
        db.query(Organization)
        .filter(
            Organization.id == organization_id,
            Organization.is_active.is_(True),
        )
        .first()
    )

    if organization is None:
        _raise_error(
            request,
            403,
            "permission.denied",
            "Permission denied.",
        )

    is_manager = organization.created_by == current_user.id or (
        organization.managed_by is not None
        and organization.managed_by == current_user.id
    )
    if not is_manager:
        _raise_error(
            request,
            403,
            "permission.denied",
            "Permission denied.",
        )

    if "name" in fields:
        organization.name = payload.name.strip()
    if "options" in fields:
        organization.options = payload.options

    db.commit()
    db.refresh(organization)

    return organization
