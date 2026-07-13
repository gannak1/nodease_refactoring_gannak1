import pytest

from apps.gateway.core.http_security import (
    parse_credentialed_cors_origins,
    resolve_session_signing_secret,
)


def test_production_requires_non_default_session_signing_secret():
    with pytest.raises(RuntimeError, match="not configured"):
        resolve_session_signing_secret(None, node_env="production")

    with pytest.raises(RuntimeError, match="not configured"):
        resolve_session_signing_secret(
            "your-secret-key-change-in-production",
            node_env="production",
        )

    with pytest.raises(RuntimeError, match="not configured"):
        resolve_session_signing_secret("   ", node_env="production")

    with pytest.raises(RuntimeError, match="not configured"):
        resolve_session_signing_secret(
            " your-secret-key-change-in-production ",
            node_env="production",
        )


def test_non_production_can_use_development_session_signing_fallback():
    assert resolve_session_signing_secret(None, node_env="development")


def test_production_environment_check_is_case_and_whitespace_insensitive():
    with pytest.raises(RuntimeError, match="not configured"):
        resolve_session_signing_secret(None, node_env=" Production ")


def test_explicit_session_signing_secret_is_returned_without_logging():
    configured = "synthetic-test-session-signing-value"

    assert (
        resolve_session_signing_secret(configured, node_env="production")
        == configured
    )


def test_credentialed_cors_origins_are_trimmed_and_deduplicated():
    assert parse_credentialed_cors_origins(
        " https://client.example,https://client.example/,http://localhost:3000 "
    ) == ["https://client.example", "http://localhost:3000"]


@pytest.mark.parametrize(
    "raw_value",
    [
        "*",
        "",
        "null",
        "https://user@client.example",
        "https://client.example/path",
        "https://client.example?query=1",
        "javascript:alert(1)",
    ],
)
def test_credentialed_cors_origins_fail_closed(raw_value):
    with pytest.raises(RuntimeError):
        parse_credentialed_cors_origins(raw_value)
