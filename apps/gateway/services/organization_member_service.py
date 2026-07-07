from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from apps.shared.audit.actions import AuditAction
from apps.shared.audit.context import get_current_metadata
from apps.shared.audit.logger import record_audit
from apps.shared.db.models.audit_log import AuditLog
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.organization_membership import (
    ORGANIZATION_AUTH_MEMBER,
    ORGANIZATION_AUTH_MANAGER,
    ORGANIZATION_MEMBERSHIP_ACTIVE,
    ORGANIZATION_MEMBERSHIP_INVITED,
    ORGANIZATION_MEMBERSHIP_REMOVED,
    ORGANIZATION_MEMBERSHIP_SUSPENDED,
    OrganizationMembership,
)
from apps.shared.db.models.team import (
    TeamMembership,
    UserLLMPermission,
    UserWorkflowPermission,
)
from apps.shared.db.models.user import User
from apps.shared.db.models.user_app_creation_permission import UserAppCreationPermission
from apps.shared.schemas.organization_membership import (
    OrganizationMemberInviteRequest,
    OrganizationMemberRemoveResponse,
    OrganizationMemberResponse,
    OrganizationMemberUpdateRequest,
    OrganizationSummaryResponse,
    RevokedUserPermissionCounts,
)
from apps.shared.services.permissions import (
    has_organization_manager_permission,
    has_organization_scope_access,
)

from .notification_service import publish_notifications_changed

VISIBLE_ORGANIZATION_STATES = {
    ORGANIZATION_MEMBERSHIP_ACTIVE,
    ORGANIZATION_MEMBERSHIP_INVITED,
}
LIST_MEMBER_STATES = {
    ORGANIZATION_MEMBERSHIP_ACTIVE,
    ORGANIZATION_MEMBERSHIP_INVITED,
    ORGANIZATION_MEMBERSHIP_SUSPENDED,
}
ALL_MEMBER_STATES = {
    *LIST_MEMBER_STATES,
    ORGANIZATION_MEMBERSHIP_REMOVED,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _flush_or_conflict(db: Session, message: str) -> None:
    # INSERT는 commit이 아니라 flush 시점에 실행되므로, unique 충돌을 409로
    # 변환하려면 flush를 감싸야 한다. commit을 감싸면 race를 놓친다.
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=message) from exc


def _get_active_organization(db: Session, organization_id: Any) -> Organization:
    organization = (
        db.query(Organization)
        .filter(
            Organization.id == organization_id,
            Organization.is_active.is_(True),
        )
        .first()
    )
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return organization


def _get_active_user(db: Session, user_id: Any) -> User:
    user = (
        db.query(User)
        .filter(
            User.id == user_id,
            User.deactivated_at.is_(None),
        )
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


def _get_membership(
    db: Session,
    organization_id: Any,
    user_id: Any,
) -> OrganizationMembership | None:
    return (
        db.query(OrganizationMembership)
        .options(joinedload(OrganizationMembership.user))
        .filter(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
        )
        .first()
    )


def _ensure_manager(db: Session, current_user: User, organization_id: Any) -> None:
    if has_organization_manager_permission(db, current_user.id, organization_id):
        return
    if not has_organization_scope_access(db, current_user.id, organization_id):
        raise HTTPException(status_code=404, detail="Organization not found.")
    detail = "Organization manager permission is required."
    record_audit(
        action=AuditAction.PERMISSION_DENIED,
        category="action",
        actor_id=current_user.id,
        actor_type="user",
        target_type="organization",
        target_id=organization_id,
        status="failure",
        metadata={
            **get_current_metadata(),
            "actor": _actor_snapshot(current_user),
            "policy_result": "deny",
            "resource_type": "organization",
            "resource_id": str(organization_id),
            "required_permission": ORGANIZATION_AUTH_MANAGER,
            "permission_action": "manage_members",
            "effective_auth_state": ORGANIZATION_AUTH_MEMBER,
            "status_code": 403,
            "detail": detail,
        },
    )
    exc = HTTPException(
        status_code=403,
        detail=detail,
    )
    setattr(exc, "audit_recorded", True)
    raise exc


def _member_response(membership: OrganizationMembership) -> OrganizationMemberResponse:
    user = membership.user
    return OrganizationMemberResponse(
        id=membership.id,
        organization_id=membership.organization_id,
        user_id=membership.user_id,
        user_email=user.email,
        user_name=user.name,
        membership_state=membership.membership_state,
        organization_auth_state=membership.organization_auth_state,
        invited_by=membership.invited_by,
        invited_at=membership.invited_at,
        accepted_at=membership.accepted_at,
        removed_at=membership.removed_at,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


def _organization_summary(
    organization: Organization,
    membership: OrganizationMembership,
) -> OrganizationSummaryResponse:
    return OrganizationSummaryResponse(
        id=organization.id,
        name=organization.name,
        membership_state=membership.membership_state,
        organization_auth_state=membership.organization_auth_state,
        is_active=organization.is_active,
    )


def _audit_metadata(
    membership: OrganizationMembership,
    *,
    previous_membership_state: str | None = None,
    next_membership_state: str | None = None,
    previous_organization_auth_state: str | None = None,
    next_organization_auth_state: str | None = None,
    cleanup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "organization_id": str(membership.organization_id),
        "membership_id": str(membership.id),
        "target_user_id": str(membership.user_id),
    }
    if previous_membership_state is not None:
        metadata["previous_membership_state"] = previous_membership_state
    if next_membership_state is not None:
        metadata["next_membership_state"] = next_membership_state
    if previous_organization_auth_state is not None:
        metadata["previous_organization_auth_state"] = previous_organization_auth_state
    if next_organization_auth_state is not None:
        metadata["next_organization_auth_state"] = next_organization_auth_state
    if cleanup is not None:
        metadata["cleanup"] = cleanup
    return metadata


def _actor_snapshot(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": getattr(user, "email", None),
        "name": getattr(user, "name", None),
    }


def _merge_audit_context(
    current_user: User,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    enriched = get_current_metadata()
    enriched["actor"] = _actor_snapshot(current_user)
    enriched.update(metadata)
    return enriched


def _add_audit_log(
    db: Session,
    action: str,
    current_user: User,
    membership: OrganizationMembership,
    metadata: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            action=action,
            category="action",
            actor_id=current_user.id,
            actor_type="user",
            target_type="organization_membership",
            target_id=str(membership.id),
            status="success",
            audit_metadata=_merge_audit_context(current_user, metadata),
        )
    )


def _locked_manager_count(db: Session, organization_id: Any) -> int:
    # count()는 row lock을 잡지 못하므로 실제 active manager row를 조회해 잠근다.
    # 이렇게 해야 동시 강등/삭제 요청이 같은 manager 수를 보고 함께 통과하지 않는다.
    active_managers = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.membership_state == ORGANIZATION_MEMBERSHIP_ACTIVE,
            OrganizationMembership.organization_auth_state == ORGANIZATION_AUTH_MANAGER,
        )
        # ponytail: id 정렬로 동시 강등/제거 시 락 획득 순서를 고정해 데드락 회피
        .order_by(OrganizationMembership.id)
        .with_for_update()
        .all()
    )
    return len(active_managers)


def _guard_last_manager(
    db: Session,
    membership: OrganizationMembership,
    next_membership_state: str,
    next_auth_state: str,
) -> None:
    if (
        membership.membership_state != ORGANIZATION_MEMBERSHIP_ACTIVE
        or membership.organization_auth_state != ORGANIZATION_AUTH_MANAGER
    ):
        return
    if (
        next_membership_state == ORGANIZATION_MEMBERSHIP_ACTIVE
        and next_auth_state == ORGANIZATION_AUTH_MANAGER
    ):
        return
    if _locked_manager_count(db, membership.organization_id) <= 1:
        raise HTTPException(
            status_code=409,
            detail="Cannot remove the last organization manager.",
        )


def _cleanup_counts(
    removed_team_memberships: int,
    revoked_user_permissions: RevokedUserPermissionCounts,
) -> dict[str, Any]:
    return {
        "team_memberships": removed_team_memberships,
        "user_workflow_permissions": revoked_user_permissions.workflow,
        "user_llm_permissions": revoked_user_permissions.llm_credential,
        "user_app_creation_permissions": revoked_user_permissions.app_creation,
        "user_knowledge_permissions": revoked_user_permissions.knowledge_base,
        "user_audit_permissions": revoked_user_permissions.audit,
    }


class OrganizationMemberService:
    @staticmethod
    def list_active_organizations(
        db: Session,
        current_user: User,
    ) -> list[Organization]:
        rows = (
            db.query(Organization, OrganizationMembership)
            .join(
                OrganizationMembership,
                OrganizationMembership.organization_id == Organization.id,
            )
            .filter(
                OrganizationMembership.user_id == current_user.id,
                OrganizationMembership.membership_state
                == ORGANIZATION_MEMBERSHIP_ACTIVE,
                Organization.is_active.is_(True),
            )
            .order_by(
                OrganizationMembership.accepted_at.asc().nulls_last(),
                OrganizationMembership.created_at.asc(),
                Organization.name.asc(),
            )
            .all()
        )
        return [organization for organization, _membership in rows]

    @staticmethod
    def list_organization_memberships(
        db: Session,
        current_user: User,
    ) -> list[OrganizationSummaryResponse]:
        rows = (
            db.query(Organization, OrganizationMembership)
            .join(
                OrganizationMembership,
                OrganizationMembership.organization_id == Organization.id,
            )
            .filter(
                OrganizationMembership.user_id == current_user.id,
                OrganizationMembership.membership_state.in_(
                    VISIBLE_ORGANIZATION_STATES
                ),
                Organization.is_active.is_(True),
            )
            .order_by(
                OrganizationMembership.accepted_at.asc().nulls_last(),
                OrganizationMembership.created_at.asc(),
                Organization.name.asc(),
            )
            .all()
        )
        return [
            _organization_summary(organization, membership)
            for organization, membership in rows
        ]

    @staticmethod
    def list_members(
        db: Session,
        current_user: User,
        organization_id: Any,
        state: str | None = None,
    ) -> list[OrganizationMemberResponse]:
        _get_active_organization(db, organization_id)
        _ensure_manager(db, current_user, organization_id)
        if state is not None:
            state = state.strip().lower()
            if state not in ALL_MEMBER_STATES:
                raise HTTPException(status_code=400, detail="Invalid membership state.")
            states = {state}
        else:
            states = LIST_MEMBER_STATES

        memberships = (
            db.query(OrganizationMembership)
            .options(joinedload(OrganizationMembership.user))
            .join(User, User.id == OrganizationMembership.user_id)
            .filter(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.membership_state.in_(states),
            )
            .order_by(User.name.asc(), User.email.asc(), OrganizationMembership.id.asc())
            .all()
        )
        return [_member_response(membership) for membership in memberships]

    @staticmethod
    def invite_member(
        db: Session,
        current_user: User,
        organization_id: Any,
        request: OrganizationMemberInviteRequest,
    ) -> OrganizationMemberResponse:
        _get_active_organization(db, organization_id)
        _ensure_manager(db, current_user, organization_id)
        if request.user_id == current_user.id:
            raise HTTPException(status_code=400, detail="Cannot invite yourself.")
        target_user = _get_active_user(db, request.user_id)
        membership = _get_membership(db, organization_id, request.user_id)
        if membership is not None:
            # 이미 활동 중이거나 초대 중이면 초대 요청을 멱등하게 처리한다.
            if membership.membership_state in {
                ORGANIZATION_MEMBERSHIP_ACTIVE,
                ORGANIZATION_MEMBERSHIP_INVITED,
            }:
                return _member_response(membership)
            if membership.membership_state == ORGANIZATION_MEMBERSHIP_SUSPENDED:
                raise HTTPException(
                    status_code=409,
                    detail="Suspended member must be reactivated with PATCH.",
                )

            # removed row는 unique 제약을 유지한 채 기존 membership을 재초대 상태로 되살린다.
            previous_state = membership.membership_state
            previous_auth_state = membership.organization_auth_state
            membership.membership_state = ORGANIZATION_MEMBERSHIP_INVITED
            membership.organization_auth_state = request.organization_auth_state
            membership.invited_by = current_user.id
            membership.invited_at = _now()
            membership.accepted_at = None
            membership.removed_at = None
        else:
            previous_state = None
            previous_auth_state = None
            membership = OrganizationMembership(
                organization_id=organization_id,
                user_id=request.user_id,
                membership_state=ORGANIZATION_MEMBERSHIP_INVITED,
                organization_auth_state=request.organization_auth_state,
                invited_by=current_user.id,
                invited_at=_now(),
            )
            membership.user = target_user
            db.add(membership)

        _flush_or_conflict(db, "Organization membership already exists.")
        _add_audit_log(
            db,
            AuditAction.ORGANIZATION_INVITE,
            current_user,
            membership,
            _audit_metadata(
                membership,
                previous_membership_state=previous_state,
                next_membership_state=membership.membership_state,
                previous_organization_auth_state=previous_auth_state,
                next_organization_auth_state=membership.organization_auth_state,
            ),
        )
        db.commit()
        publish_notifications_changed(membership.user_id)
        db.refresh(membership)
        return _member_response(membership)

    @staticmethod
    def accept_invitation(
        db: Session,
        current_user: User,
        organization_id: Any,
    ) -> OrganizationMemberResponse:
        _get_active_organization(db, organization_id)
        membership = _get_membership(db, organization_id, current_user.id)
        if membership is None:
            raise HTTPException(status_code=404, detail="Invitation not found.")
        if membership.membership_state == ORGANIZATION_MEMBERSHIP_ACTIVE:
            return _member_response(membership)
        if membership.membership_state != ORGANIZATION_MEMBERSHIP_INVITED:
            raise HTTPException(status_code=409, detail="Invitation cannot be accepted.")

        # 초대 수락은 사용자 본인만 수행하므로 manager 권한 검사를 하지 않는다.
        previous_state = membership.membership_state
        membership.membership_state = ORGANIZATION_MEMBERSHIP_ACTIVE
        membership.accepted_at = _now()
        membership.removed_at = None
        _add_audit_log(
            db,
            AuditAction.ORGANIZATION_MEMBER_ACCEPT,
            current_user,
            membership,
            _audit_metadata(
                membership,
                previous_membership_state=previous_state,
                next_membership_state=membership.membership_state,
            ),
        )
        db.commit()
        publish_notifications_changed(current_user.id)
        db.refresh(membership)
        return _member_response(membership)

    @staticmethod
    def decline_invitation(
        db: Session,
        current_user: User,
        organization_id: Any,
    ) -> OrganizationMemberResponse:
        _get_active_organization(db, organization_id)
        membership = _get_membership(db, organization_id, current_user.id)
        if membership is None:
            raise HTTPException(status_code=404, detail="Invitation not found.")
        if membership.membership_state != ORGANIZATION_MEMBERSHIP_INVITED:
            raise HTTPException(status_code=409, detail="Invitation cannot be declined.")

        previous_state = membership.membership_state
        membership.membership_state = ORGANIZATION_MEMBERSHIP_REMOVED
        membership.accepted_at = None
        membership.removed_at = _now()
        _add_audit_log(
            db,
            AuditAction.ORGANIZATION_MEMBER_DECLINE,
            current_user,
            membership,
            _audit_metadata(
                membership,
                previous_membership_state=previous_state,
                next_membership_state=membership.membership_state,
            ),
        )
        db.commit()
        publish_notifications_changed(current_user.id)
        db.refresh(membership)
        return _member_response(membership)

    @staticmethod
    def update_member(
        db: Session,
        current_user: User,
        organization_id: Any,
        user_id: Any,
        request: OrganizationMemberUpdateRequest,
    ) -> OrganizationMemberResponse:
        _get_active_organization(db, organization_id)
        _ensure_manager(db, current_user, organization_id)
        membership = _get_membership(db, organization_id, user_id)
        if membership is None:
            raise HTTPException(status_code=404, detail="Member not found.")
        if membership.membership_state == ORGANIZATION_MEMBERSHIP_REMOVED:
            raise HTTPException(
                status_code=409,
                detail="Removed member must be re-invited.",
            )
        provided_fields = request.model_fields_set & {
            "membership_state",
            "organization_auth_state",
        }
        if not provided_fields or all(
            getattr(request, field_name) is None for field_name in provided_fields
        ):
            raise HTTPException(status_code=400, detail="No update fields provided.")

        next_state = request.membership_state or membership.membership_state
        next_auth_state = (
            request.organization_auth_state or membership.organization_auth_state
        )
        if (
            membership.membership_state == ORGANIZATION_MEMBERSHIP_INVITED
            and request.membership_state is not None
        ):
            raise HTTPException(
                status_code=409,
                detail="Invited member must accept the invitation.",
            )
        if current_user.id == membership.user_id and (
            next_auth_state != membership.organization_auth_state
            or next_state != membership.membership_state
        ):
            # 본인 권한 강등/상태 변경은 마지막 manager 회피나 셀프 잠금을 막기 위해 금지한다.
            raise HTTPException(status_code=400, detail="Cannot update yourself.")
        if (
            next_state == membership.membership_state
            and next_auth_state == membership.organization_auth_state
        ):
            return _member_response(membership)

        _guard_last_manager(db, membership, next_state, next_auth_state)
        previous_state = membership.membership_state
        previous_auth_state = membership.organization_auth_state
        membership.membership_state = next_state
        membership.organization_auth_state = next_auth_state
        if next_state == ORGANIZATION_MEMBERSHIP_ACTIVE:
            membership.removed_at = None
        if next_state == ORGANIZATION_MEMBERSHIP_SUSPENDED:
            membership.removed_at = None

        _add_audit_log(
            db,
            AuditAction.ORGANIZATION_MEMBER_UPDATE,
            current_user,
            membership,
            _audit_metadata(
                membership,
                previous_membership_state=previous_state,
                next_membership_state=membership.membership_state,
                previous_organization_auth_state=previous_auth_state,
                next_organization_auth_state=membership.organization_auth_state,
            ),
        )
        db.commit()
        db.refresh(membership)
        return _member_response(membership)

    @staticmethod
    def remove_member(
        db: Session,
        current_user: User,
        organization_id: Any,
        user_id: Any,
    ) -> OrganizationMemberRemoveResponse:
        _get_active_organization(db, organization_id)
        _ensure_manager(db, current_user, organization_id)
        if current_user.id == user_id:
            raise HTTPException(status_code=400, detail="Cannot remove yourself.")
        membership = _get_membership(db, organization_id, user_id)
        if membership is None:
            raise HTTPException(status_code=404, detail="Member not found.")
        if membership.membership_state == ORGANIZATION_MEMBERSHIP_REMOVED:
            return OrganizationMemberRemoveResponse(
                status="removed",
                removed_team_memberships=0,
                revoked_user_permissions=RevokedUserPermissionCounts(),
            )

        _guard_last_manager(
            db,
            membership,
            ORGANIZATION_MEMBERSHIP_REMOVED,
            membership.organization_auth_state,
        )
        previous_state = membership.membership_state
        previous_auth_state = membership.organization_auth_state
        # 조직에서 제거되면 팀 소속과 사용자별 리소스 권한도 함께 회수한다.
        removed_team_memberships = (
            db.query(TeamMembership)
            .filter(
                TeamMembership.grantee_organization_id == organization_id,
                TeamMembership.user_id == user_id,
            )
            .delete(synchronize_session=False)
        )
        revoked_workflow_permissions = (
            db.query(UserWorkflowPermission)
            .filter(
                UserWorkflowPermission.grantee_organization_id == organization_id,
                UserWorkflowPermission.user_id == user_id,
            )
            .delete(synchronize_session=False)
        )
        revoked_llm_permissions = (
            db.query(UserLLMPermission)
            .filter(
                UserLLMPermission.grantee_organization_id == organization_id,
                UserLLMPermission.user_id == user_id,
            )
            .delete(synchronize_session=False)
        )
        revoked_app_creation_permissions = (
            db.query(UserAppCreationPermission)
            .filter(
                UserAppCreationPermission.grantee_organization_id == organization_id,
                UserAppCreationPermission.user_id == user_id,
            )
            .delete(synchronize_session=False)
        )
        membership.membership_state = ORGANIZATION_MEMBERSHIP_REMOVED
        membership.removed_at = _now()

        revoked_user_permissions = RevokedUserPermissionCounts(
            workflow=revoked_workflow_permissions,
            llm_credential=revoked_llm_permissions,
            app_creation=revoked_app_creation_permissions,
            knowledge_base=0,
            audit=0,
        )
        cleanup = _cleanup_counts(removed_team_memberships, revoked_user_permissions)
        _add_audit_log(
            db,
            AuditAction.ORGANIZATION_MEMBER_REMOVE,
            current_user,
            membership,
            _audit_metadata(
                membership,
                previous_membership_state=previous_state,
                next_membership_state=membership.membership_state,
                previous_organization_auth_state=previous_auth_state,
                next_organization_auth_state=membership.organization_auth_state,
                cleanup=cleanup,
            ),
        )
        _add_audit_log(
            db,
            AuditAction.PERMISSION_REVOKE,
            current_user,
            membership,
            {
                **_audit_metadata(membership, cleanup=cleanup),
                "reason": AuditAction.ORGANIZATION_MEMBER_REMOVE,
            },
        )
        db.commit()
        return OrganizationMemberRemoveResponse(
            status="removed",
            removed_team_memberships=removed_team_memberships,
            revoked_user_permissions=revoked_user_permissions,
        )


__all__ = ["OrganizationMemberService"]
