from __future__ import annotations

import json
import secrets
import threading
import time
from collections.abc import Callable

import pytest

from apps.gateway.adapters.cache.agent_builder_intent_plan import (
    RedisIntentPlanCacheAdapter,
)
from apps.gateway.application.agent_builder.intent_cache import CachedIntentPlanV1
from apps.gateway.application.agent_builder.intent_cache import IntentPlanCodecError
from apps.gateway.application.agent_builder.intent_cache.contracts import (
    IntentPlanContractVersions,
    LogicalStepRef,
)


class InMemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.generations: dict[str, int] = {}
        self.calls: list[tuple[object, ...]] = []
        self.coordination_read = threading.Event()

    def get(self, key: str):
        self.calls.append(("get", key))
        return self.values.get(key)

    def mget(self, *keys: str):
        self.calls.append(("mget", *keys))
        self.coordination_read.set()
        return [self.values.get(key) for key in keys]

    def set(self, key: str, value: bytes, **kwargs):
        self.calls.append(("set", key, value, kwargs))
        if kwargs.get("nx") and key in self.values:
            return None
        self.values[key] = value
        return True

    def delete(self, *keys: str):
        self.calls.append(("delete", *keys))
        deleted = 0
        for key in keys:
            deleted += int(key in self.values)
            self.values.pop(key, None)
        return deleted

    def eval(self, script: str, key_count: int, *args: object):
        self.calls.append(("eval", script, key_count, *args))
        keys = tuple(str(value) for value in args[:key_count])
        argv = tuple(args[key_count:])
        if "intent-cache:acquire-v1" in script:
            lease_key, generation_key = keys
            existing = self.values.get(lease_key)
            if existing is not None:
                generation = int(existing.split(b":", 1)[0])
                return [b"CONTENDED", str(generation).encode("ascii")]
            generation = self.generations.get(generation_key, 0) + 1
            self.generations[generation_key] = generation
            self.values[lease_key] = (
                str(generation).encode("ascii") + b":" + str(argv[0]).encode("ascii")
            )
            return [b"ACQUIRED", str(generation).encode("ascii")]
        if "intent-cache:release-v1" in script:
            (lease_key,) = keys
            expected = str(argv[0]).encode("ascii")
            if self.values.get(lease_key) != expected:
                return 0
            del self.values[lease_key]
            return 1
        if "intent-cache:complete-v1" in script:
            lease_key, signal_key = keys
            expected = str(argv[0]).encode("ascii")
            if self.values.get(lease_key) != expected:
                return 0
            self.values[signal_key] = str(argv[1]).encode("ascii")
            del self.values[lease_key]
            return 1
        if "intent-cache:save-if-owner-v1" in script:
            lease_key, value_key = keys
            expected = str(argv[0]).encode("ascii")
            if self.values.get(lease_key) != expected:
                return 0
            self.values[value_key] = argv[1]
            return 1

        raise AssertionError("unexpected script")


class FailingRedis(InMemoryRedis):
    def __init__(self, operation: str) -> None:
        super().__init__()
        self.operation = operation

    def _fail(self, operation: str) -> None:
        if self.operation == operation:
            raise TimeoutError("sensitive redis endpoint detail")

    def get(self, key: str):
        self._fail("get")
        return super().get(key)

    def mget(self, *keys: str):
        self._fail("mget")
        return super().mget(*keys)

    def set(self, key: str, value: bytes, **kwargs):
        self._fail("set")
        return super().set(key, value, **kwargs)

    def delete(self, *keys: str):
        self._fail("delete")
        return super().delete(*keys)

    def eval(self, script: str, key_count: int, *args: object):
        self._fail("eval")
        return super().eval(script, key_count, *args)


def _plan() -> CachedIntentPlanV1:
    steps = (
        LogicalStepRef(capability="start_input", occurrence=1),
        LogicalStepRef(capability="answer", occurrence=1),
    )
    return CachedIntentPlanV1(
        schema_version=1,
        request_type="new_workflow",
        draft_mode="new_workflow",
        ordered_capabilities=("start_input", "answer"),
        logical_steps=steps,
        edit_placement=None,
        integration_actions=(),
        parameter_guidance_refs=(),
        knowledge_requirements=(),
        knowledge_placements=(),
        risk_flags=(),
        contract_versions=IntentPlanContractVersions(
            normalizer_version="normalizer-v1",
            cache_schema_version=1,
            planner_contract_version="planner-v1",
            catalog_version=3,
            canonical_text_registry_version="intent-text-v1",
            materializer_version="materializer-v1",
        ),
    )


def _adapter(
    redis_client,
    *,
    hmac_key: bytes | None = None,
    hmac_key_version: str = "hmac-v1",
    ttl_seconds: int = 30,
    max_payload_bytes: int = 4096,
    operation_timeout_ms: int = 100,
    lease_seconds: int = 5,
    follower_wait_ms: int = 250,
    max_follower_waiters: int = 8,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> RedisIntentPlanCacheAdapter:
    return RedisIntentPlanCacheAdapter(
        redis_client,
        hmac_key=hmac_key or secrets.token_bytes(32),
        hmac_key_version=hmac_key_version,
        ttl_seconds=ttl_seconds,
        max_payload_bytes=max_payload_bytes,
        operation_timeout_ms=operation_timeout_ms,
        lease_seconds=lease_seconds,
        follower_wait_ms=follower_wait_ms,
        max_follower_waiters=max_follower_waiters,
        monotonic=monotonic,
        sleep=sleep,
    )


def test_hmac_key_is_deterministic_scoped_and_plaintext_free() -> None:
    secret = secrets.token_bytes(32)
    adapter = _adapter(InMemoryRedis(), hmac_key=secret)

    first = adapter.build_key(b"canonical-material-v1")
    same = adapter.build_key(b"canonical-material-v1")
    changed = adapter.build_key(b"canonical-material-v2")
    rotated = _adapter(
        InMemoryRedis(),
        hmac_key=secret,
        hmac_key_version="hmac-v2",
    ).build_key(b"canonical-material-v1")

    assert first == same
    assert first.digest != changed.digest
    assert first.digest != rotated.digest
    assert adapter.redis_key(first) == (
        f"agent-builder:intent-plan:hmac-v1:{first.digest}"
    )
    assert "canonical-material" not in adapter.redis_key(first)
    assert secret.hex() not in repr(adapter)


def test_factory_applies_operation_timeout_to_connect_and_socket(
    monkeypatch,
) -> None:
    redis_client = InMemoryRedis()
    captured: dict[str, object] = {}

    def fake_from_url(redis_url: str, **kwargs):
        captured["url"] = redis_url
        captured["kwargs"] = kwargs
        return redis_client

    monkeypatch.setattr("redis.Redis.from_url", fake_from_url)

    adapter = RedisIntentPlanCacheAdapter.from_url(
        "redis://cache.internal:6379/0",
        hmac_key=secrets.token_bytes(32),
        hmac_key_version="hmac-v1",
        operation_timeout_ms=125,
    )

    assert adapter._redis is redis_client
    assert captured == {
        "url": "redis://cache.internal:6379/0",
        "kwargs": {
            "decode_responses": False,
            "socket_connect_timeout": 0.125,
            "socket_timeout": 0.125,
            "retry_on_timeout": False,
        },
    }

@pytest.mark.parametrize(
    "redis_url",
    [
        "redis://cache.internal/0?socket_timeout=10",
        "redis://cache.internal/0?db=not-an-int",
        "redis://cache.internal/not-a-db",
    ],
)
def test_factory_rejects_url_options_that_bypass_validated_settings(
    redis_url: str,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_from_url(raw_url: str, **_kwargs):
        calls.append(raw_url)
        return InMemoryRedis()

    monkeypatch.setattr("redis.Redis.from_url", fake_from_url)

    with pytest.raises(ValueError) as captured:
        RedisIntentPlanCacheAdapter.from_url(
            redis_url,
            hmac_key=secrets.token_bytes(32),
            hmac_key_version="hmac-v1",
        )

    assert calls == []
    assert redis_url not in str(captured.value)

def test_save_and_load_use_ttl_strict_codec_and_authenticated_envelope() -> None:
    redis_client = InMemoryRedis()
    secret = secrets.token_bytes(32)
    adapter = _adapter(redis_client, hmac_key=secret)
    key = adapter.build_key(b"canonical-material-v1")

    saved = adapter.save(key, _plan())
    loaded = adapter.load(key)

    assert saved.status == "stored"
    assert loaded.status == "hit"
    assert loaded.plan == _plan()
    set_call = next(call for call in redis_client.calls if call[0] == "set")
    assert set_call[3] == {"ex": 30}
    envelope = json.loads(set_call[2])
    assert set(envelope) == {"envelope_version", "payload", "payload_mac"}
    serialized_call = repr(set_call)
    assert secret.hex() not in serialized_call
    decoded_secret = secret.decode("utf-8", errors="ignore")
    if decoded_secret:
        assert decoded_secret not in serialized_call


def test_stale_lease_owner_cannot_overwrite_newer_generation_value() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client)
    key = adapter.build_key(b"canonical-material-v1")
    first_owner = "a" * 64
    second_owner = "b" * 64

    first = adapter.acquire_lease(key, first_owner)
    assert first.status == "acquired"
    assert first.generation == 1

    redis_client.values.pop(f"{adapter.redis_key(key)}:lease")
    second = adapter.acquire_lease(key, second_owner)
    assert second.status == "acquired"
    assert second.generation == 2
    assert (
        adapter.save_if_lease_owner(key, _plan(), second_owner, second.generation).status
        == "stored"
    )
    stored_by_current_owner = redis_client.values[adapter.redis_key(key)]

    stale = adapter.save_if_lease_owner(key, _plan(), first_owner, first.generation)

    assert stale.status == "unavailable"
    assert redis_client.values[adapter.redis_key(key)] == stored_by_current_owner


def test_envelope_is_bound_to_the_final_cache_key() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client)
    source_key = adapter.build_key(b"source-material")
    destination_key = adapter.build_key(b"destination-material")
    adapter.save(source_key, _plan())
    redis_client.values[adapter.redis_key(destination_key)] = redis_client.values[
        adapter.redis_key(source_key)
    ]

    result = adapter.load(destination_key)

    assert result.status == "invalid"
    assert result.reason == "invalid_cached_plan"
    assert adapter.redis_key(destination_key) not in redis_client.values


def test_rotated_adapter_does_not_read_or_write_an_old_version_key() -> None:
    redis_client = InMemoryRedis()
    secret = secrets.token_bytes(32)
    old_adapter = _adapter(
        redis_client,
        hmac_key=secret,
        hmac_key_version="hmac-v1",
    )
    new_adapter = _adapter(
        redis_client,
        hmac_key=secret,
        hmac_key_version="hmac-v2",
    )
    old_key = old_adapter.build_key(b"canonical-material")

    loaded = new_adapter.load(old_key)
    saved = new_adapter.save(old_key, _plan())

    assert loaded.status == "invalid"
    assert saved.status == "unavailable"
    assert redis_client.calls == []


@pytest.mark.parametrize("mutation", ["payload", "mac", "version"])
def test_corrupt_or_version_mismatched_envelope_is_an_invalid_miss(
    mutation: str,
) -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client)
    key = adapter.build_key(b"canonical-material")
    adapter.save(key, _plan())
    redis_key = adapter.redis_key(key)
    envelope = json.loads(redis_client.values[redis_key])
    if mutation == "payload":
        envelope["payload"] = envelope["payload"][:-1] + "A"
    elif mutation == "mac":
        envelope["payload_mac"] = "0" * 64
    else:
        envelope["envelope_version"] = 2
    redis_client.values[redis_key] = json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    result = adapter.load(key)

    assert result.status == "invalid"
    assert redis_key not in redis_client.values


def test_oversized_or_noncanonical_cached_value_is_deleted_as_invalid() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client, max_payload_bytes=4096)
    key = adapter.build_key(b"canonical-material")
    redis_key = adapter.redis_key(key)
    redis_client.values[redis_key] = b"x" * 100_000

    result = adapter.load(key)

    assert result.status == "invalid"
    assert redis_key not in redis_client.values


def test_noncanonical_envelope_encoding_is_deleted_as_invalid() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client)
    key = adapter.build_key(b"canonical-material")
    adapter.save(key, _plan())
    redis_key = adapter.redis_key(key)
    envelope = json.loads(redis_client.values[redis_key])
    redis_client.values[redis_key] = json.dumps(
        envelope,
        sort_keys=False,
        indent=1,
    ).encode("ascii")

    result = adapter.load(key)

    assert result.status == "invalid"
    assert redis_key not in redis_client.values


@pytest.mark.parametrize("operation", ["get", "set"])
def test_redis_timeout_or_unavailability_maps_to_typed_fail_open_result(
    operation: str,
) -> None:
    adapter = _adapter(FailingRedis(operation))
    key = adapter.build_key(b"canonical-material")

    result = adapter.load(key) if operation == "get" else adapter.save(key, _plan())

    assert result.status == "unavailable"
    assert result.reason == "cache_unavailable"


def test_put_codec_failure_is_fail_open(monkeypatch) -> None:
    adapter = _adapter(InMemoryRedis())
    key = adapter.build_key(b"canonical-material")
    monkeypatch.setattr(
        type(adapter._codec),
        "encode",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            IntentPlanCodecError("payload_too_large", "payload_size")
        ),
    )

    result = adapter.save(key, _plan())

    assert result.status == "unavailable"
    assert result.reason == "cache_unavailable"


def test_unexpected_decode_failure_is_fail_open_and_discards_the_value(
    monkeypatch,
) -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client)
    key = adapter.build_key(b"canonical-material")
    adapter.save(key, _plan())
    redis_key = adapter.redis_key(key)
    monkeypatch.setattr(
        type(adapter._codec),
        "decode",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("sensitive decoder detail")
        ),
    )

    result = adapter.load(key)

    assert result.status == "invalid"
    assert result.reason == "invalid_cached_plan"
    assert redis_key not in redis_client.values


def test_generation_fenced_lease_rejects_wrong_owner_and_stale_completion() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client)
    key = adapter.build_key(b"canonical-material")
    owner = adapter.new_owner_token()

    acquired = adapter.acquire_lease(key, owner)
    contended = adapter.acquire_lease(key, adapter.new_owner_token())
    wrong_release = adapter.release_lease(
        key,
        adapter.new_owner_token(),
        acquired.generation,
    )
    stale_completion = adapter.complete_without_value(
        key,
        owner,
        acquired.generation + 1,
    )
    completion = adapter.complete_without_value(
        key,
        owner,
        acquired.generation,
    )

    assert acquired.status == "acquired"
    assert acquired.generation == 1
    assert contended.status == "contended"
    assert contended.generation == 1
    assert wrong_release.status == "ignored"
    assert stale_completion.status == "ignored"
    assert completion.status == "signaled_and_released"


def test_missing_lease_allows_follower_recovery_without_waiting() -> None:
    redis_client = InMemoryRedis()
    sleeps: list[float] = []
    adapter = _adapter(redis_client, sleep=sleeps.append)
    key = adapter.build_key(b"canonical-material")
    lease = adapter.acquire_lease(key, adapter.new_owner_token())
    redis_client.values.pop(f"{adapter.redis_key(key)}:lease")

    result = adapter.wait_for_value(
        key,
        lease.generation,
        cancellation_fence=lambda: "active",
    )

    assert result.status == "timeout"
    assert sleeps == []


def test_expired_follower_deadline_skips_redis_io() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(
        redis_client,
        follower_wait_ms=0,
        monotonic=lambda: 10.0,
    )
    key = adapter.build_key(b"canonical-material")
    redis_client.calls.clear()

    result = adapter.wait_for_value(
        key,
        1,
        cancellation_fence=lambda: "active",
        request_deadline_monotonic=10.0,
    )

    assert result.status == "timeout"
    assert redis_client.calls == []


@pytest.mark.parametrize(
    "invalid_deadline",
    [True, "10.0", float("nan"), float("inf")],
)
def test_invalid_follower_deadline_is_fail_open_without_redis_io(
    invalid_deadline,
) -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client, monotonic=lambda: 10.0)
    key = adapter.build_key(b"canonical-material")
    redis_client.calls.clear()

    result = adapter.wait_for_value(
        key,
        1,
        cancellation_fence=lambda: "active",
        request_deadline_monotonic=invalid_deadline,
    )

    assert result.status == "unavailable"
    assert result.reason == "cache_unavailable"
    assert redis_client.calls == []

def test_owner_value_arrival_wakes_the_follower_with_a_hit() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client, follower_wait_ms=1000)
    key = adapter.build_key(b"canonical-material")
    owner = adapter.new_owner_token()
    lease = adapter.acquire_lease(key, owner)
    holder: list[object] = []

    thread = threading.Thread(
        target=lambda: holder.append(
            adapter.wait_for_value(
                key,
                lease.generation,
                cancellation_fence=lambda: "active",
            )
        )
    )
    thread.start()
    assert redis_client.coordination_read.wait(timeout=1)

    assert adapter.save(key, _plan()).status == "stored"
    thread.join(timeout=1)
    adapter.release_lease(key, owner, lease.generation)

    assert not thread.is_alive()
    assert holder and holder[0].status == "hit"
    assert holder[0].plan == _plan()


def test_follower_reloads_value_if_owner_saves_and_releases_between_reads() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client, follower_wait_ms=1000)
    key = adapter.build_key(b"canonical-material")
    owner = adapter.new_owner_token()
    lease = adapter.acquire_lease(key, owner)
    original_mget = redis_client.mget

    def owner_completes_after_first_load(*keys: str):
        assert adapter.save(key, _plan()).status == "stored"
        assert adapter.release_lease(key, owner, lease.generation).status == "released"
        return original_mget(*keys)

    redis_client.mget = owner_completes_after_first_load

    result = adapter.wait_for_value(
        key,
        lease.generation,
        cancellation_fence=lambda: "active",
    )

    assert result.status == "hit"
    assert result.plan == _plan()


def test_post_release_value_reload_loses_to_cancellation_fence() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client, follower_wait_ms=1000)
    key = adapter.build_key(b"canonical-material")
    owner = adapter.new_owner_token()
    lease = adapter.acquire_lease(key, owner)
    original_mget = redis_client.mget

    def owner_completes_after_first_load(*keys: str):
        assert adapter.save(key, _plan()).status == "stored"
        assert adapter.release_lease(key, owner, lease.generation).status == "released"
        return original_mget(*keys)

    redis_client.mget = owner_completes_after_first_load
    states = iter(("active", "active", "active", "active", "canceled"))

    result = adapter.wait_for_value(
        key,
        lease.generation,
        cancellation_fence=lambda: next(states),
    )

    assert result.status == "canceled"
    assert result.plan is None


def test_follower_wait_uses_shorter_request_deadline_in_bounded_slices() -> None:
    redis_client = InMemoryRedis()
    now = [10.0]
    sleeps: list[float] = []

    def monotonic() -> float:
        return now[0]

    def sleep(duration: float) -> None:
        sleeps.append(duration)
        now[0] += duration

    adapter = _adapter(
        redis_client,
        follower_wait_ms=60_000,
        operation_timeout_ms=10,
        monotonic=monotonic,
        sleep=sleep,
    )
    key = adapter.build_key(b"canonical-material")
    lease = adapter.acquire_lease(key, adapter.new_owner_token())

    result = adapter.wait_for_value(
        key,
        lease.generation,
        cancellation_fence=lambda: "active",
        request_deadline_monotonic=10.035,
    )

    assert result.status == "timeout"
    assert 0 < sum(sleeps) <= 0.035
    assert sleeps and all(duration <= 0.01 for duration in sleeps)

def test_follower_observes_only_its_generation_no_value_signal() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client)
    key = adapter.build_key(b"canonical-material")
    first_owner = adapter.new_owner_token()
    first = adapter.acquire_lease(key, first_owner)
    adapter.complete_without_value(key, first_owner, first.generation)
    second_owner = adapter.new_owner_token()
    second = adapter.acquire_lease(key, second_owner)

    result = adapter.wait_for_value(
        key,
        second.generation,
        cancellation_fence=lambda: "active",
        request_deadline_monotonic=time.monotonic(),
    )

    assert second.generation > first.generation
    assert result.status == "timeout"


def test_no_value_signal_loses_to_cancellation_fence() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client)
    key = adapter.build_key(b"canonical-material")
    owner = adapter.new_owner_token()
    lease = adapter.acquire_lease(key, owner)
    adapter.complete_without_value(key, owner, lease.generation)
    states = iter(("active", "active", "active", "canceled"))

    result = adapter.wait_for_value(
        key,
        lease.generation,
        cancellation_fence=lambda: next(states),
    )

    assert result.status == "canceled"
    assert any(call[0] == "mget" for call in redis_client.calls)


def test_value_arrival_loses_to_cancellation_fence() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client)
    key = adapter.build_key(b"canonical-material")
    owner = adapter.new_owner_token()
    lease = adapter.acquire_lease(key, owner)
    adapter.save(key, _plan())
    states = iter(("active", "active", "canceled"))

    result = adapter.wait_for_value(
        key,
        lease.generation,
        cancellation_fence=lambda: next(states),
    )

    assert result.status == "canceled"
    assert result.plan is None


def test_default_process_cap_admits_eight_followers_and_rejects_the_ninth() -> None:
    redis_client = InMemoryRedis()
    original_mget = redis_client.mget
    all_waiting = threading.Barrier(9)
    release_waiters = threading.Event()
    fence_state = ["active"]

    def blocking_mget(*keys: str):
        all_waiting.wait(timeout=2)
        if not release_waiters.wait(timeout=2):
            raise TimeoutError("test waiter release timed out")
        return original_mget(*keys)

    redis_client.mget = blocking_mget
    adapter = _adapter(redis_client, follower_wait_ms=1000)
    leases = []
    for index in range(9):
        key = adapter.build_key(f"material-{index}".encode("ascii"))
        lease = adapter.acquire_lease(key, adapter.new_owner_token())
        leases.append((key, lease.generation))

    results: list[object] = []
    threads = [
        threading.Thread(
            target=lambda key=key, generation=generation: results.append(
                adapter.wait_for_value(
                    key,
                    generation,
                    cancellation_fence=lambda: fence_state[0],
                )
            )
        )
        for key, generation in leases[:8]
    ]
    try:
        for thread in threads:
            thread.start()
        all_waiting.wait(timeout=2)

        overflow = adapter.wait_for_value(
            leases[8][0],
            leases[8][1],
            cancellation_fence=lambda: "active",
        )
    finally:
        fence_state[0] = "canceled"
        release_waiters.set()
        for thread in threads:
            thread.join(timeout=2)

    assert overflow.status == "overflow"
    assert overflow.reason == "waiter_capacity_exceeded"
    assert len(results) == 8
    assert all(result.status == "canceled" for result in results)
    assert all(not thread.is_alive() for thread in threads)

def test_follower_slots_are_process_wide_non_blocking_and_always_released() -> None:
    redis_client = InMemoryRedis()
    first_adapter = _adapter(
        redis_client,
        follower_wait_ms=1000,
        max_follower_waiters=1,
    )
    second_adapter = _adapter(
        redis_client,
        follower_wait_ms=1000,
        max_follower_waiters=1,
    )
    first_key = first_adapter.build_key(b"first-material")
    second_key = second_adapter.build_key(b"second-material")
    first_owner = first_adapter.new_owner_token()
    second_owner = second_adapter.new_owner_token()
    first_lease = first_adapter.acquire_lease(first_key, first_owner)
    second_lease = second_adapter.acquire_lease(second_key, second_owner)
    holder: list[object] = []

    thread = threading.Thread(
        target=lambda: holder.append(
            first_adapter.wait_for_value(
                first_key,
                first_lease.generation,
                cancellation_fence=lambda: "active",
            )
        )
    )
    thread.start()
    assert redis_client.coordination_read.wait(timeout=1)

    canceled = second_adapter.wait_for_value(
        second_key,
        second_lease.generation,
        cancellation_fence=lambda: "canceled",
    )
    overflow = second_adapter.wait_for_value(
        second_key,
        second_lease.generation,
        cancellation_fence=lambda: "active",
    )
    first_adapter.complete_without_value(
        first_key,
        first_owner,
        first_lease.generation,
    )
    thread.join(timeout=1)

    assert canceled.status == "canceled"
    assert overflow.status == "overflow"
    assert overflow.reason == "waiter_capacity_exceeded"
    assert holder and holder[0].status == "owner_completed_without_value"

    after_release = second_adapter.wait_for_value(
        second_key,
        second_lease.generation,
        cancellation_fence=lambda: "canceled",
    )
    assert after_release.status == "canceled"


def test_redis_error_during_wait_releases_the_process_slot() -> None:
    redis_client = FailingRedis("mget")
    adapter = _adapter(
        redis_client,
        max_follower_waiters=1,
    )
    key = adapter.build_key(b"canonical-material")

    failed = adapter.wait_for_value(
        key,
        1,
        cancellation_fence=lambda: "active",
    )
    after_failure = adapter.wait_for_value(
        key,
        1,
        cancellation_fence=lambda: "canceled",
    )

    assert failed.status == "unavailable"
    assert after_failure.status == "canceled"

def test_adapter_never_uses_broad_redis_commands() -> None:
    redis_client = InMemoryRedis()
    adapter = _adapter(redis_client)
    key = adapter.build_key(b"canonical-material")
    adapter.load(key)
    adapter.save(key, _plan())
    owner = adapter.new_owner_token()
    lease = adapter.acquire_lease(key, owner)
    adapter.release_lease(key, owner, lease.generation)

    command_names = {str(call[0]).lower() for call in redis_client.calls}
    assert command_names.isdisjoint({"keys", "scan", "flushdb", "flushall"})


@pytest.mark.parametrize(
    "override",
    [
        {"hmac_key": b"short"},
        {"hmac_key_version": "INVALID"},
        {"ttl_seconds": 29},
        {"ttl_seconds": 3601},
        {"max_payload_bytes": 4095},
        {"max_payload_bytes": 65537},
        {"operation_timeout_ms": 9},
        {"operation_timeout_ms": 501},
        {"lease_seconds": 4},
        {"lease_seconds": 301},
        {"follower_wait_ms": -1},
        {"follower_wait_ms": 60001},
        {"max_follower_waiters": 0},
        {"max_follower_waiters": 65},
    ],
)
def test_adapter_rejects_invalid_bounded_configuration(override) -> None:
    arguments = {
        "redis_client": InMemoryRedis(),
        "hmac_key": secrets.token_bytes(32),
        "hmac_key_version": "hmac-v1",
        "ttl_seconds": 30,
        "max_payload_bytes": 4096,
        "operation_timeout_ms": 100,
        "lease_seconds": 5,
        "follower_wait_ms": 250,
        "max_follower_waiters": 8,
    }
    arguments.update(override)

    with pytest.raises(ValueError) as captured:
        RedisIntentPlanCacheAdapter(**arguments)

    rendered = str(captured.value) + repr(captured.value)
    assert "short" not in rendered

def test_adapter_close_releases_an_owned_redis_client_once() -> None:
    class ClosingRedis(InMemoryRedis):
        def __init__(self) -> None:
            super().__init__()
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    redis_client = ClosingRedis()
    adapter = _adapter(redis_client)

    adapter.close()
    adapter.close()

    assert redis_client.close_calls == 1
