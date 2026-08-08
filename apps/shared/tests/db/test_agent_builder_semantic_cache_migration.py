from __future__ import annotations

from pathlib import Path

from apps.shared.alembic.versions import (
    b19d0e1f2a34_add_agent_builder_private_semantic_cache as migration,
)
from apps.shared.db import models
from apps.shared.db.models.agent_builder import (
    AgentBuilderIntentPlanCacheRecord,
    AgentBuilderIntentPlanSemanticCacheEntry,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, inspect


def test_semantic_cache_migration_extends_the_jeo7_head() -> None:
    assert migration.revision == "b19d0e1f2a34"
    assert migration.down_revision == "b18c9d0e1f23"
    assert migration.SEMANTIC_DOWNGRADE_GUARD == (
        "Cannot remove Agent Builder semantic cache while entries exist."
    )


def test_semantic_cache_model_has_private_scope_vector_and_lifecycle_contract() -> None:
    table = AgentBuilderIntentPlanSemanticCacheEntry.__table__
    columns = table.c

    assert isinstance(columns.safe_query_embedding.type, Vector)
    assert columns.organization_id.nullable is False
    assert columns.user_id.nullable is False
    assert columns.intent_plan_record_id.nullable is False
    assert columns.expires_at.nullable is False
    assert columns.safe_query_embedding.nullable is False
    assert "raw_request" not in columns
    assert "query_text" not in columns
    assert "plan" not in columns
    assert "score" not in columns

    foreign_keys = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]
    assert any(
        tuple(element.parent.name for element in constraint.elements)
        == ("organization_id", "intent_plan_record_id")
        and tuple(element.target_fullname for element in constraint.elements)
        == (
            "agent_builder_intent_plan_cache_records.organization_id",
            "agent_builder_intent_plan_cache_records.id",
        )
        and constraint.ondelete == "CASCADE"
        for constraint in foreign_keys
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns} == {"organization_id", "id"}
        for constraint in AgentBuilderIntentPlanCacheRecord.__table__.constraints
    )


def test_semantic_cache_migration_source_has_cascade_indexes_and_guarded_downgrade() -> (
    None
):
    source = Path(migration.__file__).read_text(encoding="utf-8")

    assert 'ondelete="CASCADE"' in source
    assert "safe_query_embedding" in source
    assert "semantic_query_projection_version" in source
    assert "embedding_profile_version" in source
    assert "embedding_model_version" in source
    assert "rehydration_contract_version" in source
    assert "ix_agent_builder_semantic_cache_scope_versions_expiry" in source
    assert "uq_agent_builder_semantic_cache_parent_profile_contract" in source
    assert "SEMANTIC_DOWNGRADE_GUARD" in source
    assert source.index("SEMANTIC_DOWNGRADE_GUARD") < source.index(
        'op.drop_table("agent_builder_intent_plan_semantic_cache_entries")'
    )


def test_semantic_cache_model_is_registered_once() -> None:
    mapper = inspect(AgentBuilderIntentPlanSemanticCacheEntry)

    assert mapper.local_table.name == "agent_builder_intent_plan_semantic_cache_entries"
    assert (
        models.AgentBuilderIntentPlanSemanticCacheEntry
        is AgentBuilderIntentPlanSemanticCacheEntry
    )
