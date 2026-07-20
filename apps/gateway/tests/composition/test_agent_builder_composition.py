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
