from __future__ import annotations

import secrets

import pytest

from apps.gateway.core.config import Settings


def _valid_cache_environment(*, node_env: str = "development") -> dict[str, str]:
    password = secrets.token_urlsafe(12)
    return {
        "NODE_ENV": node_env,
        "AGENT_BUILDER_INTENT_CACHE_ENABLED": "true",
        "AGENT_BUILDER_INTENT_CACHE_TTL_SECONDS": "900",
        "AGENT_BUILDER_INTENT_CACHE_TIMEOUT_MS": "100",
        "AGENT_BUILDER_INTENT_CACHE_MAX_BYTES": "32768",
        "AGENT_BUILDER_INTENT_CACHE_HMAC_KEY": secrets.token_urlsafe(32),
        "AGENT_BUILDER_INTENT_CACHE_HMAC_KEY_VERSION": "hmac-v1",
        "AGENT_BUILDER_INTENT_CACHE_LEASE_SECONDS": "240",
        "AGENT_BUILDER_INTENT_CACHE_WAIT_MS": "45000",
        "AGENT_BUILDER_INTENT_CACHE_MAX_FOLLOWER_WAITERS": "8",
        "AGENT_BUILDER_INTENT_CACHE_REDIS_URL": (
            f"redis://cache-user:{password}@cache.internal:6379/0"
        ),
        "AGENT_BUILDER_INTENT_CACHE_PRODUCTION_READY": "false",
    }


def _settings(values: dict[str, str] | None = None) -> Settings:
    return Settings(_env_file=None, **(values or {}))


def test_cache_defaults_to_disabled_with_bounded_defaults() -> None:
    config = _settings().agent_builder_intent_cache_config()

    assert config.enabled is False
    assert config.disabled_reason == "feature_disabled"
    assert config.ttl_seconds == 900
    assert config.operation_timeout_ms == 100
    assert config.max_payload_bytes == 32768
    assert config.lease_seconds == 240
    assert config.follower_wait_ms == 45000
    assert config.max_follower_waiters == 8
    assert config.redis_url is None
    assert config.hmac_key is None


def test_development_can_enable_only_with_dedicated_complete_configuration() -> None:
    values = _valid_cache_environment()

    config = _settings(values).agent_builder_intent_cache_config()

    assert config.enabled is True
    assert config.disabled_reason is None
    assert config.redis_url == values["AGENT_BUILDER_INTENT_CACHE_REDIS_URL"]
    assert config.hmac_key == values[
        "AGENT_BUILDER_INTENT_CACHE_HMAC_KEY"
    ].encode("utf-8")


@pytest.mark.parametrize("node_env", ["production", "staging"])
def test_production_and_staging_require_explicit_readiness_attestation(
    node_env: str,
) -> None:
    values = _valid_cache_environment(node_env=node_env)

    disabled = _settings(values).agent_builder_intent_cache_config()
    values["AGENT_BUILDER_INTENT_CACHE_PRODUCTION_READY"] = "true"
    enabled = _settings(values).agent_builder_intent_cache_config()

    assert disabled.enabled is False
    assert disabled.disabled_reason == "production_not_ready"
    assert enabled.enabled is True
    assert enabled.disabled_reason is None


def test_cache_url_never_falls_back_to_celery_broker_or_result_backend() -> None:
    values = _valid_cache_environment()
    values.pop("AGENT_BUILDER_INTENT_CACHE_REDIS_URL")
    values["CELERY_BROKER_URL"] = "redis://broker.internal:6379/0"
    values["CELERY_RESULT_BACKEND"] = "redis://result.internal:6379/1"

    config = _settings(values).agent_builder_intent_cache_config()

    assert config.enabled is False
    assert config.disabled_reason == "cache_redis_url_missing"
    assert config.redis_url is None


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("AGENT_BUILDER_INTENT_CACHE_ENABLED", "sometimes", "invalid_enabled_flag"),
        ("AGENT_BUILDER_INTENT_CACHE_TTL_SECONDS", "29", "invalid_ttl"),
        ("AGENT_BUILDER_INTENT_CACHE_TTL_SECONDS", "3601", "invalid_ttl"),
        ("AGENT_BUILDER_INTENT_CACHE_TIMEOUT_MS", "9", "invalid_timeout"),
        ("AGENT_BUILDER_INTENT_CACHE_TIMEOUT_MS", "501", "invalid_timeout"),
        ("AGENT_BUILDER_INTENT_CACHE_MAX_BYTES", "4095", "invalid_max_payload"),
        ("AGENT_BUILDER_INTENT_CACHE_MAX_BYTES", "65537", "invalid_max_payload"),
        ("AGENT_BUILDER_INTENT_CACHE_LEASE_SECONDS", "4", "invalid_lease"),
        ("AGENT_BUILDER_INTENT_CACHE_LEASE_SECONDS", "301", "invalid_lease"),
        ("AGENT_BUILDER_INTENT_CACHE_WAIT_MS", "-1", "invalid_wait"),
        ("AGENT_BUILDER_INTENT_CACHE_WAIT_MS", "60001", "invalid_wait"),
        ("AGENT_BUILDER_INTENT_CACHE_MAX_FOLLOWER_WAITERS", "0", "invalid_waiter_cap"),
        ("AGENT_BUILDER_INTENT_CACHE_MAX_FOLLOWER_WAITERS", "65", "invalid_waiter_cap"),
        ("AGENT_BUILDER_INTENT_CACHE_HMAC_KEY_VERSION", "INVALID", "invalid_hmac_key_version"),
        ("AGENT_BUILDER_INTENT_CACHE_REDIS_URL", "http://cache.internal", "cache_redis_url_invalid"),
        (
            "AGENT_BUILDER_INTENT_CACHE_REDIS_URL",
            "redis://cache.internal/0?socket_timeout=10",
            "cache_redis_url_invalid",
        ),
        (
            "AGENT_BUILDER_INTENT_CACHE_REDIS_URL",
            "redis://cache.internal/0?db=not-an-int",
            "cache_redis_url_invalid",
        ),
        (
            "AGENT_BUILDER_INTENT_CACHE_REDIS_URL",
            "redis://cache.internal/not-a-db",
            "cache_redis_url_invalid",
        ),
        ("NODE_ENV", "prod", "invalid_node_env"),
    ],
)
def test_invalid_cache_configuration_disables_only_the_cache(
    field: str,
    value: str,
    reason: str,
) -> None:
    values = _valid_cache_environment()
    values[field] = value

    settings = _settings(values)
    config = settings.agent_builder_intent_cache_config()

    assert config.enabled is False
    assert config.disabled_reason == reason


def test_missing_or_short_hmac_key_disables_cache_without_secret_disclosure() -> None:
    missing_values = _valid_cache_environment()
    missing_values.pop("AGENT_BUILDER_INTENT_CACHE_HMAC_KEY")
    short_values = _valid_cache_environment()
    short_values["AGENT_BUILDER_INTENT_CACHE_HMAC_KEY"] = "short-sensitive-value"

    missing = _settings(missing_values).agent_builder_intent_cache_config()
    short_settings = _settings(short_values)
    short = short_settings.agent_builder_intent_cache_config()

    assert missing.enabled is False
    assert missing.disabled_reason == "hmac_key_missing"
    assert short.enabled is False
    assert short.disabled_reason == "hmac_key_too_short"
    rendered = repr(short_settings) + repr(short)
    assert "short-sensitive-value" not in rendered


def test_configuration_repr_redacts_hmac_key_and_redis_credentials() -> None:
    values = _valid_cache_environment()
    settings = _settings(values)
    config = settings.agent_builder_intent_cache_config()

    rendered = repr(settings) + repr(config)

    assert values["AGENT_BUILDER_INTENT_CACHE_HMAC_KEY"] not in rendered
    assert values["AGENT_BUILDER_INTENT_CACHE_REDIS_URL"] not in rendered
    assert values["AGENT_BUILDER_INTENT_CACHE_REDIS_URL"].split("@", 1)[0] not in rendered
