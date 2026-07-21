from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI


class _Session:
    def close(self) -> None:
        return None


class _Engine:
    @contextmanager
    def begin(self):
        yield SimpleNamespace(execute=lambda _statement: None)


@pytest.mark.asyncio
async def test_lifespan_initializes_and_shuts_down_cache_runtime_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.gateway import lifespan as lifespan_module
    from apps.gateway.api import deps as deps_module
    from apps.gateway.composition import agent_builder_cache as cache_module
    from apps.gateway.composition import connectors as connectors_module
    from apps.gateway.composition import deployment as deployment_module
    from apps.gateway.composition import memory as memory_module
    from apps.gateway.services import llm_service as llm_service_module
    from apps.gateway.services import scheduler_service as scheduler_module
    from apps.shared.audit import listeners as audit_listeners_module
    from apps.shared.db import session as session_module

    events: list[str] = []
    scheduler = SimpleNamespace(shutdown=lambda: events.append("scheduler_shutdown"))

    monkeypatch.setattr(lifespan_module, "engine", _Engine())
    monkeypatch.setattr(lifespan_module, "inspect", lambda _engine: object())
    monkeypatch.setattr(lifespan_module, "text", lambda statement: statement)
    monkeypatch.setattr(lifespan_module, "schedule_dispatch_settings_from_environment", lambda _environment: object())
    monkeypatch.setattr(lifespan_module, "require_schedule_dispatch_migration_ready", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(lifespan_module, "required_schedule_dispatch_schema_exists", lambda _inspector: False)
    monkeypatch.setattr(lifespan_module, "require_mail_credential_keyring_ready", lambda: None)
    monkeypatch.setattr(lifespan_module, "require_llm_credential_keyring_ready", lambda: None)
    monkeypatch.setattr(lifespan_module, "seed_placeholder_user", lambda _db: None)
    monkeypatch.setattr(lifespan_module, "seed_default_llm_providers", lambda _db: None)
    monkeypatch.setattr(lifespan_module, "seed_default_llm_models", lambda _db: None)
    monkeypatch.setattr(session_module, "SessionLocal", _Session)
    monkeypatch.setattr(audit_listeners_module, "register_audit_listeners", lambda: None)
    monkeypatch.setattr(connectors_module, "require_connector_test_security_ready", lambda: None)
    monkeypatch.setattr(memory_module, "require_public_conversation_schema_ready", lambda _db: None)
    monkeypatch.setattr(llm_service_module.LLMService, "sync_system_prices", lambda _db: {"updated_models": 0})
    monkeypatch.setattr(deps_module, "get_deployment_runtime_policy", lambda: object())
    monkeypatch.setattr(deployment_module, "build_schedule_task_publisher", lambda: object())
    monkeypatch.setattr(deployment_module, "build_schedule_dispatch_dependencies", lambda: object())
    monkeypatch.setattr(deployment_module, "build_schedule_next_fire_calculator", lambda: object())
    monkeypatch.setattr(scheduler_module, "init_scheduler_service", lambda *_args, **_kwargs: events.append("scheduler_initialized"))
    monkeypatch.setattr(scheduler_module, "get_scheduler_service", lambda: scheduler)
    monkeypatch.setattr(cache_module, "initialize_agent_builder_intent_cache_application", lambda app: events.append("cache_initialized"))
    monkeypatch.setattr(cache_module, "shutdown_agent_builder_intent_cache_application", lambda app: events.append("cache_shutdown"))

    async def shutdown_connectors() -> None:
        events.append("connectors_shutdown")

    monkeypatch.setattr(connectors_module, "shutdown_connector_test_application", shutdown_connectors)

    async with lifespan_module.lifespan(FastAPI()):
        events.append("request_handling")

    assert events == [
        "scheduler_initialized",
        "cache_initialized",
        "request_handling",
        "cache_shutdown",
        "scheduler_shutdown",
        "connectors_shutdown",
    ]
