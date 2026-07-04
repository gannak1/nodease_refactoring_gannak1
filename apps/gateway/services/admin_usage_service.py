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
from apps.shared.schemas.admin_usage import (
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
    ) -> AdminWorkflowUsageResponse:
        if not hasattr(db, "usage_logs"):
            return _aggregate_workflow_usage_query(
                db,
                organization_id=organization_id,
                period=period,
                page=page,
                limit=limit,
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
        total = len(sorted_items)
        return AdminWorkflowUsageResponse(
            total=total,
            period=AdminUsagePeriodResponse(
                start_at=period.start_at,
                end_at=period.end_at,
            ),
            items=_page_items(sorted_items, page, limit),
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
) -> AdminWorkflowUsageResponse:
    prompt_tokens = func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0).label(
        "prompt_tokens"
    )
    completion_tokens = func.coalesce(
        func.sum(LLMUsageLog.completion_tokens), 0
    ).label("completion_tokens")
    call_count = func.count(LLMUsageLog.id).label("call_count")
    total_cost = func.coalesce(
        func.sum(func.coalesce(LLMUsageLog.total_cost, 0)), 0
    ).label("total_cost")

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
            LLMUsageLog.created_at >= period.start_at,
            LLMUsageLog.created_at < period.end_at,
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
    return AdminWorkflowUsageResponse(
        total=total,
        period=AdminUsagePeriodResponse(
            start_at=period.start_at,
            end_at=period.end_at,
        ),
        items=[_usage_item_from_row(row) for row in rows],
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
