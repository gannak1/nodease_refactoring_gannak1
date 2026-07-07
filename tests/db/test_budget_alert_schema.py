"""budget alert 저장 구조 스키마 계약 테스트 (docs/features/budget-alerts).

- BGA-REQ-030: 두 영속 구조 — 전이 원장(budget_alert_states)과
  수신자별 알림 항목(budget_alerts).
- BGA-REQ-011: 전이 중복 방지의 기반인 DB unique 제약.
- 팬아웃 멱등성: 수신자별 항목의 UNIQUE(workflow_id, period_month, status, user_id).
- BGA-REQ-032: workflow 삭제 시 관련 row 함께 삭제 (FK cascade).
- BGA-REQ-031: 표시값 스냅샷(usage_ratio, monthly_budget_usd, current_month_cost).
"""

from datetime import datetime  # noqa: F401  (관례 유지용)

from sqlalchemy import (
    DateTime,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

# 주의: 모듈 top-level import 유지 (tests/db 다른 테스트의 Base registry 격리 이슈).
from apps.shared.db import models as shared_models
from apps.shared.db.models.budget_alert import BudgetAlert, BudgetAlertState


def _constraint(table, constraint_type, name):
    for constraint in table.constraints:
        if isinstance(constraint, constraint_type) and constraint.name == name:
            return constraint
    return None


# ---------------------------------------------------------------------------
# budget_alert_states (전이 원장)
# ---------------------------------------------------------------------------


def test_state_table_name_and_registration():
    assert BudgetAlertState.__tablename__ == "budget_alert_states"
    assert shared_models.BudgetAlertState is BudgetAlertState


def test_state_unique_workflow_period_month():
    # 전이 중복 방지: (workflow, 당월)당 원장 1 row (BGA-REQ-011).
    table = BudgetAlertState.__table__
    constraint = _constraint(
        table, UniqueConstraint, "uq_budget_alert_states_workflow_month"
    )
    assert constraint is not None
    assert [c.name for c in constraint.columns] == ["workflow_id", "period_month"]


def test_state_workflow_fk_cascade():
    # workflow 삭제 시 원장 삭제 (BGA-REQ-032).
    table = BudgetAlertState.__table__
    column = table.columns["workflow_id"]
    assert column.nullable is False
    assert isinstance(column.type, UUID)
    fks = list(column.foreign_keys)
    assert fks and all(fk.target_fullname == "workflows.id" for fk in fks)
    assert all(fk.ondelete == "CASCADE" for fk in fks)


def test_state_period_month_and_last_status_required():
    table = BudgetAlertState.__table__
    for name in ("period_month", "last_notified_status"):
        column = table.columns[name]
        assert column.nullable is False, name
        assert isinstance(column.type, String), name


def test_state_updated_at_tz_aware_with_server_default():
    table = BudgetAlertState.__table__
    column = table.columns["updated_at"]
    assert column.nullable is False
    assert isinstance(column.type, DateTime)
    assert column.type.timezone is True
    assert column.server_default is not None


# ---------------------------------------------------------------------------
# budget_alerts (수신자별 알림 항목)
# ---------------------------------------------------------------------------


def test_alert_table_name_and_registration():
    assert BudgetAlert.__tablename__ == "budget_alerts"
    assert shared_models.BudgetAlert is BudgetAlert


def test_alert_unique_workflow_month_status_user():
    # 전이 + 팬아웃 멱등성: 수신자당 (workflow, 월, 임계) 1 row.
    table = BudgetAlert.__table__
    constraint = _constraint(
        table, UniqueConstraint, "uq_budget_alerts_workflow_month_status_user"
    )
    assert constraint is not None
    assert [c.name for c in constraint.columns] == [
        "workflow_id",
        "period_month",
        "status",
        "user_id",
    ]


def test_alert_workflow_and_user_fk_cascade():
    # workflow/user 삭제 시 항목 삭제 (BGA-REQ-032).
    table = BudgetAlert.__table__
    for name, target in (("workflow_id", "workflows.id"), ("user_id", "users.id")):
        column = table.columns[name]
        assert column.nullable is False, name
        fks = list(column.foreign_keys)
        assert fks and all(fk.target_fullname == target for fk in fks), name
        assert all(fk.ondelete == "CASCADE" for fk in fks), name


def test_alert_organization_fk_required():
    table = BudgetAlert.__table__
    column = table.columns["organization_id"]
    assert column.nullable is False
    assert isinstance(column.type, UUID)
    assert any(fk.target_fullname == "organization.id" for fk in column.foreign_keys)


def test_alert_status_and_period_required():
    table = BudgetAlert.__table__
    for name in ("status", "period_month"):
        column = table.columns[name]
        assert column.nullable is False, name
        assert isinstance(column.type, String), name


def test_alert_snapshot_numeric_columns():
    # 표시값 스냅샷 (BGA-REQ-031). 스냅샷 수치는 예산 범위 이상을 담아야 한다.
    table = BudgetAlert.__table__

    budget = table.columns["monthly_budget_usd"]
    assert budget.nullable is False
    assert isinstance(budget.type, Numeric)
    assert budget.type.precision == 12 and budget.type.scale == 2
    budget_int_digits = budget.type.precision - budget.type.scale

    # current_month_cost는 월 누적 비용(예산 초과 포함) 스냅샷이므로
    # 예산 정수부 이상을 담아야 하고(overflow 방지), 6자리 정밀도를 유지한다.
    cost = table.columns["current_month_cost"]
    assert cost.nullable is False
    assert isinstance(cost.type, Numeric)
    assert cost.type.scale >= 6
    assert cost.type.precision - cost.type.scale >= budget_int_digits

    # usage_ratio도 작은 예산 대비 큰 비율을 담도록 예산 정수부 이상.
    usage_ratio = table.columns["usage_ratio"]
    assert usage_ratio.nullable is False
    assert isinstance(usage_ratio.type, Numeric)
    assert usage_ratio.type.precision - usage_ratio.type.scale >= budget_int_digits


def test_alert_read_at_nullable_and_created_at_default():
    table = BudgetAlert.__table__

    read_at = table.columns["read_at"]
    assert read_at.nullable is True  # null = 안읽음
    assert isinstance(read_at.type, DateTime)
    assert read_at.type.timezone is True

    created_at = table.columns["created_at"]
    assert created_at.nullable is False
    assert isinstance(created_at.type, DateTime)
    assert created_at.type.timezone is True
    assert created_at.server_default is not None


# ---------------------------------------------------------------------------
# alembic
# ---------------------------------------------------------------------------


def test_alembic_single_head_with_budget_alert_migration():
    # additive migration이 단일 head를 유지하며 두 테이블을 생성해야 한다.
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "apps" / "shared" / "alembic.ini"))
    config.set_main_option(
        "script_location", str(root / "apps" / "shared" / "alembic")
    )
    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()
    assert len(heads) == 1, f"multiple alembic heads: {heads}"

    texts = [
        Path(revision.path).read_text(encoding="utf-8")
        for revision in script.walk_revisions()
    ]
    assert any("budget_alert_states" in t for t in texts), "원장 테이블 migration 없음"
    assert any("budget_alerts" in t for t in texts), "알림 항목 테이블 migration 없음"
