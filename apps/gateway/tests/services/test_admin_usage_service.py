from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException


def _service():
    from apps.gateway.services.admin_usage_service import (
        AdminUsagePeriod,
        AdminUsageService,
    )

    return AdminUsageService, AdminUsagePeriod


def test_resolve_month_period_kst_returns_calendar_month_boundaries():
    AdminUsageService, _ = _service()

    period = AdminUsageService.resolve_month_period_kst(
        datetime(2026, 7, 15, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    )

    assert period.start_at == datetime(2026, 7, 1, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    assert period.end_at == datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))


def test_resolve_period_defaults_to_current_month_and_rejects_invalid_range():
    AdminUsageService, _ = _service()

    default_period = AdminUsageService.resolve_period(
        start_at=None,
        end_at=None,
        now=datetime(2026, 7, 15, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    explicit_period = AdminUsageService.resolve_period(
        start_at=datetime(2026, 7, 2, 9, 30),
        end_at=datetime(2026, 7, 3, 18, 0),
        now=datetime(2026, 7, 15, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert default_period.start_at == datetime(
        2026, 7, 1, 0, 0, tzinfo=ZoneInfo("Asia/Seoul")
    )
    assert default_period.end_at == datetime(
        2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Asia/Seoul")
    )
    # timezone 없는 query datetime은 KST 기준으로 해석한다.
    assert explicit_period.start_at == datetime(
        2026, 7, 2, 9, 30, tzinfo=ZoneInfo("Asia/Seoul")
    )
    assert explicit_period.end_at == datetime(
        2026, 7, 3, 18, 0, tzinfo=ZoneInfo("Asia/Seoul")
    )

    with pytest.raises(HTTPException) as exc:
        AdminUsageService.resolve_period(
            start_at=datetime(2026, 7, 3, 18, 0),
            end_at=datetime(2026, 7, 3, 18, 0),
            now=datetime(2026, 7, 15, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        )

    assert exc.value.status_code == 400

    for kwargs in (
        {"start_at": datetime(2026, 7, 1, 0, 0), "end_at": None},
        {"start_at": None, "end_at": datetime(2026, 8, 1, 0, 0)},
    ):
        with pytest.raises(HTTPException) as exc:
            AdminUsageService.resolve_period(
                **kwargs,
                now=datetime(2026, 7, 15, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            )

        assert exc.value.status_code == 400


def test_coalesce_cost_preserves_precision_and_normalizes_none():
    AdminUsageService, _ = _service()

    assert AdminUsageService.coalesce_cost(None) == Decimal("0")
    assert AdminUsageService.coalesce_cost(Decimal("12.345678")) == Decimal(
        "12.345678"
    )


def test_aggregate_workflow_usage_groups_sums_sorts_scopes_and_uses_app_name():
    AdminUsageService, AdminUsagePeriod = _service()
    organization_id = uuid4()
    other_organization_id = uuid4()
    expensive_workflow_id = uuid4()
    cheap_workflow_id = uuid4()
    other_workflow_id = uuid4()
    expensive_app_id = uuid4()
    cheap_app_id = uuid4()
    other_app_id = uuid4()
    start_at = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    end_at = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    db = _UsageSession(
        usage_logs=[
            _usage_log(
                organization_id,
                expensive_workflow_id,
                prompt_tokens=100,
                completion_tokens=20,
                total_cost=Decimal("1.100000"),
                created_at=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
            ),
            _usage_log(
                organization_id,
                expensive_workflow_id,
                prompt_tokens=50,
                completion_tokens=10,
                total_cost=None,
                created_at=datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc),
            ),
            _usage_log(
                organization_id,
                cheap_workflow_id,
                prompt_tokens=5,
                completion_tokens=3,
                total_cost=Decimal("0.123456"),
                created_at=datetime(2026, 7, 3, 0, 0, tzinfo=timezone.utc),
            ),
            _usage_log(
                other_organization_id,
                other_workflow_id,
                prompt_tokens=999,
                completion_tokens=999,
                total_cost=Decimal("99.000000"),
                created_at=datetime(2026, 7, 4, 0, 0, tzinfo=timezone.utc),
            ),
            _usage_log(
                organization_id,
                expensive_workflow_id,
                prompt_tokens=999,
                completion_tokens=999,
                total_cost=Decimal("9.000000"),
                created_at=end_at,
            ),
        ],
        workflows=[
            _workflow(expensive_workflow_id, expensive_app_id, organization_id),
            _workflow(cheap_workflow_id, cheap_app_id, organization_id),
            _workflow(other_workflow_id, other_app_id, other_organization_id),
        ],
        apps=[
            _app(expensive_app_id, "비싼 워크플로우"),
            _app(cheap_app_id, "저렴한 워크플로우"),
            _app(other_app_id, "다른 조직 워크플로우"),
        ],
    )

    result = AdminUsageService.aggregate_workflow_usage(
        db,
        organization_id=organization_id,
        period=AdminUsagePeriod(start_at=start_at, end_at=end_at),
        page=1,
        limit=20,
    )
    second_page = AdminUsageService.aggregate_workflow_usage(
        db,
        organization_id=organization_id,
        period=AdminUsagePeriod(start_at=start_at, end_at=end_at),
        page=2,
        limit=1,
    )

    assert result.total == 2
    assert [
        (
            item.workflow_id,
            item.workflow_name,
            item.prompt_tokens,
            item.completion_tokens,
            item.call_count,
            item.total_cost,
        )
        for item in result.items
    ] == [
        (
            expensive_workflow_id,
            "비싼 워크플로우",
            150,
            30,
            2,
            1.1,
        ),
        (
            cheap_workflow_id,
            "저렴한 워크플로우",
            5,
            3,
            1,
            0.123456,
        ),
    ]
    assert isinstance(result.items[0].total_cost, float)
    assert [item.workflow_id for item in second_page.items] == [cheap_workflow_id]


class _UsageSession:
    def __init__(self, *, usage_logs, workflows, apps):
        self.usage_logs = usage_logs
        self.workflows = workflows
        self.apps = apps


def _usage_log(
    organization_id,
    workflow_id,
    *,
    prompt_tokens,
    completion_tokens,
    total_cost,
    created_at,
):
    return SimpleNamespace(
        organization_id=organization_id,
        workflow_id=workflow_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_cost=total_cost,
        created_at=created_at,
    )


def _workflow(workflow_id, app_id, organization_id):
    return SimpleNamespace(
        id=workflow_id,
        app_id=app_id,
        organization_id=organization_id,
    )


def _app(app_id, name):
    return SimpleNamespace(id=app_id, name=name)
