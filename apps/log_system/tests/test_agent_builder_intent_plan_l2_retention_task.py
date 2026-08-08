import pytest
from apps.log_system import tasks as log_tasks
from apps.shared.services.agent_builder_intent_plan_l2_retention import (
    DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN,
    DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT,
    AgentBuilderIntentPlanL2RetentionService,
)


def test_l2_retention_purge_beat_can_run_without_task_data(monkeypatch) -> None:
    events: list[tuple] = []

    class Session:
        def close(self) -> None:
            events.append(("close",))

    session = Session()
    monkeypatch.setattr(log_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        AgentBuilderIntentPlanL2RetentionService,
        "purge",
        lambda db, *, limit: events.append(("purge", db, limit))
        or {
            "semantic_purged_count": 0,
            "parent_purged_count": 0,
            "purged_count": 0,
            "limit": limit,
            "batch_full": False,
        },
    )

    result = log_tasks.agent_builder_intent_plan_l2_retention_purge.run()

    assert result == {
        "status": "success",
        "result": {
            "semantic_purged_count": 0,
            "parent_purged_count": 0,
            "purged_count": 0,
            "limit": DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT,
            "batches": 1,
        },
    }
    assert events == [
        ("purge", session, DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT),
        ("close",),
    ]


def test_l2_retention_purge_uses_bounded_catch_up_batches(monkeypatch) -> None:
    events: list[tuple] = []

    class Session:
        def close(self) -> None:
            events.append(("close",))

    session = Session()
    purge_results = iter(((10, 0), (0, 10), (1, 3)))
    monkeypatch.setattr(log_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        AgentBuilderIntentPlanL2RetentionService,
        "purge",
        lambda db, *, limit: events.append(("purge", db, limit))
        or (lambda counts: {
            "semantic_purged_count": counts[0],
            "parent_purged_count": counts[1],
            "purged_count": counts[0] + counts[1],
            "limit": limit,
            "batch_full": counts[0] == limit or counts[1] == limit,
        })(next(purge_results)),
    )

    result = log_tasks.agent_builder_intent_plan_l2_retention_purge.run(
        {"limit": 10, "max_batches": 3}
    )

    assert result == {
        "status": "success",
        "result": {
            "semantic_purged_count": 11,
            "parent_purged_count": 13,
            "purged_count": 24,
            "limit": 10,
            "batches": 3,
        },
    }
    assert events == [
        ("purge", session, 10),
        ("purge", session, 10),
        ("purge", session, 10),
        ("close",),
    ]
    assert DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN >= 3


@pytest.mark.parametrize(
    "data",
    [
        {"limit": 1001},
        {"max_batches": 6},
    ],
)
def test_l2_retention_purge_rejects_values_above_the_documented_hard_cap(
    monkeypatch,
    data,
) -> None:
    events: list[tuple] = []

    class Session:
        def rollback(self) -> None:
            events.append(("rollback",))

        def close(self) -> None:
            events.append(("close",))

    session = Session()
    monkeypatch.setattr(log_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        AgentBuilderIntentPlanL2RetentionService,
        "purge",
        lambda _db, *, limit: {
            "semantic_purged_count": 0,
            "parent_purged_count": 0,
            "purged_count": 0,
            "limit": limit,
            "batch_full": False,
        },
    )

    result = log_tasks.agent_builder_intent_plan_l2_retention_purge.run(data)

    assert result == {
        "status": "failed",
        "error": "invalid_agent_builder_intent_plan_l2_purge_request",
    }
    assert events == [("rollback",), ("close",)]
