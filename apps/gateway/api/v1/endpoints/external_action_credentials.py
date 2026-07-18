from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.services.external_action_credential_service import (
    ExternalActionCredentialService,
    ExternalActionCredentialServiceError,
)
from apps.gateway.services.organization_context import resolve_active_organization_id
from apps.gateway.utils.api_errors import raise_api_error
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db
from apps.shared.schemas.external_action_credential import (
    ExternalActionCredentialCreate,
    ExternalActionCredentialOptionResponse,
    ExternalActionCredentialPermissionGrant,
    ExternalActionCredentialPermissionResponse,
    ExternalActionCredentialResponse,
    ExternalActionCredentialRevoke,
    ExternalActionCredentialUpdate,
)
from apps.shared.schemas.team import ResourcePermissionListResponse


router = APIRouter()


def _organization_id(
    db: Session,
    request: Request,
    raw_organization_id: str | None,
    current_user: User,
) -> UUID:
    return resolve_active_organization_id(
        db, request, raw_organization_id, current_user.id
    )


def _handle_service_error(
    request: Request, exc: ExternalActionCredentialServiceError
) -> None:
    raise_api_error(request, exc.status_code, exc.code, exc.detail)


@router.post("/credentials", response_model=ExternalActionCredentialResponse)
def create_external_action_credential(
    payload: ExternalActionCredentialCreate,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return ExternalActionCredentialService(db).create(
            current_user.id, organization_id, payload
        )
    except ExternalActionCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.get("/credentials", response_model=list[ExternalActionCredentialOptionResponse])
def list_external_action_credentials(
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    return ExternalActionCredentialService(db).list_available(
        current_user.id, organization_id
    )


@router.get(
    "/credentials/management-options",
    response_model=list[ExternalActionCredentialOptionResponse],
)
def list_manageable_external_action_credentials(
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    return ExternalActionCredentialService(db).list_manageable(
        current_user.id, organization_id
    )


@router.get(
    "/credentials/{credential_id}", response_model=ExternalActionCredentialResponse
)
def get_external_action_credential(
    credential_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return ExternalActionCredentialService(db).get(
            current_user.id, organization_id, credential_id
        )
    except ExternalActionCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.patch(
    "/credentials/{credential_id}", response_model=ExternalActionCredentialResponse
)
def update_external_action_credential(
    credential_id: UUID,
    payload: ExternalActionCredentialUpdate,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return ExternalActionCredentialService(db).update(
            current_user.id, organization_id, credential_id, payload
        )
    except ExternalActionCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.post(
    "/credentials/{credential_id}/revoke", response_model=ExternalActionCredentialResponse
)
def revoke_external_action_credential(
    credential_id: UUID,
    payload: ExternalActionCredentialRevoke,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return ExternalActionCredentialService(db).revoke(
            current_user.id,
            organization_id,
            credential_id,
            expected_revision=payload.expected_revision,
        )
    except ExternalActionCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.get(
    "/credentials/{credential_id}/permissions",
    response_model=ResourcePermissionListResponse,
)
def list_external_action_credential_permissions(
    credential_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return ExternalActionCredentialService(db).list_permissions(
            current_user.id, organization_id, credential_id
        )
    except ExternalActionCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.put(
    "/credentials/{credential_id}/permissions/users/{user_id}",
    response_model=ExternalActionCredentialPermissionResponse,
)
def put_user_external_action_credential_permission(
    credential_id: UUID,
    user_id: UUID,
    payload: ExternalActionCredentialPermissionGrant,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return ExternalActionCredentialService(db).grant_user_permission(
            current_user.id, organization_id, credential_id, user_id, payload
        )
    except ExternalActionCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.put(
    "/credentials/{credential_id}/permissions/teams/{team_id}",
    response_model=ExternalActionCredentialPermissionResponse,
)
def put_team_external_action_credential_permission(
    credential_id: UUID,
    team_id: UUID,
    payload: ExternalActionCredentialPermissionGrant,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return ExternalActionCredentialService(db).grant_team_permission(
            current_user.id, organization_id, credential_id, team_id, payload
        )
    except ExternalActionCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.delete("/credentials/{credential_id}/permissions/users/{user_id}")
def delete_user_external_action_credential_permission(
    credential_id: UUID,
    user_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        ExternalActionCredentialService(db).revoke_user_permission(
            current_user.id, organization_id, credential_id, user_id
        )
        return {"status": "deleted"}
    except ExternalActionCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.delete("/credentials/{credential_id}/permissions/teams/{team_id}")
def delete_team_external_action_credential_permission(
    credential_id: UUID,
    team_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        ExternalActionCredentialService(db).revoke_team_permission(
            current_user.id, organization_id, credential_id, team_id
        )
        return {"status": "deleted"}
    except ExternalActionCredentialServiceError as exc:
        _handle_service_error(request, exc)
