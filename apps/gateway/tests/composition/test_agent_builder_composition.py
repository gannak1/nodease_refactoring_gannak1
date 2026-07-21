import uuid
from types import SimpleNamespace

from apps.gateway.adapters.db.knowledge_recommendation import (
    PostgresParentRecommendationAdapter,
)
from apps.gateway.composition.agent_builder import AgentBuilderComposition
from apps.gateway.services.agent_builder.intent_usage_service import (
    AgentBuilderIntentUsageService,
)
from apps.gateway.services.knowledge_recommendation_credentials import (
    RecommendationEmbeddingCredentialResolver,
)
from apps.shared.db.session import SessionLocal


def test_agent_builder_composition_wires_durable_intent_and_recommendation_ports(
    monkeypatch,
):
    monkeypatch.setattr(
        PostgresParentRecommendationAdapter,
        "_default_session_factory",
        staticmethod(lambda _caller_db: lambda: SimpleNamespace()),
    )
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
    port = service.knowledge_recommendation_retrieval_port
    assert isinstance(port, PostgresParentRecommendationAdapter)
    assert port._caller_db is composition.db  # noqa: SLF001
    resolver = port._embedding_resolver  # noqa: SLF001
    assert isinstance(resolver, RecommendationEmbeddingCredentialResolver)
    assert resolver.session_factory is SessionLocal


def test_knowledge_selection_stale_refresh_bridge_is_metadata_only(monkeypatch):
    semantic_port_calls = 0

    def fail_if_semantic_port_is_built(_composition):
        nonlocal semantic_port_calls
        semantic_port_calls += 1
        raise AssertionError("stale refresh must not build the semantic port")

    monkeypatch.setattr(
        AgentBuilderComposition,
        "_knowledge_recommendation_retrieval_port",
        fail_if_semantic_port_is_built,
    )
    composition = AgentBuilderComposition(
        db=SimpleNamespace(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    selection = composition.knowledge_selection()
    bridge = selection.knowledge_selection_refresher.__self__

    assert semantic_port_calls == 0
    assert bridge.knowledge_recommendation_retrieval_port is None
