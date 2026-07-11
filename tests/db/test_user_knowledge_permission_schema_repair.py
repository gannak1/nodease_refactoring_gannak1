from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def _script_directory() -> ScriptDirectory:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "apps" / "shared" / "alembic.ini"))
    config.set_main_option(
        "script_location", str(root / "apps" / "shared" / "alembic")
    )
    return ScriptDirectory.from_config(config)


def test_user_knowledge_permission_schema_repair_follows_current_head():
    """이미 stamp된 로컬 DB도 KB 직접 권한 스키마를 보정할 수 있어야 한다."""
    script = _script_directory()
    revision = script.get_revision("fd0e1f2a3b4c")

    assert revision is not None
    assert revision.down_revision == "fc9a1b2c3d4e"

    source = Path(revision.path).read_text(encoding="utf-8")
    assert "uq_knowledge_bases_id_organization_id" in source
    assert "user_knowledge_permissions" in source


def test_latest_merge_joins_cost_optimizer_and_schedule_heads_without_rewriting_history():
    """이미 적용 가능한 migration parent는 유지하고 새 merge revision으로 합쳐야 한다."""
    script = _script_directory()
    model_routing_revision = script.get_revision("fb8c9d0e1f23")
    external_effect_revision = script.get_revision("fe3f4a5b6c78")
    merge_revision = script.get_revision("ff6d7e8f9012")

    assert model_routing_revision.down_revision == "fa7b8c9d0e12"
    assert external_effect_revision.down_revision == "b39e0f1a2b43"
    assert set(merge_revision.down_revision) == {
        "fd0e1f2a3b4c",
        "fe3f4a5b6c78",
    }
    assert script.get_heads() == ["ff6d7e8f9012"]
