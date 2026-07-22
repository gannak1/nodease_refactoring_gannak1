from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_provider_usage_migration_remains_the_only_alembic_head() -> None:
    config = Config("apps/shared/alembic.ini")
    config.set_main_option("script_location", "apps/shared/alembic")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert len(heads) == 1
    head = script.get_revision(heads[0])
    assert head is not None
    assert head.down_revision is not None
    assert "provider_usage" in head.module.__name__
