from __future__ import annotations

import secrets
import uuid

import pytest

from apps.memory.adapters.admission import (
    PublicConversationAdmissionPolicy,
    RedisPublicConversationAdmission,
)
from apps.memory.application.public_lifecycle import PublicDeploymentBinding
from apps.memory.domain.errors import (
    MemoryAdapterUnavailableError,
    PublicConversationRateLimitedError,
)


class _Redis:
    def __init__(self, result=(1, 0), error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = []

    def eval(self, *args):
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result


def _binding() -> PublicDeploymentBinding:
    return PublicDeploymentBinding(
        organization_id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        deployment_id=uuid.uuid4(),
        deployment_version=1,
        mapping_version="mapping-v1",
        memory_policy_version="memory-v1",
        memory_contract_version="conversation-memory-v1",
        storage_generation=1,
    )


def _admission(redis: _Redis) -> RedisPublicConversationAdmission:
    return RedisPublicConversationAdmission(
        redis,
        hmac_key=secrets.token_bytes(32),
        policy=PublicConversationAdmissionPolicy(
            deployment_rate_limit=2,
            organization_rate_limit=3,
            network_rate_limit=4,
            grant_rate_limit=5,
            create_window_seconds=600,
            create_deployment_rate_limit=6,
            create_organization_rate_limit=7,
            create_deployment_network_rate_limit=8,
        ),
    )


def test_admission_uses_hashed_dimensions_not_network_or_grant_values_in_redis_key():
    redis = _Redis()
    admission = _admission(redis)
    network = "198.51.100.42"
    grant_id = uuid.uuid4()

    admission.admit(
        operation="conversation.close",
        binding=_binding(),
        grant_id=grant_id,
        network_address=network,
    )

    call = redis.calls[0]
    keys = call[2:6]
    assert all(network not in key for key in keys)
    assert all(str(grant_id) not in key for key in keys)
    assert call[-5:] == (60, 2, 3, 4, 5)


def test_create_uses_deployment_network_bucket_without_a_global_grant_bucket():
    redis = _Redis()
    admission = _admission(redis)
    first = _binding()
    second = _binding()
    network = "198.51.100.42"

    for binding in (first, second):
        admission.admit(
            operation="conversation.create",
            binding=binding,
            grant_id=None,
            network_address=network,
        )

    first_call, second_call = redis.calls
    first_keys = set(first_call[2:5])
    second_keys = set(second_call[2:5])
    assert len(first_keys) == len(second_keys) == 3
    assert not first_keys & second_keys
    assert first_call[-4:] == (600, 6, 7, 8)
    assert second_call[-4:] == (600, 6, 7, 8)


def test_admission_returns_bounded_retry_after_when_any_scope_is_limited():
    with pytest.raises(PublicConversationRateLimitedError) as error:
        _admission(_Redis(result=(0, b"120"))).admit(
            operation="conversation.create",
            binding=_binding(),
            grant_id=None,
            network_address="203.0.113.7",
        )

    assert error.value.retry_after_seconds == 60


def test_admission_backend_failure_is_fail_closed():
    with pytest.raises(MemoryAdapterUnavailableError):
        _admission(_Redis(error=OSError("unavailable"))).admit(
            operation="conversation.create",
            binding=_binding(),
            grant_id=None,
            network_address="203.0.113.8",
        )
