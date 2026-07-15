import pytest

from apps.gateway.composition.connectors import (
    connector_test_policy_from_environment,
    require_connector_test_security_ready,
)


def test_default_policy_matches_documented_limits() -> None:
    policy = connector_test_policy_from_environment({})

    assert policy.rate_window_seconds == 60
    assert policy.user_rate_limit == 5
    assert policy.organization_rate_limit == 30
    assert policy.network_rate_limit == 20
    assert policy.user_concurrency_limit == 1
    assert policy.organization_concurrency_limit == 4
    assert policy.global_concurrency_limit == 16
    assert policy.allowed_ports == frozenset({5432})
    assert policy.trusted_local_targets == frozenset()
    assert policy.trusted_local_ca_file is None


def test_policy_parses_deployment_managed_allowed_ports() -> None:
    policy = connector_test_policy_from_environment(
        {"CONNECTOR_TEST_ALLOWED_PORTS": "5432, 54322,55432"}
    )

    assert policy.allowed_ports == frozenset({5432, 54322, 55432})


def test_development_policy_parses_exact_trusted_local_target(tmp_path) -> None:
    ca_file = tmp_path / "ca.crt"
    ca_file.write_text("test-only-ca-placeholder", encoding="utf-8")
    environment = {
        "NODE_ENV": "development",
        "CONNECTOR_TEST_ALLOWED_PORTS": "5432,55432",
        "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS": (
            "LOCALHOST.:55432,connector-test-postgres:5432"
        ),
        "CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE": str(ca_file),
    }

    policy = connector_test_policy_from_environment(environment)

    assert {(target.host, target.port) for target in policy.trusted_local_targets} == {
        ("localhost", 55432),
        ("connector-test-postgres", 5432),
    }
    assert policy.trusted_local_ca_file == str(ca_file)
    require_connector_test_security_ready(environment)


@pytest.mark.parametrize("node_env", ["production", " PRODUCTION "])
def test_production_rejects_trusted_local_configuration(node_env: str) -> None:
    with pytest.raises(RuntimeError):
        connector_test_policy_from_environment(
            {
                "NODE_ENV": node_env,
                "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS": "localhost:5432",
                "CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE": "local-ca.crt",
            }
        )


@pytest.mark.parametrize(
    "environment",
    [
        {
            "NODE_ENV": "development",
            "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS": "localhost:5432",
        },
        {
            "NODE_ENV": "development",
            "CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE": "local-ca.crt",
        },
        {
            "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS": "localhost:5432",
            "CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE": "local-ca.crt",
        },
        {
            "NODE_ENV": "development",
            "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS": "*:5432",
            "CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE": "local-ca.crt",
        },
        {
            "NODE_ENV": "development",
            "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS": "10.0.0.0/8:5432",
            "CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE": "local-ca.crt",
        },
        {
            "NODE_ENV": "development",
            "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS": "127.0.0.1:5432",
            "CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE": "local-ca.crt",
        },
        {
            "NODE_ENV": "development",
            "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS": "localhost:55432",
            "CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE": "local-ca.crt",
        },
        {
            "NODE_ENV": "development",
            "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS": (
                "localhost:5432,LOCALHOST.:5432"
            ),
            "CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE": "local-ca.crt",
        },
    ],
)
def test_invalid_trusted_local_configuration_fails_startup(
    environment: dict[str, str],
) -> None:
    with pytest.raises((RuntimeError, ValueError)):
        connector_test_policy_from_environment(environment)


def test_missing_trusted_local_ca_file_fails_security_readiness(tmp_path) -> None:
    with pytest.raises(RuntimeError):
        require_connector_test_security_ready(
            {
                "NODE_ENV": "development",
                "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS": "localhost:5432",
                "CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE": str(tmp_path / "missing.crt"),
            }
        )


def test_production_requires_strong_admission_hmac_key() -> None:
    with pytest.raises(RuntimeError):
        require_connector_test_security_ready({"NODE_ENV": "production"})
    with pytest.raises(RuntimeError):
        require_connector_test_security_ready(
            {
                "NODE_ENV": "production",
                "CONNECTOR_TEST_ADMISSION_HMAC_KEY": "short",
            }
        )

    require_connector_test_security_ready(
        {
            "NODE_ENV": "production",
            "CONNECTOR_TEST_ADMISSION_HMAC_KEY": "x" * 32,
        }
    )


@pytest.mark.parametrize(
    "environment",
    [
        {"CONNECTOR_TEST_USER_RATE_LIMIT": "0"},
        {"CONNECTOR_TEST_GLOBAL_CONCURRENCY_LIMIT": "not-an-integer"},
        {
            "CONNECTOR_TEST_USER_CONCURRENCY_LIMIT": "5",
            "CONNECTOR_TEST_ORGANIZATION_CONCURRENCY_LIMIT": "4",
        },
        {
            "CONNECTOR_TEST_RESPONSE_TIMEOUT_SECONDS": "5",
            "CONNECTOR_TEST_CONNECT_TIMEOUT_SECONDS": "5",
        },
        {"CONNECTOR_TEST_RESPONSE_TIMEOUT_SECONDS": "nan"},
        {"CONNECTOR_TEST_USER_RATE_LIMIT": "101"},
        {"CONNECTOR_TEST_ORGANIZATION_RATE_LIMIT": "1001"},
        {"CONNECTOR_TEST_NETWORK_RATE_LIMIT": "1001"},
        {"CONNECTOR_TEST_CONNECT_TIMEOUT_SECONDS": "11"},
        {"CONNECTOR_TEST_STATEMENT_TIMEOUT_SECONDS": "11"},
        {"CONNECTOR_TEST_RESPONSE_TIMEOUT_SECONDS": "31"},
        {"CONNECTOR_TEST_LEASE_TTL_SECONDS": "121"},
        {"CONNECTOR_TEST_ALLOWED_PORTS": "5432,"},
        {"CONNECTOR_TEST_ALLOWED_PORTS": "5432,5432"},
        {"CONNECTOR_TEST_ALLOWED_PORTS": "0"},
        {"CONNECTOR_TEST_ALLOWED_PORTS": "65536"},
        {"CONNECTOR_TEST_ALLOWED_PORTS": "not-a-port"},
        {
            "CONNECTOR_TEST_ALLOWED_PORTS": ",".join(
                str(port) for port in range(10000, 10017)
            )
        },
    ],
)
def test_invalid_security_limits_fail_startup(environment: dict[str, str]) -> None:
    with pytest.raises((RuntimeError, ValueError)):
        require_connector_test_security_ready(environment)
