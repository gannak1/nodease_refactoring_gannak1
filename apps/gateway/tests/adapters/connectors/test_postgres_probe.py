from contextlib import nullcontext
from uuid import uuid4

import pytest

from apps.gateway.adapters.connectors import postgres_probe as probe_module
from apps.gateway.adapters.connectors.postgres_probe import StrictPostgresConnectorProbe
from apps.gateway.application.connectors.errors import (
    ConnectorProbeCapacityExceeded,
    ConnectorProbeFailed,
    ConnectorTargetNotAllowed,
)
from apps.gateway.application.connectors.models import (
    ConnectorTestCommand,
    ConnectorTestPolicy,
)
from apps.shared.services.egress_guard import EgressGuardError


def command(*, host: str = "db.example.com") -> ConnectorTestCommand:
    return ConnectorTestCommand(
        organization_id=uuid4(),
        actor_id=uuid4(),
        network_address="203.0.113.9",
        host=host,
        port=5432,
        database="app",
        username="app-user",
        password="placeholder-secret",
    )


class FakeResult:
    def scalar_one(self) -> int:
        return 1


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement):
        self.statements.append(str(statement))
        return FakeResult()


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()
        self.disposed = False

    def connect(self):
        return nullcontext(self.connection)

    def dispose(self) -> None:
        self.disposed = True


def test_probe_pins_public_ip_enforces_tls_and_runs_constant_read_only_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    engine = FakeEngine()

    def fake_guard(host: str, port: int, *, allowed_ports):
        captured["guard"] = (host, port, allowed_ports)
        return "db.example.com", 5432, "203.0.113.20"

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return engine

    monkeypatch.setattr(probe_module, "ensure_network_target_allowed", fake_guard)
    monkeypatch.setattr(probe_module, "create_engine", fake_create_engine)
    probe = StrictPostgresConnectorProbe(ConnectorTestPolicy())

    try:
        assert probe._probe_sync(command()) is True
    finally:
        probe.shutdown()

    url = captured["url"]
    assert url.host == "db.example.com"
    assert url.port == 5432
    assert dict(url.query) == {
        "hostaddr": "203.0.113.20",
        "sslmode": "verify-full",
    }
    assert captured["guard"] == (
        "db.example.com",
        5432,
        frozenset({5432}),
    )
    assert captured["kwargs"]["connect_args"] == {
        "connect_timeout": 5,
        "options": "-c statement_timeout=3000",
    }
    assert engine.connection.statements == ["SET TRANSACTION READ ONLY", "SELECT 1"]
    assert engine.disposed is True


@pytest.mark.parametrize(
    "host",
    [
        "postgresql://db.example.com",
        "db.example.com/path",
        "user@db.example.com",
        "db.example.com?sslmode=disable",
        "db.example.com#fragment",
    ],
)
def test_probe_rejects_url_shaped_host_before_dns(
    host: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def guard(*_args, **_kwargs):
        pytest.fail("DNS guard must not run")

    monkeypatch.setattr(probe_module, "ensure_network_target_allowed", guard)
    probe = StrictPostgresConnectorProbe(ConnectorTestPolicy())

    try:
        with pytest.raises(ConnectorTargetNotAllowed):
            probe._probe_sync(command(host=host))
    finally:
        probe.shutdown()


def test_probe_normalizes_egress_and_driver_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = StrictPostgresConnectorProbe(ConnectorTestPolicy())
    try:
        monkeypatch.setattr(
            probe_module,
            "ensure_network_target_allowed",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                EgressGuardError("egress.private_target")
            ),
        )
        with pytest.raises(ConnectorTargetNotAllowed):
            probe._probe_sync(command())

        monkeypatch.setattr(
            probe_module,
            "ensure_network_target_allowed",
            lambda *_args, **_kwargs: ("db.example.com", 5432, "203.0.113.20"),
        )
        monkeypatch.setattr(
            probe_module,
            "create_engine",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("raw-driver-detail")
            ),
        )
        with pytest.raises(ConnectorProbeFailed) as exc_info:
            probe._probe_sync(command())
        assert "raw-driver-detail" not in str(exc_info.value)
    finally:
        probe.shutdown()


@pytest.mark.asyncio
async def test_local_executor_capacity_fails_without_queueing() -> None:
    probe = StrictPostgresConnectorProbe(ConnectorTestPolicy())
    acquired = [
        probe._capacity.acquire(blocking=False)
        for _ in range(ConnectorTestPolicy().global_concurrency_limit)
    ]
    assert all(acquired)
    try:
        with pytest.raises(ConnectorProbeCapacityExceeded):
            await probe.probe(command())
    finally:
        for _ in acquired:
            probe._capacity.release()
        probe.shutdown()
