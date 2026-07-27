from __future__ import annotations

import uuid

import pytest

from apps.gateway.services.agent_builder.benchmark_diagnostics import (
    AgentBuilderBenchmarkDiagnostics,
)


@pytest.mark.parametrize("environment", ("production", "staging"))
def test_benchmark_diagnostics_never_activate_in_serving_environments(
    monkeypatch, environment: str
) -> None:
    request_id = uuid.uuid4()
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    AgentBuilderBenchmarkDiagnostics.clear()
    monkeypatch.setenv("AGENT_BUILDER_CACHE_BENCHMARK_DIAGNOSTICS_ENABLED", "true")
    monkeypatch.setenv("NODE_ENV", environment)

    AgentBuilderBenchmarkDiagnostics.record(
        request_id=request_id,
        user_id=user_id,
        organization_id=organization_id,
        outcome="hit",
        planning_latency_ms=1,
        provider_call_count=0,
        repair_call_count=0,
        terminal_status="success",
        validation_passed=True,
    )

    assert AgentBuilderBenchmarkDiagnostics.enabled() is False
    assert (
        AgentBuilderBenchmarkDiagnostics.get_for_scope(
            request_id=request_id,
            user_id=user_id,
            organization_id=organization_id,
        )
        is None
    )
