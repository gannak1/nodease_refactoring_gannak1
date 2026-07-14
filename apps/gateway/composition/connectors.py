from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from apps.gateway.adapters.audit.connector_test import ConnectorTestAuditRecorder
from apps.gateway.adapters.connectors.postgres_probe import StrictPostgresConnectorProbe
from apps.gateway.adapters.connectors.redis_test_admission import (
    RedisConnectorTestAdmission,
)
from apps.gateway.application.connectors.models import ConnectorTestPolicy
from apps.gateway.application.connectors.test_connection import TestConnectorConnection
from apps.shared.pubsub import get_async_redis_client

_LOCAL_ADMISSION_KEY = b"connector-test-local-development-key-v1"


@dataclass(frozen=True, slots=True)
class ConnectorTestApplication:
    use_case: TestConnectorConnection
    probe: StrictPostgresConnectorProbe


_application: ConnectorTestApplication | None = None


def connector_test_policy_from_environment(
    environ: Mapping[str, str],
) -> ConnectorTestPolicy:
    return ConnectorTestPolicy(
        allowed_ports=_ports(environ, "CONNECTOR_TEST_ALLOWED_PORTS", {5432}),
        rate_window_seconds=_integer(environ, "CONNECTOR_TEST_RATE_WINDOW_SECONDS", 60),
        user_rate_limit=_integer(environ, "CONNECTOR_TEST_USER_RATE_LIMIT", 5),
        organization_rate_limit=_integer(
            environ, "CONNECTOR_TEST_ORGANIZATION_RATE_LIMIT", 30
        ),
        network_rate_limit=_integer(environ, "CONNECTOR_TEST_NETWORK_RATE_LIMIT", 20),
        user_concurrency_limit=_integer(
            environ, "CONNECTOR_TEST_USER_CONCURRENCY_LIMIT", 1
        ),
        organization_concurrency_limit=_integer(
            environ, "CONNECTOR_TEST_ORGANIZATION_CONCURRENCY_LIMIT", 4
        ),
        global_concurrency_limit=_integer(
            environ, "CONNECTOR_TEST_GLOBAL_CONCURRENCY_LIMIT", 16
        ),
        connect_timeout_seconds=_integer(
            environ, "CONNECTOR_TEST_CONNECT_TIMEOUT_SECONDS", 5
        ),
        statement_timeout_seconds=_integer(
            environ, "CONNECTOR_TEST_STATEMENT_TIMEOUT_SECONDS", 3
        ),
        response_timeout_seconds=_float(
            environ, "CONNECTOR_TEST_RESPONSE_TIMEOUT_SECONDS", 10.0
        ),
        lease_ttl_seconds=_integer(environ, "CONNECTOR_TEST_LEASE_TTL_SECONDS", 30),
    )


def require_connector_test_security_ready(
    environ: Mapping[str, str] | None = None,
) -> None:
    values = environ if environ is not None else os.environ
    connector_test_policy_from_environment(values)
    _admission_key(values)


def get_connector_test_application() -> ConnectorTestApplication:
    global _application
    if _application is None:
        policy = connector_test_policy_from_environment(os.environ)
        admission = RedisConnectorTestAdmission(
            get_async_redis_client(),
            policy=policy,
            hmac_key=_admission_key(os.environ),
        )
        probe = StrictPostgresConnectorProbe(policy)
        _application = ConnectorTestApplication(
            use_case=TestConnectorConnection(
                admission,
                probe,
                ConnectorTestAuditRecorder(),
                policy,
            ),
            probe=probe,
        )
    return _application


def shutdown_connector_test_application() -> None:
    global _application
    application = _application
    _application = None
    if application is not None:
        application.probe.shutdown()


def _admission_key(environ: Mapping[str, str]) -> bytes:
    raw_key = environ.get("CONNECTOR_TEST_ADMISSION_HMAC_KEY", "")
    if not raw_key:
        if environ.get("NODE_ENV") == "production":
            raise RuntimeError(
                "CONNECTOR_TEST_ADMISSION_HMAC_KEY is required in production"
            )
        return _LOCAL_ADMISSION_KEY
    key = raw_key.encode("utf-8")
    if len(key) < 32:
        raise RuntimeError(
            "CONNECTOR_TEST_ADMISSION_HMAC_KEY must contain at least 32 bytes"
        )
    return key


def _integer(environ: Mapping[str, str], name: str, default: int) -> int:
    raw_value = environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _ports(
    environ: Mapping[str, str],
    name: str,
    default: set[int],
) -> frozenset[int]:
    raw_value = environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        return frozenset(default)

    parts = [part.strip() for part in raw_value.split(",")]
    if any(not part for part in parts):
        raise RuntimeError(f"{name} must be a comma-separated port list")
    try:
        ports = [int(part) for part in parts]
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a comma-separated port list") from exc
    if len(set(ports)) != len(ports):
        raise RuntimeError(f"{name} must not contain duplicate ports")
    return frozenset(ports)


def _float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw_value = environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        return float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be numeric") from exc


__all__ = [
    "ConnectorTestApplication",
    "connector_test_policy_from_environment",
    "get_connector_test_application",
    "require_connector_test_security_ready",
    "shutdown_connector_test_application",
]
