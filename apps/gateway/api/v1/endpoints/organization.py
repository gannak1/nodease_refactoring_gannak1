from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.utils.api_errors import parse_organization_id, raise_api_error
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


def _get_organization_in_active_membership_scope(
    db: Session,
    organization_id: UUID,
    user_id: UUID,
) -> Organization | None:
    # Active organization은 서버에 저장하지 않고, 요청 header 값이
    # 현재 사용자의 active team membership scope 안에 있는지로 판정한다.
    return (
        db.query(Organization)
        .join(
            TeamMembership,
            TeamMembership.grantee_organization_id == Organization.id,
        )
        .join(Team, Team.id == TeamMembership.team_id)
        .filter(
            Organization.id == organization_id,
            TeamMembership.user_id == user_id,
            TeamMembership.grantee_organization_id == Organization.id,
            TeamMembership.grantee_organization_id == Team.organization_id,
            Team.is_active.is_(True),
            Organization.is_active.is_(True),
        )
        .first()
    )


def _is_organization_manager(organization: Organization, user_id: UUID) -> bool:
    return organization.created_by == user_id or (
        organization.managed_by is not None and organization.managed_by == user_id
    )


def _to_organization_response(
    organization: Organization,
    user_id: UUID,
) -> OrganizationResponse:
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        options=organization.options,
        is_active=organization.is_active,
        is_manager=_is_organization_manager(organization, user_id),
        created_at=organization.created_at,
        updated_at=organization.updated_at,
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

    return [
        _to_organization_response(organization, current_user.id)
        for organization in organizations
    ]


# literal path인 current가 /{organization_id} UUID path parameter로 해석되지 않도록
# 먼저 등록한다.
@router.get("/current", response_model=OrganizationResponse)
def get_current_organization(
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # current organization 상태를 session/cookie에 저장하지 않고
    # 매 요청의 header 값을 검증한다.
    organization_id = parse_organization_id(request, x_organization_id)
    organization = _get_organization_in_active_membership_scope(
        db,
        organization_id,
        current_user.id,
    )

    if organization is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Organization not found.",
        )

    return _to_organization_response(organization, current_user.id)


# 인증된 사용자가 접근 가능한 특정 active organization 상세를 조회하는 API.
@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(
    request: Request,
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization = _get_organization_in_active_membership_scope(
        db,
        organization_id,
        current_user.id,
    )

    if organization is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Organization not found.",
        )

    return _to_organization_response(organization, current_user.id)


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
    parsed_organization_id = parse_organization_id(request, x_organization_id)

    if parsed_organization_id != organization_id:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Organization not found.",
        )

    fields = payload.model_fields_set
    if not fields:
        raise_api_error(
            request,
            400,
            "validation.failed",
            "No organization fields to update.",
        )

    if "name" in fields and (
        payload.name is None or payload.name.strip() == ""
    ):
        raise_api_error(
            request,
            400,
            "validation.failed",
            "Organization name is required.",
            {"field": "name"},
        )

    if "options" in fields and payload.options is None:
        raise_api_error(
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
        raise_api_error(
            request,
            403,
            "permission.denied",
            "Permission denied.",
        )

    if not _is_organization_manager(organization, current_user.id):
        raise_api_error(
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

    return _to_organization_response(organization, current_user.id)
