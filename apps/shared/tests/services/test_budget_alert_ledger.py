"""Red-phase tests for budget alert transition ledger update (BGA-REQ-010~013).

`record_transition(db, *, workflow_id, period_month, new_status)`는 (workflow, 당월)
전이 원장을 조건부로 갱신하고, 상향 전이면 발송할 임계를, 아니면 None을 반환한다.

동시성 안전:
- 갱신 전 with_for_update()로 원장 행을 잠가 UPDATE 경합을 직렬화한다.
- 생성 경합(concurrent insert)은 IntegrityError → rollback → 조건부 갱신으로 전환한다.
- commit은 호출자(평가 파이프라인)가 수행한다(원장 갱신 + 수신자 팬아웃 원자성).

대응 문서: docs/features/budget-alerts/test_cases.md
  - Concurrency Tests > 전이 중복 방지
  - Acceptance Criteria AC-2, AC-3
"""

from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.operators import eq

from apps.shared.db.models.budget_alert import BudgetAlertState
from apps.shared.services.budget_alerts import record_transition


# --- 최소 세션 fake (house 패턴) -------------------------------------------


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

    def first(self):
        for row in self.rows:
            if all(_matches_expression(row, e) for e in self.filters):
                return row
        return None


class _LedgerDb:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.added = []
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

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, obj):
        pass

    def added_of(self, model):
        return [o for o in self.added if isinstance(o, model)]


class _RacyLedgerDb(_LedgerDb):
    """첫 flush에서 unique 위반 → 경쟁 insert가 먼저 커밋된 상태 재현."""

    def __init__(self, competing_row):
        super().__init__(rows=[])
        self.competing_row = competing_row
        self._raised = False

    def flush(self):
        if not self._raised and any(
            isinstance(o, BudgetAlertState) for o in self.added
        ):
            self._raised = True
            self.added = [
                o for o in self.added if not isinstance(o, BudgetAlertState)
            ]
            self.rows = [
                r for r in self.rows if not isinstance(r, BudgetAlertState)
            ]
            self.rows.append(self.competing_row)
            raise IntegrityError(
                "INSERT INTO budget_alert_states ...",
                {},
                Exception(
                    "duplicate key value violates unique constraint "
                    '"uq_budget_alert_states_workflow_month"'
                ),
            )


def _state(workflow_id, period_month, last_status):
    return BudgetAlertState(
        workflow_id=workflow_id,
        period_month=period_month,
        last_notified_status=last_status,
    )


# --- 신규(원장 없음) --------------------------------------------------------


def test_first_at_risk_creates_row_and_returns_threshold():
    db = _LedgerDb()
    wf = uuid4()
    result = record_transition(
        db, workflow_id=wf, period_month="2026-07", new_status="at_risk"
    )
    assert result == "at_risk"
    rows = db.added_of(BudgetAlertState)
    assert len(rows) == 1
    assert rows[0].workflow_id == wf
    assert rows[0].period_month == "2026-07"
    assert rows[0].last_notified_status == "at_risk"


def test_first_exceeded_creates_row_returns_exceeded():
    db = _LedgerDb()
    wf = uuid4()
    result = record_transition(
        db, workflow_id=wf, period_month="2026-07", new_status="exceeded"
    )
    assert result == "exceeded"
    assert db.added_of(BudgetAlertState)[0].last_notified_status == "exceeded"


def test_normal_on_empty_creates_nothing_returns_none():
    db = _LedgerDb()
    wf = uuid4()
    result = record_transition(
        db, workflow_id=wf, period_month="2026-07", new_status="normal"
    )
    assert result is None
    assert db.added_of(BudgetAlertState) == []


# --- 기존 원장 있음 ---------------------------------------------------------


def test_escalation_updates_and_returns_exceeded():
    wf = uuid4()
    existing = _state(wf, "2026-07", "at_risk")
    db = _LedgerDb(rows=[existing])
    result = record_transition(
        db, workflow_id=wf, period_month="2026-07", new_status="exceeded"
    )
    assert result == "exceeded"
    assert existing.last_notified_status == "exceeded"
    assert db.added_of(BudgetAlertState) == []  # 새 row 없음


def test_same_status_no_update_returns_none():
    wf = uuid4()
    existing = _state(wf, "2026-07", "at_risk")
    db = _LedgerDb(rows=[existing])
    result = record_transition(
        db, workflow_id=wf, period_month="2026-07", new_status="at_risk"
    )
    assert result is None
    assert existing.last_notified_status == "at_risk"


def test_downward_no_update_returns_none():
    wf = uuid4()
    for new_status in ("at_risk", "normal"):
        existing = _state(wf, "2026-07", "exceeded")
        db = _LedgerDb(rows=[existing])
        result = record_transition(
            db, workflow_id=wf, period_month="2026-07", new_status=new_status
        )
        assert result is None
        assert existing.last_notified_status == "exceeded"


def test_different_month_creates_separate_row():
    wf = uuid4()
    june = _state(wf, "2026-06", "exceeded")
    db = _LedgerDb(rows=[june])
    result = record_transition(
        db, workflow_id=wf, period_month="2026-07", new_status="at_risk"
    )
    assert result == "at_risk"
    added = db.added_of(BudgetAlertState)
    assert len(added) == 1 and added[0].period_month == "2026-07"
    assert june.last_notified_status == "exceeded"  # 전월 불변


# --- 동시성: 행 잠금 + 생성 경합 --------------------------------------------


def test_uses_row_lock_before_update():
    # UPDATE 경합 직렬화: 갱신 전 with_for_update()로 행 잠금.
    wf = uuid4()
    existing = _state(wf, "2026-07", "at_risk")
    db = _LedgerDb(rows=[existing])
    record_transition(
        db, workflow_id=wf, period_month="2026-07", new_status="exceeded"
    )
    assert db.for_update_used is True


def test_create_race_falls_back_to_conditional_update():
    # 생성 경합: 경쟁 insert가 at_risk로 먼저 커밋 → 우리는 exceeded로 조건부 갱신.
    wf = uuid4()
    competing = _state(wf, "2026-07", "at_risk")
    db = _RacyLedgerDb(competing_row=competing)
    result = record_transition(
        db, workflow_id=wf, period_month="2026-07", new_status="exceeded"
    )
    assert result == "exceeded"
    assert competing.last_notified_status == "exceeded"
    assert db.rollbacks >= 1


def test_create_race_same_threshold_returns_none():
    # 경쟁 insert가 at_risk로 먼저 → 우리도 at_risk면 재발송 없음(중복 방지).
    wf = uuid4()
    competing = _state(wf, "2026-07", "at_risk")
    db = _RacyLedgerDb(competing_row=competing)
    result = record_transition(
        db, workflow_id=wf, period_month="2026-07", new_status="at_risk"
    )
    assert result is None
    assert competing.last_notified_status == "at_risk"
    assert db.rollbacks >= 1
