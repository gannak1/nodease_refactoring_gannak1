import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
import redis.asyncio as redis_asyncio

from apps.gateway.adapters.connectors.postgres_probe import StrictPostgresConnectorProbe
from apps.gateway.adapters.connectors.redis_test_admission import (
    RedisConnectorTestAdmission,
)
from apps.gateway.api.v1.endpoints import connectors as connector_endpoint
from apps.gateway.application.connectors.models import (
    ConnectorTestPolicy,
    TrustedLocalConnectorTarget,
)
from apps.gateway.application.connectors.test_connection import (
    TestConnectorConnection as ConnectorConnectionUseCase,
)
from apps.gateway.main import app
from apps.shared.db.models.user import User


class _NoopAudit:
    def __init__(self) -> None:
        self.results: list[bool] = []

    def record(self, _command, result, _duration_bucket: str) -> None:
        self.results.append(result.success)


def _integration_settings() -> tuple[str, str, str]:
    redis_url = os.getenv("CONNECTOR_TEST_INTEGRATION_REDIS_URL", "").strip()
    password = os.getenv("CONNECTOR_TEST_INTEGRATION_POSTGRES_PASSWORD", "")
    ca_file = os.getenv("CONNECTOR_TEST_INTEGRATION_POSTGRES_CA_FILE", "").strip()
    if not redis_url or not password or not ca_file:
        pytest.skip("connector demo integration settings are not configured")

    parsed_redis = urlsplit(redis_url)
    if (
        parsed_redis.scheme not in {"redis", "rediss"}
        or parsed_redis.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed_redis.path.lstrip("/") != "15"
    ):
        raise RuntimeError(
            "connector demo integration requires a local dedicated Redis database"
        )
    if not Path(ca_file).is_file():
        raise RuntimeError("connector demo integration CA file is unavailable")
    return redis_url, password, ca_file


@pytest.mark.asyncio
async def test_authenticated_api_uses_real_redis_and_local_tls_postgres(
    monkeypatch,
    caplog,
) -> None:
    redis_url, password, ca_file = _integration_settings()
    redis_client = redis_asyncio.from_url(redis_url, decode_responses=False)
    await redis_client.ping()
    await redis_client.flushdb()

    target = TrustedLocalConnectorTarget(host="localhost", port=55432)
    policy = ConnectorTestPolicy(
        allowed_ports=frozenset({55432}),
        trusted_local_targets=frozenset({target}),
        trusted_local_ca_file=ca_file,
    )
    admission = RedisConnectorTestAdmission(
        redis_client,
        policy=policy,
        hmac_key=b"integration-test-only-key-material" * 2,
    )
    probe = StrictPostgresConnectorProbe(policy)
    audit = _NoopAudit()
    use_case = ConnectorConnectionUseCase(admission, probe, audit, policy)
    user = User(
        id=uuid4(),
        email="connector-integration@example.com",
        name="Connector Integration",
        social_provider="local",
    )
    organization_id = uuid4()

    app.dependency_overrides[connector_endpoint.get_db] = lambda: object()
    app.dependency_overrides[connector_endpoint.get_current_user] = lambda: user
    monkeypatch.setattr(
        connector_endpoint,
        "resolve_active_organization_id",
        lambda *_args, **_kwargs: organization_id,
    )
    monkeypatch.setattr(
        connector_endpoint,
        "get_connector_test_application",
        lambda: SimpleNamespace(use_case=use_case),
    )

    try:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41000))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://connector-test.local",
        ) as client:
            response = await client.post(
                "/api/v1/connectors/test",
                headers={"X-Organization-Id": str(organization_id)},
                json={
                    "connection_name": "local-tls-demo",
                    "type": "postgres",
                    "host": "localhost",
                    "port": 55432,
                    "database": "connector_demo",
                    "username": "connector_demo_user",
                    "password": password,
                    "ssh": None,
                },
            )

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["reason_code"] is None
        assert audit.results == [True]
        if password in response.text or password in caplog.text:
            raise AssertionError("connector credential appeared in observable output")
    finally:
        app.dependency_overrides = {}
        probe.shutdown()
        await redis_client.flushdb()
        await redis_client.aclose()
