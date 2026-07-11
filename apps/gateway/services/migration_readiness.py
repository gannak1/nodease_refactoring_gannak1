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


_REQUIRED_SCHEDULE_DISPATCH_SCHEMA = {
    "schedule_dispatch_claims": {
        "id",
        "schedule_id",
        "organization_id",
        "deployment_id",
        "scheduled_for",
        "idempotency_key",
        "status",
        "attempt_count",
        "claimed_at",
        "workflow_run_id",
        "workflow_run_missing_reported_at",
        "execution_deadline_at",
    },
    "workflow_runs": {"user_id", "trigger_mode", "workflow_task_id"},
    "schedules": {"configuration_error_code"},
}


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
    inspector = inspect(engine)
    result = gateway_alembic_readiness(inspector)
    if not result.ready or not _required_schedule_dispatch_schema_exists(inspector):
        raise GatewayMigrationNotReadyError(
            "database migration is not ready for schedule dispatch"
        )


def _required_schedule_dispatch_schema_exists(schema_inspector) -> bool:
    try:
        for table_name, required_columns in _REQUIRED_SCHEDULE_DISPATCH_SCHEMA.items():
            if not schema_inspector.has_table(table_name):
                return False
            actual_columns = {
                column["name"] for column in schema_inspector.get_columns(table_name)
            }
            if not required_columns <= actual_columns:
                return False
        return True
    except Exception:
        return False


def _script_directory() -> ScriptDirectory:
    config = Config(str(ROOT_DIR / "apps" / "shared" / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(ROOT_DIR / "apps" / "shared" / "alembic"),
    )
    return ScriptDirectory.from_config(config)
