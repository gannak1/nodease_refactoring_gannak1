"""Red-phase tests for budget alert recipient fan-out (BGA-REQ-030, 팬아웃 멱등성).

`create_alert_items(db, *, workflow_id, organization_id, period_month, status,
recipient_ids, usage_ratio, monthly_budget_usd, current_month_cost)`는
수신자별 budget_alerts 항목을 스냅샷과 함께 생성한다.

- 멱등: (workflow, 당월, status)에 이미 있는 user는 건너뛰고 누락분만 채운다.
- status가 다르면 별도 항목(escalation).
- 생성된 항목 리스트를 반환한다(호출자가 SSE 발행 대상 결정).

대응 문서: docs/features/budget-alerts/test_cases.md
  - Concurrency Tests > 팬아웃 멱등성
  - Acceptance Criteria AC-4
"""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy.sql.operators import eq

from apps.shared.db.models.budget_alert import BudgetAlert
from apps.shared.services.budget_alerts import create_alert_items


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
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def filter(self, *exprs):
        self.filters.extend(exprs)
        return self

    def all(self):
        return [
            r for r in self.rows if all(_matches_expression(r, e) for e in self.filters)
        ]


class _FanoutDb:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.added = []

    def query(self, model, *rest):
        return _Query([r for r in self.rows if isinstance(r, model)])

    def add(self, obj):
        self.added.append(obj)
        self.rows.append(obj)

    def added_of(self, model):
        return [o for o in self.added if isinstance(o, model)]


def _existing(workflow_id, organization_id, user_id, period_month, status):
    return BudgetAlert(
        workflow_id=workflow_id,
        organization_id=organization_id,
        user_id=user_id,
        period_month=period_month,
        status=status,
        usage_ratio=Decimal("0.95"),
        monthly_budget_usd=Decimal("100.00"),
        current_month_cost=Decimal("95.00"),
    )


def _create(db, wf, org, users, *, status="at_risk", period="2026-07",
            usage_ratio=Decimal("0.95"), budget=Decimal("100.00"), cost=Decimal("95.00")):
    return create_alert_items(
        db,
        workflow_id=wf,
        organization_id=org,
        period_month=period,
        status=status,
        recipient_ids=users,
        usage_ratio=usage_ratio,
        monthly_budget_usd=budget,
        current_month_cost=cost,
    )


def test_creates_item_per_recipient():
    db = _FanoutDb()
    wf, org = uuid4(), uuid4()
    users = [uuid4() for _ in range(3)]
    created = _create(db, wf, org, users)
    rows = db.added_of(BudgetAlert)
    assert len(rows) == 3
    assert {r.user_id for r in rows} == set(users)
    assert {r.user_id for r in created} == set(users)
    for r in rows:
        assert r.workflow_id == wf
        assert r.organization_id == org
        assert r.period_month == "2026-07"
        assert r.status == "at_risk"


def test_snapshot_values_stored():
    db = _FanoutDb()
    wf, org, u = uuid4(), uuid4(), uuid4()
    _create(
        db, wf, org, [u], status="exceeded",
        usage_ratio=Decimal("1.5"), budget=Decimal("200.00"), cost=Decimal("300.00"),
    )
    row = db.added_of(BudgetAlert)[0]
    assert row.usage_ratio == Decimal("1.5")
    assert row.monthly_budget_usd == Decimal("200.00")
    assert row.current_month_cost == Decimal("300.00")


def test_skips_existing_recipient_items():
    wf, org = uuid4(), uuid4()
    u1, u2, u3 = uuid4(), uuid4(), uuid4()
    db = _FanoutDb(rows=[_existing(wf, org, u1, "2026-07", "at_risk")])
    created = _create(db, wf, org, [u1, u2, u3])
    assert {r.user_id for r in db.added_of(BudgetAlert)} == {u2, u3}
    assert {r.user_id for r in created} == {u2, u3}


def test_all_existing_creates_nothing():
    wf, org = uuid4(), uuid4()
    u1, u2 = uuid4(), uuid4()
    db = _FanoutDb(
        rows=[
            _existing(wf, org, u1, "2026-07", "at_risk"),
            _existing(wf, org, u2, "2026-07", "at_risk"),
        ]
    )
    created = _create(db, wf, org, [u1, u2])
    assert db.added_of(BudgetAlert) == []
    assert created == []


def test_different_status_not_skipped():
    # 같은 (workflow, month, user)라도 status가 다르면 별도 항목 (escalation).
    wf, org, u1 = uuid4(), uuid4(), uuid4()
    db = _FanoutDb(rows=[_existing(wf, org, u1, "2026-07", "at_risk")])
    _create(db, wf, org, [u1], status="exceeded")
    added = db.added_of(BudgetAlert)
    assert len(added) == 1
    assert added[0].user_id == u1
    assert added[0].status == "exceeded"


def test_empty_recipients_creates_nothing():
    db = _FanoutDb()
    created = _create(db, uuid4(), uuid4(), [])
    assert created == []
    assert db.added_of(BudgetAlert) == []


def test_duplicate_recipient_ids_deduped():
    # BGA-REQ-021: 한 사용자는 하나의 전이에 최대 1건. 입력에 중복이 있어도
    # 같은 row를 두 번 add하지 않는다(unique 위반으로 task 실패 방지).
    db = _FanoutDb()
    wf, org, u = uuid4(), uuid4(), uuid4()
    created = _create(db, wf, org, [u, u])
    added = db.added_of(BudgetAlert)
    assert len(added) == 1
    assert added[0].user_id == u
    assert len(created) == 1
