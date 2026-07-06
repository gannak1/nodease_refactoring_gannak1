from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from apps.gateway.services.app_service import AppService
from apps.gateway.services.workflow_budget_service import WorkflowBudgetService
from apps.shared.db.models.workflow_budget import WorkflowBudget

KST = ZoneInfo("Asia/Seoul")


def test_app_budget_status_boundaries_and_null_conditions():
    organization_id = uuid4()
    workflow_ids = {
        "normal": uuid4(),
        "at_risk": uuid4(),
        "exact_budget": uuid4(),
        "exceeded": uuid4(),
        "null_cost": uuid4(),
        "disabled": uuid4(),
        "zero_budget": uuid4(),
        "no_budget": uuid4(),
    }
    db = _BudgetStatusDb(
        budgets=[
            _budget_row(organization_id, workflow_ids["normal"], Decimal("100.00")),
            _budget_row(organization_id, workflow_ids["at_risk"], Decimal("100.00")),
            _budget_row(
                organization_id, workflow_ids["exact_budget"], Decimal("100.00")
            ),
            _budget_row(organization_id, workflow_ids["exceeded"], Decimal("100.00")),
            _budget_row(organization_id, workflow_ids["null_cost"], Decimal("100.00")),
            _budget_row(
                organization_id,
                workflow_ids["disabled"],
                Decimal("100.00"),
                is_enabled=False,
            ),
            _budget_row(organization_id, workflow_ids["zero_budget"], Decimal("0")),
            _budget_row(uuid4(), uuid4(), Decimal("100.00")),
        ],
        usage_logs=[
            _usage_log(
                organization_id,
                workflow_ids["normal"],
                total_cost=Decimal("89.99"),
                created_at=datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
            ),
            _usage_log(
                organization_id,
                workflow_ids["at_risk"],
                total_cost=Decimal("90.00"),
                created_at=datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
            ),
            _usage_log(
                organization_id,
                workflow_ids["exact_budget"],
                total_cost=Decimal("100.00"),
                created_at=datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
            ),
            _usage_log(
                organization_id,
                workflow_ids["exceeded"],
                total_cost=Decimal("100.000001"),
                created_at=datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
            ),
            _usage_log(
                organization_id,
                workflow_ids["null_cost"],
                total_cost=None,
                created_at=datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
            ),
        ],
    )

    statuses = AppService._budget_status_by_workflow_id(
        db,
        list(workflow_ids.values()),
        organization_id=organization_id,
        now=datetime(2026, 7, 15, 9, 0, tzinfo=KST),
    )

    assert statuses[workflow_ids["normal"]] == {
        "usage_ratio": pytest.approx(0.8999),
        "status": "normal",
    }
    assert statuses[workflow_ids["at_risk"]] == {
        "usage_ratio": pytest.approx(0.9),
        "status": "at_risk",
    }
    assert statuses[workflow_ids["exact_budget"]] == {
        "usage_ratio": pytest.approx(1.0),
        "status": "at_risk",
    }
    assert statuses[workflow_ids["exceeded"]] == {
        "usage_ratio": pytest.approx(1.00000001),
        "status": "exceeded",
    }
    assert statuses[workflow_ids["null_cost"]] == {
        "usage_ratio": pytest.approx(0.0),
        "status": "normal",
    }
    assert statuses[workflow_ids["disabled"]] is None
    assert statuses[workflow_ids["zero_budget"]] is None
    assert statuses[workflow_ids["no_budget"]] is None
    for status in statuses.values():
        if status is None:
            continue
        assert set(status) == {"usage_ratio", "status"}


def test_app_budget_status_uses_kst_month_window():
    organization_id = uuid4()
    workflow_id = uuid4()
    db = _BudgetStatusDb(
        budgets=[_budget_row(organization_id, workflow_id, Decimal("100.00"))],
        usage_logs=[
            # KST 2026-08-01 00:00 - 8월 포함
            _usage_log(
                organization_id,
                workflow_id,
                total_cost=Decimal("90.00"),
                created_at=datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc),
            ),
            # KST 2026-07-31 23:59:59 - 8월 제외
            _usage_log(
                organization_id,
                workflow_id,
                total_cost=Decimal("10.00"),
                created_at=datetime(2026, 7, 31, 14, 59, 59, tzinfo=timezone.utc),
            ),
            # KST 2026-09-01 00:00 - 8월 [start, end) 끝 경계라 제외
            _usage_log(
                organization_id,
                workflow_id,
                total_cost=Decimal("10.00"),
                created_at=datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc),
            ),
        ],
    )

    statuses = AppService._budget_status_by_workflow_id(
        db,
        [workflow_id],
        organization_id=organization_id,
        now=datetime(2026, 8, 1, 1, 0, tzinfo=KST),
    )

    assert statuses[workflow_id] == {
        "usage_ratio": pytest.approx(0.9),
        "status": "at_risk",
    }


def test_app_budget_status_uses_grouped_cost_lookup(monkeypatch):
    organization_id = uuid4()
    workflow_ids = [uuid4(), uuid4()]
    db = _BudgetStatusDb(
        budgets=[
            _budget_row(organization_id, workflow_ids[0], Decimal("100.00")),
            _budget_row(organization_id, workflow_ids[1], Decimal("100.00")),
        ],
        usage_logs=[
            _usage_log(
                organization_id,
                workflow_ids[0],
                total_cost=Decimal("10.00"),
                created_at=datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
            ),
            _usage_log(
                organization_id,
                workflow_ids[1],
                total_cost=Decimal("95.00"),
                created_at=datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
            ),
        ],
    )

    def fail_per_workflow_cost(*args, **kwargs):
        raise AssertionError("budget_status must not call per-workflow cost lookup")

    monkeypatch.setattr(
        WorkflowBudgetService,
        "get_current_month_cost",
        fail_per_workflow_cost,
    )

    statuses = AppService._budget_status_by_workflow_id(
        db,
        workflow_ids,
        organization_id=organization_id,
        now=datetime(2026, 7, 15, 9, 0, tzinfo=KST),
    )

    assert statuses[workflow_ids[0]]["status"] == "normal"
    assert statuses[workflow_ids[1]]["status"] == "at_risk"


class _BudgetStatusDb:
    def __init__(self, *, budgets, usage_logs):
        self.budgets = budgets
        self.usage_logs = usage_logs


def _budget_row(organization_id, workflow_id, monthly_budget_usd, *, is_enabled=True):
    return WorkflowBudget(
        id=uuid4(),
        organization_id=organization_id,
        workflow_id=workflow_id,
        monthly_budget_usd=monthly_budget_usd,
        is_enabled=is_enabled,
        created_by=uuid4(),
    )


def _usage_log(organization_id, workflow_id, *, total_cost, created_at):
    return SimpleNamespace(
        organization_id=organization_id,
        workflow_id=workflow_id,
        prompt_tokens=1,
        completion_tokens=1,
        total_cost=total_cost,
        created_at=created_at,
    )
