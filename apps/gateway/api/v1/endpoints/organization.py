from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.team import Team, TeamMembership
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db
from apps.shared.schemas.organization import OrganizationResponse

router = APIRouter()


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
