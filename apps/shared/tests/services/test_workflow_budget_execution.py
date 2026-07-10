from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from apps.shared.db.models.workflow_budget import WorkflowBudget
from apps.shared.services.workflow_budget_execution import (
    evaluate_workflow_budget_execution,
)


class _Query:
    def __init__(self, row):
        self.row = row

    def filter(self, *args):
        return self

    def first(self):
        return self.row


class _Db:
    def __init__(self, budget, usage_logs):
        self.budget = budget
        self.usage_logs = usage_logs
        self.commits = 0

    def query(self, model):
        assert model is WorkflowBudget
        return _Query(self.budget)


def test_shared_budget_evaluator_is_side_effect_free_and_uses_kst_month():
    workflow_id = uuid4()
    now = datetime(2026, 7, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    db = _Db(
        SimpleNamespace(
            workflow_id=workflow_id,
            is_enabled=True,
            monthly_budget_usd=Decimal("100"),
        ),
        [
            SimpleNamespace(
                workflow_id=workflow_id,
                total_cost=Decimal("101"),
                created_at=now,
            )
        ],
    )

    decision = evaluate_workflow_budget_execution(
        db,
        workflow_id=workflow_id,
        now=now,
    )

    assert decision.status == "blocked"
    assert db.commits == 0
