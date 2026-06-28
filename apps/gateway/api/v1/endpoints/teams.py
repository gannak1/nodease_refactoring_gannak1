from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.services.organization_context import ensure_user_default_organization
from apps.gateway.services.team_service import TeamService
from apps.shared.db.models.llm import LLMCredential
from apps.shared.db.models.user import User
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.session import get_db
from apps.shared.schemas.team import (
    PermissionMutationResponse,
    ResourceAuthStateRequest,
    ResourcePermissionGrantRequest,
    ResourcePermissionRevokeRequest,
    TeamCreateRequest,
    TeamMembershipRequest,
    TeamResponse,
    TeamUpdateRequest,
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
