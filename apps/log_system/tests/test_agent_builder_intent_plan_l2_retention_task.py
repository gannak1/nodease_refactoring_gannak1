from apps.log_system import tasks as log_tasks
from apps.shared.services.agent_builder_intent_plan_l2_retention import (
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
        or {"purged_count": 0, "limit": limit},
    )

    result = log_tasks.agent_builder_intent_plan_l2_retention_purge.run()

    assert result == {
        "status": "success",
        "result": {
            "purged_count": 0,
            "limit": DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT,
        },
    }
    assert events == [
        ("purge", session, DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT),
        ("close",),
    ]
