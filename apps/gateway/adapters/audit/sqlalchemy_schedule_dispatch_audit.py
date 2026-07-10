from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from apps.shared.db.models.audit_log import (
    ActorType,
    AuditCategory,
    AuditLog,
    AuditStatus,
)

_ALLOWED_ACTIONS = frozenset(
    {
        "schedule_dispatch.blocked",
        "schedule_dispatch.canceled",
        "schedule_dispatch.deferred",
    }
)


class SqlAlchemyScheduleDispatchAuditRecorder:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record_policy_result(
        self,
        *,
        organization_id: uuid.UUID,
        claim_id: uuid.UUID,
        action: str,
        reason: str,
    ) -> None:
        if action not in _ALLOWED_ACTIONS:
            raise ValueError("unsupported schedule dispatch audit action")
        self.db.add(
            AuditLog(
                action=action,
                category=AuditCategory.ACTION,
                actor_id=None,
                actor_type=ActorType.SYSTEM,
                target_type="schedule_dispatch_claim",
                target_id=str(claim_id),
                before=None,
                after=None,
                status=(
                    AuditStatus.FAILURE
                    if action != "schedule_dispatch.deferred"
                    else AuditStatus.SUCCESS
                ),
                audit_metadata={
                    "organization_id": str(organization_id),
                    "reason": reason,
                },
            )
        )

    def record_schedule_configuration_invalid(
        self,
        *,
        organization_id: uuid.UUID,
        schedule_id: uuid.UUID,
    ) -> None:
        self.db.add(
            AuditLog(
                action="schedule.configuration_invalid",
                category=AuditCategory.ACTION,
                actor_id=None,
                actor_type=ActorType.SYSTEM,
                target_type="schedule",
                target_id=str(schedule_id),
                before=None,
                after=None,
                status=AuditStatus.FAILURE,
                audit_metadata={
                    "organization_id": str(organization_id),
                    "reason": "schedule_configuration_invalid",
                },
            )
        )
