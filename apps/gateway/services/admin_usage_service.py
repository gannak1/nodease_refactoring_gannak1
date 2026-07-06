from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func

from apps.shared.db.models.app import App
from apps.shared.db.models.llm import LLMUsageLog
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_budget import WorkflowBudget
from apps.shared.schemas.admin_usage import (
    AdminBudgetSummaryBlock,
    AdminOrganizationSummaryResponse,
    AdminWorkflowBudgetBlock,
    AdminWorkflowUsageItem,
    AdminWorkflowUsageResponse,
    AdminUsagePeriodResponse,
)

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class AdminUsagePeriod:
    start_at: datetime
    end_at: datetime


class AdminUsageService:
    @staticmethod
    def resolve_month_period_kst(now: datetime) -> AdminUsagePeriod:
        kst_now = _ensure_timezone(now).astimezone(KST)
        start = kst_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return AdminUsagePeriod(start_at=start, end_at=end)

    @staticmethod
    def resolve_period(
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        now: datetime | None = None,
    ) -> AdminUsagePeriod:
        if start_at is None and end_at is None:
            return AdminUsageService.resolve_month_period_kst(now or datetime.now(KST))

        if start_at is None or end_at is None:
            raise HTTPException(status_code=400, detail="Invalid period")

        start = _ensure_timezone(start_at)
        end = _ensure_timezone(end_at)
        if end <= start:
            raise HTTPException(status_code=400, detail="Invalid period")
        return AdminUsagePeriod(start_at=start, end_at=end)

    @staticmethod
    def coalesce_cost(value: Any) -> Decimal:
        if value is None:
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def aggregate_workflow_usage(
        db,
        organization_id: Any,
        period: AdminUsagePeriod,
        page: int = 1,
        limit: int = 20,
        now: datetime | None = None,
    ) -> AdminWorkflowUsageResponse:
        budget_now = now or datetime.now(KST)
        if not hasattr(db, "usage_logs"):
            return _aggregate_workflow_usage_query(
                db,
                organization_id=organization_id,
                period=period,
                page=page,
                limit=limit,
                budget_now=budget_now,
            )

        rows = _fake_usage_rows(db)
        aggregates: dict[Any, dict[str, Any]] = {}
        for usage, workflow, app in rows:
            if not _is_usage_in_scope(usage, workflow, organization_id, period):
                continue

            aggregate = aggregates.setdefault(
                usage.workflow_id,
                _empty_usage_item(usage.workflow_id, app.name),
            )
            _add_usage(aggregate, usage)

        sorted_items = sorted(
            aggregates.values(),
            key=lambda item: item["total_cost"],
            reverse=True,
        )
        for item in sorted_items:
            item["budget"] = _workflow_budget_block(
                db,
                organization_id=organization_id,
                workflow_id=item["workflow_id"],
                now=budget_now,
            )
        total = len(sorted_items)
        return AdminWorkflowUsageResponse(
            total=total,
            period=AdminUsagePeriodResponse(
                start_at=period.start_at,
                end_at=period.end_at,
            ),
            items=_page_items(sorted_items, page, limit),
        )

    @staticmethod
    def get_organization_summary(
        db,
        organization_id: Any,
        now: datetime | None = None,
    ) -> AdminOrganizationSummaryResponse:
        budget_now = now or datetime.now(KST)
        period = AdminUsageService.resolve_month_period_kst(budget_now)
        if hasattr(db, "usage_logs"):
            total_cost = _organization_period_cost_fake(db, organization_id, period)
        else:
            total_cost = _organization_period_cost_query(db, organization_id, period)
        return AdminOrganizationSummaryResponse(
            month=period.start_at.strftime("%Y-%m"),
            total_cost=float(total_cost),
            budget=_budget_summary_block(
                db,
                organization_id=organization_id,
                now=budget_now,
            ),
        )


def _ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=KST)
    return value


def _aggregate_workflow_usage_query(
    db,
    organization_id: Any,
    period: AdminUsagePeriod,
    page: int,
    limit: int,
    budget_now: datetime,
) -> AdminWorkflowUsageResponse:
    prompt_tokens = func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0).label(
        "prompt_tokens"
    )
    completion_tokens = func.coalesce(
        func.sum(LLMUsageLog.completion_tokens), 0
    ).label("completion_tokens")
    call_count = func.count(LLMUsageLog.id).label("call_count")
    total_cost = _total_cost_sum().label("total_cost")

    query = (
        db.query(
            LLMUsageLog.workflow_id.label("workflow_id"),
            App.name.label("workflow_name"),
            prompt_tokens,
            completion_tokens,
            call_count,
            total_cost,
        )
        .join(Workflow, LLMUsageLog.workflow_id == Workflow.id)
        .join(App, Workflow.app_id == App.id)
        .filter(
            LLMUsageLog.organization_id == organization_id,
            Workflow.organization_id == organization_id,
            App.organization_id == organization_id,
            *_usage_in_period_conditions(period),
        )
        .group_by(LLMUsageLog.workflow_id, App.name)
    )
    total = query.count()
    rows = (
        query.order_by(total_cost.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    items = []
    for row in rows:
        item = _usage_item_from_row(row)
        item.budget = _workflow_budget_block(
            db,
            organization_id=organization_id,
            workflow_id=row.workflow_id,
            now=budget_now,
        )
        items.append(item)
    return AdminWorkflowUsageResponse(
        total=total,
        period=AdminUsagePeriodResponse(
            start_at=period.start_at,
            end_at=period.end_at,
        ),
        items=items,
    )


def _total_cost_sum():
    return func.coalesce(func.sum(func.coalesce(LLMUsageLog.total_cost, 0)), 0)


def _usage_in_period_conditions(period: AdminUsagePeriod):
    return (
        LLMUsageLog.created_at >= period.start_at,
        LLMUsageLog.created_at < period.end_at,
    )


def _organization_period_cost_query(
    db,
    organization_id: Any,
    period: AdminUsagePeriod,
) -> Decimal:
    total = (
        db.query(_total_cost_sum())
        .filter(
            LLMUsageLog.organization_id == organization_id,
            *_usage_in_period_conditions(period),
        )
        .scalar()
    )
    return AdminUsageService.coalesce_cost(total)


def _organization_period_cost_fake(
    db,
    organization_id: Any,
    period: AdminUsagePeriod,
) -> Decimal:
    return sum(
        (
            AdminUsageService.coalesce_cost(usage.total_cost)
            for usage in db.usage_logs
            if usage.organization_id == organization_id
            and period.start_at <= usage.created_at < period.end_at
        ),
        Decimal("0"),
    )


def _is_usage_in_scope(
    usage: Any,
    workflow: Any,
    organization_id: Any,
    period: AdminUsagePeriod,
) -> bool:
    return (
        usage.organization_id == organization_id
        and workflow.organization_id == organization_id
        and period.start_at <= usage.created_at < period.end_at
    )


def _empty_usage_item(workflow_id: Any, workflow_name: str) -> dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "workflow_name": workflow_name,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "call_count": 0,
        "total_cost": Decimal("0"),
    }


def _add_usage(aggregate: dict[str, Any], usage: Any) -> None:
    aggregate["prompt_tokens"] += usage.prompt_tokens or 0
    aggregate["completion_tokens"] += usage.completion_tokens or 0
    aggregate["call_count"] += 1
    aggregate["total_cost"] += AdminUsageService.coalesce_cost(usage.total_cost)


def _usage_item_from_row(row: Any) -> AdminWorkflowUsageItem:
    return AdminWorkflowUsageItem(
        workflow_id=row.workflow_id,
        workflow_name=row.workflow_name,
        prompt_tokens=int(row.prompt_tokens or 0),
        completion_tokens=int(row.completion_tokens or 0),
        call_count=int(row.call_count or 0),
        total_cost=float(row.total_cost or 0),
    )


def _budget_service():
    """workflow_budget_service가 이 모듈을 top-level import하므로,
    역방향은 호출 시점 지연 import로 순환을 끊는다."""
    from apps.gateway.services.workflow_budget_service import WorkflowBudgetService

    return WorkflowBudgetService


def _budget_summary_block(
    db,
    organization_id: Any,
    now: datetime,
) -> AdminBudgetSummaryBlock | None:
    budgets = _active_budgets(db, organization_id)
    if not budgets:
        return None

    WorkflowBudgetService = _budget_service()

    at_risk_count = 0
    exceeded_count = 0
    for budget in budgets:
        current_cost = WorkflowBudgetService.get_current_month_cost(
            db,
            workflow_id=budget.workflow_id,
            now=now,
        )
        status = WorkflowBudgetService.classify_budget_usage(
            current_cost=current_cost,
            monthly_budget_usd=budget.monthly_budget_usd,
            is_enabled=budget.is_enabled,
        )
        if status == "at_risk":
            at_risk_count += 1
        elif status == "exceeded":
            exceeded_count += 1

    budgeted_count = len(budgets)
    return AdminBudgetSummaryBlock(
        budgeted_workflow_count=budgeted_count,
        at_risk_count=at_risk_count,
        exceeded_count=exceeded_count,
        ratio=(at_risk_count + exceeded_count) / budgeted_count,
    )


def _workflow_budget_block(
    db,
    organization_id: Any,
    workflow_id: Any,
    now: datetime,
) -> AdminWorkflowBudgetBlock | None:
    budget = _active_budget_for_workflow(db, organization_id, workflow_id)
    if budget is None:
        return None

    WorkflowBudgetService = _budget_service()

    current_cost = WorkflowBudgetService.get_current_month_cost(
        db,
        workflow_id=workflow_id,
        now=now,
    )
    monthly_budget = AdminUsageService.coalesce_cost(budget.monthly_budget_usd)
    status = WorkflowBudgetService.classify_budget_usage(
        current_cost=current_cost,
        monthly_budget_usd=monthly_budget,
        is_enabled=budget.is_enabled,
    )
    if status is None:
        return None

    return AdminWorkflowBudgetBlock(
        monthly_budget_usd=float(monthly_budget),
        current_month_cost=float(current_cost),
        usage_ratio=float(current_cost / monthly_budget),
        status=status,
    )


def _active_budgets(db, organization_id: Any) -> list[Any]:
    if hasattr(db, "usage_logs"):
        return [
            budget
            for budget in getattr(db, "budgets", [])
            if _is_active_budget(budget, organization_id)
        ]

    return (
        db.query(WorkflowBudget)
        .filter(
            WorkflowBudget.organization_id == organization_id,
            WorkflowBudget.is_enabled.is_(True),
            WorkflowBudget.monthly_budget_usd > 0,
        )
        .all()
    )


def _active_budget_for_workflow(db, organization_id: Any, workflow_id: Any):
    if hasattr(db, "usage_logs"):
        return next(
            (
                budget
                for budget in getattr(db, "budgets", [])
                if _is_active_budget(budget, organization_id)
                and budget.workflow_id == workflow_id
            ),
            None,
        )

    return (
        db.query(WorkflowBudget)
        .filter(
            WorkflowBudget.organization_id == organization_id,
            WorkflowBudget.workflow_id == workflow_id,
            WorkflowBudget.is_enabled.is_(True),
            WorkflowBudget.monthly_budget_usd > 0,
        )
        .first()
    )


def _is_active_budget(budget: Any, organization_id: Any) -> bool:
    return (
        budget.organization_id == organization_id
        and bool(budget.is_enabled)
        and AdminUsageService.coalesce_cost(budget.monthly_budget_usd) > 0
    )


def _page_items(
    items: list[dict[str, Any]],
    page: int,
    limit: int,
) -> list[AdminWorkflowUsageItem]:
    start_index = (page - 1) * limit
    return [
        AdminWorkflowUsageItem(**item)
        for item in items[start_index : start_index + limit]
    ]


def _fake_usage_rows(db) -> list[tuple[Any, Any, Any]]:
    workflows = {workflow.id: workflow for workflow in db.workflows}
    apps = {app.id: app for app in db.apps}
    return [
        (
            usage,
            workflows[usage.workflow_id],
            apps[workflows[usage.workflow_id].app_id],
        )
        for usage in db.usage_logs
        if usage.workflow_id in workflows
        and workflows[usage.workflow_id].app_id in apps
    ]
