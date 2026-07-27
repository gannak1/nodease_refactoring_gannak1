from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.main import app
from apps.gateway.services.agent_builder.benchmark_diagnostics import (
    AgentBuilderBenchmarkDiagnostics,
)


def test_benchmark_diagnostic_is_localhost_and_owner_scoped(monkeypatch):
    request_id = uuid.uuid4()
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    AgentBuilderBenchmarkDiagnostics.clear()
    monkeypatch.setenv("AGENT_BUILDER_CACHE_BENCHMARK_DIAGNOSTICS_ENABLED", "true")
    AgentBuilderBenchmarkDiagnostics.record(
        request_id=request_id,
        user_id=user_id,
        organization_id=organization_id,
        outcome="hit",
        planning_latency_ms=17,
        provider_call_count=0,
        repair_call_count=0,
        terminal_status="success",
        validation_passed=True,
    )
    monkeypatch.setenv("AGENT_BUILDER_CACHE_BENCHMARK_DIAGNOSTICS_ENABLED", "true")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).get(
            f"/api/v1/agent-builder/benchmark/diagnostics/{request_id}",
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}
        AgentBuilderBenchmarkDiagnostics.clear()

    assert response.status_code == 200
    assert response.json() == {
        "cache_outcome": "hit",
        "planning_latency_ms": 17,
        "provider_call_count": 0,
        "repair_call_count": 0,
        "terminal_status": "success",
        "validation_passed": True,
    }


def test_benchmark_diagnostic_is_not_returned_for_another_organization(monkeypatch):
    request_id = uuid.uuid4()
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    AgentBuilderBenchmarkDiagnostics.clear()
    monkeypatch.setenv("AGENT_BUILDER_CACHE_BENCHMARK_DIAGNOSTICS_ENABLED", "true")
    AgentBuilderBenchmarkDiagnostics.record(
        request_id=request_id,
        user_id=user_id,
        organization_id=organization_id,
        outcome="miss",
        planning_latency_ms=41,
        provider_call_count=1,
        repair_call_count=0,
        terminal_status="success",
        validation_passed=True,
    )
    monkeypatch.setenv("AGENT_BUILDER_CACHE_BENCHMARK_DIAGNOSTICS_ENABLED", "true")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).get(
            f"/api/v1/agent-builder/benchmark/diagnostics/{request_id}",
            headers={"X-Organization-Id": str(uuid.uuid4())},
        )
    finally:
        app.dependency_overrides = {}
        AgentBuilderBenchmarkDiagnostics.clear()

    assert response.status_code == 404
