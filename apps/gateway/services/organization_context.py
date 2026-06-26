import uuid
from typing import Optional

from apps.shared.db.models.team import Team, TeamMembership
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
