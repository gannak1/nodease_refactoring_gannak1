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
