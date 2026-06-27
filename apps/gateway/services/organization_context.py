import uuid
from typing import Optional

from apps.shared.db.models.organization import Organization
from apps.shared.db.models.team import Team, TeamMembership
from apps.shared.db.models.user import User
from sqlalchemy.orm import Session


def get_user_primary_organization_id(
    db: Session,
    user_id: uuid.UUID,
) -> Optional[uuid.UUID]:
    """Return the first organization available through active team membership."""

    row = (
        db.query(TeamMembership.grantee_organization_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .filter(
            TeamMembership.user_id == user_id,
            TeamMembership.grantee_organization_id == Team.organization_id,
            Team.is_active.is_(True),
        )
        .order_by(TeamMembership.assigned_at.asc())
        .first()
    )
    return row[0] if row else None


def ensure_user_default_organization(
    db: Session,
    user: User | uuid.UUID,
) -> uuid.UUID:
    """Create the default organization/team/membership foundation if missing."""

    user_id = getattr(user, "id", user)
    user_name = getattr(user, "name", None)
    existing_id = get_user_primary_organization_id(db, user_id)
    if existing_id:
        return existing_id

    if not user_name:
        db_user = db.query(User).filter(User.id == user_id).first()
        user_name = db_user.name if db_user else "Personal"

    organization = Organization(
        id=uuid.uuid4(),
        name=f"{user_name}'s Organization",
        created_by=user_id,
        managed_by=user_id,
    )
    team = Team(
        id=uuid.uuid4(),
        organization_id=organization.id,
        name="Default",
        created_by=user_id,
        managed_by=user_id,
        is_auto_add=True,
    )
    membership = TeamMembership(
        grantee_organization_id=organization.id,
        user_id=user_id,
        team_id=team.id,
        assigned_by=user_id,
    )
    db.add(organization)
    db.add(team)
    db.add(membership)
    db.flush()
    return organization.id
