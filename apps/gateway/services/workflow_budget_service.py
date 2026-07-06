from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.gateway.services.audit_records import add_action_audit
from apps.shared.audit.actions import AuditAction
from apps.shared.db.models.llm import LLMUsageLog
from apps.shared.db.models.workflow_budget import WorkflowBudget


class WorkflowBudgetService:
    """Workflow monthly LLM budget helpers."""

    @staticmethod
    def classify_budget_usage(
        current_cost: Any,
        monthly_budget_usd: Any,
        is_enabled: bool = True,
    ) -> str | None:
        if not is_enabled or monthly_budget_usd is None:
            return None

        budget = _to_decimal(monthly_budget_usd)
        if budget <= 0:
            return None

        ratio = _to_decimal(current_cost) / budget
        if ratio > Decimal("1.0"):
            return "exceeded"
        if ratio >= Decimal("0.9"):
            return "at_risk"
        return "normal"

    @staticmethod
    def get_current_month_cost(
        db: Session,
        workflow_id: Any,
        now: datetime,
    ) -> Decimal:
        from apps.gateway.services.admin_usage_service import AdminUsageService

        period = AdminUsageService.resolve_month_period_kst(now)
        if hasattr(db, "usage_logs"):
            return _current_month_cost_fake(
                db,
                workflow_id=workflow_id,
                period=period,
            )

        return _current_month_cost_query(
            db,
            workflow_id=workflow_id,
            period=period,
        )

    @staticmethod
    def upsert_budget(
        db: Session,
        organization_id: Any,
        workflow_id: Any,
        actor_id: Any,
        monthly_budget_usd: Any,
        is_enabled: bool,
    ) -> WorkflowBudget:
        amount = _to_decimal(monthly_budget_usd)
        enabled = bool(is_enabled)
        existing = _find_budget(db, organization_id, workflow_id)

        if existing is None:
            budget = WorkflowBudget(
                id=uuid.uuid4(),
                organization_id=organization_id,
                workflow_id=workflow_id,
                monthly_budget_usd=amount,
                is_enabled=enabled,
                created_by=actor_id,
            )
            db.add(budget)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                existing = _find_budget(db, organization_id, workflow_id)
                if existing is None:
                    raise
                return _update_budget(
                    db,
                    existing,
                    actor_id=actor_id,
                    monthly_budget_usd=amount,
                    is_enabled=enabled,
                )

            _add_budget_audit(
                db,
                AuditAction.WORKFLOW_BUDGET_CREATED,
                budget,
                actor_id=actor_id,
            )
            db.commit()
            db.refresh(budget)
            return budget

        return _update_budget(
            db,
            existing,
            actor_id=actor_id,
            monthly_budget_usd=amount,
            is_enabled=enabled,
        )


def _find_budget(db: Session, organization_id: Any, workflow_id: Any):
    return (
        db.query(WorkflowBudget)
        .filter(
            WorkflowBudget.organization_id == organization_id,
            WorkflowBudget.workflow_id == workflow_id,
        )
        .first()
    )


def _current_month_cost_fake(
    db: Session,
    *,
    workflow_id: Any,
    period: Any,
) -> Decimal:
    from apps.gateway.services.admin_usage_service import AdminUsageService

    return sum(
        (
            AdminUsageService.coalesce_cost(usage.total_cost)
            for usage in db.usage_logs
            if usage.workflow_id == workflow_id
            and period.start_at <= usage.created_at < period.end_at
        ),
        Decimal("0"),
    )


def _current_month_cost_query(
    db: Session,
    *,
    workflow_id: Any,
    period: Any,
) -> Decimal:
    from apps.gateway.services.admin_usage_service import AdminUsageService

    total = (
        db.query(
            func.coalesce(func.sum(func.coalesce(LLMUsageLog.total_cost, 0)), 0)
        )
        .filter(
            LLMUsageLog.workflow_id == workflow_id,
            LLMUsageLog.created_at >= period.start_at,
            LLMUsageLog.created_at < period.end_at,
        )
        .scalar()
    )
    return AdminUsageService.coalesce_cost(total)


def _update_budget(
    db: Session,
    budget: WorkflowBudget,
    *,
    actor_id: Any,
    monthly_budget_usd: Decimal,
    is_enabled: bool,
) -> WorkflowBudget:
    if (
        _to_decimal(budget.monthly_budget_usd) == monthly_budget_usd
        and bool(budget.is_enabled) is is_enabled
    ):
        return budget

    budget.monthly_budget_usd = monthly_budget_usd
    budget.is_enabled = is_enabled
    budget.updated_by = actor_id
    _add_budget_audit(
        db,
        AuditAction.WORKFLOW_BUDGET_UPDATED,
        budget,
        actor_id=actor_id,
    )
    db.commit()
    db.refresh(budget)
    return budget


def _add_budget_audit(
    db: Session,
    action: str,
    budget: WorkflowBudget,
    *,
    actor_id: Any,
) -> None:
    add_action_audit(
        db,
        action,
        actor_id=actor_id,
        target_type="workflow_budget",
        target_id=budget.id,
        organization_id=budget.organization_id,
        metadata={
            "monthly_budget_usd": _format_budget_amount(budget.monthly_budget_usd),
            "is_enabled": bool(budget.is_enabled),
        },
    )


def _format_budget_amount(value: Any) -> str:
    return f"{_to_decimal(value):.2f}"


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
