"""예산 알림 발송 오케스트레이션 (docs/features/budget-alerts).

run 완료 시 재계산된 상태를 받아, 상향 전이면 수신자에게 in-app 알림을 발송한다.
budget 판정/집계는 gateway의 WorkflowBudgetService를 재사용하고, 전이/팬아웃 로직은
shared의 budget_alerts 헬퍼를 재사용한다. log_system은 이 함수를 감싼 Celery task를
send_task(이름 기반)로 호출한다(앱 경계 import 없음).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from apps.gateway.services.notification_service import publish_notifications_changed
from apps.gateway.services.workflow_budget_service import WorkflowBudgetService
from apps.shared.services.budget_alerts import (
    create_alert_items,
    record_transition,
    resolve_alert_recipients,
)

KST = ZoneInfo("Asia/Seoul")


def evaluate_budget_alert(db, *, workflow, organization, budget, now=None):
    """상향 전이면 수신자 팬아웃 후 SSE를 발행하고 임계를 반환한다. 무발송이면 None.

    당월 누적 비용은 workflow_id/now로 직접 재계산한다(BGA-REQ-003) — 호출자가 방금
    끝난 run 비용을 넘겨 normal로 오판정하는 것을 막는다.
    무발송: 예산 없음/비활성/정상, 또는 이미 알린 임계(전이 아님).
    SSE는 커밋 이후에 발행한다(도달 시점에 저장된 알림이 보이도록).
    """
    if budget is None:
        return None

    now = now or datetime.now(KST)
    current_cost = WorkflowBudgetService.get_current_month_cost(db, workflow.id, now)
    status = WorkflowBudgetService.classify_budget_usage(
        current_cost, budget.monthly_budget_usd, budget.is_enabled
    )
    if status is None:
        return None  # 비활성/0 이하 예산

    period_month = _period_month_kst(now)
    threshold = record_transition(
        db,
        workflow_id=workflow.id,
        period_month=period_month,
        new_status=status,
    )
    if threshold is None:
        return None  # 상향 전이 아님(정상/동일/하향)

    recipients = resolve_alert_recipients(db, workflow, organization)
    usage_ratio = _to_decimal(current_cost) / _to_decimal(budget.monthly_budget_usd)
    created = create_alert_items(
        db,
        workflow_id=workflow.id,
        organization_id=workflow.organization_id,
        period_month=period_month,
        status=threshold,
        recipient_ids=recipients,
        usage_ratio=usage_ratio,
        monthly_budget_usd=budget.monthly_budget_usd,
        current_month_cost=current_cost,
    )
    db.commit()
    for item in created:
        publish_notifications_changed(item.user_id)
    return threshold


def _period_month_kst(now) -> str:
    now = now or datetime.now(KST)
    kst = now.astimezone(KST)
    return f"{kst.year:04d}-{kst.month:02d}"


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
