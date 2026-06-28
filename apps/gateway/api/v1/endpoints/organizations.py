from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.services.organization_context import (
    ensure_user_default_organization,
)
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.team import Team, TeamMembership
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db
from apps.shared.schemas.organization import OrganizationResponse
from apps.shared.services.permissions import has_organization_manager_permission

router = APIRouter()


def _organization_response(
    db: Session, organization: Organization, current_user: User
) -> dict:
    return {
        "id": organization.id,
        "name": organization.name,
        "created_by": organization.created_by,
        "managed_by": organization.managed_by,
        "is_active": organization.is_active,
        "created_at": organization.created_at,
        "updated_at": organization.updated_at,
        "is_manager": has_organization_manager_permission(
            db, current_user.id, organization.id
        ),
    }


@router.get("", response_model=list[OrganizationResponse])
def list_organizations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memberships = (
        db.query(Organization)
        .join(TeamMembership, TeamMembership.grantee_organization_id == Organization.id)
        .join(Team, Team.id == TeamMembership.team_id)
        .filter(
            TeamMembership.user_id == current_user.id,
            TeamMembership.grantee_organization_id == Team.organization_id,
            Team.is_active.is_(True),
            Organization.is_active.is_(True),
        )
        .all()
    )
    managed = (
        db.query(Organization)
        .filter(
            Organization.is_active.is_(True),
            (
                (Organization.created_by == current_user.id)
                | (Organization.managed_by == current_user.id)
            ),
        )
        .all()
    )

    organizations = {organization.id: organization for organization in memberships}
    organizations.update({organization.id: organization for organization in managed})
    return [
        _organization_response(db, organization, current_user)
        for organization in organizations.values()
    ]


@router.get("/current", response_model=OrganizationResponse)
def get_current_organization(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = ensure_user_default_organization(db, current_user)
    db.commit()

    organization = (
        db.query(Organization).filter(Organization.id == organization_id).first()
    )
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _organization_response(db, organization, current_user)
