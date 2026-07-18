from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

import redis
from sqlalchemy.orm import Session

from apps.memory.adapters.admission import (
    PublicConversationAdmissionPolicy,
    RedisPublicConversationAdmission,
)
from apps.memory.adapters.audit import SqlAlchemyPublicConversationAudit
from apps.memory.adapters.persistence.repository import (
    SqlAlchemyConversationMemoryRepository,
    SqlAlchemyMemoryUnitOfWork,
)
from apps.memory.adapters.security import (
    FernetSecretReplayCipher,
    HmacPublicSecretIssuer,
)
from apps.memory.application.public_lifecycle import (
    ClosePublicConversationUseCase,
    CreatePublicConversationUseCase,
    DeletePublicConversationUseCase,
    GetPublicPurgeStatusUseCase,
    GetPublicTranscriptUseCase,
    PublicConversationPolicy,
    ResetPublicConversationUseCase,
)
from apps.memory.domain.errors import PublicConversationFeatureDisabledError


@dataclass(frozen=True, slots=True)
class PublicConversationApplication:
    create: CreatePublicConversationUseCase
    close: ClosePublicConversationUseCase
    reset: ResetPublicConversationUseCase
    delete: DeletePublicConversationUseCase
    transcript: GetPublicTranscriptUseCase
    purge_status: GetPublicPurgeStatusUseCase


def build_public_conversation_application(
    db: Session,
    *,
    environ: Mapping[str, str] | None = None,
    redis_client=None,
) -> PublicConversationApplication:
    values = environ if environ is not None else os.environ
    validate_public_conversation_security_configuration(values)
    if not public_conversation_enabled_from_environment(values):
        raise PublicConversationFeatureDisabledError()
    policy = public_conversation_policy_from_environment(values)
    admission_policy = public_conversation_admission_policy_from_environment(values)
    repository = SqlAlchemyConversationMemoryRepository(db)
    uow = SqlAlchemyMemoryUnitOfWork(db)
    secrets = HmacPublicSecretIssuer.from_environment(values)
    replay_cipher = FernetSecretReplayCipher.from_environment(values)
    admission_key = _admission_key(values)
    admission = RedisPublicConversationAdmission(
        redis_client if redis_client is not None else _redis_client(values),
        hmac_key=admission_key,
        policy=admission_policy,
        key_namespace=values.get(
            "MEMORY_PUBLIC_ADMISSION_KEY_NAMESPACE",
            "nodease-memory-public",
        ),
    )
    audit = SqlAlchemyPublicConversationAudit(db)
    kwargs = {
        "repository": repository,
        "uow": uow,
        "secrets": secrets,
        "replay_cipher": replay_cipher,
        "audit": audit,
        "policy": policy,
        "admission": admission,
    }
    return PublicConversationApplication(
        create=CreatePublicConversationUseCase(**kwargs),
        close=ClosePublicConversationUseCase(**kwargs),
        reset=ResetPublicConversationUseCase(**kwargs),
        delete=DeletePublicConversationUseCase(**kwargs),
        transcript=GetPublicTranscriptUseCase(**kwargs),
        purge_status=GetPublicPurgeStatusUseCase(**kwargs),
    )


def validate_public_conversation_security_configuration(
    environ: Mapping[str, str] | None = None,
) -> None:
    values = environ if environ is not None else os.environ
    if not public_conversation_enabled_from_environment(values):
        return
    if values.get("MEMORY_PUBLIC_REPLAY_BACKUP_ERASURE_MODE", "") not in {
        "external_crypto_erasure",
        "no_database_backups",
    }:
        raise RuntimeError(
            "MEMORY_PUBLIC_REPLAY_BACKUP_ERASURE_MODE must confirm an approved mode"
        )
    public_conversation_policy_from_environment(values)
    public_conversation_admission_policy_from_environment(values)
    HmacPublicSecretIssuer.from_environment(values)
    FernetSecretReplayCipher.from_environment(values)
    _admission_key(values)


def public_conversation_enabled_from_environment(
    environ: Mapping[str, str],
) -> bool:
    value = environ.get("MEMORY_PUBLIC_CONVERSATION_ENABLED", "false").strip().lower()
    if value in {"true", "1"}:
        return True
    if value in {"false", "0"}:
        return False
    raise RuntimeError("MEMORY_PUBLIC_CONVERSATION_ENABLED must be true or false")


def public_conversation_policy_from_environment(
    environ: Mapping[str, str],
) -> PublicConversationPolicy:
    return PublicConversationPolicy(
        idle_lifetime=_seconds(
            environ,
            "MEMORY_PUBLIC_IDLE_SECONDS",
            86_400,
            60,
            604_800,
        ),
        absolute_lifetime=_seconds(
            environ,
            "MEMORY_PUBLIC_ABSOLUTE_SECONDS",
            604_800,
            120,
            2_592_000,
        ),
        access_grant_lifetime=_seconds(
            environ,
            "MEMORY_PUBLIC_GRANT_SECONDS",
            86_400,
            60,
            604_800,
        ),
        access_secret_replay_lifetime=_seconds(
            environ,
            "MEMORY_PUBLIC_SECRET_REPLAY_SECONDS",
            600,
            60,
            600,
        ),
        purge_receipt_lifetime=_seconds(
            environ,
            "MEMORY_PUBLIC_PURGE_RECEIPT_SECONDS",
            604_800,
            3600,
            691_200,
        ),
        purge_secret_replay_lifetime=_seconds(
            environ,
            "MEMORY_PUBLIC_PURGE_REPLAY_SECONDS",
            86_400,
            60,
            86_400,
        ),
        idempotency_retention=_seconds(
            environ,
            "MEMORY_PUBLIC_IDEMPOTENCY_RETENTION_SECONDS",
            691_200,
            86_400,
            1_209_600,
        ),
        purge_max_attempts=_integer(
            environ,
            "MEMORY_PUBLIC_PURGE_MAX_ATTEMPTS",
            8,
            1,
            100,
        ),
    )


def public_conversation_admission_policy_from_environment(
    environ: Mapping[str, str],
) -> PublicConversationAdmissionPolicy:
    return PublicConversationAdmissionPolicy(
        window_seconds=_integer(
            environ,
            "MEMORY_PUBLIC_ADMISSION_WINDOW_SECONDS",
            60,
            1,
            3600,
        ),
        deployment_rate_limit=_integer(
            environ,
            "MEMORY_PUBLIC_DEPLOYMENT_RATE_LIMIT",
            60,
            1,
            100_000,
        ),
        organization_rate_limit=_integer(
            environ,
            "MEMORY_PUBLIC_ORGANIZATION_RATE_LIMIT",
            240,
            1,
            100_000,
        ),
        network_rate_limit=_integer(
            environ,
            "MEMORY_PUBLIC_NETWORK_RATE_LIMIT",
            60,
            1,
            100_000,
        ),
        grant_rate_limit=_integer(
            environ,
            "MEMORY_PUBLIC_GRANT_RATE_LIMIT",
            30,
            1,
            100_000,
        ),
        create_window_seconds=_integer(
            environ,
            "MEMORY_PUBLIC_CREATE_WINDOW_SECONDS",
            600,
            1,
            3600,
        ),
        create_deployment_rate_limit=_integer(
            environ,
            "MEMORY_PUBLIC_CREATE_DEPLOYMENT_RATE_LIMIT",
            200,
            1,
            100_000,
        ),
        create_organization_rate_limit=_integer(
            environ,
            "MEMORY_PUBLIC_CREATE_ORGANIZATION_RATE_LIMIT",
            1_000,
            1,
            100_000,
        ),
        create_deployment_network_rate_limit=_integer(
            environ,
            "MEMORY_PUBLIC_CREATE_DEPLOYMENT_NETWORK_RATE_LIMIT",
            10,
            1,
            100_000,
        ),
    )


def _admission_key(environ: Mapping[str, str]) -> bytes:
    raw_key = environ.get("MEMORY_PUBLIC_ADMISSION_HMAC_KEY", "")
    if not raw_key:
        raise RuntimeError("MEMORY_PUBLIC_ADMISSION_HMAC_KEY is required")
    key = raw_key.encode("utf-8")
    if len(key) < 32:
        raise RuntimeError(
            "MEMORY_PUBLIC_ADMISSION_HMAC_KEY must contain at least 32 bytes"
        )
    return key


def _redis_client(environ: Mapping[str, str]):
    try:
        port = int(environ.get("REDIS_PORT", "6379"))
        database = int(environ.get("REDIS_DB", "0"))
    except ValueError as exc:
        raise RuntimeError("public conversation Redis configuration is invalid") from exc
    if not 1 <= port <= 65535 or not 0 <= database <= 255:
        raise RuntimeError("public conversation Redis configuration is invalid")
    return redis.Redis(
        host=environ.get("REDIS_HOST", "localhost"),
        port=port,
        db=database,
        password=environ.get("REDIS_PASSWORD") or None,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        health_check_interval=30,
    )


def _integer(
    environ: Mapping[str, str],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} is outside allowed bounds")
    return value


def _seconds(
    environ: Mapping[str, str],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
):
    from datetime import timedelta

    return timedelta(seconds=_integer(environ, name, default, minimum, maximum))


__all__ = [
    "PublicConversationApplication",
    "build_public_conversation_application",
    "public_conversation_enabled_from_environment",
    "public_conversation_admission_policy_from_environment",
    "public_conversation_policy_from_environment",
    "validate_public_conversation_security_configuration",
]
