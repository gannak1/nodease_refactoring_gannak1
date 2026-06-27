from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
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
        raise HTTPException(status_code=404, detail="Organization not found")

    return organization


@router.patch("/{organization_id}", response_model=OrganizationResponse)
@audit(AuditAction.ORGANIZATION_UPDATE, target_param="organization_id")
def update_organization(
    organization_id: UUID,
    request: OrganizationPatchRequest,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if x_organization_id is None:
        raise HTTPException(
            status_code=400, detail="X-Organization-Id header is required"
        )

    if x_organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    fields = request.model_fields_set
    if not fields:
        raise HTTPException(status_code=400, detail="No organization fields to update")

    if "name" in fields and (
        request.name is None or request.name.strip() == ""
    ):
        raise HTTPException(status_code=400, detail="Organization name is required")

    if "options" in fields and request.options is None:
        raise HTTPException(status_code=400, detail="Organization options are required")

    organization = (
        db.query(Organization)
        .filter(
            Organization.id == organization_id,
            Organization.is_active.is_(True),
        )
        .first()
    )

    if organization is None:
        raise HTTPException(status_code=403, detail="Permission denied")

    is_manager = organization.created_by == current_user.id or (
        organization.managed_by is not None
        and organization.managed_by == current_user.id
    )
    if not is_manager:
        raise HTTPException(status_code=403, detail="Permission denied")

    if "name" in fields:
        organization.name = request.name.strip()
    if "options" in fields:
        organization.options = request.options

    db.commit()
    db.refresh(organization)

    return organization
