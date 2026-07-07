"""Budget alert helpers (docs/features/budget-alerts).

- `decide_alert_transition`: 당월 high-water mark 대비 상향 전이 임계 판정 (BGA-REQ-010, 013).
- `resolve_alert_recipients`: 제작자 + 조직 관리자 전원 수신자 산출 (BGA-REQ-020~022).
- `serialize_alert_item`: 알림 항목을 API 응답 dict로 직렬화, 금액 리댁션 (BGA-REQ-051, 052).
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from apps.shared.db.models.budget_alert import BudgetAlertState
from apps.shared.services.permissions import (
    has_organization_manager_permission,
    has_organization_scope_access,
)

# 상태 심각도. None/"normal"은 미알림(0), at_risk(1) < exceeded(2).
_SEVERITY = {None: 0, "normal": 0, "at_risk": 1, "exceeded": 2}


def decide_alert_transition(last_status: str | None, new_status: str | None) -> str | None:
    """상향 전이면 발송할 임계("at_risk"|"exceeded"), 아니면 None."""
    if _SEVERITY[new_status] > _SEVERITY[last_status]:
        return new_status
    return None


def resolve_alert_recipients(db, workflow, organization) -> set:
    """수신자 = 조직 관리자 전원 + created_by(조직 접근 보유). dedup (BGA-REQ-020~022).

    관리자/접근 판정은 권한 경계(has_organization_manager_permission /
    has_organization_scope_access)를 재사용한다. 후보군에 membership row 없이
    organization.created_by/managed_by로 manager로 인정되는 owner를 포함해,
    설정 권한은 있으나 알림은 못 받는 gap을 막는다.
    """
    org_id = organization.id
    candidates = {m.user_id for m in organization.memberships}
    for owner_id in (organization.created_by, organization.managed_by):
        if owner_id is not None:
            candidates.add(owner_id)

    recipients = {
        user_id
        for user_id in candidates
        if has_organization_manager_permission(db, user_id, org_id)
    }

    creator_id = workflow.created_by
    if creator_id is not None and has_organization_scope_access(db, creator_id, org_id):
        recipients.add(creator_id)

    return recipients


def serialize_alert_item(item, viewer_is_manager: bool) -> dict:
    """알림 항목을 API 응답 dict로 직렬화. 관리자만 금액 필드 포함 (BGA-REQ-051, 052)."""
    data = {
        "id": item.id,
        "type": f"budget.{item.status}",
        "workflow_id": item.workflow_id,
        "workflow_name": item.workflow_name,
        "organization_id": item.organization_id,
        "status": item.status,
        "usage_ratio": item.usage_ratio,
        "read": item.read,
        "created_at": item.created_at,
    }
    if viewer_is_manager:
        data["monthly_budget_usd"] = item.monthly_budget_usd
        data["current_month_cost"] = item.current_month_cost
    return data


def record_transition(db, *, workflow_id, period_month, new_status) -> str | None:
    """(workflow, 당월) 전이 원장을 조건부 갱신하고 상향 전이면 발송 임계를 반환한다.

    동시성 안전 (BGA-REQ-011): 갱신 전 with_for_update로 원장 행을 잠가 UPDATE 경합을
    직렬화하고, 생성 경합은 IntegrityError → rollback → 조건부 갱신으로 전환한다.
    commit은 호출자가 수행한다(원장 갱신 + 수신자 팬아웃 원자성).
    """
    existing = _lock_alert_state(db, workflow_id, period_month)
    if existing is not None:
        return _apply_transition(existing, new_status)

    threshold = decide_alert_transition(None, new_status)
    if threshold is None:
        return None

    db.add(
        BudgetAlertState(
            workflow_id=workflow_id,
            period_month=period_month,
            last_notified_status=threshold,
        )
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = _lock_alert_state(db, workflow_id, period_month)
        if existing is None:
            raise
        return _apply_transition(existing, new_status)
    return threshold


def _lock_alert_state(db, workflow_id, period_month):
    """(workflow, 당월) 원장 행을 with_for_update로 잠그고 반환한다 (UPDATE 경합 직렬화)."""
    return (
        db.query(BudgetAlertState)
        .filter(
            BudgetAlertState.workflow_id == workflow_id,
            BudgetAlertState.period_month == period_month,
        )
        .with_for_update()
        .first()
    )


def _apply_transition(state, new_status) -> str | None:
    threshold = decide_alert_transition(state.last_notified_status, new_status)
    if threshold is None:
        return None
    state.last_notified_status = threshold
    return threshold
