from __future__ import annotations

import json
import secrets
from uuid import uuid4

from cryptography.fernet import Fernet
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


def test_cache_is_requested_by_default_but_incomplete_configuration_stays_disabled() -> None:
    config = _settings().agent_builder_intent_cache_config()

    assert config.enabled is False
    assert config.disabled_reason == "cache_redis_url_missing"
    assert _settings().AGENT_BUILDER_INTENT_CACHE_ENABLED == "true"
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
    assert _settings().AGENT_BUILDER_INTENT_CACHE_ENABLED == "true"
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


def test_l2_defaults_to_disabled_without_loading_a_keyring() -> None:
    config = _settings().agent_builder_intent_plan_l2_config()

    assert config.mode == "disabled"
    assert config.disabled_reason == "feature_disabled"
    assert config.should_read(uuid4()) is False
    assert config.should_write(uuid4()) is False


def test_l2_read_mode_requires_a_strict_allowlist_and_dedicated_keyring() -> None:
    selected_organization = uuid4()
    other_organization = uuid4()
    keyring = {"l2-v1": Fernet.generate_key().decode("utf-8")}
    values = {
        "AGENT_BUILDER_INTENT_L2_MODE": "read",
        "AGENT_BUILDER_INTENT_L2_ORGANIZATION_ALLOWLIST": str(
            selected_organization
        ),
        "AGENT_BUILDER_INTENT_L2_ENCRYPTION_KEYS": json.dumps(keyring),
        "AGENT_BUILDER_INTENT_L2_ACTIVE_KEY_VERSION": "l2-v1",
    }

    config = _settings(values).agent_builder_intent_plan_l2_config()

    assert config.mode == "read"
    assert config.disabled_reason is None
    assert config.should_read(selected_organization) is True
    assert config.should_write(selected_organization) is True
    assert config.should_read(other_organization) is False
    assert config.should_write(other_organization) is False
    assert json.dumps(keyring) not in repr(config)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("AGENT_BUILDER_INTENT_L2_MODE", "invalid", "invalid_mode"),
        (
            "AGENT_BUILDER_INTENT_L2_ORGANIZATION_ALLOWLIST",
            "not-a-uuid",
            "invalid_organization_allowlist",
        ),
        (
            "AGENT_BUILDER_INTENT_L2_ENCRYPTION_KEYS",
            "not-json",
            "invalid_encryption_keyring",
        ),
    ],
)
def test_invalid_l2_configuration_disables_l2_without_affecting_l1(
    field: str,
    value: str,
    reason: str,
) -> None:
    organization_id = uuid4()
    values = _valid_cache_environment()
    values.update(
        {
            "AGENT_BUILDER_INTENT_L2_MODE": "read",
            "AGENT_BUILDER_INTENT_L2_ORGANIZATION_ALLOWLIST": str(
                organization_id
            ),
            "AGENT_BUILDER_INTENT_L2_ENCRYPTION_KEYS": json.dumps(
                {"l2-v1": Fernet.generate_key().decode("utf-8")}
            ),
            "AGENT_BUILDER_INTENT_L2_ACTIVE_KEY_VERSION": "l2-v1",
        }
    )
    values[field] = value

    l1 = _settings(values).agent_builder_intent_cache_config()
    l2 = _settings(values).agent_builder_intent_plan_l2_config()

    assert l1.enabled is True
    assert l2.mode == "disabled"
    assert l2.disabled_reason == reason
    assert l2.should_write(organization_id) is False
