"""Tests for budget alert evaluation orchestration (docs/features/budget-alerts).

`evaluate_budget_alert(db, *, workflow, organization, budget, now)`는 알림 발송
오케스트레이션을 담당한다:
  당월 누적 비용 재계산(get_current_month_cost) → 활성 예산 판정(classify) →
  record_transition(전이 원장) → 상향 전이면 resolve_alert_recipients +
  create_alert_items(팬아웃) → commit → 생성된 수신자에게 SSE.

당월 비용은 이 service가 workflow_id/now로 직접 재계산한다(BGA-REQ-003).
호출자가 run 비용을 넘겨 normal로 오판정하는 footgun을 없앤다.

대응 문서: docs/features/budget-alerts/test_cases.md
  - Acceptance Criteria AC-1~4
  - Policies: SSE는 커밋 이후(도달 보장은 저장 기록)
"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.sql.operators import eq

from apps.gateway.services import budget_alert_service
from apps.shared.db.models.budget_alert import BudgetAlert, BudgetAlertState

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 7, 7, 12, 0, tzinfo=KST)  # period_month == "2026-07"


# --- 최소 세션 fake (ledger with_for_update + fanout all) --------------------


def _matches_expression(item, expression):
    if not hasattr(expression, "left"):
        return True
    column = str(expression.left).split(".")[-1]
    if not hasattr(item, column):
        return True
    if expression.operator is not eq:
        return True
    right = expression.right
    right_value = right.value if hasattr(right, "value") else right
    return getattr(item, column) == right_value


class _Query:
    def __init__(self, rows, db):
        self.rows = rows
        self.db = db
        self.filters = []

    def filter(self, *exprs):
        self.filters.extend(exprs)
        return self

    def with_for_update(self):
        self.db.for_update_used = True
        return self

    def _matched(self):
        return [r for r in self.rows if all(_matches_expression(r, e) for e in self.filters)]

    def first(self):
        matched = self._matched()
        return matched[0] if matched else None

    def all(self):
        return self._matched()


class _EvalDb:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.added = []
        self.events = []
        self.commits = 0
        self.rollbacks = 0
        self.for_update_used = False

    def query(self, model, *rest):
        return _Query([r for r in self.rows if isinstance(r, model)], self)

    def add(self, obj):
        self.added.append(obj)
        self.rows.append(obj)

    def flush(self):
        pass

    def commit(self):
        self.commits += 1
        self.events.append("commit")

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, obj):
        pass

    def added_of(self, model):
        return [o for o in self.added if isinstance(o, model)]


def _budget(is_enabled=True, amount="100.00"):
    return SimpleNamespace(monthly_budget_usd=Decimal(amount), is_enabled=is_enabled)


def _workflow(org_id):
    return SimpleNamespace(id=uuid4(), organization_id=org_id, created_by=uuid4())


def _org(org_id):
    return SimpleNamespace(id=org_id, created_by=None, managed_by=None, memberships=[])


def _state(workflow_id, last_status, period_month="2026-07"):
    return BudgetAlertState(
        workflow_id=workflow_id,
        period_month=period_month,
        last_notified_status=last_status,
    )


@pytest.fixture
def wire(monkeypatch):
    """당월 비용 재계산, 수신자 해석, SSE 발행을 대체한다. 발행은 db.events에 남긴다."""

    def _apply(db, recipients, month_cost):
        monkeypatch.setattr(
            budget_alert_service,
            "resolve_alert_recipients",
            lambda _db, _wf, _org: set(recipients),
        )
        monkeypatch.setattr(
            budget_alert_service,
            "publish_notifications_changed",
            lambda uid: db.events.append(("publish", uid)),
        )
        monkeypatch.setattr(
            budget_alert_service.WorkflowBudgetService,
            "get_current_month_cost",
            lambda _db, _workflow_id, _now: month_cost,
        )

    return _apply


def _evaluate(db, *, workflow, organization, budget):
    return budget_alert_service.evaluate_budget_alert(
        db, workflow=workflow, organization=organization, budget=budget, now=NOW
    )


# --- 발송 케이스 -------------------------------------------------------------


def test_at_risk_creates_items_and_publishes(wire):
    org_id = uuid4()
    wf, org, budget = _workflow(org_id), _org(org_id), _budget(amount="100.00")
    u1, u2 = uuid4(), uuid4()
    db = _EvalDb()
    wire(db, {u1, u2}, month_cost=Decimal("95.00"))

    result = _evaluate(db, workflow=wf, organization=org, budget=budget)

    assert result == "at_risk"
    items = db.added_of(BudgetAlert)
    assert len(items) == 2
    assert {i.user_id for i in items} == {u1, u2}
    assert all(i.status == "at_risk" for i in items)
    published = {e[1] for e in db.events if e[0] == "publish"}
    assert published == {u1, u2}
    assert db.commits >= 1


def test_escalation_publishes_exceeded(wire):
    org_id = uuid4()
    wf, org, budget = _workflow(org_id), _org(org_id), _budget(amount="100.00")
    u1 = uuid4()
    db = _EvalDb(rows=[_state(wf.id, "at_risk")])
    wire(db, {u1}, month_cost=Decimal("150.00"))

    result = _evaluate(db, workflow=wf, organization=org, budget=budget)

    assert result == "exceeded"
    items = db.added_of(BudgetAlert)
    assert len(items) == 1 and items[0].status == "exceeded"
    assert ("publish", u1) in db.events


def test_snapshot_values_on_created_items(wire):
    org_id = uuid4()
    wf, org, budget = _workflow(org_id), _org(org_id), _budget(amount="200.00")
    u1 = uuid4()
    db = _EvalDb()
    wire(db, {u1}, month_cost=Decimal("190.00"))

    _evaluate(db, workflow=wf, organization=org, budget=budget)

    item = db.added_of(BudgetAlert)[0]
    assert item.monthly_budget_usd == Decimal("200.00")
    assert item.current_month_cost == Decimal("190.00")
    assert item.usage_ratio == Decimal("0.95")


def test_commits_before_publishing(wire):
    # SSE는 커밋 이후에 발행되어야 한다(도달 시점에 데이터가 보이도록).
    org_id = uuid4()
    wf, org, budget = _workflow(org_id), _org(org_id), _budget(amount="100.00")
    u1, u2 = uuid4(), uuid4()
    db = _EvalDb()
    wire(db, {u1, u2}, month_cost=Decimal("95.00"))

    _evaluate(db, workflow=wf, organization=org, budget=budget)

    commit_index = db.events.index("commit")
    publish_indexes = [i for i, e in enumerate(db.events) if e[0] == "publish"]
    assert publish_indexes
    assert all(commit_index < pi for pi in publish_indexes)


def test_recomputes_current_month_cost_not_run_cost(monkeypatch):
    # run 비용이 아니라 workflow_id로 재계산한 당월 누적 비용으로 판정한다 (BGA-REQ-003).
    org_id = uuid4()
    wf, org, budget = _workflow(org_id), _org(org_id), _budget(amount="100.00")
    u1 = uuid4()
    db = _EvalDb()
    calls = []

    monkeypatch.setattr(
        budget_alert_service, "resolve_alert_recipients", lambda _db, _wf, _org: {u1}
    )
    monkeypatch.setattr(
        budget_alert_service,
        "publish_notifications_changed",
        lambda uid: db.events.append(("publish", uid)),
    )

    def _fake_cost(_db, workflow_id, _now):
        calls.append(workflow_id)
        return Decimal("91.00")  # 당월 누적(at_risk); 방금 run 비용은 작을 수 있음

    monkeypatch.setattr(
        budget_alert_service.WorkflowBudgetService,
        "get_current_month_cost",
        _fake_cost,
    )

    result = budget_alert_service.evaluate_budget_alert(
        db, workflow=wf, organization=org, budget=budget, now=NOW
    )

    assert result == "at_risk"
    assert calls == [wf.id]
    assert db.added_of(BudgetAlert)[0].current_month_cost == Decimal("91.00")


# --- 무발송 케이스 -----------------------------------------------------------


def test_no_transition_no_items_no_publish(wire):
    org_id = uuid4()
    wf, org, budget = _workflow(org_id), _org(org_id), _budget(amount="100.00")
    db = _EvalDb(rows=[_state(wf.id, "at_risk")])  # 이미 at_risk 알림됨
    wire(db, {uuid4()}, month_cost=Decimal("95.00"))

    result = _evaluate(db, workflow=wf, organization=org, budget=budget)

    assert result is None
    assert db.added_of(BudgetAlert) == []
    assert [e for e in db.events if e[0] == "publish"] == []


def test_normal_status_skips(wire):
    org_id = uuid4()
    wf, org, budget = _workflow(org_id), _org(org_id), _budget(amount="100.00")
    db = _EvalDb()
    wire(db, {uuid4()}, month_cost=Decimal("50.00"))

    result = _evaluate(db, workflow=wf, organization=org, budget=budget)

    assert result is None
    assert db.added_of(BudgetAlert) == []
    assert db.added_of(BudgetAlertState) == []
    assert [e for e in db.events if e[0] == "publish"] == []


def test_inactive_budget_skips(wire):
    org_id = uuid4()
    wf, org = _workflow(org_id), _org(org_id)
    budget = _budget(is_enabled=False, amount="100.00")
    db = _EvalDb()
    wire(db, {uuid4()}, month_cost=Decimal("95.00"))

    result = _evaluate(db, workflow=wf, organization=org, budget=budget)

    assert result is None
    assert db.added_of(BudgetAlert) == []
    assert db.added_of(BudgetAlertState) == []
    assert [e for e in db.events if e[0] == "publish"] == []


def test_budget_none_skips(wire):
    org_id = uuid4()
    wf, org = _workflow(org_id), _org(org_id)
    db = _EvalDb()
    wire(db, {uuid4()}, month_cost=Decimal("95.00"))

    result = _evaluate(db, workflow=wf, organization=org, budget=None)

    assert result is None
    assert db.added_of(BudgetAlert) == []


# --- run_budget_alert_evaluation (task 래퍼: workflow/org/budget 로드) --------


class _LoaderDb:
    """model 클래스별 preset row를 반환하는 최소 로더 fake."""

    class _One:
        def __init__(self, obj):
            self.obj = obj

        def filter(self, *args):
            return self

        def first(self):
            return self.obj

    def __init__(self, by_model):
        self._by_model = by_model

    def query(self, model, *rest):
        return _LoaderDb._One(self._by_model.get(model))


def _models():
    from apps.shared.db.models.organization import Organization
    from apps.shared.db.models.workflow import Workflow
    from apps.shared.db.models.workflow_budget import WorkflowBudget

    return Workflow, WorkflowBudget, Organization


def test_run_loads_entities_and_evaluates(monkeypatch):
    Workflow, WorkflowBudget, Organization = _models()
    org_id, wf_id = uuid4(), uuid4()
    workflow = SimpleNamespace(id=wf_id, organization_id=org_id)
    budget = SimpleNamespace(monthly_budget_usd=Decimal("100.00"), is_enabled=True)
    organization = SimpleNamespace(id=org_id)
    db = _LoaderDb({Workflow: workflow, WorkflowBudget: budget, Organization: organization})

    captured = {}
    monkeypatch.setattr(
        budget_alert_service,
        "evaluate_budget_alert",
        lambda _db, **kw: captured.update(kw) or "at_risk",
    )

    result = budget_alert_service.run_budget_alert_evaluation(db, wf_id, now=NOW)

    assert result == "at_risk"
    assert captured["workflow"] is workflow
    assert captured["organization"] is organization
    assert captured["budget"] is budget
    assert captured["now"] == NOW


def test_run_skips_when_workflow_missing(monkeypatch):
    Workflow, WorkflowBudget, Organization = _models()
    db = _LoaderDb({Workflow: None, WorkflowBudget: None, Organization: None})
    called = []
    monkeypatch.setattr(
        budget_alert_service, "evaluate_budget_alert", lambda *a, **k: called.append(1)
    )

    result = budget_alert_service.run_budget_alert_evaluation(db, uuid4())

    assert result is None
    assert called == []


def test_run_skips_when_budget_missing(monkeypatch):
    Workflow, WorkflowBudget, Organization = _models()
    wf_id, org_id = uuid4(), uuid4()
    workflow = SimpleNamespace(id=wf_id, organization_id=org_id)
    db = _LoaderDb(
        {Workflow: workflow, WorkflowBudget: None, Organization: SimpleNamespace(id=org_id)}
    )
    called = []
    monkeypatch.setattr(
        budget_alert_service, "evaluate_budget_alert", lambda *a, **k: called.append(1)
    )

    result = budget_alert_service.run_budget_alert_evaluation(db, wf_id)

    assert result is None
    assert called == []
