from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI

from apps.gateway.application.agent_builder.intent_cache import (
    DisabledIntentPlanCacheBoundary,
)


def _enabled_config() -> SimpleNamespace:
    return SimpleNamespace(
        enabled=True,
        disabled_reason=None,
        redis_url="redis://cache.internal:6379/0",
        hmac_key=b"x" * 32,
        hmac_key_version="hmac-v1",
        ttl_seconds=900,
        max_payload_bytes=32768,
        operation_timeout_ms=100,
        lease_seconds=240,
        follower_wait_ms=45000,
        max_follower_waiters=8,
    )


def test_runtime_reuses_one_adapter_for_multiple_request_compositions(monkeypatch):
    from apps.gateway.composition import agent_builder_cache as runtime_module

    app = FastAPI()
    created = []
    adapter = SimpleNamespace(close=lambda: None)
    config = _enabled_config()

    monkeypatch.setattr(
        type(runtime_module.settings),
        "agent_builder_intent_cache_config",
        lambda _settings: config,
    )
    monkeypatch.setattr(
        runtime_module.RedisIntentPlanCacheAdapter,
        "from_url",
        lambda *args, **kwargs: created.append((args, kwargs)) or adapter,
    )

    first = runtime_module.initialize_agent_builder_intent_cache_application(app)
    second = runtime_module.initialize_agent_builder_intent_cache_application(app)

    assert first is second
    assert first.cache is runtime_module.intent_plan_cache_for_app(app)
    assert len(created) == 1


def test_disabled_runtime_never_constructs_redis_adapter(monkeypatch):
    from apps.gateway.composition import agent_builder_cache as runtime_module

    app = FastAPI()
    calls = []
    disabled = _enabled_config()
    disabled.enabled = False
    disabled.disabled_reason = "feature_disabled"

    monkeypatch.setattr(
        type(runtime_module.settings),
        "agent_builder_intent_cache_config",
        lambda _settings: disabled,
    )
    monkeypatch.setattr(
        runtime_module.RedisIntentPlanCacheAdapter,
        "from_url",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    runtime = runtime_module.initialize_agent_builder_intent_cache_application(app)

    assert isinstance(runtime.cache, DisabledIntentPlanCacheBoundary)
    assert calls == []


def test_runtime_shutdown_closes_the_owned_adapter_once(monkeypatch):
    from apps.gateway.composition import agent_builder_cache as runtime_module

    app = FastAPI()
    close_calls = []
    adapter = SimpleNamespace(close=lambda: close_calls.append("closed"))

    monkeypatch.setattr(
        type(runtime_module.settings),
        "agent_builder_intent_cache_config",
        lambda _settings: _enabled_config(),
    )
    monkeypatch.setattr(
        runtime_module.RedisIntentPlanCacheAdapter,
        "from_url",
        lambda *args, **kwargs: adapter,
    )

    runtime_module.initialize_agent_builder_intent_cache_application(app)
    runtime_module.shutdown_agent_builder_intent_cache_application(app)
    runtime_module.shutdown_agent_builder_intent_cache_application(app)

    assert close_calls == ["closed"]
    assert isinstance(
        runtime_module.intent_plan_cache_for_app(app),
        DisabledIntentPlanCacheBoundary,
    )
import uuid

def test_request_composition_uses_the_shared_runtime_cache(monkeypatch):
    from apps.gateway.composition import agent_builder as composition_module
    from apps.gateway.composition import agent_builder_cache as runtime_module

    app = FastAPI()
    adapter = SimpleNamespace(close=lambda: None)
    config = _enabled_config()

    monkeypatch.setattr(
        type(runtime_module.settings),
        "agent_builder_intent_cache_config",
        lambda _settings: config,
    )
    monkeypatch.setattr(
        runtime_module.RedisIntentPlanCacheAdapter,
        "from_url",
        lambda *args, **kwargs: adapter,
    )
    monkeypatch.setattr(
        composition_module,
        "resolve_active_organization_id",
        lambda *_args: uuid.uuid4(),
    )

    runtime = runtime_module.initialize_agent_builder_intent_cache_application(app)
    request = SimpleNamespace(app=app)
    user = SimpleNamespace(id=uuid.uuid4())

    first = composition_module.compose_agent_builder(
        db=SimpleNamespace(),
        request=request,
        raw_organization_id=None,
        current_user=user,
    )
    second = composition_module.compose_agent_builder(
        db=SimpleNamespace(),
        request=request,
        raw_organization_id=None,
        current_user=user,
    )

    assert first.intent_plan_cache() is runtime.cache
    assert second.intent_plan_cache() is runtime.cache
