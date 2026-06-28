from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.services.organization_context import ensure_user_default_organization
from apps.gateway.services.team_service import TeamService
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
from apps.shared.db.session import get_db
from apps.shared.permissions import (
    llm_credential_auth_state_allows,
    workflow_auth_state_allows,
)
from apps.shared.schemas.team import (
    PermissionMutationResponse,
    ResourceAuthStateRequest,
    ResourcePermissionListResponse,
    ResourcePermissionGrantRequest,
    ResourcePermissionRevokeRequest,
    TeamCreateRequest,
    TeamMemberResponse,
    TeamMembershipRequest,
    TeamResponse,
    TeamUpdateRequest,
)
from apps.shared.services.permissions import (
    get_effective_llm_credential_auth_state,
    get_effective_workflow_auth_state,
    has_organization_manager_permission,
)

router = APIRouter()
permissions_router = APIRouter()


def _workflow_organization_id(db: Session, workflow_id: UUID) -> UUID:
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow.organization_id


def _credential_organization_id(db: Session, credential_id: UUID) -> UUID:
    credential = db.query(LLMCredential).filter(LLMCredential.id == credential_id).first()
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")
    return credential.organization_id


def _ensure_can_manage_workflow_permissions(
    db: Session, current_user: User, workflow: Workflow
) -> None:
    if has_organization_manager_permission(
        db, current_user.id, workflow.organization_id
    ):
        return
    auth_state = get_effective_workflow_auth_state(
        db, current_user.id, workflow.id, organization_id=workflow.organization_id
    )
    if workflow_auth_state_allows(auth_state, "manage"):
        return
    raise HTTPException(status_code=403, detail="Forbidden")


def _ensure_can_manage_credential_permissions(
    db: Session, current_user: User, credential: LLMCredential
) -> None:
    if has_organization_manager_permission(
        db, current_user.id, credential.organization_id
    ):
        return
    auth_state = get_effective_llm_credential_auth_state(
        db, current_user.id, credential.id, organization_id=credential.organization_id
    )
    if llm_credential_auth_state_allows(auth_state, "manage"):
        return
    raise HTTPException(status_code=403, detail="Forbidden")


def _grant_permission(
    db: Session,
    current_user: User,
    organization_id: UUID,
    resource_type: str,
    resource_id: UUID,
    grantee_type: str,
    grantee_id: UUID,
    auth_state: str,
) -> PermissionMutationResponse:
    row = TeamService.grant_resource_permission(
        db,
        current_user,
        ResourcePermissionGrantRequest(
            organization_id=organization_id,
            resource_type=resource_type,
            resource_id=resource_id,
            grantee_type=grantee_type,
            grantee_id=grantee_id,
            auth_state=auth_state,
        ),
    )
    return PermissionMutationResponse(id=row.id, status="granted")


def _revoke_permission(
    db: Session,
    current_user: User,
    organization_id: UUID,
    resource_type: str,
    resource_id: UUID,
    grantee_type: str,
    grantee_id: UUID,
) -> PermissionMutationResponse:
    TeamService.revoke_resource_permission(
        db,
        current_user,
        ResourcePermissionRevokeRequest(
            organization_id=organization_id,
            resource_type=resource_type,
            resource_id=resource_id,
            grantee_type=grantee_type,
            grantee_id=grantee_id,
        ),
    )
    return PermissionMutationResponse(status="revoked")


@router.post("", response_model=TeamResponse)
def create_team(
    request: TeamCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return TeamService.create_team(db, current_user, request)


@router.get("", response_model=list[TeamResponse])
def list_teams(
    organization_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = organization_id or ensure_user_default_organization(
        db, current_user
    )
    return TeamService.list_teams(db, current_user, organization_id)


@router.get("/{team_id}/members", response_model=list[TeamMemberResponse])
def list_team_members(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if not has_organization_manager_permission(db, current_user.id, team.organization_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    rows = (
        db.query(TeamMembership, User)
        .join(User, User.id == TeamMembership.user_id)
        .filter(
            TeamMembership.team_id == team.id,
            TeamMembership.grantee_organization_id == team.organization_id,
            User.deactivated_at.is_(None),
        )
        .order_by(User.name.asc(), User.email.asc())
        .all()
    )
    return [
        {
            "id": membership.id,
            "user_id": user.id,
            "email": user.email,
            "name": user.name,
            "assigned_at": membership.assigned_at,
        }
        for membership, user in rows
    ]


@router.patch("/{team_id}", response_model=TeamResponse)
def update_team(
    team_id: UUID,
    request: TeamUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return TeamService.update_team(db, current_user, team_id, request)


@router.delete("/{team_id}")
def deactivate_team(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return TeamService.deactivate_team(db, current_user, team_id)


@router.post("/{team_id}/memberships")
def add_membership(
    team_id: UUID,
    request: TeamMembershipRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    membership = TeamService.add_membership(db, current_user, team_id, request)
    return {"id": str(membership.id), "status": "added"}


@router.post("/{team_id}/members")
def add_member(
    team_id: UUID,
    request: TeamMembershipRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return add_membership(team_id, request, db, current_user)


@router.delete("/{team_id}/memberships/{user_id}")
def remove_membership(
    team_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return TeamService.remove_membership(db, current_user, team_id, user_id)


@router.delete("/{team_id}/members/{user_id}")
def remove_member(
    team_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return remove_membership(team_id, user_id, db, current_user)


@permissions_router.get(
    "/workflows/{workflow_id}", response_model=ResourcePermissionListResponse
)
def list_workflow_permissions(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    _ensure_can_manage_workflow_permissions(db, current_user, workflow)

    team_rows = (
        db.query(TeamWorkflowPermission, Team)
        .join(Team, Team.id == TeamWorkflowPermission.team_id)
        .filter(
            TeamWorkflowPermission.workflow_id == workflow.id,
            TeamWorkflowPermission.grantee_organization_id == workflow.organization_id,
            Team.organization_id == workflow.organization_id,
            Team.is_active.is_(True),
        )
        .order_by(Team.name.asc())
        .all()
    )
    user_rows = (
        db.query(UserWorkflowPermission, User)
        .join(User, User.id == UserWorkflowPermission.user_id)
        .filter(
            UserWorkflowPermission.workflow_id == workflow.id,
            UserWorkflowPermission.grantee_organization_id == workflow.organization_id,
            User.deactivated_at.is_(None),
        )
        .order_by(User.name.asc(), User.email.asc())
        .all()
    )

    return {
        "resource_type": "workflow",
        "resource_id": workflow.id,
        "organization_id": workflow.organization_id,
        "team_permissions": [
            {
                "id": permission.id,
                "grantee_type": "team",
                "grantee_id": team.id,
                "grantee_name": team.name,
                "auth_state": permission.auth_state,
                "assigned_at": permission.assigned_at,
            }
            for permission, team in team_rows
        ],
        "user_permissions": [
            {
                "id": permission.id,
                "grantee_type": "user",
                "grantee_id": user.id,
                "grantee_name": f"{user.name} <{user.email}>",
                "auth_state": permission.auth_state,
                "assigned_at": permission.assigned_at,
            }
            for permission, user in user_rows
        ],
    }


@permissions_router.get(
    "/llm-credentials/{credential_id}", response_model=ResourcePermissionListResponse
)
def list_credential_permissions(
    credential_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    credential = db.query(LLMCredential).filter(LLMCredential.id == credential_id).first()
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")
    _ensure_can_manage_credential_permissions(db, current_user, credential)

    team_rows = (
        db.query(TeamLLMPermission, Team)
        .join(Team, Team.id == TeamLLMPermission.team_id)
        .filter(
            TeamLLMPermission.llm_credential_id == credential.id,
            TeamLLMPermission.grantee_organization_id == credential.organization_id,
            Team.organization_id == credential.organization_id,
            Team.is_active.is_(True),
        )
        .order_by(Team.name.asc())
        .all()
    )
    user_rows = (
        db.query(UserLLMPermission, User)
        .join(User, User.id == UserLLMPermission.user_id)
        .filter(
            UserLLMPermission.llm_credential_id == credential.id,
            UserLLMPermission.grantee_organization_id == credential.organization_id,
            User.deactivated_at.is_(None),
        )
        .order_by(User.name.asc(), User.email.asc())
        .all()
    )

    return {
        "resource_type": "llm_credential",
        "resource_id": credential.id,
        "organization_id": credential.organization_id,
        "team_permissions": [
            {
                "id": permission.id,
                "grantee_type": "team",
                "grantee_id": team.id,
                "grantee_name": team.name,
                "auth_state": permission.auth_state,
                "assigned_at": permission.assigned_at,
            }
            for permission, team in team_rows
        ],
        "user_permissions": [
            {
                "id": permission.id,
                "grantee_type": "user",
                "grantee_id": user.id,
                "grantee_name": f"{user.name} <{user.email}>",
                "auth_state": permission.auth_state,
                "assigned_at": permission.assigned_at,
            }
            for permission, user in user_rows
        ],
    }


@router.post("/permissions", response_model=PermissionMutationResponse)
def grant_resource_permission(
    request: ResourcePermissionGrantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = TeamService.grant_resource_permission(db, current_user, request)
    return PermissionMutationResponse(id=row.id, status="granted")


@router.post("/permissions/revoke", response_model=PermissionMutationResponse)
def revoke_resource_permission(
    request: ResourcePermissionRevokeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    TeamService.revoke_resource_permission(db, current_user, request)
    return PermissionMutationResponse(status="revoked")


@permissions_router.put(
    "/workflows/{workflow_id}/teams/{team_id}",
    response_model=PermissionMutationResponse,
)
def grant_workflow_team_permission(
    workflow_id: UUID,
    team_id: UUID,
    request: ResourceAuthStateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _grant_permission(
        db,
        current_user,
        _workflow_organization_id(db, workflow_id),
        "workflow",
        workflow_id,
        "team",
        team_id,
        request.auth_state,
    )


@permissions_router.delete(
    "/workflows/{workflow_id}/teams/{team_id}",
    response_model=PermissionMutationResponse,
)
def revoke_workflow_team_permission(
    workflow_id: UUID,
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _revoke_permission(
        db,
        current_user,
        _workflow_organization_id(db, workflow_id),
        "workflow",
        workflow_id,
        "team",
        team_id,
    )


@permissions_router.put(
    "/workflows/{workflow_id}/users/{user_id}",
    response_model=PermissionMutationResponse,
)
def grant_workflow_user_permission(
    workflow_id: UUID,
    user_id: UUID,
    request: ResourceAuthStateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _grant_permission(
        db,
        current_user,
        _workflow_organization_id(db, workflow_id),
        "workflow",
        workflow_id,
        "user",
        user_id,
        request.auth_state,
    )


@permissions_router.delete(
    "/workflows/{workflow_id}/users/{user_id}",
    response_model=PermissionMutationResponse,
)
def revoke_workflow_user_permission(
    workflow_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _revoke_permission(
        db,
        current_user,
        _workflow_organization_id(db, workflow_id),
        "workflow",
        workflow_id,
        "user",
        user_id,
    )


@permissions_router.put(
    "/llm-credentials/{credential_id}/teams/{team_id}",
    response_model=PermissionMutationResponse,
)
def grant_credential_team_permission(
    credential_id: UUID,
    team_id: UUID,
    request: ResourceAuthStateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _grant_permission(
        db,
        current_user,
        _credential_organization_id(db, credential_id),
        "llm_credential",
        credential_id,
        "team",
        team_id,
        request.auth_state,
    )


@permissions_router.delete(
    "/llm-credentials/{credential_id}/teams/{team_id}",
    response_model=PermissionMutationResponse,
)
def revoke_credential_team_permission(
    credential_id: UUID,
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _revoke_permission(
        db,
        current_user,
        _credential_organization_id(db, credential_id),
        "llm_credential",
        credential_id,
        "team",
        team_id,
    )


@permissions_router.put(
    "/llm-credentials/{credential_id}/users/{user_id}",
    response_model=PermissionMutationResponse,
)
def grant_credential_user_permission(
    credential_id: UUID,
    user_id: UUID,
    request: ResourceAuthStateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _grant_permission(
        db,
        current_user,
        _credential_organization_id(db, credential_id),
        "llm_credential",
        credential_id,
        "user",
        user_id,
        request.auth_state,
    )


@permissions_router.delete(
    "/llm-credentials/{credential_id}/users/{user_id}",
    response_model=PermissionMutationResponse,
)
def revoke_credential_user_permission(
    credential_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _revoke_permission(
        db,
        current_user,
        _credential_organization_id(db, credential_id),
        "llm_credential",
        credential_id,
        "user",
        user_id,
    )
