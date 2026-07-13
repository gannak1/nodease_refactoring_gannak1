import logging
import os
from collections.abc import Mapping
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from apps.gateway.auth.oauth import oauth
from apps.gateway.services.auth_return_service import AuthReturnService
from apps.gateway.services.auth_service import AuthService
from apps.shared.audit import record_audit
from apps.shared.audit.actions import AuditAction
from apps.shared.audit.context import get_current_metadata
from apps.shared.db.session import get_db
from apps.shared.schemas.auth import LoginRequest, LoginResponse, SignupRequest

router = APIRouter()
logger = logging.getLogger(__name__)


def _request_hostname(request: Request) -> str:
    try:
        return urlsplit(f"//{request.headers.get('host', '')}").hostname or ""
    except ValueError:
        return ""


def _is_loopback_hostname(hostname: str) -> bool:
    return hostname.lower() in {"localhost", "127.0.0.1", "::1"}


def _request_meta(request: Request) -> dict:
    """감사 로그용 요청 메타데이터(ip, user_agent)."""
    meta = get_current_metadata()
    if request.client and "ip" not in meta:
        meta["ip"] = request.client.host
    meta.setdefault("user_agent", request.headers.get("user-agent"))
    meta.setdefault("request_id", getattr(request.state, "request_id", None))
    return meta


def _user_snapshot(user) -> dict:
    return {"id": str(user.id), "email": user.email, "name": user.name}


def _record_auth_success(
    action: str,
    request: Request,
    user,
    **metadata,
) -> None:
    record_audit(
        action=action,
        category="action",
        actor_id=user.id,
        actor_type="user",
        metadata={
            **metadata,
            "actor": _user_snapshot(user),
            **_request_meta(request),
        },
    )


def _record_auth_failure(
    action: str,
    request: Request,
    email: str,
    error: Exception,
) -> None:
    record_audit(
        action=action,
        category="action",
        actor_type="system",
        status="failure",
        metadata={
            "email": email,
            "error_type": type(error).__name__,
            **_request_meta(request),
        },
    )


def _record_google_oauth_failure(request: Request, reason: str) -> None:
    record_audit(
        action=AuditAction.USER_LOGIN_FAILED,
        category="action",
        actor_type="system",
        status="failure",
        metadata={
            "provider": "google",
            "reason": reason,
            **_request_meta(request),
        },
    )


def _get_cookie_config(request: Request) -> tuple[bool, str | None]:
    """
    환경 감지 및 쿠키 도메인 설정 헬퍼 함수

    Returns:
        (is_production, cookie_domain)
    """
    host = _request_hostname(request)
    is_production = not _is_loopback_hostname(host)

    # 쿠키 도메인 (환경변수 우선, 없으면 호스트에서 자동 추출)
    cookie_domain = os.getenv("COOKIE_DOMAIN")
    if not cookie_domain and is_production:
        # api.moviepick.shop → .moviepick.shop
        parts = host.split(".")
        if len(parts) >= 2:
            cookie_domain = f".{'.'.join(parts[-2:])}"

    return is_production, cookie_domain


@router.post("/signup", response_model=LoginResponse)
def signup(
    request_obj: Request,
    request: SignupRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    이메일/비밀번호 회원가입

    Args:
        request_obj: FastAPI Request (호스트 확인용)
        request: 회원가입 요청 (email, password, name)
        response: FastAPI Response (쿠키 설정용)
        db: 데이터베이스 세션

    Returns:
        LoginResponse: 사용자 정보 + JWT 토큰
    """
    try:
        result = AuthService.signup(db, request)
    except Exception as e:
        _record_auth_failure(AuditAction.USER_SIGNUP_FAILED, request_obj, request.email, e)
        raise

    _record_auth_success(AuditAction.USER_SIGNUP, request_obj, result.user)

    # 환경 감지 및 쿠키 도메인 설정
    is_production, cookie_domain = _get_cookie_config(request_obj)

    cookie_params = {
        "key": "auth_token",
        "value": result.session.token,
        "httponly": True,
        "samesite": "none" if is_production else "lax",
        "max_age": 21600,  # 6시간
        "path": "/",
    }

    if is_production:
        cookie_params["secure"] = True
        if cookie_domain:
            cookie_params["domain"] = cookie_domain
    else:
        cookie_params["secure"] = False

    response.set_cookie(**cookie_params)

    return result


@router.post("/login", response_model=LoginResponse)
def login(
    request_obj: Request,
    request: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    이메일/비밀번호 로그인

    Args:
        request_obj: FastAPI Request (호스트 확인용)
        request: 로그인 요청 (email, password)
        response: FastAPI Response (쿠키 설정용)
        db: 데이터베이스 세션

    Returns:
        LoginResponse: 사용자 정보 + JWT 토큰
    """
    try:
        result = AuthService.login(db, request)
    except Exception as e:
        _record_auth_failure(AuditAction.USER_LOGIN_FAILED, request_obj, request.email, e)
        raise

    _record_auth_success(AuditAction.USER_LOGIN, request_obj, result.user)

    # 환경 감지 및 쿠키 도메인 설정
    is_production, cookie_domain = _get_cookie_config(request_obj)

    cookie_params = {
        "key": "auth_token",
        "value": result.session.token,
        "httponly": True,
        "samesite": "none" if is_production else "lax",
        "max_age": 21600,  # 6시간
        "path": "/",
    }

    if is_production:
        cookie_params["secure"] = True
        if cookie_domain:
            cookie_params["domain"] = cookie_domain
    else:
        cookie_params["secure"] = False

    response.set_cookie(**cookie_params)

    return result


@router.post("/logout")
def logout(request_obj: Request, response: Response):
    """로그아웃 - 쿠키 삭제"""
    # 환경 감지 및 쿠키 도메인 설정
    _, cookie_domain = _get_cookie_config(request_obj)

    # 쿠키 삭제 (설정 시와 동일한 domain으로)
    delete_params = {"key": "auth_token", "path": "/"}
    if cookie_domain:
        delete_params["domain"] = cookie_domain

    response.delete_cookie(**delete_params)

    # 로그아웃은 actor를 시그니처에서 알 수 없어(쿠키 삭제 시점) actor_id 없이 기록한다.
    record_audit(
        action=AuditAction.USER_LOGOUT,
        category="action",
        actor_type="user",
        metadata=_request_meta(request_obj),
    )
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=LoginResponse)
def get_current_user(request: Request, db: Session = Depends(get_db)):
    """
    현재 로그인된 사용자 정보 조회

    Args:
        request: FastAPI Request (쿠키 읽기용)
        db: 데이터베이스 세션

    Returns:
        LoginResponse: 사용자 정보 + 세션 정보
    """

    # 쿠키에서 토큰 가져오기
    token = request.cookies.get("auth_token")
    user = AuthService.get_user_from_token(db, token)

    from apps.shared.schemas.auth import SessionInfo, UserResponse

    return LoginResponse(
        user=UserResponse(
            id=str(user.id),
            email=user.email,
            name=user.name,
            created_at=user.created_at,
        ),
        session=SessionInfo(
            token=token,
            expires_at=AuthService.get_token_expiry(),
        ),
    )


# -----------------------------------------------------------------------------
# Google OAuth
# -----------------------------------------------------------------------------


@router.get("/google/login")
async def google_login(
    request: Request,
    next_path: str | None = Query(
        default=None,
        alias="next",
        max_length=2048,
    ),
):
    """
    구글 로그인 리디렉션
    - 로컬/배포 환경에 따라 redirect_uri를 동적으로 생성
    """
    # url_for는 현재 요청의 Host 헤더(또는 Forwarded 헤더)를 기반으로 절대 경로 생성
    redirect_uri = request.url_for("auth_google_callback")

    # https로 요청 보내도록 수정
    redirect_hostname = urlsplit(str(redirect_uri)).hostname or ""
    if not _is_loopback_hostname(redirect_hostname):
        redirect_uri = str(redirect_uri).replace("http://", "https://")

    AuthReturnService.remember(request, next_path)
    try:
        return await oauth.google.authorize_redirect(request, redirect_uri)
    except Exception as exc:
        AuthReturnService.consume(request)
        logger.warning(
            "Google OAuth start failed: error_type=%s",
            type(exc).__name__,
        )
        _record_google_oauth_failure(request, "oauth_start_failed")
        return Response(status_code=503, content="OAuth login is unavailable")


@router.get("/google/callback")
async def auth_google_callback(
    request: Request, response: Response, db: Session = Depends(get_db)
):
    """
    구글 로그인 콜백
    """
    return_path = AuthReturnService.consume(request)
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as exc:
        logger.warning(
            "Google OAuth callback token exchange failed: error_type=%s",
            type(exc).__name__,
        )
        _record_google_oauth_failure(request, "token_exchange_failed")
        return Response(status_code=400, content="OAuth authentication failed")

    if not isinstance(token, Mapping):
        logger.warning(
            "Google OAuth callback returned invalid token response: response_type=%s",
            type(token).__name__,
        )
        _record_google_oauth_failure(request, "invalid_token_response")
        return Response(status_code=400, content="OAuth authentication failed")

    # 사용자 정보 추출
    user_info = token.get("userinfo")
    if not isinstance(user_info, Mapping):
        try:
            user_info = await oauth.google.userinfo(token=token)
        except Exception as exc:
            logger.warning(
                "Google OAuth user info failed: error_type=%s",
                type(exc).__name__,
            )
            _record_google_oauth_failure(request, "user_info_failed")
            return Response(status_code=400, content="OAuth authentication failed")

    if not isinstance(user_info, Mapping):
        logger.warning(
            "Google OAuth callback returned invalid user info: response_type=%s",
            type(user_info).__name__,
        )
        _record_google_oauth_failure(request, "invalid_user_info")
        return Response(status_code=400, content="OAuth authentication failed")

    email = user_info.get("email")
    name = user_info.get("name", "Unknown")
    # Google의 sub 필드가 고유 ID
    social_id = user_info.get("sub")
    picture = user_info.get("picture")

    if not email:
        _record_google_oauth_failure(request, "email_missing")
        return Response(status_code=400, content="OAuth authentication failed")

    # 사용자 조회 또는 생성
    user = AuthService.get_or_create_social_user(
        db=db,
        email=email,
        name=name,
        social_provider="google",
        social_id=social_id,
        avatar_url=picture,
    )

    # 자체 JWT 토큰 생성
    AuthService.mark_login_success(db, user)
    access_token = AuthService.create_jwt_token(str(user.id))

    _record_auth_success(AuditAction.USER_LOGIN, request, user, provider="google")

    # 쿠키 설정
    is_production, cookie_domain = _get_cookie_config(request)

    redirect_url = AuthReturnService.build_client_redirect(request, return_path)

    redirect_response = RedirectResponse(url=redirect_url, status_code=302)
    redirect_response.set_cookie(
        key="auth_token",
        value=access_token,
        httponly=True,
        secure=is_production,
        samesite="lax",
        domain=cookie_domain,
        max_age=6 * 60 * 60,
    )

    return redirect_response
