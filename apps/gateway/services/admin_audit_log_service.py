from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from apps.shared.db.models.audit_log import AuditLog, AuditStatus
from apps.shared.db.models.team import Team, TeamAuditPermission, TeamMembership
from apps.shared.db.models.user import User
from apps.shared.schemas.audit import (
    AuditLogDetailResponse,
    AuditLogListResponse,
    AuditLogSchema,
)
from apps.shared.permissions import AUTH_STATE_NONE
from apps.shared.schemas.permission import AUDIT_AUTH_STATE_RANK
from apps.shared.services.permission_audit import record_resource_permission_denied
from apps.shared.services.permissions import has_organization_manager_permission

KST = ZoneInfo("Asia/Seoul")
AUDIT_READER_RANK = AUDIT_AUTH_STATE_RANK["auditor"]
AUDIT_RESOURCE_TYPE = "audit"
AUDIT_READ_ACTION = "read"
DETAIL_METADATA_KEYS = {"organization_id", "request_id", "reason", "summary"}
SECRET_METADATA_KEYS = {
    "authorization",
    "encrypted_config",
    "payload",
    "raw_payload",
    "api_key",
    "token",
    "secret",
    "password",
}


@dataclass(frozen=True)
class AuditLogPeriod:
    start_at: datetime | None = None
    end_at: datetime | None = None


@dataclass(frozen=True)
class AdminAuditLogFilters:
    actor_id: UUID | None = None
    action: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    status: AuditStatus | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None


class AdminPermissionGuard:
    @staticmethod
    def require_audit_reader(db: Session, user: User, organization_id: Any) -> None:
        if has_organization_manager_permission(db, user.id, organization_id):
            return
        if _has_team_audit_reader_permission(db, user.id, organization_id):
            return
        _raise_audit_reader_denied(user.id, organization_id)


def _raise_audit_reader_denied(user_id: Any, organization_id: Any) -> None:
    record_resource_permission_denied(
        user_id=user_id,
        resource_type=AUDIT_RESOURCE_TYPE,
        resource_id=organization_id,
        action=AUDIT_READ_ACTION,
        effective_auth_state=AUTH_STATE_NONE,
        organization_id=organization_id,
    )
    exc = HTTPException(status_code=403, detail="Forbidden")
    setattr(exc, "audit_recorded", True)
    raise exc


class AdminAuditLogService:
    @staticmethod
    def resolve_period(
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> AuditLogPeriod:
        start = _ensure_timezone(start_at)
        end = _ensure_timezone(end_at)
        if start is not None and end is not None and end <= start:
            raise HTTPException(status_code=400, detail="Invalid period")
        return AuditLogPeriod(start_at=start, end_at=end)

    @staticmethod
    def list_audit_logs(
        db: Session,
        current_user: User,
        organization_id: Any,
        filters: AdminAuditLogFilters | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> AuditLogListResponse:
        AdminPermissionGuard.require_audit_reader(db, current_user, organization_id)
        filters = filters or AdminAuditLogFilters()
        query = _filtered_query(db, organization_id, filters)
        total = query.count()
        items = (
            query.order_by(desc(AuditLog.occurred_at), desc(AuditLog.id))
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return AuditLogListResponse(
            total=total,
            items=[_list_item(item) for item in items],
        )

    @staticmethod
    def get_audit_log_detail(
        db: Session,
        current_user: User,
        organization_id: Any,
        audit_log_id: Any,
    ) -> AuditLogDetailResponse:
        AdminPermissionGuard.require_audit_reader(db, current_user, organization_id)
        filters = AdminAuditLogFilters()
        item = (
            _filtered_query(db, organization_id, filters)
            .filter(AuditLog.id == audit_log_id)
            .first()
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Audit log not found")
        return AuditLogDetailResponse(
            **_list_item(item).model_dump(),
            audit_metadata=_detail_metadata(item.audit_metadata),
        )

    @staticmethod
    def sanitize_audit_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        if not metadata:
            return {}
        sanitized: dict[str, Any] = {}
        for key, value in metadata.items():
            if _is_secret_key(key):
                continue
            if isinstance(value, dict):
                sanitized[key] = AdminAuditLogService.sanitize_audit_metadata(value)
            else:
                sanitized[key] = value
        return sanitized


def _ensure_timezone(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=KST)
    return value


def _has_team_audit_reader_permission(
    db: Session,
    user_id: Any,
    organization_id: Any,
) -> bool:
    permissions = (
        db.query(TeamAuditPermission)
        .join(
            TeamMembership,
            (TeamMembership.team_id == TeamAuditPermission.team_id)
            & (
                TeamMembership.grantee_organization_id
                == TeamAuditPermission.grantee_organization_id
            ),
        )
        .join(Team, Team.id == TeamAuditPermission.team_id)
        .filter(
            TeamMembership.user_id == user_id,
            TeamMembership.grantee_organization_id == organization_id,
            TeamAuditPermission.grantee_organization_id == organization_id,
            TeamAuditPermission.target_organization_id == organization_id,
            Team.organization_id == organization_id,
            Team.is_active.is_(True),
        )
        .all()
    )
    return any(_has_audit_reader_rank(_audit_auth_state(row)) for row in permissions)


def _audit_auth_state(row: Any) -> str | None:
    return getattr(row, "auth_state", None)


def _has_audit_reader_rank(auth_state: str | None) -> bool:
    return AUDIT_AUTH_STATE_RANK.get(auth_state, 0) >= AUDIT_READER_RANK


def _filtered_query(
    db: Session,
    organization_id: Any,
    filters: AdminAuditLogFilters,
):
    query = db.query(AuditLog).filter(
        AuditLog.audit_metadata["organization_id"].astext == str(organization_id)
    )
    if filters.actor_id is not None:
        query = query.filter(AuditLog.actor_id == filters.actor_id)
    if filters.action is not None:
        query = query.filter(AuditLog.action == filters.action)
    if filters.target_type is not None:
        query = query.filter(AuditLog.target_type == filters.target_type)
    if filters.target_id is not None:
        query = query.filter(AuditLog.target_id == filters.target_id)
    if filters.status is not None:
        query = query.filter(AuditLog.status == filters.status)
    if filters.start_at is not None:
        query = query.filter(AuditLog.occurred_at >= filters.start_at)
    if filters.end_at is not None:
        query = query.filter(AuditLog.occurred_at < filters.end_at)
    return query


def _list_item(item: AuditLog) -> AuditLogSchema:
    return AuditLogSchema(
        id=item.id,
        occurred_at=item.occurred_at,
        actor_id=item.actor_id,
        actor_type=item.actor_type,
        category=item.category,
        action=item.action,
        target_type=item.target_type,
        target_id=item.target_id,
        status=item.status,
        request_id=(item.audit_metadata or {}).get("request_id"),
    )


def _detail_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    sanitized = AdminAuditLogService.sanitize_audit_metadata(metadata)
    return {key: sanitized[key] for key in DETAIL_METADATA_KEYS if key in sanitized}


def _is_secret_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in SECRET_METADATA_KEYS or any(
        marker in normalized for marker in ("api_key", "token", "secret", "password")
    )
