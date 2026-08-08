from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from apps.shared.services.agent_builder_intent_plan_l2_retention import (
    DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN,
    DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT,
    MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN,
    MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT,
    AgentBuilderIntentPlanL2RetentionService,
)
from sqlalchemy.dialects import postgresql


class _PurgeQuery:
    def __init__(self, rows, *, error: Exception | None = None) -> None:
        self._rows = rows
        self._error = error

    def filter(self, *_conditions):
        return self

    def order_by(self, *_order):
        return self

    def limit(self, _limit: int):
        return self

    def all(self):
        if self._error is not None:
            raise self._error
        return self._rows


class _PurgeDb:
    def __init__(
        self,
        *,
        semantic_rows=(),
        parent_rows=(),
        semantic_delete_rowcount: int = 0,
        parent_delete_rowcount: int = 0,
        semantic_query_error: Exception | None = None,
    ) -> None:
        self._semantic_rows = semantic_rows
        self._parent_rows = parent_rows
        self._semantic_delete_rowcount = semantic_delete_rowcount
        self._parent_delete_rowcount = parent_delete_rowcount
        self._semantic_query_error = semantic_query_error
        self.deleted = []
        self.statements = []
        self.committed = False
        self.nested_entries = 0

    def query(self, model):
        if "SemanticCacheEntry" in str(model):
            return _PurgeQuery(
                self._semantic_rows,
                error=self._semantic_query_error,
            )
        return _PurgeQuery(self._parent_rows)

    def delete(self, row) -> None:
        self.deleted.append(row)

    def execute(self, statement):
        self.statements.append(statement)
        statement_sql = str(statement.compile(dialect=postgresql.dialect()))
        if "semantic_cache_entries" in statement_sql:
            return SimpleNamespace(rowcount=self._semantic_delete_rowcount)
        return SimpleNamespace(rowcount=self._parent_delete_rowcount)

    class _Nested:
        def __init__(self, owner) -> None:
            self.owner = owner

        def __enter__(self):
            self.owner.nested_entries += 1
            return self

        def __exit__(self, _type, _value, _traceback):
            return False

    def begin_nested(self):
        return self._Nested(self)

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


def test_l2_retention_default_batch_count_is_bounded() -> None:
    assert DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN == 5
    assert (
        AgentBuilderIntentPlanL2RetentionService.validate_batch_count(
            DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN
        )
        == DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN
    )


def test_l2_retention_beat_uses_the_bounded_catch_up_cadence() -> None:
    from apps.shared.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule[
        "agent-builder-intent-plan-l2-retention"
    ]

    assert schedule["schedule"] == 300.0
    assert schedule["options"] == {"queue": "log"}


@pytest.mark.parametrize(
    "limit",
    [0, -1, True, MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT + 1],
)
def test_l2_retention_rejects_unbounded_or_non_integer_batch_limits(limit) -> None:
    with pytest.raises(ValueError):
        AgentBuilderIntentPlanL2RetentionService.validate_limit(limit)


@pytest.mark.parametrize(
    "batch_count",
    [0, -1, True, MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN + 1],
)
def test_l2_retention_rejects_unbounded_or_non_integer_batch_counts(
    batch_count,
) -> None:
    with pytest.raises(ValueError):
        AgentBuilderIntentPlanL2RetentionService.validate_batch_count(batch_count)


def test_l2_retention_rechecks_expiry_and_reports_actual_delete_count() -> None:
    db = _PurgeDb(
        semantic_rows=[(uuid4(),)],
        parent_rows=[(uuid4(),)],
        semantic_delete_rowcount=0,
        parent_delete_rowcount=0,
    )

    result = AgentBuilderIntentPlanL2RetentionService.purge(
        db,
        now=datetime(2026, 8, 8, tzinfo=timezone.utc),
        limit=10,
    )

    assert result == {
        "semantic_purged_count": 0,
        "parent_purged_count": 0,
        "purged_count": 0,
        "limit": 10,
        "batch_full": False,
    }
    assert db.deleted == []
    assert db.committed is True
    assert db.nested_entries == 1
    assert len(db.statements) == 2
    semantic_sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    parent_sql = str(db.statements[1].compile(dialect=postgresql.dialect()))
    assert "DELETE FROM agent_builder_intent_plan_semantic_cache_entries" in semantic_sql
    assert "DELETE FROM agent_builder_intent_plan_cache_records" in parent_sql
    assert "id IN" in semantic_sql and "expires_at <=" in semantic_sql
    assert "id IN" in parent_sql and "expires_at <=" in parent_sql


class _MissingSemanticSchemaError(Exception):
    pgcode = "42P01"


def test_semantic_readiness_rolls_back_only_child_step_and_parent_purge_continues() -> None:
    db = _PurgeDb(
        parent_rows=[(uuid4(),)],
        parent_delete_rowcount=1,
        semantic_query_error=_MissingSemanticSchemaError(),
    )

    result = AgentBuilderIntentPlanL2RetentionService.purge(
        db,
        now=datetime(2026, 8, 8, tzinfo=timezone.utc),
        limit=10,
    )

    assert result == {
        "semantic_purged_count": 0,
        "parent_purged_count": 1,
        "purged_count": 1,
        "limit": 10,
        "batch_full": False,
    }
    assert db.committed is True
    assert len(db.statements) == 1
    parent_sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "DELETE FROM agent_builder_intent_plan_cache_records" in parent_sql


def test_child_or_parent_full_batch_keeps_bounded_catch_up_active() -> None:
    for semantic_count, parent_count in ((10, 0), (0, 10), (10, 10)):
        db = _PurgeDb(
            semantic_rows=[(uuid4(),)],
            parent_rows=[(uuid4(),)],
            semantic_delete_rowcount=semantic_count,
            parent_delete_rowcount=parent_count,
        )

        result = AgentBuilderIntentPlanL2RetentionService.purge(
            db,
            now=datetime(2026, 8, 8, tzinfo=timezone.utc),
            limit=10,
        )

        assert result["batch_full"] is True
        assert result["purged_count"] == semantic_count + parent_count
