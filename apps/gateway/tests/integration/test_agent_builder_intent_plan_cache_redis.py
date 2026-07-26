from __future__ import annotations

import os
import secrets
import time
from urllib.parse import urlsplit

import pytest
import redis

from apps.gateway.adapters.cache.agent_builder_intent_plan import (
    RedisIntentPlanCacheAdapter,
)
from apps.gateway.application.agent_builder.intent_cache import CachedIntentPlanV1
from apps.gateway.application.agent_builder.intent_cache.contracts import (
    IntentPlanContractVersions,
    LogicalStepRef,
)


def _integration_redis_url() -> str:
    raw_url = os.getenv(
        "AGENT_BUILDER_INTENT_CACHE_INTEGRATION_REDIS_URL",
        "",
    ).strip()
    if not raw_url:
        pytest.skip("dedicated Agent Builder cache Redis URL is not configured")
    try:
        parsed = urlsplit(raw_url)
        _ = parsed.port
    except ValueError:
        parsed = None
    if (
        parsed is None
        or any(character.isspace() for character in raw_url)
        or parsed.scheme not in {"redis", "rediss"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.path != "/15"
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "Agent Builder cache integration requires local dedicated Redis DB 15"
        )
    return raw_url


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "redis://localhost/15?db=0",
        "redis://localhost//15",
        "redis://localhost:not-a-port/15",
        "redis://localhost/15#fragment",
    ],
)
def test_integration_url_requires_exact_dedicated_local_db(
    unsafe_url: str,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "AGENT_BUILDER_INTENT_CACHE_INTEGRATION_REDIS_URL",
        unsafe_url,
    )

    with pytest.raises(RuntimeError) as captured:
        _integration_redis_url()

    assert str(captured.value) == (
        "Agent Builder cache integration requires local dedicated Redis DB 15"
    )
    assert unsafe_url not in str(captured.value)

def _plan() -> CachedIntentPlanV1:
    return CachedIntentPlanV1(
        schema_version=1,
        request_type="new_workflow",
        draft_mode="new_workflow",
        ordered_capabilities=("start_input", "answer"),
        logical_steps=(
            LogicalStepRef(capability="start_input", occurrence=1),
            LogicalStepRef(capability="answer", occurrence=1),
        ),
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


def _adapter(redis_client) -> RedisIntentPlanCacheAdapter:
    return RedisIntentPlanCacheAdapter(
        redis_client,
        hmac_key=secrets.token_bytes(32),
        hmac_key_version=f"it-{secrets.token_hex(8)}",
        ttl_seconds=30,
        max_payload_bytes=4096,
        operation_timeout_ms=100,
        lease_seconds=5,
        follower_wait_ms=250,
        max_follower_waiters=8,
    )


def _owned_keys(adapter: RedisIntentPlanCacheAdapter, key, generations=()) -> tuple[str, ...]:
    base = adapter.redis_key(key)
    return (
        base,
        f"{base}:lease",
        f"{base}:generation",
        *(f"{base}:completion:{generation}" for generation in generations),
    )


def test_real_redis_fenced_save_rejects_expired_owner_without_overwrite() -> None:
    client = redis.Redis.from_url(
        _integration_redis_url(),
        decode_responses=False,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
    )
    client.ping()
    adapter = _adapter(client)
    key = adapter.build_key(b"integration-fenced-save")
    generations: list[int] = []
    try:
        first_owner = adapter.new_owner_token()
        first = adapter.acquire_lease(key, first_owner)
        assert first.status == "acquired"
        assert first.generation is not None
        generations.append(first.generation)

        client.delete(f"{adapter.redis_key(key)}:lease")
        second_owner = adapter.new_owner_token()
        second = adapter.acquire_lease(key, second_owner)
        assert second.status == "acquired"
        assert second.generation is not None
        assert second.generation > first.generation
        generations.append(second.generation)
        current_plan = _plan()
        stale_plan = current_plan.model_copy(
            update={"risk_flags": ("external_action_requested",)}
        )
        assert (
            adapter.save_if_lease_owner(
                key, current_plan, second_owner, second.generation
            ).status
            == "stored"
        )
        stored_by_current_owner = client.get(adapter.redis_key(key))

        stale = adapter.save_if_lease_owner(
            key, stale_plan, first_owner, first.generation
        )

        assert stale.status == "unavailable"
        assert client.get(adapter.redis_key(key)) == stored_by_current_owner
        assert adapter.load(key).plan == current_plan
    finally:
        client.delete(*_owned_keys(adapter, key, generations))
        client.close()

def test_real_redis_round_trip_ttl_key_binding_and_generation_fence() -> None:
    client = redis.Redis.from_url(
        _integration_redis_url(),
        decode_responses=False,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
    )
    client.ping()
    adapter = _adapter(client)
    source = adapter.build_key(b"integration-source")
    destination = adapter.build_key(b"integration-destination")
    generations: list[int] = []
    try:
        assert adapter.save(source, _plan()).status == "stored"
        assert adapter.load(source).plan == _plan()
        ttl = client.ttl(adapter.redis_key(source))
        assert 0 < ttl <= 30

        client.set(
            adapter.redis_key(destination),
            client.get(adapter.redis_key(source)),
            ex=30,
        )
        assert adapter.load(destination).status == "invalid"
        assert client.get(adapter.redis_key(destination)) is None

        first_owner = adapter.new_owner_token()
        first = adapter.acquire_lease(source, first_owner)
        assert first.status == "acquired"
        assert first.generation is not None
        generations.append(first.generation)
        assert adapter.release_lease(
            source,
            adapter.new_owner_token(),
            first.generation,
        ).status == "ignored"
        assert adapter.complete_without_value(
            source,
            first_owner,
            first.generation,
        ).status == "signaled_and_released"

        second_owner = adapter.new_owner_token()
        second = adapter.acquire_lease(source, second_owner)
        assert second.status == "acquired"
        assert second.generation is not None
        generations.append(second.generation)
        assert second.generation > first.generation
        client.delete(adapter.redis_key(source))
        wait = adapter.wait_for_value(
            source,
            second.generation,
            cancellation_fence=lambda: "active",
            request_deadline_monotonic=time.monotonic() + 0.25,
        )
        assert wait.status == "timeout"
        assert adapter.release_lease(
            source,
            second_owner,
            second.generation,
        ).status == "released"
    finally:
        client.delete(
            *_owned_keys(adapter, source, generations),
            *_owned_keys(adapter, destination),
        )
        client.close()
