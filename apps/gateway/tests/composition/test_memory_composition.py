from __future__ import annotations

import secrets
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from apps.gateway.composition.memory import (
    build_public_conversation_application,
    validate_public_conversation_security_configuration,
)
from apps.memory.adapters.admission import RedisPublicConversationAdmission


def _environment() -> dict[str, str]:
    return {
        "MEMORY_PUBLIC_CAPABILITY_HMAC_KEY": secrets.token_urlsafe(32),
        "MEMORY_PUBLIC_REPLAY_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "MEMORY_PUBLIC_ADMISSION_HMAC_KEY": secrets.token_urlsafe(32),
    }


def test_composition_requires_three_independent_memory_security_keys():
    with pytest.raises(RuntimeError):
        validate_public_conversation_security_configuration({})


def test_composition_rejects_an_invalid_lifetime_relationship():
    environment = _environment()
    environment.update(
        {
            "MEMORY_PUBLIC_IDLE_SECONDS": "86400",
            "MEMORY_PUBLIC_ABSOLUTE_SECONDS": "86400",
        }
    )

    with pytest.raises(ValueError):
        validate_public_conversation_security_configuration(environment)


def test_composition_wires_one_shared_fail_closed_admission_adapter_per_request():
    environment = _environment()
    fake_redis = MagicMock()
    application = build_public_conversation_application(
        MagicMock(spec=Session),
        environ=environment,
        redis_client=fake_redis,
    )

    assert isinstance(application.create.admission, RedisPublicConversationAdmission)
    assert application.create.admission is application.close.admission
    assert application.create.admission is application.reset.admission
    assert application.create.admission is application.delete.admission
    assert application.create.admission._redis is fake_redis
