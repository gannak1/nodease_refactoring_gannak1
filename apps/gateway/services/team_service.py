from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from apps.gateway.auth.permissions import record_permission_denied
from apps.shared.audit.actions import AuditAction
from apps.shared.audit.logger import record_audit
from apps.shared.db.models.llm import LLMCredential
from apps.shared.db.models.team import (
    Team,
    TeamLLMPermission,
    TeamMembership,
    TeamWorkflowPermission,
    UserLLMPermission,
    UserWorkflowPermission,
)
from apps.shared.db.models.user import User
from apps.shared.db.models.workflow import Workflow
from apps.shared.permissions import (
    AUTH_STATE_BUILDER,
    AUTH_STATE_MANAGER,
    AUTH_STATE_NONE,
    AUTH_STATE_OPERATOR,
    AUTH_STATE_VIEWER,
    is_canonical_auth_state,
    llm_credential_auth_state_allows,
    normalize_auth_state,
    workflow_auth_state_allows,
)
from apps.shared.schemas.team import (
    ResourcePermissionGrantRequest,
    ResourcePermissionRevokeRequest,
    TeamCreateRequest,
    TeamMembershipRequest,
    TeamUpdateRequest,
)
from apps.shared.services.permissions import (
    get_effective_llm_credential_auth_state,
    get_effective_workflow_auth_state,
    has_organization_manager_permission,
)

RESOURCE_AUTH_STATES = {
    AUTH_STATE_NONE,
    AUTH_STATE_VIEWER,
    AUTH_STATE_OPERATOR,
    AUTH_STATE_BUILDER,
    AUTH_STATE_MANAGER,
}


def _ensure_organization_manager(
    db: Session,
    current_user: User,
    organization_id: Any,
) -> None:
    if has_organization_manager_permission(db, current_user.id, organization_id):
        return
    record_permission_denied(
        current_user,
        "organization",
        organization_id,
        "manage",
        AUTH_STATE_NONE,
    )
    raise HTTPException(status_code=403, detail="Forbidden")


def _get_team(db: Session, team_id: Any) -> Team:
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _resource_organization_id(
    db: Session,
    resource_type: str,
    resource_id: Any,
) -> Any:
    if resource_type == "workflow":
        workflow = db.query(Workflow).filter(Workflow.id == resource_id).first()
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return workflow.organization_id

    credential = (
        db.query(LLMCredential).filter(LLMCredential.id == resource_id).first()
    )
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")
    return credential.organization_id


def _ensure_resource_permission_manager(
    db: Session,
    current_user: User,
    resource_type: str,
    resource_id: Any,
    organization_id: Any,
) -> None:
    if has_organization_manager_permission(db, current_user.id, organization_id):
        return

    if resource_type == "workflow":
        effective_auth_state = get_effective_workflow_auth_state(
            db,
            current_user.id,
            resource_id,
            organization_id=organization_id,
        )
        if workflow_auth_state_allows(effective_auth_state, "manage"):
            return
    else:
        effective_auth_state = get_effective_llm_credential_auth_state(
            db,
            current_user.id,
            resource_id,
            organization_id=organization_id,
        )
        if llm_credential_auth_state_allows(effective_auth_state, "manage"):
            return

    record_permission_denied(
        current_user,
        resource_type,
        resource_id,
        "manage",
        effective_auth_state,
    )
    raise HTTPException(status_code=403, detail="Forbidden")


def _validate_grant_request(
    db: Session,
    request: ResourcePermissionGrantRequest,
) -> str:
    auth_state = normalize_auth_state(request.auth_state)
    if (
        not is_canonical_auth_state(request.auth_state)
        or auth_state not in RESOURCE_AUTH_STATES
    ):
        raise HTTPException(status_code=400, detail="Invalid auth_state")

    resource_organization_id = _resource_organization_id(
        db, request.resource_type, request.resource_id
    )
    if resource_organization_id != request.organization_id:
        raise HTTPException(status_code=400, detail="Resource organization mismatch")
    return auth_state


def _ensure_grantee_user_membership(
    db: Session,
    user_id: Any,
    organization_id: Any,
) -> None:
    membership = (
        db.query(TeamMembership)
        .join(Team, Team.id == TeamMembership.team_id)
        .join(User, User.id == TeamMembership.user_id)
        .filter(
            TeamMembership.user_id == user_id,
            TeamMembership.grantee_organization_id == organization_id,
            TeamMembership.grantee_organization_id == Team.organization_id,
            Team.organization_id == organization_id,
            Team.is_active.is_(True),
            User.deactivated_at.is_(None),
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=400,
            detail="Grantee user is not a member of the organization",
        )


def _record_permission_mutation(
    action: str,
    current_user: User,
    target_id: Any,
    request: ResourcePermissionGrantRequest | ResourcePermissionRevokeRequest,
    auth_state: str | None = None,
) -> None:
    metadata = {
        "resource_type": request.resource_type,
        "resource_id": str(request.resource_id),
        "grant_subject_type": request.grantee_type,
        "grant_subject_id": str(request.grantee_id),
        "grantee_type": request.grantee_type,
        "grantee_id": str(request.grantee_id),
        "organization_id": str(request.organization_id),
    }
    if auth_state is not None:
        metadata["auth_state"] = auth_state

    record_audit(
        action=action,
        category="action",
        actor_id=current_user.id,
        actor_type="user",
        target_type="permission",
        target_id=target_id,
        metadata=metadata,
    )


class TeamService:
    @staticmethod
    def list_teams(
        db: Session,
        current_user: User,
        organization_id: Any,
    ) -> list[Team]:
        _ensure_organization_manager(db, current_user, organization_id)
        return (
            db.query(Team)
            .filter(
                Team.organization_id == organization_id,
                Team.is_active.is_(True),
            )
            .order_by(Team.created_at.asc())
            .all()
        )

    @staticmethod
    def create_team(
        db: Session,
        current_user: User,
        request: TeamCreateRequest,
    ) -> Team:
        _ensure_organization_manager(db, current_user, request.organization_id)
        team = Team(
            organization_id=request.organization_id,
            name=request.name,
            description=request.description,
            created_by=current_user.id,
            managed_by=current_user.id,
            is_auto_add=request.is_auto_add,
        )
        db.add(team)
        db.commit()
        db.refresh(team)
        return team

    @staticmethod
    def update_team(
        db: Session,
        current_user: User,
        team_id: Any,
        request: TeamUpdateRequest,
    ) -> Team:
        team = _get_team(db, team_id)
        _ensure_organization_manager(db, current_user, team.organization_id)
        if request.name is not None:
            team.name = request.name
        if request.description is not None:
            team.description = request.description
        if request.managed_by is not None:
            team.managed_by = request.managed_by
        if request.is_auto_add is not None:
            team.is_auto_add = request.is_auto_add
        db.commit()
        db.refresh(team)
        return team

    @staticmethod
    def deactivate_team(db: Session, current_user: User, team_id: Any) -> dict:
        team = _get_team(db, team_id)
        _ensure_organization_manager(db, current_user, team.organization_id)
        team.is_active = False
        team.deactivated_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "deactivated"}

    @staticmethod
    def add_membership(
        db: Session,
        current_user: User,
        team_id: Any,
        request: TeamMembershipRequest,
    ) -> TeamMembership:
        team = _get_team(db, team_id)
        _ensure_organization_manager(db, current_user, team.organization_id)
        membership = (
            db.query(TeamMembership)
            .filter(
                TeamMembership.grantee_organization_id == team.organization_id,
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == request.user_id,
            )
            .first()
        )
        if membership:
            return membership

        membership = TeamMembership(
            grantee_organization_id=team.organization_id,
            team_id=team.id,
            user_id=request.user_id,
            assigned_by=current_user.id,
        )
        db.add(membership)
        db.commit()
        db.refresh(membership)
        return membership

    @staticmethod
    def remove_membership(
        db: Session,
        current_user: User,
        team_id: Any,
        user_id: Any,
    ) -> dict:
        team = _get_team(db, team_id)
        _ensure_organization_manager(db, current_user, team.organization_id)
        membership = (
            db.query(TeamMembership)
            .filter(
                TeamMembership.grantee_organization_id == team.organization_id,
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == user_id,
            )
            .first()
        )
        if membership:
            db.delete(membership)
            db.commit()
        return {"status": "removed"}

    @staticmethod
    def grant_resource_permission(
        db: Session,
        current_user: User,
        request: ResourcePermissionGrantRequest,
    ) -> Any:
        auth_state = _validate_grant_request(db, request)
        _ensure_resource_permission_manager(
            db,
            current_user,
            request.resource_type,
            request.resource_id,
            request.organization_id,
        )

        if request.grantee_type == "team":
            team = _get_team(db, request.grantee_id)
            if team.organization_id != request.organization_id:
                raise HTTPException(status_code=400, detail="Team organization mismatch")
            if not getattr(team, "is_active", True):
                raise HTTPException(status_code=400, detail="Team is inactive")
            if request.resource_type == "workflow":
                model = TeamWorkflowPermission
                filters = {
                    "workflow_id": request.resource_id,
                    "team_id": request.grantee_id,
                }
            else:
                model = TeamLLMPermission
                filters = {
                    "llm_credential_id": request.resource_id,
                    "team_id": request.grantee_id,
                }
        else:
            _ensure_grantee_user_membership(
                db,
                request.grantee_id,
                request.organization_id,
            )
            if request.resource_type == "workflow":
                model = UserWorkflowPermission
                filters = {
                    "workflow_id": request.resource_id,
                    "user_id": request.grantee_id,
                }
            else:
                model = UserLLMPermission
                filters = {
                    "llm_credential_id": request.resource_id,
                    "user_id": request.grantee_id,
                }

        row = db.query(model).filter(
            model.grantee_organization_id == request.organization_id,
            *(getattr(model, key) == value for key, value in filters.items()),
        ).first()
        if not row:
            row = model(
                grantee_organization_id=request.organization_id,
                assigned_by=current_user.id,
                **filters,
            )
            db.add(row)
        row.auth_state = auth_state
        db.commit()
        db.refresh(row)
        _record_permission_mutation(
            AuditAction.PERMISSION_GRANT,
            current_user,
            row.id,
            request,
            auth_state,
        )
        return row

    @staticmethod
    def revoke_resource_permission(
        db: Session,
        current_user: User,
        request: ResourcePermissionRevokeRequest,
    ) -> dict:
        resource_organization_id = _resource_organization_id(
            db, request.resource_type, request.resource_id
        )
        if resource_organization_id != request.organization_id:
            raise HTTPException(status_code=400, detail="Resource organization mismatch")
        _ensure_resource_permission_manager(
            db,
            current_user,
            request.resource_type,
            request.resource_id,
            request.organization_id,
        )

        if request.grantee_type == "team":
            if request.resource_type == "workflow":
                model = TeamWorkflowPermission
                filters = {
                    "workflow_id": request.resource_id,
                    "team_id": request.grantee_id,
                }
            else:
                model = TeamLLMPermission
                filters = {
                    "llm_credential_id": request.resource_id,
                    "team_id": request.grantee_id,
                }
        else:
            if request.resource_type == "workflow":
                model = UserWorkflowPermission
                filters = {
                    "workflow_id": request.resource_id,
                    "user_id": request.grantee_id,
                }
            else:
                model = UserLLMPermission
                filters = {
                    "llm_credential_id": request.resource_id,
                    "user_id": request.grantee_id,
                }

        row = db.query(model).filter(
            model.grantee_organization_id == request.organization_id,
            *(getattr(model, key) == value for key, value in filters.items()),
        ).first()
        target_id = row.id if row else None
        if row:
            db.delete(row)
            db.commit()
        _record_permission_mutation(
            AuditAction.PERMISSION_REVOKE,
            current_user,
            target_id,
            request,
        )
        return {"status": "revoked"}
