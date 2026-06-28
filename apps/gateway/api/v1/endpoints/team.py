from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from apps.gateway.services.auth_service import AuthService
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.team import Team, TeamMembership
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db
from apps.shared.schemas.team import TeamResponse

router = APIRouter()


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", None),
                "details": details or {},
            }
        },
    )


def _authenticate(
    request: Request,
    db: Session,
    auth_token: str | None,
) -> tuple[User | None, JSONResponse | None]:
    try:
        return AuthService.get_user_from_token(db, auth_token), None
    except HTTPException as exc:
        if exc.status_code == 401:
            code = "auth.invalid" if auth_token else "auth.required"
        else:
            code = "permission.denied"
        message = (
            exc.detail if isinstance(exc.detail, str) else "Authentication failed"
        )
        return None, _error_response(request, exc.status_code, code, message)


def _parse_organization_id(
    request: Request, raw_organization_id: str | None
) -> tuple[UUID | None, JSONResponse | None]:
    if raw_organization_id is None:
        return None, _error_response(
            request,
            400,
            "organization.required",
            "X-Organization-Id header is required.",
        )
    try:
        return UUID(raw_organization_id), None
    except ValueError:
        return None, _error_response(
            request,
            422,
            "validation.failed",
            "X-Organization-Id must be a valid UUID.",
            {"field": "X-Organization-Id"},
        )


def _parse_limit(
    request: Request, raw_limit: str
) -> tuple[int | None, JSONResponse | None]:
    try:
        limit = int(raw_limit)
    except ValueError:
        return None, _error_response(
            request,
            422,
            "validation.failed",
            "limit must be an integer.",
            {"field": "limit"},
        )

    if limit < 1 or limit > 100:
        return None, _error_response(
            request,
            422,
            "validation.failed",
            "limit must be between 1 and 100.",
            {"field": "limit"},
        )

    return limit, None


def _is_organization_manager(organization: Organization, user_id: UUID) -> bool:
    return organization.created_by == user_id or (
        organization.managed_by is not None and organization.managed_by == user_id
    )


def _has_active_membership(
    db: Session, organization_id: UUID, user_id: UUID
) -> bool:
    return (
        db.query(TeamMembership)
        .join(Team, Team.id == TeamMembership.team_id)
        .filter(
            TeamMembership.user_id == user_id,
            TeamMembership.grantee_organization_id == organization_id,
            TeamMembership.grantee_organization_id == Team.organization_id,
            Team.is_active.is_(True),
        )
        .first()
        is not None
    )


def _require_organization_manager(
    request: Request,
    db: Session,
    organization_id: UUID,
    user_id: UUID,
) -> JSONResponse | None:
    # Team 관리 API는 organization owner/manager만 허용한다.
    # manager가 아닌 사용자는 active membership 여부로 403/404를 구분한다.
    organization = (
        db.query(Organization)
        .filter(
            Organization.id == organization_id,
            Organization.is_active.is_(True),
        )
        .first()
    )
    if organization is None:
        return _error_response(
            request,
            404,
            "resource.not_found",
            "Organization not found.",
        )

    if not _is_organization_manager(organization, user_id):
        # organization scope 밖이면 존재 여부를 숨기기 위해 404를 반환하고,
        # scope 안의 일반 member면 manager 권한 부족으로 403을 반환한다.
        if not _has_active_membership(db, organization_id, user_id):
            return _error_response(
                request,
                404,
                "resource.not_found",
                "Organization not found.",
            )
        return _error_response(
            request,
            403,
            "permission.denied",
            "Organization manager permission is required.",
        )

    return None


@router.get("", response_model=list[TeamResponse])
def list_teams(
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    limit: str = Query(default="10"),
    db: Session = Depends(get_db),
    auth_token: str | None = Cookie(default=None),
):
    current_user, error = _authenticate(request, db, auth_token)
    if error is not None:
        return error

    organization_id, error = _parse_organization_id(request, x_organization_id)
    if error is not None:
        return error

    parsed_limit, error = _parse_limit(request, limit)
    if error is not None:
        return error

    error = _require_organization_manager(
        request,
        db,
        organization_id,
        current_user.id,
    )
    if error is not None:
        return error

    return (
        db.query(Team)
        .filter(Team.organization_id == organization_id)
        .order_by(Team.name.asc(), Team.id.asc())
        .limit(parsed_limit)
        .all()
    )


@router.post(
    "",
    status_code=501,
    responses={
        501: {"description": "Team creation contract is not implemented yet."}
    },
)
def create_team(
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    auth_token: str | None = Cookie(default=None),
):
    current_user, error = _authenticate(request, db, auth_token)
    if error is not None:
        return error

    organization_id, error = _parse_organization_id(request, x_organization_id)
    if error is not None:
        return error

    error = _require_organization_manager(
        request,
        db,
        organization_id,
        current_user.id,
    )
    if error is not None:
        return error

    # 문서상 Request/Response 계약이 아직 TBD이므로, 지금은 문서화된
    # organization manager 권한 관문만 노출한다.
    return _error_response(
        request,
        501,
        "operation.not_implemented",
        "Team creation request and response contract is TBD.",
    )


# PATCH /teams/{team_id}는 수정 계약이 확정되기 전까지 권한 관문만 구현한다.
@router.patch(
    "/{team_id}",
    status_code=501,
    responses={
        501: {"description": "Team update contract is not implemented yet."}
    },
)
def update_team(
    team_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    auth_token: str | None = Cookie(default=None),
):
    # 현재는 route UUID validation만 사용하고, 실제 team 조회/수정은 계약 확정 후 추가한다.
    _ = team_id

    current_user, error = _authenticate(request, db, auth_token)
    if error is not None:
        return error

    organization_id, error = _parse_organization_id(request, x_organization_id)
    if error is not None:
        return error

    error = _require_organization_manager(
        request,
        db,
        organization_id,
        current_user.id,
    )
    if error is not None:
        return error

    # team_id는 확정될 PATCH 계약의 route 식별자다. 문서상 Request/Response
    # 계약이 아직 TBD이므로, 지금은 임의 update schema나 DB update를 만들지 않는다.
    return _error_response(
        request,
        501,
        "operation.not_implemented",
        "Team update request and response contract is TBD.",
    )


# POST /teams/{team_id}/members는 membership 추가 계약이 확정되기 전까지
# organization manager 권한 관문만 구현한다.
@router.post(
    "/{team_id}/members",
    status_code=501,
    responses={
        501: {
            "description": "Team member addition contract is not implemented yet."
        }
    },
)
def add_team_member(
    team_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    auth_token: str | None = Cookie(default=None),
):
    # 현재는 route UUID validation만 사용하고, 실제 membership 생성은 계약 확정 후 추가한다.
    _ = team_id

    current_user, error = _authenticate(request, db, auth_token)
    if error is not None:
        return error

    organization_id, error = _parse_organization_id(request, x_organization_id)
    if error is not None:
        return error

    error = _require_organization_manager(
        request,
        db,
        organization_id,
        current_user.id,
    )
    if error is not None:
        return error

    # 문서상 Request/Response 계약이 아직 TBD이므로, 지금은 임의 membership
    # request schema, response schema, DB insert를 만들지 않는다.
    return _error_response(
        request,
        501,
        "operation.not_implemented",
        "Team member addition request and response contract is TBD.",
    )


# DELETE /teams/{team_id}/members/{user_id}는 membership 제거 응답 계약이
# 확정되기 전까지 organization manager 권한 관문만 구현한다.
@router.delete(
    "/{team_id}/members/{user_id}",
    status_code=501,
    responses={
        501: {
            "description": "Team member removal contract is not implemented yet."
        }
    },
)
def remove_team_member(
    team_id: UUID,
    user_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    auth_token: str | None = Cookie(default=None),
):
    # 현재는 route UUID validation만 사용하고, 실제 membership 삭제는 계약 확정 후 추가한다.
    _ = (team_id, user_id)

    current_user, error = _authenticate(request, db, auth_token)
    if error is not None:
        return error

    organization_id, error = _parse_organization_id(request, x_organization_id)
    if error is not None:
        return error

    error = _require_organization_manager(
        request,
        db,
        organization_id,
        current_user.id,
    )
    if error is not None:
        return error

    # 문서상 Request는 없고 Response 상세는 TBD이므로, 지금은 임의 response
    # schema나 DB delete를 만들지 않는다.
    return _error_response(
        request,
        501,
        "operation.not_implemented",
        "Team member removal response contract is TBD.",
    )
