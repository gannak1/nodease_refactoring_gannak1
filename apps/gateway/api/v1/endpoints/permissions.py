from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request
from sqlalchemy import func, inspect, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from apps.gateway.services.auth_service import AuthService
from apps.gateway.utils.api_errors import (
    auth_error_code,
    auth_error_message,
    parse_organization_id,
    raise_api_error,
)
from apps.shared.audit.context import get_current_metadata
from apps.shared.audit.logger import record_audit
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.team import (
    Team,
    TeamLLMPermission,
    TeamMembership,
    TeamWorkflowPermission,
    UserWorkflowPermission,
)
from apps.shared.db.models.user import User
from apps.shared.db.models.llm import LLMCredential
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.session import get_db
from apps.shared.schemas.permission import (
    PermissionGrantRequest,
    TeamLLMPermissionResponse,
    TeamWorkflowPermissionResponse,
    UserWorkflowPermissionResponse,
    WORKFLOW_AUTH_STATE_RANK,
)

router = APIRouter()


def _authenticate(
    request: Request,
    db: Session,
    auth_token: str | None,
) -> User:
    """쿠키 토큰으로 사용자를 인증하고 오류 형식을 맞춘다."""
    # 기존 AuthService 예외를 신규 API error envelope으로 변환한다.
    try:
        return AuthService.get_user_from_token(db, auth_token)
    except HTTPException as exc:
        raise_api_error(
            request,
            exc.status_code,
            auth_error_code(exc, auth_token),
            auth_error_message(exc),
        )


def _is_organization_manager(organization: Organization, user_id: UUID) -> bool:
    """사용자가 organization owner 또는 managed_by 관리자인지 판정한다."""
    return organization.created_by == user_id or (
        organization.managed_by is not None and organization.managed_by == user_id
    )


def _has_active_membership(
    db: Session,
    organization_id: UUID,
    user_id: UUID,
) -> bool:
    """사용자의 활성 team membership 보유 여부를 확인한다."""
    # 일반 사용자는 active team membership이 있어야 organization scope 안으로 본다.
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


def _normalize_workflow_auth_state(auth_state: str | None) -> str:
    """DB의 workflow 권한 값을 rank 비교 가능한 상태로 정규화한다."""
    # DB에는 string으로 저장되므로 알 수 없는 값은 fail-closed로 none 처리한다.
    value = str(auth_state or "none").lower()
    if value not in WORKFLOW_AUTH_STATE_RANK:
        return "none"
    return value


def _has_workflow_manage_permission(
    db: Session,
    organization_id: UUID,
    workflow_id: UUID,
    user_id: UUID,
) -> bool:
    """team 권한과 user-direct 권한을 합산해 manager 이상인지 계산한다."""
    team_permissions = (
        db.query(TeamWorkflowPermission)
        .join(
            TeamMembership,
            TeamMembership.team_id == TeamWorkflowPermission.team_id,
        )
        .join(Team, Team.id == TeamWorkflowPermission.team_id)
        .filter(
            TeamMembership.user_id == user_id,
            TeamWorkflowPermission.workflow_id == workflow_id,
            TeamWorkflowPermission.grantee_organization_id == organization_id,
            TeamMembership.grantee_organization_id
            == TeamWorkflowPermission.grantee_organization_id,
            Team.organization_id == TeamWorkflowPermission.grantee_organization_id,
            Team.is_active.is_(True),
        )
        .all()
    )
    user_permissions = (
        db.query(UserWorkflowPermission)
        .filter(
            UserWorkflowPermission.user_id == user_id,
            UserWorkflowPermission.workflow_id == workflow_id,
            UserWorkflowPermission.grantee_organization_id == organization_id,
        )
        .all()
    )

    best_rank = WORKFLOW_AUTH_STATE_RANK["none"]
    for permission in [*team_permissions, *user_permissions]:
        state = _normalize_workflow_auth_state(permission.auth_state)
        best_rank = max(best_rank, WORKFLOW_AUTH_STATE_RANK[state])

    return best_rank >= WORKFLOW_AUTH_STATE_RANK["manager"]


def _has_llm_credential_manage_permission(
    db: Session,
    organization_id: UUID,
    credential_id: UUID,
    user_id: UUID,
) -> bool:
    """team 권한을 합산해 LLM credential manager 이상인지 계산한다."""
    team_permissions = (
        db.query(TeamLLMPermission)
        .join(
            TeamMembership,
            TeamMembership.team_id == TeamLLMPermission.team_id,
        )
        .join(Team, Team.id == TeamLLMPermission.team_id)
        .filter(
            TeamMembership.user_id == user_id,
            TeamLLMPermission.llm_credential_id == credential_id,
            TeamLLMPermission.grantee_organization_id == organization_id,
            TeamMembership.grantee_organization_id
            == TeamLLMPermission.grantee_organization_id,
            Team.organization_id == TeamLLMPermission.grantee_organization_id,
            Team.is_active.is_(True),
        )
        .all()
    )

    best_rank = WORKFLOW_AUTH_STATE_RANK["none"]
    for permission in team_permissions:
        state = _normalize_workflow_auth_state(permission.auth_state)
        best_rank = max(best_rank, WORKFLOW_AUTH_STATE_RANK[state])

    return best_rank >= WORKFLOW_AUTH_STATE_RANK["manager"]


def _lock_team_workflow_permission_key(
    db: Session,
    organization_id: UUID,
    workflow_id: UUID,
    team_id: UUID,
) -> None:
    """권한 natural key 단위로 pre-read와 upsert 사이의 감사 레이스를 막는다."""
    lock_key = f"{organization_id}:{workflow_id}:{team_id}"
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtext("team_workflow_permission"),
                func.hashtext(lock_key),
            )
        )
    )


def _lock_team_llm_permission_key(
    db: Session,
    organization_id: UUID,
    credential_id: UUID,
    team_id: UUID,
) -> None:
    """권한 natural key 단위로 pre-read와 upsert 사이의 감사 레이스를 막는다."""
    lock_key = f"{organization_id}:{credential_id}:{team_id}"
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtext("team_llm_permission"),
                func.hashtext(lock_key),
            )
        )
    )


def _lock_user_workflow_permission_key(
    db: Session,
    organization_id: UUID,
    workflow_id: UUID,
    user_id: UUID,
) -> None:
    """권한 natural key 단위로 pre-read와 upsert 사이의 감사 레이스를 막는다."""
    # 같은 user/workflow 권한 row를 동시에 수정해도 감사 before 값이 섞이지 않게 잠근다.
    lock_key = f"{organization_id}:{workflow_id}:{user_id}"
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtext("user_workflow_permission"),
                func.hashtext(lock_key),
            )
        )
    )


def _permission_audit_columns(permission: TeamWorkflowPermission) -> dict:
    """감사 로그에 기록할 permission column 값을 dict로 추출한다."""
    return {
        attr.key: getattr(permission, attr.key, None)
        for attr in inspect(permission).mapper.column_attrs
    }


def _changed_permission_columns(before: dict, after: dict) -> tuple[dict, dict]:
    """권한 row의 변경된 column만 before/after dict로 분리한다."""
    before_changes = {}
    after_changes = {}
    for key, after_value in after.items():
        before_value = before.get(key)
        if before_value == after_value:
            continue
        before_changes[key] = before_value
        after_changes[key] = after_value
    return before_changes, after_changes


def _record_team_workflow_permission_audit(
    current_user: User,
    permission: TeamWorkflowPermission,
    before: dict | None,
    after: dict,
) -> None:
    """Core upsert가 우회한 권한 변경 감사를 직접 남긴다."""
    metadata = get_current_metadata()
    metadata["actor"] = {
        "id": str(current_user.id),
        "email": getattr(current_user, "email", None),
        "name": getattr(current_user, "name", None),
    }

    if before is None:
        action = "team_workflow_permission.created"
        audit_before = None
        audit_after = after
    else:
        audit_before, audit_after = _changed_permission_columns(before, after)
        if not audit_before and not audit_after:
            return
        action = "team_workflow_permission.updated"

    record_audit(
        action=action,
        category="data_change",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="team_workflow_permission",
        target_id=permission.id,
        before=audit_before,
        after=audit_after,
        metadata=metadata,
    )


def _record_team_workflow_permission_delete_audit(
    current_user: User,
    permission: TeamWorkflowPermission,
    before: dict,
) -> None:
    """team-workflow 권한 회수 감사를 직접 남긴다."""
    metadata = get_current_metadata()
    metadata["actor"] = {
        "id": str(current_user.id),
        "email": getattr(current_user, "email", None),
        "name": getattr(current_user, "name", None),
    }

    record_audit(
        action="team_workflow_permission.deleted",
        category="data_change",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="team_workflow_permission",
        target_id=permission.id,
        before=before,
        after=None,
        metadata=metadata,
    )


def _record_team_llm_permission_audit(
    current_user: User,
    permission: TeamLLMPermission,
    before: dict | None,
    after: dict,
) -> None:
    """Core upsert가 우회한 LLM credential team 권한 변경 감사를 직접 남긴다."""
    metadata = get_current_metadata()
    metadata["actor"] = {
        "id": str(current_user.id),
        "email": getattr(current_user, "email", None),
        "name": getattr(current_user, "name", None),
    }

    if before is None:
        action = "team_llm_permission.created"
        audit_before = None
        audit_after = after
    else:
        audit_before, audit_after = _changed_permission_columns(before, after)
        if not audit_before and not audit_after:
            return
        action = "team_llm_permission.updated"

    record_audit(
        action=action,
        category="data_change",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="team_llm_permission",
        target_id=permission.id,
        before=audit_before,
        after=audit_after,
        metadata=metadata,
    )


def _record_user_workflow_permission_audit(
    current_user: User,
    permission: UserWorkflowPermission,
    before: dict | None,
    after: dict,
) -> None:
    """Core upsert가 우회한 user-workflow 권한 변경 감사를 직접 남긴다."""
    # Core upsert는 ORM 이벤트를 타지 않으므로 endpoint에서 audit payload를 직접 구성한다.
    metadata = get_current_metadata()
    metadata["actor"] = {
        "id": str(current_user.id),
        "email": getattr(current_user, "email", None),
        "name": getattr(current_user, "name", None),
    }

    if before is None:
        action = "user_workflow_permission.created"
        audit_before = None
        audit_after = after
    else:
        # 변경이 없는 upsert는 감사 로그를 남기지 않는다.
        audit_before, audit_after = _changed_permission_columns(before, after)
        if not audit_before and not audit_after:
            return
        action = "user_workflow_permission.updated"

    record_audit(
        action=action,
        category="data_change",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="user_workflow_permission",
        target_id=permission.id,
        before=audit_before,
        after=audit_after,
        metadata=metadata,
    )


def _record_user_workflow_permission_delete_audit(
    current_user: User,
    permission: UserWorkflowPermission,
    before: dict,
) -> None:
    """user-workflow 권한 회수 감사를 직접 남긴다."""
    metadata = get_current_metadata()
    metadata["actor"] = {
        "id": str(current_user.id),
        "email": getattr(current_user, "email", None),
        "name": getattr(current_user, "name", None),
    }

    record_audit(
        action="user_workflow_permission.deleted",
        category="data_change",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="user_workflow_permission",
        target_id=permission.id,
        before=before,
        after=None,
        metadata=metadata,
    )


def _authorize_team_workflow_permission_change(
    request: Request,
    db: Session,
    current_user: User,
    organization_id: UUID,
    workflow_id: UUID,
    team_id: UUID,
) -> tuple[Organization, Workflow, Team]:
    """team workflow permission 변경 공통 scope와 manage 권한을 검증한다."""
    # 먼저 organization scope를 확정한다. scope 밖이면 리소스 존재 여부를 숨긴다.
    organization = (
        db.query(Organization)
        .filter(
            Organization.id == organization_id,
            Organization.is_active.is_(True),
        )
        .first()
    )
    if organization is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Organization not found.",
        )

    is_organization_manager = _is_organization_manager(
        organization,
        current_user.id,
    )
    # organization manager는 active membership 없이도 권한 관리가 가능하다.
    if not is_organization_manager and not _has_active_membership(
        db,
        organization_id,
        current_user.id,
    ):
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Organization not found.",
        )

    # 대상 workflow는 요청 organization 안에 있어야 한다.
    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.organization_id == organization_id,
        )
        .first()
    )
    if workflow is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Workflow not found.",
        )

    # inactive team에는 workflow 권한을 부여하거나 회수하지 않는다.
    team = (
        db.query(Team)
        .filter(
            Team.id == team_id,
            Team.organization_id == organization_id,
            Team.is_active.is_(True),
        )
        .first()
    )
    if team is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Team not found.",
        )

    # 최종 허용 주체는 organization manager 또는 workflow manager다.
    if not is_organization_manager and not _has_workflow_manage_permission(
        db,
        organization_id,
        workflow_id,
        current_user.id,
    ):
        raise_api_error(
            request,
            403,
            "permission.denied",
            "Workflow manage or organization manager permission is required.",
        )

    return organization, workflow, team


def _authorize_team_llm_permission_change(
    request: Request,
    db: Session,
    current_user: User,
    organization_id: UUID,
    credential_id: UUID,
    team_id: UUID,
) -> tuple[Organization, LLMCredential, Team]:
    """team LLM credential permission 변경 공통 scope와 manage 권한을 검증한다."""
    organization = (
        db.query(Organization)
        .filter(
            Organization.id == organization_id,
            Organization.is_active.is_(True),
        )
        .first()
    )
    if organization is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Organization not found.",
        )

    is_organization_manager = _is_organization_manager(
        organization,
        current_user.id,
    )
    if not is_organization_manager and not _has_active_membership(
        db,
        organization_id,
        current_user.id,
    ):
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Organization not found.",
        )

    credential = (
        db.query(LLMCredential)
        .filter(
            LLMCredential.id == credential_id,
            LLMCredential.organization_id == organization_id,
            LLMCredential.is_valid.is_(True),
        )
        .first()
    )
    if credential is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "LLM credential not found.",
        )

    team = (
        db.query(Team)
        .filter(
            Team.id == team_id,
            Team.organization_id == organization_id,
            Team.is_active.is_(True),
        )
        .first()
    )
    if team is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Team not found.",
        )

    if not is_organization_manager and not _has_llm_credential_manage_permission(
        db,
        organization_id,
        credential_id,
        current_user.id,
    ):
        raise_api_error(
            request,
            403,
            "permission.denied",
            "Credential manage or organization manager permission is required.",
        )

    return organization, credential, team


def _authorize_user_workflow_permission_change(
    request: Request,
    db: Session,
    current_user: User,
    organization_id: UUID,
    workflow_id: UUID,
    user_id: UUID,
) -> tuple[Organization, Workflow, User]:
    """user workflow permission 변경 공통 scope와 manage 권한을 검증한다."""
    # 먼저 organization scope를 확정한다. scope 밖이면 리소스 존재 여부를 숨긴다.
    organization = (
        db.query(Organization)
        .filter(
            Organization.id == organization_id,
            Organization.is_active.is_(True),
        )
        .first()
    )
    if organization is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Organization not found.",
        )

    is_organization_manager = _is_organization_manager(
        organization,
        current_user.id,
    )
    # organization manager는 active membership 없이도 권한 관리가 가능하다.
    if not is_organization_manager and not _has_active_membership(
        db,
        organization_id,
        current_user.id,
    ):
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Organization not found.",
        )

    # 대상 workflow는 요청 organization 안에 있어야 한다.
    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.organization_id == organization_id,
        )
        .first()
    )
    if workflow is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Workflow not found.",
        )

    # 비활성화된 user에는 direct workflow permission을 부여하지 않는다.
    target_user = (
        db.query(User)
        .filter(
            User.id == user_id,
            User.deactivated_at.is_(None),
        )
        .first()
    )
    if target_user is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "User not found.",
        )

    target_is_organization_manager = _is_organization_manager(organization, user_id)
    # 대상 user도 같은 organization의 manager이거나 active member여야 한다.
    if not target_is_organization_manager and not _has_active_membership(
        db,
        organization_id,
        user_id,
    ):
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "User not found.",
        )

    # 최종 허용 주체는 organization manager 또는 workflow manager다.
    if not is_organization_manager and not _has_workflow_manage_permission(
        db,
        organization_id,
        workflow_id,
        current_user.id,
    ):
        raise_api_error(
            request,
            403,
            "permission.denied",
            "Workflow manage or organization manager permission is required.",
        )

    return organization, workflow, target_user


def _upsert_team_workflow_permission(
    db: Session,
    current_user: User,
    organization_id: UUID,
    workflow_id: UUID,
    team_id: UUID,
    auth_state: str,
    assigned_by: UUID,
    assigned_at: datetime,
) -> TeamWorkflowPermission:
    """team-workflow 권한을 원자적으로 생성/수정하고 감사 로그를 남긴다."""
    _lock_team_workflow_permission_key(db, organization_id, workflow_id, team_id)
    existing_permission = (
        db.query(TeamWorkflowPermission)
        .filter(
            TeamWorkflowPermission.grantee_organization_id == organization_id,
            TeamWorkflowPermission.workflow_id == workflow_id,
            TeamWorkflowPermission.team_id == team_id,
        )
        .first()
    )
    before = (
        _permission_audit_columns(existing_permission)
        if existing_permission is not None
        else None
    )

    # PostgreSQL upsert로 같은 권한 row를 동시에 생성하려는 요청도 DB에서 원자적으로 처리한다.
    insert_stmt = pg_insert(TeamWorkflowPermission).values(
        grantee_organization_id=organization_id,
        workflow_id=workflow_id,
        team_id=team_id,
        auth_state=auth_state,
        assigned_by=assigned_by,
        assigned_at=assigned_at,
        options={},
        flags=0,
    )
    upsert_stmt = (
        insert_stmt.on_conflict_do_update(
            index_elements=[
                TeamWorkflowPermission.grantee_organization_id,
                TeamWorkflowPermission.workflow_id,
                TeamWorkflowPermission.team_id,
            ],
            set_={
                "auth_state": insert_stmt.excluded.auth_state,
                "assigned_by": insert_stmt.excluded.assigned_by,
                "assigned_at": insert_stmt.excluded.assigned_at,
            },
            where=TeamWorkflowPermission.auth_state
            != insert_stmt.excluded.auth_state,
        )
        .returning(TeamWorkflowPermission)
        .execution_options(populate_existing=True)
    )

    permission = db.scalars(upsert_stmt).one_or_none()
    if permission is None:
        permission = existing_permission
    after = _permission_audit_columns(permission)
    db.commit()
    _record_team_workflow_permission_audit(
        current_user,
        permission,
        before,
        after,
    )
    return permission


def _upsert_user_workflow_permission(
    db: Session,
    current_user: User,
    organization_id: UUID,
    workflow_id: UUID,
    user_id: UUID,
    auth_state: str,
    assigned_by: UUID,
    assigned_at: datetime,
) -> UserWorkflowPermission:
    """user-workflow 권한을 원자적으로 생성/수정하고 감사 로그를 남긴다."""
    _lock_user_workflow_permission_key(db, organization_id, workflow_id, user_id)
    # upsert 전 기존 row를 읽어 감사 로그의 before 값으로 사용한다.
    existing_permission = (
        db.query(UserWorkflowPermission)
        .filter(
            UserWorkflowPermission.grantee_organization_id == organization_id,
            UserWorkflowPermission.workflow_id == workflow_id,
            UserWorkflowPermission.user_id == user_id,
        )
        .first()
    )
    before = (
        _permission_audit_columns(existing_permission)
        if existing_permission is not None
        else None
    )

    # PostgreSQL upsert로 같은 권한 row를 동시에 생성하려는 요청도 DB에서 원자적으로 처리한다.
    insert_stmt = pg_insert(UserWorkflowPermission).values(
        grantee_organization_id=organization_id,
        workflow_id=workflow_id,
        user_id=user_id,
        auth_state=auth_state,
        assigned_by=assigned_by,
        assigned_at=assigned_at,
        options={},
        flags=0,
    )
    upsert_stmt = (
        insert_stmt.on_conflict_do_update(
            index_elements=[
                UserWorkflowPermission.grantee_organization_id,
                UserWorkflowPermission.user_id,
                UserWorkflowPermission.workflow_id,
            ],
            set_={
                "auth_state": insert_stmt.excluded.auth_state,
                "assigned_by": insert_stmt.excluded.assigned_by,
                "assigned_at": insert_stmt.excluded.assigned_at,
            },
            where=UserWorkflowPermission.auth_state
            != insert_stmt.excluded.auth_state,
        )
        .returning(UserWorkflowPermission)
        .execution_options(populate_existing=True)
    )

    permission = db.scalars(upsert_stmt).one_or_none()
    if permission is None:
        # 같은 auth_state PUT은 no-op이므로 returning row가 없고 기존 row를 응답에 재사용한다.
        permission = existing_permission
    after = _permission_audit_columns(permission)
    db.commit()
    _record_user_workflow_permission_audit(
        current_user,
        permission,
        before,
        after,
    )
    return permission


def _upsert_team_llm_permission(
    db: Session,
    current_user: User,
    organization_id: UUID,
    credential_id: UUID,
    team_id: UUID,
    auth_state: str,
    assigned_by: UUID,
    assigned_at: datetime,
) -> TeamLLMPermission:
    """team-LLM credential 권한을 원자적으로 생성/수정하고 감사 로그를 남긴다."""
    _lock_team_llm_permission_key(db, organization_id, credential_id, team_id)
    existing_permission = (
        db.query(TeamLLMPermission)
        .filter(
            TeamLLMPermission.grantee_organization_id == organization_id,
            TeamLLMPermission.llm_credential_id == credential_id,
            TeamLLMPermission.team_id == team_id,
        )
        .first()
    )
    before = (
        _permission_audit_columns(existing_permission)
        if existing_permission is not None
        else None
    )

    insert_stmt = pg_insert(TeamLLMPermission).values(
        grantee_organization_id=organization_id,
        llm_credential_id=credential_id,
        team_id=team_id,
        auth_state=auth_state,
        assigned_by=assigned_by,
        assigned_at=assigned_at,
        options={},
        flags=0,
    )
    upsert_stmt = (
        insert_stmt.on_conflict_do_update(
            index_elements=[
                TeamLLMPermission.grantee_organization_id,
                TeamLLMPermission.llm_credential_id,
                TeamLLMPermission.team_id,
            ],
            set_={
                "auth_state": insert_stmt.excluded.auth_state,
                "assigned_by": insert_stmt.excluded.assigned_by,
                "assigned_at": insert_stmt.excluded.assigned_at,
            },
            where=TeamLLMPermission.auth_state != insert_stmt.excluded.auth_state,
        )
        .returning(TeamLLMPermission)
        .execution_options(populate_existing=True)
    )

    permission = db.scalars(upsert_stmt).one_or_none()
    if permission is None:
        permission = existing_permission
    after = _permission_audit_columns(permission)
    db.commit()
    _record_team_llm_permission_audit(
        current_user,
        permission,
        before,
        after,
    )
    return permission


@router.put(
    "/workflows/{workflow_id}/teams/{team_id}",
    response_model=TeamWorkflowPermissionResponse,
)
def put_team_workflow_permission(
    workflow_id: UUID,
    team_id: UUID,
    payload: PermissionGrantRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    auth_token: str | None = Cookie(default=None),
):
    """team에 workflow 권한을 부여하거나 갱신하는 PUT endpoint."""
    current_user = _authenticate(request, db, auth_token)
    organization_id = parse_organization_id(request, x_organization_id)
    _authorize_team_workflow_permission_change(
        request,
        db,
        current_user,
        organization_id,
        workflow_id,
        team_id,
    )

    now = datetime.now(timezone.utc)
    return _upsert_team_workflow_permission(
        db,
        current_user,
        organization_id,
        workflow_id,
        team_id,
        payload.auth_state,
        current_user.id,
        now,
    )


@router.put(
    "/llm-credentials/{credential_id}/teams/{team_id}",
    response_model=TeamLLMPermissionResponse,
)
def put_team_llm_permission(
    credential_id: UUID,
    team_id: UUID,
    payload: PermissionGrantRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    auth_token: str | None = Cookie(default=None),
):
    """team에 LLM credential 권한을 부여하거나 갱신하는 PUT endpoint."""
    current_user = _authenticate(request, db, auth_token)
    organization_id = parse_organization_id(request, x_organization_id)
    _authorize_team_llm_permission_change(
        request,
        db,
        current_user,
        organization_id,
        credential_id,
        team_id,
    )

    now = datetime.now(timezone.utc)
    return _upsert_team_llm_permission(
        db,
        current_user,
        organization_id,
        credential_id,
        team_id,
        payload.auth_state,
        current_user.id,
        now,
    )


@router.put(
    "/workflows/{workflow_id}/users/{user_id}",
    response_model=UserWorkflowPermissionResponse,
)
def put_user_workflow_permission(
    workflow_id: UUID,
    user_id: UUID,
    payload: PermissionGrantRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    auth_token: str | None = Cookie(default=None),
):
    """user에 workflow 직접 권한을 부여하거나 갱신하는 PUT endpoint."""
    current_user = _authenticate(request, db, auth_token)
    organization_id = parse_organization_id(request, x_organization_id)
    # scope, 대상 user 상태, 부여자 권한을 모두 통과해야 permission row를 만든다.
    _authorize_user_workflow_permission_change(
        request,
        db,
        current_user,
        organization_id,
        workflow_id,
        user_id,
    )

    now = datetime.now(timezone.utc)
    return _upsert_user_workflow_permission(
        db,
        current_user,
        organization_id,
        workflow_id,
        user_id,
        payload.auth_state,
        current_user.id,
        now,
    )


@router.delete("/workflows/{workflow_id}/teams/{team_id}")
def delete_team_workflow_permission(
    workflow_id: UUID,
    team_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    auth_token: str | None = Cookie(default=None),
):
    """team의 workflow 권한을 회수하는 DELETE endpoint."""
    current_user = _authenticate(request, db, auth_token)
    organization_id = parse_organization_id(request, x_organization_id)
    _authorize_team_workflow_permission_change(
        request,
        db,
        current_user,
        organization_id,
        workflow_id,
        team_id,
    )

    permission = (
        db.query(TeamWorkflowPermission)
        .filter(
            TeamWorkflowPermission.grantee_organization_id == organization_id,
            TeamWorkflowPermission.workflow_id == workflow_id,
            TeamWorkflowPermission.team_id == team_id,
        )
        .first()
    )
    if permission is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Team workflow permission not found.",
        )

    before = _permission_audit_columns(permission)
    db.delete(permission)
    db.commit()
    _record_team_workflow_permission_delete_audit(
        current_user,
        permission,
        before,
    )
    return {"message": "Team workflow permission deleted", "id": str(permission.id)}


@router.delete("/workflows/{workflow_id}/users/{user_id}")
def delete_user_workflow_permission(
    workflow_id: UUID,
    user_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    auth_token: str | None = Cookie(default=None),
):
    """user의 workflow 직접 권한을 회수하는 DELETE endpoint."""
    current_user = _authenticate(request, db, auth_token)
    organization_id = parse_organization_id(request, x_organization_id)
    _authorize_user_workflow_permission_change(
        request,
        db,
        current_user,
        organization_id,
        workflow_id,
        user_id,
    )

    _lock_user_workflow_permission_key(db, organization_id, workflow_id, user_id)
    permission = (
        db.query(UserWorkflowPermission)
        .filter(
            UserWorkflowPermission.grantee_organization_id == organization_id,
            UserWorkflowPermission.workflow_id == workflow_id,
            UserWorkflowPermission.user_id == user_id,
        )
        .first()
    )
    if permission is None:
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "User workflow permission not found.",
        )

    before = _permission_audit_columns(permission)
    db.delete(permission)
    db.commit()
    _record_user_workflow_permission_delete_audit(
        current_user,
        permission,
        before,
    )
    return {"message": "User workflow permission deleted", "id": str(permission.id)}
