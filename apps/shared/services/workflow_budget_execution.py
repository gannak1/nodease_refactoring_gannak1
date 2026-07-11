from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from apps.shared.db.models.llm import LLMUsageLog
from apps.shared.db.models.workflow_budget import WorkflowBudget
from apps.shared.domain.workflow_budget import (
    BudgetExecutionDecision,
    resolve_month_period_kst,
)
from sqlalchemy import func
from sqlalchemy.orm import Session


def evaluate_workflow_budget_execution(
    db: Session,
    *,
    workflow_id: Any,
    now: datetime,
) -> BudgetExecutionDecision:
    if workflow_id is None:
        return BudgetExecutionDecision(status="allowed")
    normalized_id = _normalize_workflow_id(workflow_id)

    begin_nested = getattr(db, "begin_nested", None)
    if not callable(begin_nested):
        try:
            return _evaluate_workflow_budget_execution(
                db,
                workflow_id=normalized_id,
                now=now,
            )
        except Exception:
            return BudgetExecutionDecision(status="unavailable")

    # Schedule callers hold canonical row locks in the outer transaction. A
    # failed aggregate must roll back only its statement/savepoint so the
    # caller can persist a bounded unavailable/dead-letter transition.
    nested_transaction = begin_nested()
    try:
        with nested_transaction:
            return _evaluate_workflow_budget_execution(
                db,
                workflow_id=normalized_id,
                now=now,
            )
    except Exception:
        return BudgetExecutionDecision(status="unavailable")


def _evaluate_workflow_budget_execution(
    db: Session,
    *,
    workflow_id: Any,
    now: datetime,
) -> BudgetExecutionDecision:
    budget = (
        db.query(WorkflowBudget)
        .filter(WorkflowBudget.workflow_id == workflow_id)
        .first()
    )
    if budget is None or not budget.is_enabled:
        return BudgetExecutionDecision(status="allowed")
    monthly_budget = _decimal(budget.monthly_budget_usd)
    if monthly_budget <= 0:
        return BudgetExecutionDecision(status="allowed")

    period = resolve_month_period_kst(now)
    if hasattr(db, "usage_logs"):
        current_cost = sum(
            (
                _decimal(usage.total_cost)
                for usage in db.usage_logs
                if usage.workflow_id == workflow_id
                and period.start_at <= usage.created_at < period.end_at
            ),
            Decimal("0"),
        )
    else:
        current_cost = _decimal(
            db.query(func.sum(LLMUsageLog.total_cost))
            .filter(
                LLMUsageLog.workflow_id == workflow_id,
                LLMUsageLog.created_at >= period.start_at,
                LLMUsageLog.created_at < period.end_at,
            )
            .scalar()
        )

    return BudgetExecutionDecision(
        status="blocked" if current_cost > monthly_budget else "allowed"
    )


def _normalize_workflow_id(value: Any):
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return value


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
