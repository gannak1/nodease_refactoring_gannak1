from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from apps.shared.domain.schedule_dispatch import ScheduleDispatchSettings
from apps.shared.services.alembic_readiness import (
    AlembicReadinessResult,
    check_alembic_readiness_with_inspector,
)

ROOT_DIR = Path(__file__).resolve().parents[3]


class GatewayMigrationNotReadyError(RuntimeError):
    pass


def gateway_alembic_readiness(
    schema_inspector,
    *,
    script_directory: ScriptDirectory | None = None,
) -> AlembicReadinessResult:
    script = script_directory or _script_directory()
    return check_alembic_readiness_with_inspector(
        schema_inspector,
        code_heads=script.get_heads(),
        known_revisions=[revision.revision for revision in script.walk_revisions()],
    )


def require_schedule_dispatch_migration_ready(
    engine: Engine,
    *,
    settings: ScheduleDispatchSettings,
) -> None:
    if not settings.processes_existing_claims:
        return
    result = gateway_alembic_readiness(inspect(engine))
    if not result.ready:
        raise GatewayMigrationNotReadyError(
            "database migration is not ready for schedule dispatch"
        )


def _script_directory() -> ScriptDirectory:
    config = Config(str(ROOT_DIR / "apps" / "shared" / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(ROOT_DIR / "apps" / "shared" / "alembic"),
    )
    return ScriptDirectory.from_config(config)
