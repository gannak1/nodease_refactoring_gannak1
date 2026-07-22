from apps.shared.alembic.versions import (
    ae2f3a4b5c6d_add_query_embedding_provider_capability as migration,
)


def test_query_embedding_capability_migration_extends_current_provider_head():
    assert migration.revision == "ae2f3a4b5c6d"
    assert migration.down_revision == "ad1e2f3a4b5c"


def test_query_embedding_downgrade_guard_is_explicit():
    assert migration.QUERY_EMBEDDING_DOWNGRADE_GUARD == (
        "query_embedding policies or capabilities must be removed before downgrade"
    )
