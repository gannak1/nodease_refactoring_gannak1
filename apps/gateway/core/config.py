from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Literal, Optional
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.shared.services.credential_encryption import (
    CredentialEncryptionError,
    CredentialEncryptionService,
)


_CACHE_VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class AgentBuilderIntentCacheConfig:
    enabled: bool
    disabled_reason: str | None
    ttl_seconds: int = 900
    operation_timeout_ms: int = 100
    max_payload_bytes: int = 32 * 1024
    lease_seconds: int = 240
    follower_wait_ms: int = 45_000
    max_follower_waiters: int = 8
    redis_url: str | None = field(default=None, repr=False)
    hmac_key: bytes | None = field(default=None, repr=False)
    hmac_key_version: str | None = None


@dataclass(frozen=True, slots=True)
class AgentBuilderIntentPlanL2Config:
    mode: Literal["disabled", "write_only", "read"]
    disabled_reason: str | None
    organization_allowlist: frozenset[uuid.UUID] = frozenset()
    encryption: CredentialEncryptionService | None = field(default=None, repr=False)

    def should_read(self, organization_id: uuid.UUID) -> bool:
        return (
            self.mode == "read"
            and organization_id in self.organization_allowlist
            and self.encryption is not None
        )

    def should_write(self, organization_id: uuid.UUID) -> bool:
        return (
            self.mode in {"write_only", "read"}
            and organization_id in self.organization_allowlist
            and self.encryption is not None
        )


@dataclass(frozen=True, slots=True)
class AgentBuilderSemanticCacheConfig:
    assist_enabled: bool
    planner_free_serving_enabled: bool
    disabled_reason: str | None
    embedding_profile_version: str | None = None
    embedding_model_version: str | None = None
    embedding_dimension: int | None = None
    top_k: int | None = None
    rehydration_contract_version: str | None = None


def _cache_flag(value: str | bool) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return None


def _cache_bounded_int(
    value: str | int | None,
    minimum: int,
    maximum: int,
) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(value, str) and value.strip() != str(parsed):
        return None
    if not minimum <= parsed <= maximum:
        return None
    return parsed


def _valid_cache_redis_url(value: str) -> bool:
    if not value or any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme in {"redis", "rediss"}
        and parsed.hostname
        and not parsed.query
        and not parsed.fragment
        and (parsed.path in {"", "/"} or re.fullmatch(r"/[0-9]+", parsed.path))
    )


class Settings(BaseSettings):
    """
    pydantic-settings의 BaseSettings 클래스를 상속합니다.
    이 클래스를 상속받아 설정 모델을 정의하면, 환경 변수나 .env 파일의 값을 자동으로 읽어와서 Python 타입으로 변환 및 검증을 수행합니다.
    """

    # RAG Ingestion Mode
    STORAGE_TYPE: Literal["LOCAL", "CLOUD"] = "LOCAL"

    # App auth secret lifecycle rollout gate. Keep disabled until every Gateway
    # pod runs the verifier-aware revision.
    APP_AUTH_SECRET_LIFECYCLE_MODE: Literal["disabled", "active"] = "disabled"

    # Cache serving is requested by default. Incomplete or invalid configuration
    # still disables only this optional optimization without failing startup.
    NODE_ENV: str = "development"
    AGENT_BUILDER_INTENT_CACHE_ENABLED: str | bool = "true"
    AGENT_BUILDER_INTENT_CACHE_TTL_SECONDS: str | int = "900"
    AGENT_BUILDER_INTENT_CACHE_TIMEOUT_MS: str | int = "100"
    AGENT_BUILDER_INTENT_CACHE_MAX_BYTES: str | int = str(32 * 1024)
    AGENT_BUILDER_INTENT_CACHE_HMAC_KEY: SecretStr | None = Field(
        default=None,
        repr=False,
    )
    AGENT_BUILDER_INTENT_CACHE_HMAC_KEY_VERSION: str | None = None
    AGENT_BUILDER_INTENT_CACHE_LEASE_SECONDS: str | int = "240"
    AGENT_BUILDER_INTENT_CACHE_WAIT_MS: str | int = "45000"
    AGENT_BUILDER_INTENT_CACHE_MAX_FOLLOWER_WAITERS: str | int = "8"
    AGENT_BUILDER_INTENT_CACHE_REDIS_URL: SecretStr | None = Field(
        default=None,
        repr=False,
    )
    AGENT_BUILDER_INTENT_CACHE_PRODUCTION_READY: str | bool = "false"
    AGENT_BUILDER_INTENT_L2_MODE: str = "disabled"
    AGENT_BUILDER_INTENT_L2_ORGANIZATION_ALLOWLIST: str = ""
    AGENT_BUILDER_INTENT_L2_ENCRYPTION_KEYS: SecretStr | None = Field(
        default=None,
        repr=False,
    )
    AGENT_BUILDER_INTENT_L2_ACTIVE_KEY_VERSION: str | None = None
    # JEO-8 remains dormant until every semantic contract coordinate is
    # supplied explicitly. Provider/model choices are deployment policy, not
    # source-code defaults.
    AGENT_BUILDER_SEMANTIC_ASSIST_ENABLED: str | bool = "false"
    AGENT_BUILDER_SEMANTIC_SERVING_ENABLED: str | bool = "false"
    AGENT_BUILDER_SEMANTIC_EMBEDDING_PROFILE_VERSION: str | None = None
    AGENT_BUILDER_SEMANTIC_EMBEDDING_MODEL_VERSION: str | None = None
    AGENT_BUILDER_SEMANTIC_EMBEDDING_DIMENSION: str | int | None = None
    AGENT_BUILDER_SEMANTIC_TOP_K: str | int | None = None
    AGENT_BUILDER_SEMANTIC_REHYDRATION_CONTRACT_VERSION: str | None = None

    # Keep query-embedding policy writes dormant until all purpose-unaware
    # Gateway and Worker processes have drained.
    QUERY_EMBEDDING_POLICY_WRITE_MODE: Literal["disabled", "active"] = "disabled"

    # AWS Settings
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: Optional[str] = None
    S3_BUCKET_NAME: Optional[str] = None

    @field_validator("STORAGE_TYPE", mode="before")
    @classmethod
    def normalize_storage_type(cls, value):
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("AWS_REGION", "S3_BUCKET_NAME", mode="before")
    @classmethod
    def normalize_storage_coordinate(cls, value):
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("S3_BUCKET_NAME")
    @classmethod
    def require_complete_cloud_storage(
        cls,
        bucket_name: Optional[str],
        info: ValidationInfo,
    ) -> Optional[str]:
        if info.data.get("STORAGE_TYPE") == "CLOUD" and (
            not bucket_name or not info.data.get("AWS_REGION")
        ):
            # Keep the error stable and free of configuration values. A field
            # validator also prevents Pydantic from including the full Settings
            # input (which may contain credentials) in this validation error.
            raise ValueError("cloud_storage_configuration_incomplete")
        return bucket_name

    # Load from .env file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
        validate_default=True,
    )

    def agent_builder_intent_cache_config(self) -> AgentBuilderIntentCacheConfig:
        requested_enabled = _cache_flag(
            self.AGENT_BUILDER_INTENT_CACHE_ENABLED
        )
        if requested_enabled is None:
            return AgentBuilderIntentCacheConfig(
                enabled=False,
                disabled_reason="invalid_enabled_flag",
            )
        if not requested_enabled:
            return AgentBuilderIntentCacheConfig(
                enabled=False,
                disabled_reason="feature_disabled",
            )

        bounded_fields = (
            (
                self.AGENT_BUILDER_INTENT_CACHE_TTL_SECONDS,
                30,
                3600,
                "invalid_ttl",
            ),
            (
                self.AGENT_BUILDER_INTENT_CACHE_TIMEOUT_MS,
                10,
                500,
                "invalid_timeout",
            ),
            (
                self.AGENT_BUILDER_INTENT_CACHE_MAX_BYTES,
                4 * 1024,
                64 * 1024,
                "invalid_max_payload",
            ),
            (
                self.AGENT_BUILDER_INTENT_CACHE_LEASE_SECONDS,
                5,
                300,
                "invalid_lease",
            ),
            (
                self.AGENT_BUILDER_INTENT_CACHE_WAIT_MS,
                0,
                60_000,
                "invalid_wait",
            ),
            (
                self.AGENT_BUILDER_INTENT_CACHE_MAX_FOLLOWER_WAITERS,
                1,
                64,
                "invalid_waiter_cap",
            ),
        )
        parsed_values: list[int] = []
        for raw, minimum, maximum, reason in bounded_fields:
            parsed = _cache_bounded_int(raw, minimum, maximum)
            if parsed is None:
                return AgentBuilderIntentCacheConfig(
                    enabled=False,
                    disabled_reason=reason,
                )
            parsed_values.append(parsed)

        redis_url = (
            self.AGENT_BUILDER_INTENT_CACHE_REDIS_URL.get_secret_value()
            if self.AGENT_BUILDER_INTENT_CACHE_REDIS_URL is not None
            else ""
        )
        if not redis_url:
            return AgentBuilderIntentCacheConfig(
                enabled=False,
                disabled_reason="cache_redis_url_missing",
            )
        if not _valid_cache_redis_url(redis_url):
            return AgentBuilderIntentCacheConfig(
                enabled=False,
                disabled_reason="cache_redis_url_invalid",
            )

        raw_hmac_key = (
            self.AGENT_BUILDER_INTENT_CACHE_HMAC_KEY.get_secret_value()
            if self.AGENT_BUILDER_INTENT_CACHE_HMAC_KEY is not None
            else ""
        )
        if not raw_hmac_key:
            return AgentBuilderIntentCacheConfig(
                enabled=False,
                disabled_reason="hmac_key_missing",
            )
        hmac_key = raw_hmac_key.encode("utf-8")
        if len(hmac_key) < 32:
            return AgentBuilderIntentCacheConfig(
                enabled=False,
                disabled_reason="hmac_key_too_short",
            )

        hmac_key_version = (
            self.AGENT_BUILDER_INTENT_CACHE_HMAC_KEY_VERSION or ""
        ).strip()
        if not hmac_key_version:
            return AgentBuilderIntentCacheConfig(
                enabled=False,
                disabled_reason="hmac_key_version_missing",
            )
        if _CACHE_VERSION_PATTERN.fullmatch(hmac_key_version) is None:
            return AgentBuilderIntentCacheConfig(
                enabled=False,
                disabled_reason="invalid_hmac_key_version",
            )

        production_ready = _cache_flag(
            self.AGENT_BUILDER_INTENT_CACHE_PRODUCTION_READY
        )
        if production_ready is None:
            return AgentBuilderIntentCacheConfig(
                enabled=False,
                disabled_reason="invalid_production_ready_flag",
            )
        node_env = self.NODE_ENV.strip().lower()
        if node_env not in {"development", "test", "production", "staging"}:
            return AgentBuilderIntentCacheConfig(
                enabled=False,
                disabled_reason="invalid_node_env",
            )
        if node_env in {"production", "staging"} and not production_ready:
            return AgentBuilderIntentCacheConfig(
                enabled=False,
                disabled_reason="production_not_ready",
            )

        (
            ttl_seconds,
            operation_timeout_ms,
            max_payload_bytes,
            lease_seconds,
            follower_wait_ms,
            max_follower_waiters,
        ) = parsed_values
        return AgentBuilderIntentCacheConfig(
            enabled=True,
            disabled_reason=None,
            ttl_seconds=ttl_seconds,
            operation_timeout_ms=operation_timeout_ms,
            max_payload_bytes=max_payload_bytes,
            lease_seconds=lease_seconds,
            follower_wait_ms=follower_wait_ms,
            max_follower_waiters=max_follower_waiters,
            redis_url=redis_url,
            hmac_key=hmac_key,
            hmac_key_version=hmac_key_version,
        )

    def agent_builder_semantic_cache_config(
        self,
    ) -> AgentBuilderSemanticCacheConfig:
        assist_enabled = _cache_flag(self.AGENT_BUILDER_SEMANTIC_ASSIST_ENABLED)
        if assist_enabled is None:
            return AgentBuilderSemanticCacheConfig(
                assist_enabled=False,
                planner_free_serving_enabled=False,
                disabled_reason="invalid_assist_flag",
            )

        serving_enabled = _cache_flag(self.AGENT_BUILDER_SEMANTIC_SERVING_ENABLED)
        if serving_enabled is None:
            return AgentBuilderSemanticCacheConfig(
                assist_enabled=False,
                planner_free_serving_enabled=False,
                disabled_reason="invalid_serving_flag",
            )
        if serving_enabled and not assist_enabled:
            return AgentBuilderSemanticCacheConfig(
                assist_enabled=False,
                planner_free_serving_enabled=False,
                disabled_reason="serving_requires_assist",
            )
        if not assist_enabled:
            return AgentBuilderSemanticCacheConfig(
                assist_enabled=False,
                planner_free_serving_enabled=False,
                disabled_reason="feature_disabled",
            )

        profile_version = (
            self.AGENT_BUILDER_SEMANTIC_EMBEDDING_PROFILE_VERSION or ""
        ).strip()
        model_version = (
            self.AGENT_BUILDER_SEMANTIC_EMBEDDING_MODEL_VERSION or ""
        ).strip()
        rehydration_version = (
            self.AGENT_BUILDER_SEMANTIC_REHYDRATION_CONTRACT_VERSION or ""
        ).strip()
        version_values = (profile_version, model_version, rehydration_version)
        if any(
            not value or _CACHE_VERSION_PATTERN.fullmatch(value) is None
            for value in version_values
        ):
            return AgentBuilderSemanticCacheConfig(
                assist_enabled=False,
                planner_free_serving_enabled=False,
                disabled_reason="profile_configuration_incomplete",
            )

        dimension = _cache_bounded_int(
            self.AGENT_BUILDER_SEMANTIC_EMBEDDING_DIMENSION, 1, 4096
        )
        if dimension is None:
            return AgentBuilderSemanticCacheConfig(
                assist_enabled=False,
                planner_free_serving_enabled=False,
                disabled_reason="invalid_dimension",
            )
        top_k = _cache_bounded_int(self.AGENT_BUILDER_SEMANTIC_TOP_K, 1, 20)
        if top_k is None:
            return AgentBuilderSemanticCacheConfig(
                assist_enabled=False,
                planner_free_serving_enabled=False,
                disabled_reason="invalid_top_k",
            )

        return AgentBuilderSemanticCacheConfig(
            assist_enabled=True,
            planner_free_serving_enabled=serving_enabled,
            disabled_reason=None,
            embedding_profile_version=profile_version,
            embedding_model_version=model_version,
            embedding_dimension=dimension,
            top_k=top_k,
            rehydration_contract_version=rehydration_version,
        )

    def agent_builder_intent_plan_l2_config(
        self,
    ) -> AgentBuilderIntentPlanL2Config:
        requested_mode = self.AGENT_BUILDER_INTENT_L2_MODE.strip()
        if requested_mode not in {"disabled", "write_only", "read"}:
            return AgentBuilderIntentPlanL2Config(
                mode="disabled",
                disabled_reason="invalid_mode",
            )
        if requested_mode == "disabled":
            return AgentBuilderIntentPlanL2Config(
                mode="disabled",
                disabled_reason="feature_disabled",
            )

        raw_allowlist = self.AGENT_BUILDER_INTENT_L2_ORGANIZATION_ALLOWLIST
        if not raw_allowlist.strip():
            return AgentBuilderIntentPlanL2Config(
                mode="disabled",
                disabled_reason="organization_allowlist_empty",
            )
        organization_ids: list[uuid.UUID] = []
        for raw_identifier in raw_allowlist.split(","):
            identifier = raw_identifier.strip()
            try:
                parsed_identifier = uuid.UUID(identifier)
            except (AttributeError, ValueError):
                return AgentBuilderIntentPlanL2Config(
                    mode="disabled",
                    disabled_reason="invalid_organization_allowlist",
                )
            if str(parsed_identifier) != identifier:
                return AgentBuilderIntentPlanL2Config(
                    mode="disabled",
                    disabled_reason="invalid_organization_allowlist",
                )
            organization_ids.append(parsed_identifier)
        allowlist = frozenset(organization_ids)
        if len(allowlist) != len(organization_ids):
            return AgentBuilderIntentPlanL2Config(
                mode="disabled",
                disabled_reason="invalid_organization_allowlist",
            )

        raw_keyring = (
            self.AGENT_BUILDER_INTENT_L2_ENCRYPTION_KEYS.get_secret_value()
            if self.AGENT_BUILDER_INTENT_L2_ENCRYPTION_KEYS is not None
            else ""
        )
        active_key_version = (
            self.AGENT_BUILDER_INTENT_L2_ACTIVE_KEY_VERSION or ""
        ).strip()
        if not raw_keyring or not active_key_version:
            return AgentBuilderIntentPlanL2Config(
                mode="disabled",
                disabled_reason="encryption_keyring_missing",
            )
        if _CACHE_VERSION_PATTERN.fullmatch(active_key_version) is None:
            return AgentBuilderIntentPlanL2Config(
                mode="disabled",
                disabled_reason="invalid_encryption_keyring",
            )
        try:
            parsed_keyring = json.loads(raw_keyring)
            if (
                not isinstance(parsed_keyring, dict)
                or not parsed_keyring
                or any(
                    not isinstance(version, str)
                    or _CACHE_VERSION_PATTERN.fullmatch(version) is None
                    or not isinstance(key, str)
                    or not key
                    for version, key in parsed_keyring.items()
                )
            ):
                raise ValueError("invalid keyring")
            encryption = CredentialEncryptionService(
                parsed_keyring,
                active_key_version,
                subject_label="Agent Builder L2 cache",
            )
        except (
            CredentialEncryptionError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return AgentBuilderIntentPlanL2Config(
                mode="disabled",
                disabled_reason="invalid_encryption_keyring",
            )
        return AgentBuilderIntentPlanL2Config(
            mode=requested_mode,
            disabled_reason=None,
            organization_allowlist=allowlist,
            encryption=encryption,
        )


settings = Settings()
