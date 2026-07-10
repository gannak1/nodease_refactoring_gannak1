from types import SimpleNamespace

import pytest

from apps.gateway.services import migration_readiness
from apps.gateway.services.migration_readiness import (
    GatewayMigrationNotReadyError,
    require_schedule_dispatch_migration_ready,
)
from apps.shared.domain.schedule_dispatch import ScheduleDispatchSettings


def test_disabled_mode_does_not_introspect_or_mutate_schema(monkeypatch):
    monkeypatch.setattr(
        migration_readiness,
        "inspect",
        lambda _engine: (_ for _ in ()).throw(AssertionError("must not inspect")),
    )

    require_schedule_dispatch_migration_ready(
        object(),
        settings=ScheduleDispatchSettings(mode="disabled"),
    )


def test_claim_mode_fails_startup_when_migration_is_not_ready(monkeypatch):
    monkeypatch.setattr(migration_readiness, "inspect", lambda _engine: object())
    monkeypatch.setattr(
        migration_readiness,
        "gateway_alembic_readiness",
        lambda _inspector: SimpleNamespace(ready=False),
    )

    with pytest.raises(GatewayMigrationNotReadyError):
        require_schedule_dispatch_migration_ready(
            object(),
            settings=ScheduleDispatchSettings(mode="claim"),
        )


def test_claim_mode_fails_when_claim_schema_is_missing(monkeypatch):
    class _Inspector:
        def has_table(self, table_name):
            return table_name != "schedule_dispatch_claims"

    monkeypatch.setattr(migration_readiness, "inspect", lambda _engine: _Inspector())
    monkeypatch.setattr(
        migration_readiness,
        "gateway_alembic_readiness",
        lambda _inspector: SimpleNamespace(ready=True),
    )

    with pytest.raises(GatewayMigrationNotReadyError):
        require_schedule_dispatch_migration_ready(
            object(),
            settings=ScheduleDispatchSettings(mode="claim"),
        )


def test_claim_mode_accepts_current_single_head(monkeypatch):
    class _Inspector:
        def has_table(self, _table_name):
            return True

        def get_columns(self, _table_name):
            return [{"name": name} for name in {
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
                "execution_deadline_at",
                "user_id",
                "trigger_mode",
                "workflow_task_id",
            }]

    monkeypatch.setattr(migration_readiness, "inspect", lambda _engine: _Inspector())
    monkeypatch.setattr(
        migration_readiness,
        "gateway_alembic_readiness",
        lambda _inspector: SimpleNamespace(ready=True),
    )

    require_schedule_dispatch_migration_ready(
        object(),
        settings=ScheduleDispatchSettings(mode="claim"),
    )
