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
        request_deduplication_ttl_seconds=86_400,
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
        request_key_hash="a" * 64,
        request_fingerprint="b" * 64,
    )

    call = redis.calls[0]
    assert call[1] == 5
    request_marker = call[2]
    keys = call[3:7]
    assert "a" * 64 not in request_marker
    assert all(network not in key for key in keys)
    assert all(str(grant_id) not in key for key in keys)
    assert call[-6:] == (60, 86_400, 2, 3, 4, 5)


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
            request_key_hash="a" * 64,
            request_fingerprint="b" * 64,
        )

    first_call, second_call = redis.calls
    first_keys = set(first_call[3:6])
    second_keys = set(second_call[3:6])
    assert len(first_keys) == len(second_keys) == 3
    assert not first_keys & second_keys
    assert first_call[-5:] == (600, 86_400, 6, 7, 8)
    assert second_call[-5:] == (600, 86_400, 6, 7, 8)


def test_same_logical_request_uses_one_hmac_marker_for_concurrent_admission():
    redis = _Redis()
    admission = _admission(redis)
    binding = _binding()

    for _ in range(2):
        admission.admit(
            operation="conversation.create",
            binding=binding,
            grant_id=None,
            network_address="198.51.100.42",
            request_key_hash="b" * 64,
            request_fingerprint="c" * 64,
        )

    assert redis.calls[0][2] == redis.calls[1][2]


def test_same_idempotency_key_with_a_different_fingerprint_uses_another_marker():
    redis = _Redis()
    admission = _admission(redis)
    binding = _binding()

    for fingerprint in ("c" * 64, "d" * 64):
        admission.admit(
            operation="conversation.create",
            binding=binding,
            grant_id=None,
            network_address="198.51.100.42",
            request_key_hash="b" * 64,
            request_fingerprint=fingerprint,
        )

    assert redis.calls[0][2] != redis.calls[1][2]


def test_create_admission_preserves_retry_after_within_the_create_window():
    with pytest.raises(PublicConversationRateLimitedError) as error:
        _admission(_Redis(result=(0, b"120"))).admit(
            operation="conversation.create",
            binding=_binding(),
            grant_id=None,
            network_address="203.0.113.7",
            request_key_hash="a" * 64,
            request_fingerprint="b" * 64,
        )

    assert error.value.retry_after_seconds == 120


def test_lifecycle_admission_caps_retry_after_to_its_shorter_window():
    with pytest.raises(PublicConversationRateLimitedError) as error:
        _admission(_Redis(result=(0, b"120"))).admit(
            operation="conversation.close",
            binding=_binding(),
            grant_id=uuid.uuid4(),
            network_address="203.0.113.7",
            request_key_hash="a" * 64,
            request_fingerprint="b" * 64,
        )

    assert error.value.retry_after_seconds == 60


def test_admission_backend_failure_is_fail_closed():
    with pytest.raises(MemoryAdapterUnavailableError):
        _admission(_Redis(error=OSError("unavailable"))).admit(
            operation="conversation.create",
            binding=_binding(),
            grant_id=None,
            network_address="203.0.113.8",
            request_key_hash="a" * 64,
            request_fingerprint="b" * 64,
        )
