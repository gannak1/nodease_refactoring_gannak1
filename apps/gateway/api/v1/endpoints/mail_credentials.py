from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.services.mail_credential_service import (
    MailCredentialService,
    MailCredentialServiceError,
)
from apps.gateway.services.organization_context import resolve_active_organization_id
from apps.gateway.utils.api_errors import raise_api_error
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db
from apps.shared.schemas.mail_credential import (
    MailCredentialCreate,
    MailCredentialOptionResponse,
    MailCredentialPermissionGrant,
    MailCredentialPermissionResponse,
    MailCredentialResponse,
    MailCredentialUpdate,
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


def _handle_service_error(request: Request, exc: MailCredentialServiceError) -> None:
    raise_api_error(request, exc.status_code, exc.code, exc.detail)


@router.post("/credentials", response_model=MailCredentialResponse)
def create_mail_credential(
    payload: MailCredentialCreate,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return MailCredentialService(db).create(
            current_user.id, organization_id, payload
        )
    except MailCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.get("/credentials", response_model=list[MailCredentialOptionResponse])
def list_mail_credentials(
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    return MailCredentialService(db).list_available(current_user.id, organization_id)


@router.get("/credentials/{credential_id}", response_model=MailCredentialResponse)
def get_mail_credential(
    credential_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return MailCredentialService(db).get(
            current_user.id, organization_id, credential_id
        )
    except MailCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.patch("/credentials/{credential_id}", response_model=MailCredentialResponse)
def update_mail_credential(
    credential_id: UUID,
    payload: MailCredentialUpdate,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return MailCredentialService(db).update(
            current_user.id, organization_id, credential_id, payload
        )
    except MailCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.delete("/credentials/{credential_id}", response_model=MailCredentialResponse)
def revoke_mail_credential(
    credential_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return MailCredentialService(db).revoke(
            current_user.id, organization_id, credential_id
        )
    except MailCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.get(
    "/credentials/{credential_id}/permissions",
    response_model=ResourcePermissionListResponse,
)
def list_mail_credential_permissions(
    credential_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return MailCredentialService(db).list_permissions(
            current_user.id, organization_id, credential_id
        )
    except MailCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.put(
    "/credentials/{credential_id}/permissions/users/{user_id}",
    response_model=MailCredentialPermissionResponse,
)
def put_user_mail_credential_permission(
    credential_id: UUID,
    user_id: UUID,
    payload: MailCredentialPermissionGrant,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return MailCredentialService(db).grant_user_permission(
            current_user.id, organization_id, credential_id, user_id, payload
        )
    except MailCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.put(
    "/credentials/{credential_id}/permissions/teams/{team_id}",
    response_model=MailCredentialPermissionResponse,
)
def put_team_mail_credential_permission(
    credential_id: UUID,
    team_id: UUID,
    payload: MailCredentialPermissionGrant,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        return MailCredentialService(db).grant_team_permission(
            current_user.id, organization_id, credential_id, team_id, payload
        )
    except MailCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.delete("/credentials/{credential_id}/permissions/users/{user_id}")
def delete_user_mail_credential_permission(
    credential_id: UUID,
    user_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        MailCredentialService(db).revoke_user_permission(
            current_user.id, organization_id, credential_id, user_id
        )
        return {"status": "deleted"}
    except MailCredentialServiceError as exc:
        _handle_service_error(request, exc)


@router.delete("/credentials/{credential_id}/permissions/teams/{team_id}")
def delete_team_mail_credential_permission(
    credential_id: UUID,
    team_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = _organization_id(db, request, x_organization_id, current_user)
    try:
        MailCredentialService(db).revoke_team_permission(
            current_user.id, organization_id, credential_id, team_id
        )
        return {"status": "deleted"}
    except MailCredentialServiceError as exc:
        _handle_service_error(request, exc)
