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


def test_claim_mode_accepts_current_single_head(monkeypatch):
    monkeypatch.setattr(migration_readiness, "inspect", lambda _engine: object())
    monkeypatch.setattr(
        migration_readiness,
        "gateway_alembic_readiness",
        lambda _inspector: SimpleNamespace(ready=True),
    )

    require_schedule_dispatch_migration_ready(
        object(),
        settings=ScheduleDispatchSettings(mode="claim"),
    )
