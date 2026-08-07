from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from apps.shared.services.agent_builder_intent_plan_l2_retention import (
    DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT,
    MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT,
    AgentBuilderIntentPlanL2RetentionService,
)


class _PurgeQuery:
    def __init__(self, rows) -> None:
        self._rows = rows

    def filter(self, *_conditions):
        return self

    def order_by(self, *_order):
        return self

    def limit(self, _limit: int):
        return self

    def all(self):
        return self._rows


class _PurgeDb:
    def __init__(self, *, rows, delete_rowcount: int) -> None:
        self._rows = rows
        self._delete_rowcount = delete_rowcount
        self.deleted = []
        self.statement = None
        self.committed = False

    def query(self, _model):
        return _PurgeQuery(self._rows)

    def delete(self, row) -> None:
        self.deleted.append(row)

    def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(rowcount=self._delete_rowcount)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        raise AssertionError("purge should not roll back")


def test_l2_retention_default_limit_is_bounded() -> None:
    assert DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT == 1000
    assert (
        AgentBuilderIntentPlanL2RetentionService.validate_limit(
            DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT
        )
        == DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT
    )


@pytest.mark.parametrize(
    "limit",
    [0, -1, True, MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT + 1],
)
def test_l2_retention_rejects_unbounded_or_non_integer_batch_limits(limit) -> None:
    with pytest.raises(ValueError):
        AgentBuilderIntentPlanL2RetentionService.validate_limit(limit)


def test_l2_retention_rechecks_expiry_and_reports_actual_delete_count() -> None:
    db = _PurgeDb(rows=[(uuid4(),)], delete_rowcount=0)

    result = AgentBuilderIntentPlanL2RetentionService.purge(
        db,
        now=datetime(2026, 8, 8, tzinfo=timezone.utc),
        limit=10,
    )

    assert result == {"purged_count": 0, "limit": 10}
    assert db.deleted == []
    assert db.committed is True
    assert db.statement is not None
    statement_sql = str(db.statement.compile(dialect=postgresql.dialect()))
    assert "DELETE FROM agent_builder_intent_plan_cache_records" in statement_sql
    assert "id IN" in statement_sql
    assert "expires_at <=" in statement_sql
