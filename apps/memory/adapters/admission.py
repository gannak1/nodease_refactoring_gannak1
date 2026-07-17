from __future__ import annotations

import hashlib
import hmac
import math
import re
from dataclasses import dataclass
from typing import Any

from apps.memory.application.public_lifecycle import PublicDeploymentBinding
from apps.memory.domain.errors import (
    MemoryAdapterUnavailableError,
    PublicConversationRateLimitedError,
)


_KEY_NAMESPACE_PATTERN = re.compile(
    r"[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?"
)

_ADMIT_SCRIPT = r"""
local time = redis.call('TIME')
local now = tonumber(time[1]) + (tonumber(time[2]) / 1000000)
local window_seconds = tonumber(ARGV[1])
local window = math.floor(now / window_seconds)
local window_end = (window + 1) * window_seconds

for index, key in ipairs(KEYS) do
  local current = tonumber(redis.call('GET', key) or '0')
  if current >= tonumber(ARGV[index + 1]) then
    return {0, tostring(math.max(1, math.ceil(window_end - now)))}
  end
end

for _, key in ipairs(KEYS) do
  redis.call('INCR', key)
  redis.call('EXPIREAT', key, window_end + 60)
end
return {1, '0'}
"""


@dataclass(frozen=True, slots=True)
class PublicConversationAdmissionPolicy:
    window_seconds: int = 60
    deployment_rate_limit: int = 60
    organization_rate_limit: int = 240
    network_rate_limit: int = 60
    grant_rate_limit: int = 30

    def __post_init__(self) -> None:
        values = (
            self.window_seconds,
            self.deployment_rate_limit,
            self.organization_rate_limit,
            self.network_rate_limit,
            self.grant_rate_limit,
        )
        if any(value < 1 for value in values):
            raise ValueError("public conversation admission policy is invalid")
        if self.window_seconds > 3600 or max(values[1:]) > 100_000:
            raise ValueError("public conversation admission policy is unbounded")


class RedisPublicConversationAdmission:
    """Fail-closed distributed fixed-window admission for public mutations."""

    def __init__(
        self,
        redis_client: Any,
        *,
        hmac_key: bytes,
        policy: PublicConversationAdmissionPolicy,
        key_namespace: str = "nodease-memory-public",
    ) -> None:
        if len(hmac_key) < 32:
            raise ValueError("public conversation admission HMAC key must be at least 32 bytes")
        if not _KEY_NAMESPACE_PATTERN.fullmatch(key_namespace):
            raise ValueError("public conversation admission key namespace is invalid")
        self._redis = redis_client
        self._hmac_key = hmac_key
        self._policy = policy
        self._key_prefix = f"{key_namespace}:{{admission-v1}}"

    def admit(
        self,
        *,
        operation: str,
        binding: PublicDeploymentBinding,
        grant_id,
        network_address: str,
    ) -> None:
        if not network_address or len(network_address) > 255:
            raise MemoryAdapterUnavailableError()
        dimensions = (
            ("deployment", str(binding.deployment_id), self._policy.deployment_rate_limit),
            ("organization", str(binding.organization_id), self._policy.organization_rate_limit),
            ("network", network_address, self._policy.network_rate_limit),
            (
                "grant",
                str(grant_id) if grant_id is not None else f"create:{operation}",
                self._policy.grant_rate_limit,
            ),
        )
        keys = tuple(
            f"{self._key_prefix}:{operation}:{dimension}:{self._digest(dimension, value)}"
            for dimension, value, _limit in dimensions
        )
        limits = tuple(limit for _dimension, _value, limit in dimensions)
        try:
            result = self._redis.eval(
                _ADMIT_SCRIPT,
                len(keys),
                *keys,
                self._policy.window_seconds,
                *limits,
            )
        except Exception as exc:
            raise MemoryAdapterUnavailableError() from exc
        allowed, retry_after = self._parse_result(result)
        if not allowed:
            raise PublicConversationRateLimitedError(retry_after)

    def _digest(self, dimension: str, value: str) -> str:
        payload = f"memory-public-admission-v1:{dimension}:{value}".encode("utf-8")
        return hmac.new(self._hmac_key, payload, hashlib.sha256).hexdigest()

    @staticmethod
    def _parse_result(result: Any) -> tuple[bool, int]:
        if not isinstance(result, (list, tuple)) or len(result) != 2:
            raise MemoryAdapterUnavailableError()
        try:
            allowed = int(result[0])
            raw_retry = result[1]
            if isinstance(raw_retry, bytes):
                raw_retry = raw_retry.decode("ascii", errors="strict")
            retry_after = math.ceil(float(raw_retry))
        except (TypeError, ValueError, UnicodeDecodeError, OverflowError) as exc:
            raise MemoryAdapterUnavailableError() from exc
        if allowed not in {0, 1} or retry_after < 0:
            raise MemoryAdapterUnavailableError()
        return bool(allowed), max(1, min(60, retry_after))


__all__ = [
    "PublicConversationAdmissionPolicy",
    "RedisPublicConversationAdmission",
]
