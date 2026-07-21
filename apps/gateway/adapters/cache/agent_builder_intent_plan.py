from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from apps.gateway.application.agent_builder.intent_cache import (
    CachedIntentPlanV1,
    CanonicalIntentPlanCodec,
    IntentCacheKey,
    IntentPlanLoadResult,
    IntentPlanSaveResult,
)


_KEY_NAMESPACE = "agent-builder:intent-plan"
_ENVELOPE_VERSION = 1
_VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_OWNER_TOKEN_PATTERN = re.compile(r"^[a-f0-9]{32,128}$")
_HEX_DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _valid_redis_url(value: str) -> bool:
    if not isinstance(value, str) or not value or any(
        character.isspace() for character in value
    ):
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


_ACQUIRE_LEASE_SCRIPT = r"""
-- intent-cache:acquire-v1
local current = redis.call('GET', KEYS[1])
if current then
    local generation = string.match(current, '^(%d+):')
    if generation == nil then
        return {'UNAVAILABLE', '0'}
    end
    return {'CONTENDED', generation}
end

local generation = redis.call('INCR', KEYS[2])
redis.call('PEXPIRE', KEYS[2], ARGV[3])
local lease_value = tostring(generation) .. ':' .. ARGV[1]
local stored = redis.call('SET', KEYS[1], lease_value, 'NX', 'PX', ARGV[2])
if not stored then
    return {'UNAVAILABLE', '0'}
end
return {'ACQUIRED', tostring(generation)}
"""

_RELEASE_LEASE_SCRIPT = r"""
-- intent-cache:release-v1
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
return redis.call('DEL', KEYS[1])
"""

_COMPLETE_WITHOUT_VALUE_SCRIPT = r"""
-- intent-cache:complete-v1
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
redis.call('SET', KEYS[2], ARGV[2], 'PX', ARGV[3])
redis.call('DEL', KEYS[1])
return 1
"""


class _DuplicateEnvelopeKey(ValueError):
    pass


def _object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateEnvelopeKey()
        result[key] = value
    return result


def _reject_nonfinite(_value):
    raise ValueError("non-finite number")


class _ProcessFollowerSlots:
    _lock = threading.Lock()
    _active = 0

    @classmethod
    def acquire(cls, limit: int) -> bool:
        with cls._lock:
            if cls._active >= limit:
                return False
            cls._active += 1
            return True

    @classmethod
    def release(cls) -> None:
        with cls._lock:
            if cls._active > 0:
                cls._active -= 1


@dataclass(frozen=True, slots=True)
class IntentPlanLeaseAcquireResult:
    status: Literal["acquired", "contended", "unavailable"]
    generation: int | None

    def __post_init__(self) -> None:
        if self.status not in {"acquired", "contended", "unavailable"}:
            raise ValueError("invalid intent cache lease result")
        if self.status == "unavailable":
            valid = self.generation is None
        else:
            valid = type(self.generation) is int and self.generation > 0
        if not valid:
            raise ValueError("invalid intent cache lease result")


@dataclass(frozen=True, slots=True)
class IntentPlanLeaseReleaseResult:
    status: Literal["released", "ignored", "unavailable"]

    def __post_init__(self) -> None:
        if self.status not in {"released", "ignored", "unavailable"}:
            raise ValueError("invalid intent cache release result")


@dataclass(frozen=True, slots=True)
class IntentPlanCompletionResult:
    status: Literal["signaled_and_released", "ignored", "unavailable"]

    def __post_init__(self) -> None:
        if self.status not in {
            "signaled_and_released",
            "ignored",
            "unavailable",
        }:
            raise ValueError("invalid intent cache completion result")


@dataclass(frozen=True, slots=True)
class IntentPlanWaitResult:
    status: Literal[
        "hit",
        "owner_completed_without_value",
        "canceled",
        "stale",
        "timeout",
        "unavailable",
        "overflow",
    ]
    plan: CachedIntentPlanV1 | None = None
    reason: Literal["cache_unavailable", "waiter_capacity_exceeded"] | None = None

    def __post_init__(self) -> None:
        valid_statuses = {
            "hit",
            "owner_completed_without_value",
            "canceled",
            "stale",
            "timeout",
            "unavailable",
            "overflow",
        }
        if self.status not in valid_statuses:
            raise ValueError("invalid intent cache wait result")
        if self.status == "hit":
            valid = self.plan is not None and self.reason is None
        elif self.status == "unavailable":
            valid = self.plan is None and self.reason == "cache_unavailable"
        elif self.status == "overflow":
            valid = (
                self.plan is None
                and self.reason == "waiter_capacity_exceeded"
            )
        else:
            valid = self.plan is None and self.reason is None
        if not valid:
            raise ValueError("invalid intent cache wait result")


class RedisIntentPlanCacheAdapter:
    """Fail-open Redis storage and foreground single-flight coordination."""

    def __init__(
        self,
        redis_client,
        *,
        hmac_key: bytes,
        hmac_key_version: str,
        ttl_seconds: int = 900,
        max_payload_bytes: int = 32 * 1024,
        operation_timeout_ms: int = 100,
        lease_seconds: int = 240,
        follower_wait_ms: int = 45_000,
        max_follower_waiters: int = 8,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._validate_configuration(
            hmac_key=hmac_key,
            hmac_key_version=hmac_key_version,
            ttl_seconds=ttl_seconds,
            max_payload_bytes=max_payload_bytes,
            operation_timeout_ms=operation_timeout_ms,
            lease_seconds=lease_seconds,
            follower_wait_ms=follower_wait_ms,
            max_follower_waiters=max_follower_waiters,
        )
        if not callable(monotonic) or not callable(sleep):
            raise ValueError("invalid intent cache clock configuration")
        self._redis = redis_client
        self._hmac_key = hmac_key
        self._hmac_key_version = hmac_key_version
        self._ttl_seconds = ttl_seconds
        self._max_payload_bytes = max_payload_bytes
        self._operation_timeout_ms = operation_timeout_ms
        self._lease_seconds = lease_seconds
        self._follower_wait_ms = follower_wait_ms
        self._max_follower_waiters = max_follower_waiters
        self._monotonic = monotonic
        self._sleep = sleep
        self._closed = False
        self._codec = CanonicalIntentPlanCodec()

    @classmethod
    def from_url(cls, redis_url: str, **configuration):
        """Build a binary Redis client with both connect and socket deadlines."""
        if not _valid_redis_url(redis_url):
            raise ValueError("invalid intent cache Redis URL")

        import redis

        timeout_ms = configuration.get("operation_timeout_ms", 100)
        if type(timeout_ms) is not int or not 10 <= timeout_ms <= 500:
            raise ValueError("invalid intent cache timeout configuration")
        timeout_seconds = timeout_ms / 1000
        client = redis.Redis.from_url(
            redis_url,
            decode_responses=False,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
            retry_on_timeout=False,
        )
        return cls(client, **configuration)

    def close(self) -> None:
        """Release the pool created by :meth:`from_url` once at app shutdown."""
        if self._closed:
            return
        self._closed = True
        close = getattr(self._redis, "close", None)
        if callable(close):
            try:
                close(close_connection_pool=True)
            except TypeError:
                close()
            return
        pool = getattr(self._redis, "connection_pool", None)
        disconnect = getattr(pool, "disconnect", None)
        if callable(disconnect):
            disconnect()

    def __repr__(self) -> str:
        return "<RedisIntentPlanCacheAdapter redacted>"

    @staticmethod
    def _validate_configuration(
        *,
        hmac_key: bytes,
        hmac_key_version: str,
        ttl_seconds: int,
        max_payload_bytes: int,
        operation_timeout_ms: int,
        lease_seconds: int,
        follower_wait_ms: int,
        max_follower_waiters: int,
    ) -> None:
        if not isinstance(hmac_key, bytes) or len(hmac_key) < 32:
            raise ValueError("invalid intent cache HMAC configuration")
        if not isinstance(hmac_key_version, str) or not _VERSION_PATTERN.fullmatch(
            hmac_key_version
        ):
            raise ValueError("invalid intent cache HMAC configuration")
        bounded_values = (
            (ttl_seconds, 30, 3600),
            (max_payload_bytes, 4 * 1024, 64 * 1024),
            (operation_timeout_ms, 10, 500),
            (lease_seconds, 5, 300),
            (follower_wait_ms, 0, 60_000),
            (max_follower_waiters, 1, 64),
        )
        if any(
            type(value) is not int or not minimum <= value <= maximum
            for value, minimum, maximum in bounded_values
        ):
            raise ValueError("invalid intent cache bounded configuration")

    def build_key(self, canonical_key_material: bytes) -> IntentCacheKey:
        if not isinstance(canonical_key_material, bytes) or not canonical_key_material:
            raise ValueError("invalid intent cache key material")
        domain = f"agent-builder-cache:key:{self._hmac_key_version}".encode(
            "ascii"
        )
        framed = (
            domain
            + b"\0"
            + len(canonical_key_material).to_bytes(8, "big")
            + canonical_key_material
        )
        digest = hmac.new(self._hmac_key, framed, hashlib.sha256).hexdigest()
        return IntentCacheKey(
            namespace=_KEY_NAMESPACE,
            key_version=self._hmac_key_version,
            digest=digest,
        )

    def redis_key(self, key: IntentCacheKey) -> str:
        if (
            not isinstance(key, IntentCacheKey)
            or key.key_version != self._hmac_key_version
        ):
            raise ValueError("invalid intent cache key")
        return f"{key.namespace}:{key.key_version}:{key.digest}"

    def load(self, key: IntentCacheKey) -> IntentPlanLoadResult:
        try:
            redis_key = self.redis_key(key)
        except ValueError:
            return IntentPlanLoadResult(
                status="invalid",
                plan=None,
                reason="invalid_cached_plan",
            )
        try:
            stored = self._redis.get(redis_key)
        except Exception:
            return self._unavailable_load()
        if stored is None:
            return IntentPlanLoadResult(
                status="miss",
                plan=None,
                reason="not_found",
            )
        try:
            plan = self._decode_envelope(key, stored)
        except Exception:
            self._best_effort_delete(redis_key)
            return IntentPlanLoadResult(
                status="invalid",
                plan=None,
                reason="invalid_cached_plan",
            )
        return IntentPlanLoadResult(status="hit", plan=plan, reason=None)

    def save(
        self,
        key: IntentCacheKey,
        plan: CachedIntentPlanV1,
    ) -> IntentPlanSaveResult:
        try:
            redis_key = self.redis_key(key)
            envelope = self._encode_envelope(key, plan)
            stored = self._redis.set(
                redis_key,
                envelope,
                ex=self._ttl_seconds,
            )
        except Exception:
            return self._unavailable_save()
        if not stored:
            return self._unavailable_save()
        return IntentPlanSaveResult(status="stored", reason=None)

    def _encode_envelope(
        self,
        key: IntentCacheKey,
        plan: CachedIntentPlanV1,
    ) -> bytes:
        payload = self._codec.encode(plan, self._max_payload_bytes)
        encoded_payload = base64.urlsafe_b64encode(payload).rstrip(b"=").decode(
            "ascii"
        )
        envelope = {
            "envelope_version": _ENVELOPE_VERSION,
            "payload": encoded_payload,
            "payload_mac": self._payload_mac(key, payload),
        }
        return json.dumps(
            envelope,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")

    def _decode_envelope(
        self,
        key: IntentCacheKey,
        stored,
    ) -> CachedIntentPlanV1:
        if not isinstance(stored, bytes):
            raise ValueError("invalid envelope")
        maximum_encoded_payload = math.ceil(self._max_payload_bytes * 4 / 3)
        maximum_envelope_bytes = maximum_encoded_payload + 256
        if len(stored) > maximum_envelope_bytes:
            raise ValueError("invalid envelope")
        try:
            text = stored.decode("ascii", errors="strict")
            raw = json.loads(
                text,
                object_pairs_hook=_object_without_duplicates,
                parse_constant=_reject_nonfinite,
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            _DuplicateEnvelopeKey,
            TypeError,
            ValueError,
            RecursionError,
        ):
            raise ValueError("invalid envelope") from None
        if not isinstance(raw, dict) or set(raw) != {
            "envelope_version",
            "payload",
            "payload_mac",
        }:
            raise ValueError("invalid envelope")
        canonical_envelope = json.dumps(
            raw,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        if canonical_envelope != stored:
            raise ValueError("invalid envelope")
        if type(raw["envelope_version"]) is not int or raw["envelope_version"] != 1:
            raise ValueError("invalid envelope")
        payload_text = raw["payload"]
        payload_mac = raw["payload_mac"]
        if (
            not isinstance(payload_text, str)
            or not isinstance(payload_mac, str)
            or _HEX_DIGEST_PATTERN.fullmatch(payload_mac) is None
            or len(payload_text) > maximum_encoded_payload
        ):
            raise ValueError("invalid envelope")
        padding = "=" * (-len(payload_text) % 4)
        try:
            payload = base64.b64decode(
                (payload_text + padding).encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
        except (UnicodeEncodeError, binascii.Error, ValueError):
            raise ValueError("invalid envelope") from None
        canonical_payload_text = base64.urlsafe_b64encode(payload).rstrip(b"=")
        if canonical_payload_text != payload_text.encode("ascii"):
            raise ValueError("invalid envelope")
        expected_mac = self._payload_mac(key, payload)
        if not hmac.compare_digest(payload_mac, expected_mac):
            raise ValueError("invalid envelope")
        return self._codec.decode(payload, self._max_payload_bytes)

    def _payload_mac(self, key: IntentCacheKey, payload: bytes) -> str:
        domain = f"agent-builder-cache:value:{self._hmac_key_version}".encode(
            "ascii"
        )
        framed = (
            domain
            + b"\0"
            + key.digest.encode("ascii")
            + len(payload).to_bytes(8, "big")
            + payload
        )
        return hmac.new(self._hmac_key, framed, hashlib.sha256).hexdigest()

    def _best_effort_delete(self, redis_key: str) -> None:
        try:
            self._redis.delete(redis_key)
        except Exception:
            pass

    @staticmethod
    def _unavailable_load() -> IntentPlanLoadResult:
        return IntentPlanLoadResult(
            status="unavailable",
            plan=None,
            reason="cache_unavailable",
        )

    @staticmethod
    def _unavailable_save() -> IntentPlanSaveResult:
        return IntentPlanSaveResult(
            status="unavailable",
            reason="cache_unavailable",
        )

    @staticmethod
    def new_owner_token() -> str:
        return secrets.token_hex(32)

    def acquire_lease(
        self,
        key: IntentCacheKey,
        owner_token: str,
    ) -> IntentPlanLeaseAcquireResult:
        self._validate_owner(owner_token)
        try:
            base = self.redis_key(key)
        except ValueError:
            return IntentPlanLeaseAcquireResult(
                status="unavailable",
                generation=None,
            )
        lease_ms = self._lease_seconds * 1000
        try:
            response = self._redis.eval(
                _ACQUIRE_LEASE_SCRIPT,
                2,
                f"{base}:lease",
                f"{base}:generation",
                owner_token,
                lease_ms,
                lease_ms * 3,
            )
            parsed = self._parse_acquire_response(response)
        except Exception:
            parsed = None
        if parsed is None:
            return IntentPlanLeaseAcquireResult(
                status="unavailable",
                generation=None,
            )
        return parsed

    def release_lease(
        self,
        key: IntentCacheKey,
        owner_token: str,
        lease_generation: int,
    ) -> IntentPlanLeaseReleaseResult:
        expected = self._lease_value(owner_token, lease_generation)
        try:
            redis_key = self.redis_key(key)
        except ValueError:
            return IntentPlanLeaseReleaseResult(status="unavailable")
        try:
            released = self._redis.eval(
                _RELEASE_LEASE_SCRIPT,
                1,
                f"{redis_key}:lease",
                expected,
            )
        except Exception:
            return IntentPlanLeaseReleaseResult(status="unavailable")
        if released == 1:
            return IntentPlanLeaseReleaseResult(status="released")
        if released == 0:
            return IntentPlanLeaseReleaseResult(status="ignored")
        return IntentPlanLeaseReleaseResult(status="unavailable")

    def complete_without_value(
        self,
        key: IntentCacheKey,
        owner_token: str,
        lease_generation: int,
    ) -> IntentPlanCompletionResult:
        expected = self._lease_value(owner_token, lease_generation)
        try:
            base = self.redis_key(key)
        except ValueError:
            return IntentPlanCompletionResult(status="unavailable")
        try:
            completed = self._redis.eval(
                _COMPLETE_WITHOUT_VALUE_SCRIPT,
                2,
                f"{base}:lease",
                f"{base}:completion:{lease_generation}",
                expected,
                lease_generation,
                self._lease_seconds * 1000,
            )
        except Exception:
            return IntentPlanCompletionResult(status="unavailable")
        if completed == 1:
            return IntentPlanCompletionResult(status="signaled_and_released")
        if completed == 0:
            return IntentPlanCompletionResult(status="ignored")
        return IntentPlanCompletionResult(status="unavailable")

    def wait_for_value(
        self,
        key: IntentCacheKey,
        lease_generation: int,
        *,
        cancellation_fence: Callable[
            [], Literal["active", "canceled", "stale"]
        ],
        request_deadline_monotonic: float | None = None,
    ) -> IntentPlanWaitResult:
        self._validate_generation(lease_generation)
        if not callable(cancellation_fence):
            raise ValueError("invalid intent cache cancellation fence")
        try:
            fence_result = self._read_fence(cancellation_fence)
        except Exception:
            return IntentPlanWaitResult(
                status="unavailable",
                reason="cache_unavailable",
            )
        if fence_result != "active":
            return fence_result
        if not _ProcessFollowerSlots.acquire(self._max_follower_waiters):
            return IntentPlanWaitResult(
                status="overflow",
                reason="waiter_capacity_exceeded",
            )
        try:
            started = self._monotonic()
            deadline = started + (self._follower_wait_ms / 1000)
            if request_deadline_monotonic is not None:
                if (
                    type(request_deadline_monotonic) not in {int, float}
                    or not math.isfinite(request_deadline_monotonic)
                ):
                    return IntentPlanWaitResult(
                        status="unavailable",
                        reason="cache_unavailable",
                    )
                deadline = min(deadline, float(request_deadline_monotonic))
            operation_timeout_seconds = self._operation_timeout_ms / 1000
            slice_seconds = min(0.1, max(0.01, operation_timeout_seconds))
            while True:
                fence_result = self._read_fence(cancellation_fence)
                if fence_result != "active":
                    return fence_result

                now = self._monotonic()
                if deadline - now < operation_timeout_seconds:
                    return IntentPlanWaitResult(status="timeout")
                loaded = self.load(key)

                fence_result = self._read_fence(cancellation_fence)
                if fence_result != "active":
                    return fence_result
                now = self._monotonic()
                if now >= deadline:
                    return IntentPlanWaitResult(status="timeout")
                if loaded.status == "hit":
                    return IntentPlanWaitResult(
                        status="hit",
                        plan=loaded.plan,
                    )
                if loaded.status == "unavailable":
                    return IntentPlanWaitResult(
                        status="unavailable",
                        reason="cache_unavailable",
                    )

                if deadline - now < operation_timeout_seconds:
                    return IntentPlanWaitResult(status="timeout")
                coordination = self._coordination_state(key, lease_generation)

                fence_result = self._read_fence(cancellation_fence)
                if fence_result != "active":
                    return fence_result
                now = self._monotonic()
                if now >= deadline:
                    return IntentPlanWaitResult(status="timeout")
                if coordination == "completed":
                    return IntentPlanWaitResult(
                        status="owner_completed_without_value"
                    )
                if coordination == "expired":
                    if deadline - now < operation_timeout_seconds:
                        return IntentPlanWaitResult(status="timeout")
                    recovered = self.load(key)
                    fence_result = self._read_fence(cancellation_fence)
                    if fence_result != "active":
                        return fence_result
                    now = self._monotonic()
                    if now >= deadline:
                        return IntentPlanWaitResult(status="timeout")
                    if recovered.status == "hit":
                        return IntentPlanWaitResult(
                            status="hit",
                            plan=recovered.plan,
                        )
                    if recovered.status == "unavailable":
                        return IntentPlanWaitResult(
                            status="unavailable",
                            reason="cache_unavailable",
                        )
                    return IntentPlanWaitResult(status="timeout")
                if coordination == "unavailable":
                    return IntentPlanWaitResult(
                        status="unavailable",
                        reason="cache_unavailable",
                    )

                self._sleep(min(slice_seconds, deadline - now))
        except Exception:
            return IntentPlanWaitResult(
                status="unavailable",
                reason="cache_unavailable",
            )
        finally:
            _ProcessFollowerSlots.release()

    @staticmethod
    def _read_fence(cancellation_fence) -> IntentPlanWaitResult | str:
        state = cancellation_fence()
        if state == "active":
            return "active"
        if state == "canceled":
            return IntentPlanWaitResult(status="canceled")
        if state == "stale":
            return IntentPlanWaitResult(status="stale")
        return IntentPlanWaitResult(
            status="unavailable",
            reason="cache_unavailable",
        )

    def _coordination_state(
        self,
        key: IntentCacheKey,
        lease_generation: int,
    ) -> Literal["waiting", "completed", "expired", "unavailable"]:
        base = self.redis_key(key)
        try:
            signal, lease = self._redis.mget(
                f"{base}:completion:{lease_generation}",
                f"{base}:lease",
            )
        except Exception:
            return "unavailable"
        expected_generation = str(lease_generation).encode("ascii")
        if signal is not None:
            if signal == expected_generation:
                return "completed"
            return "unavailable"
        if lease is None:
            return "expired"
        if not isinstance(lease, bytes):
            return "unavailable"
        try:
            observed_generation, owner_token = lease.decode("ascii").split(":", 1)
        except (UnicodeDecodeError, ValueError):
            return "unavailable"
        if (
            not observed_generation.isdecimal()
            or int(observed_generation) != lease_generation
            or _OWNER_TOKEN_PATTERN.fullmatch(owner_token) is None
        ):
            return "expired"
        return "waiting"

    @staticmethod
    def _parse_acquire_response(response) -> IntentPlanLeaseAcquireResult | None:
        if not isinstance(response, (list, tuple)) or len(response) != 2:
            return None
        try:
            status_raw, generation_raw = response
            status = (
                status_raw.decode("ascii")
                if isinstance(status_raw, bytes)
                else str(status_raw)
            )
            generation_text = (
                generation_raw.decode("ascii")
                if isinstance(generation_raw, bytes)
                else str(generation_raw)
            )
            generation = int(generation_text)
        except (UnicodeDecodeError, TypeError, ValueError, OverflowError):
            return None
        if generation <= 0:
            return None
        if status == "ACQUIRED":
            return IntentPlanLeaseAcquireResult("acquired", generation)
        if status == "CONTENDED":
            return IntentPlanLeaseAcquireResult("contended", generation)
        return None

    @staticmethod
    def _validate_owner(owner_token: str) -> None:
        if not isinstance(owner_token, str) or _OWNER_TOKEN_PATTERN.fullmatch(
            owner_token
        ) is None:
            raise ValueError("invalid intent cache lease owner")

    @classmethod
    def _lease_value(cls, owner_token: str, lease_generation: int) -> str:
        cls._validate_owner(owner_token)
        cls._validate_generation(lease_generation)
        return f"{lease_generation}:{owner_token}"

    @staticmethod
    def _validate_generation(lease_generation: int) -> None:
        if type(lease_generation) is not int or lease_generation <= 0:
            raise ValueError("invalid intent cache lease generation")


__all__ = [
    "IntentPlanCompletionResult",
    "IntentPlanLeaseAcquireResult",
    "IntentPlanLeaseReleaseResult",
    "IntentPlanWaitResult",
    "RedisIntentPlanCacheAdapter",
]
