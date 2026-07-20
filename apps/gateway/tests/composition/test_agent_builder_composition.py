import uuid
from types import SimpleNamespace

from apps.gateway.application.agent_builder.intent_cache import (
    DisabledIntentPlanCacheBoundary,
)
from apps.gateway.composition.agent_builder import AgentBuilderComposition
from apps.gateway.services.agent_builder.intent_usage_service import (
    AgentBuilderIntentUsageService,
)


def test_agent_builder_composition_wires_durable_intent_usage_recorder():
    composition = AgentBuilderComposition(
        db=SimpleNamespace(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    service = composition.orchestration(
        intent_credential_id=uuid.uuid4(),
        intent_model_id=uuid.uuid4(),
    )

    assert isinstance(
        service.intent_extractor.usage_recorder,
        AgentBuilderIntentUsageService,
    )


def test_agent_builder_composition_wires_disabled_intent_plan_cache(monkeypatch):
    composition = AgentBuilderComposition(
        db=SimpleNamespace(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    boundary = DisabledIntentPlanCacheBoundary()
    calls = []

    def fake_factory(self):
        calls.append(self)
        return boundary

    monkeypatch.setattr(AgentBuilderComposition, "intent_plan_cache", fake_factory)

    service = composition.orchestration()

    assert calls == [composition]
    assert service.intent_plan_cache is boundary


def test_agent_builder_cache_factory_has_no_request_scope_dependencies():
    composition = AgentBuilderComposition(
        db=SimpleNamespace(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    boundary = composition.intent_plan_cache()

    assert isinstance(boundary, DisabledIntentPlanCacheBoundary)
    assert not hasattr(boundary, "db")
    assert not hasattr(boundary, "user")
    assert not hasattr(boundary, "organization_id")
