from apps.shared.alembic.versions import (
    b18c9d0e1f23_add_agent_builder_intent_plan_l2_cache as migration,
)
from apps.shared.db.models.agent_builder import AgentBuilderRequest
from sqlalchemy import inspect


def test_l2_migration_extends_the_current_alembic_head() -> None:
    assert migration.revision == "b18c9d0e1f23"
    assert migration.down_revision == "b17c8d9e0f12"


def test_l2_migration_declares_a_non_destructive_downgrade_guard() -> None:
    assert migration.L2_DOWNGRADE_GUARD == (
        "Cannot remove Agent Builder durable intent-plan cache while records exist."
    )


def test_request_history_outcome_is_omitted_until_its_additive_column_exists() -> None:
    mapper = inspect(AgentBuilderRequest)

    assert mapper.attrs.intent_cache_outcome.deferred is True
    assert AgentBuilderRequest.__table__.c.intent_cache_outcome.server_default is not None
    assert mapper.eager_defaults is False
