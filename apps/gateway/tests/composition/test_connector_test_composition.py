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
    ],
)
def test_invalid_security_limits_fail_startup(environment: dict[str, str]) -> None:
    with pytest.raises((RuntimeError, ValueError)):
        require_connector_test_security_ready(environment)
