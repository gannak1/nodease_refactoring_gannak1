from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_

from apps.shared.db.models.app import App
from apps.shared.db.models.llm import LLMUsageLog
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_budget import WorkflowBudget
from apps.shared.domain.llm_usage import (
    AGENT_BUILDER_INTENT_RUNTIME_SURFACE,
    is_agent_builder_intent_usage,
    is_billable_llm_usage,
)
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


@dataclass(frozen=True)
class UsageCostBreakdown:
    total_cost: Decimal
    agent_builder_cost: Decimal

    @property
    def workflow_execution_cost(self) -> Decimal:
        return self.total_cost - self.agent_builder_cost


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
        aggregate = (
            _aggregate_workflow_usage_fake
            if hasattr(db, "usage_logs")
            else _aggregate_workflow_usage_query
        )
        return aggregate(
            db,
            organization_id=organization_id,
            period=period,
            page=page,
            limit=limit,
            budget_now=now or datetime.now(KST),
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
            costs = _organization_period_cost_fake(db, organization_id, period)
        else:
            costs = _organization_period_cost_query(db, organization_id, period)
        return AdminOrganizationSummaryResponse(
            month=period.start_at.strftime("%Y-%m"),
            total_cost=float(costs.total_cost),
            workflow_execution_cost=float(costs.workflow_execution_cost),
            agent_builder_cost=float(costs.agent_builder_cost),
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


def _aggregate_workflow_usage_fake(
    db,
    organization_id: Any,
    period: AdminUsagePeriod,
    page: int,
    limit: int,
    budget_now: datetime,
) -> AdminWorkflowUsageResponse:
    aggregates = _primary_workflow_zero_items(db, organization_id)
    for usage in db.usage_logs:
        aggregate = aggregates.get(usage.workflow_id)
        if (
            aggregate is None
            or not _is_usage_in_period(usage, period)
            or not _is_usage_in_organization(usage, organization_id)
            or not is_billable_llm_usage(
                getattr(usage, "runtime_surface", None),
                getattr(usage, "status", "success"),
            )
        ):
            continue
        _add_usage(aggregate, usage)

    sorted_items = sorted(aggregates.values(), key=_usage_sort_key)
    for item in sorted_items:
        item["budget"] = _workflow_budget_block(
            db,
            organization_id=organization_id,
            workflow_id=item["workflow_id"],
            now=budget_now,
        )
    return _usage_response(
        total=len(sorted_items),
        period=period,
        items=_page_items(sorted_items, page, limit),
    )


def _primary_workflow_zero_items(
    db, organization_id: Any
) -> dict[Any, dict[str, Any]]:
    """목록 기준은 usage 유무가 아니라 organization scope 안의
    App primary workflow(apps.workflow_id) 전체다 (FR-012, BGT-REQ-020)."""
    workflow_organizations = {
        workflow.id: workflow.organization_id
        for workflow in getattr(db, "workflows", [])
    }
    return {
        app.workflow_id: _empty_usage_item(app.workflow_id, app.name)
        for app in db.apps
        if app.organization_id == organization_id
        and app.workflow_id is not None
        and workflow_organizations.get(app.workflow_id) == organization_id
    }


def _usage_sort_key(item: dict[str, Any]) -> tuple:
    # total_cost 내림차순, 동률은 workflow 이름/id 오름차순 안정 정렬.
    return (-item["total_cost"], item["workflow_name"], item["workflow_id"])


def _usage_response(
    total: int,
    period: AdminUsagePeriod,
    items: list[AdminWorkflowUsageItem],
) -> AdminWorkflowUsageResponse:
    return AdminWorkflowUsageResponse(
        total=total,
        period=AdminUsagePeriodResponse(
            start_at=period.start_at,
            end_at=period.end_at,
        ),
        items=items,
    )


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
    agent_builder_cost = _agent_builder_cost_sum().label("agent_builder_cost")

    query = (
        db.query(
            App.workflow_id.label("workflow_id"),
            App.name.label("workflow_name"),
            prompt_tokens,
            completion_tokens,
            call_count,
            total_cost,
            agent_builder_cost,
        )
        .join(
            Workflow,
            and_(
                Workflow.id == App.workflow_id,
                Workflow.organization_id == organization_id,
            ),
        )
        .outerjoin(
            LLMUsageLog,
            and_(
                LLMUsageLog.workflow_id == App.workflow_id,
                or_(
                    LLMUsageLog.organization_id == organization_id,
                    LLMUsageLog.organization_id.is_(None),
                ),
                *_usage_in_period_conditions(period),
            ),
        )
        .filter(
            App.organization_id == organization_id,
            App.workflow_id.isnot(None),
        )
        .group_by(App.workflow_id, App.name)
    )
    total = query.count()
    rows = (
        query.order_by(
            total_cost.desc(),
            App.name.asc(),
            App.workflow_id.asc(),
        )
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
    return _usage_response(total=total, period=period, items=items)


def _total_cost_sum():
    return func.coalesce(func.sum(func.coalesce(LLMUsageLog.total_cost, 0)), 0)


def _agent_builder_cost_sum():
    return func.coalesce(
        func.sum(
            case(
                (
                    LLMUsageLog.runtime_surface
                    == AGENT_BUILDER_INTENT_RUNTIME_SURFACE,
                    func.coalesce(LLMUsageLog.total_cost, 0),
                ),
                else_=0,
            )
        ),
        0,
    )


def _usage_in_period_conditions(period: AdminUsagePeriod):
    return (
        LLMUsageLog.created_at >= period.start_at,
        LLMUsageLog.created_at < period.end_at,
        or_(
            LLMUsageLog.runtime_surface.is_(None),
            LLMUsageLog.runtime_surface
            != AGENT_BUILDER_INTENT_RUNTIME_SURFACE,
            LLMUsageLog.status == "success",
        ),
    )


def _organization_period_cost_query(
    db,
    organization_id: Any,
    period: AdminUsagePeriod,
) -> UsageCostBreakdown:
    row = (
        db.query(
            _total_cost_sum().label("total_cost"),
            _agent_builder_cost_sum().label("agent_builder_cost"),
        )
        .filter(
            LLMUsageLog.organization_id == organization_id,
            *_usage_in_period_conditions(period),
        )
        .one()
    )
    return _cost_breakdown(row.total_cost, row.agent_builder_cost)


def _organization_period_cost_fake(
    db,
    organization_id: Any,
    period: AdminUsagePeriod,
) -> UsageCostBreakdown:
    total_cost = Decimal("0")
    agent_builder_cost = Decimal("0")
    for usage in db.usage_logs:
        if (
            usage.organization_id != organization_id
            or not period.start_at <= usage.created_at < period.end_at
            or not is_billable_llm_usage(
                getattr(usage, "runtime_surface", None),
                getattr(usage, "status", "success"),
            )
        ):
            continue
        cost = AdminUsageService.coalesce_cost(usage.total_cost)
        total_cost += cost
        if is_agent_builder_intent_usage(
            getattr(usage, "runtime_surface", None)
        ):
            agent_builder_cost += cost
    return UsageCostBreakdown(total_cost, agent_builder_cost)


def _is_usage_in_period(usage: Any, period: AdminUsagePeriod) -> bool:
    return period.start_at <= usage.created_at < period.end_at


def _is_usage_in_organization(usage: Any, organization_id: Any) -> bool:
    return usage.organization_id is None or usage.organization_id == organization_id


def _empty_usage_item(workflow_id: Any, workflow_name: str) -> dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "workflow_name": workflow_name,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "call_count": 0,
        "total_cost": Decimal("0"),
        "workflow_execution_cost": Decimal("0"),
        "agent_builder_cost": Decimal("0"),
    }


def _add_usage(aggregate: dict[str, Any], usage: Any) -> None:
    aggregate["prompt_tokens"] += usage.prompt_tokens or 0
    aggregate["completion_tokens"] += usage.completion_tokens or 0
    aggregate["call_count"] += 1
    cost = AdminUsageService.coalesce_cost(usage.total_cost)
    aggregate["total_cost"] += cost
    if is_agent_builder_intent_usage(getattr(usage, "runtime_surface", None)):
        aggregate["agent_builder_cost"] += cost
    else:
        aggregate["workflow_execution_cost"] += cost


def _usage_item_from_row(row: Any) -> AdminWorkflowUsageItem:
    costs = _cost_breakdown(row.total_cost, row.agent_builder_cost)
    return AdminWorkflowUsageItem(
        workflow_id=row.workflow_id,
        workflow_name=row.workflow_name,
        prompt_tokens=int(row.prompt_tokens or 0),
        completion_tokens=int(row.completion_tokens or 0),
        call_count=int(row.call_count or 0),
        total_cost=float(costs.total_cost),
        workflow_execution_cost=float(costs.workflow_execution_cost),
        agent_builder_cost=float(costs.agent_builder_cost),
    )


def _cost_breakdown(total_cost: Any, agent_builder_cost: Any) -> UsageCostBreakdown:
    return UsageCostBreakdown(
        total_cost=AdminUsageService.coalesce_cost(total_cost),
        agent_builder_cost=AdminUsageService.coalesce_cost(agent_builder_cost),
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
            organization_id=organization_id,
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
        organization_id=organization_id,
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
