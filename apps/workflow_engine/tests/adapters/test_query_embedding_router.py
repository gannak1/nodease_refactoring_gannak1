from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.workflow_engine.adapters.query_embedding import (
    QueryEmbeddingExecutionRuntimeRouter,
)
from apps.workflow_engine.adapters.query_embedding_legacy import (
    LegacyQueryEmbeddingAdapter,
)
from apps.workflow_engine.application.query_embedding_execution import (
    QueryEmbeddingAttribution,
    QueryEmbeddingConfigurationError,
    QueryEmbeddingEgressScope,
    QueryEmbeddingModelBinding,
    QueryEmbeddingPlan,
    QueryEmbeddingPreflight,
    QueryEmbeddingProviderResult,
    QueryEmbeddingOperationRequest,
    QueryEmbeddingRequest,
)


class _Strategy:
    def __init__(self, name: str) -> None:
        self.name = name
        self.preflight_calls = []
        self.resolve_calls = []

    def preflight(self, request):
        self.preflight_calls.append(request)
        return QueryEmbeddingPlan(
            capability_required=self.name == "capability",
            state=self.name,
        )

    def resolve(self, request):
        self.resolve_calls.append(request)
        return self.name


def _preflight(*, required):
    return QueryEmbeddingPreflight(
        node_id="llm-1",
        organization_id=uuid.uuid4(),
        legacy_credential_user_id=uuid.uuid4(),
        execution_context={"provider_execution_capability_required": required},
        runtime_control=None,
    )


def test_query_embedding_router_uses_only_server_boolean_strategy():
    legacy = _Strategy("legacy")
    capability = _Strategy("capability")
    router = QueryEmbeddingExecutionRuntimeRouter(
        legacy_strategy=legacy,
        capability_strategy=capability,
    )

    legacy_plan = router.preflight(_preflight(required=False))
    capability_plan = router.preflight(_preflight(required=True))

    request = QueryEmbeddingRequest(
        plan=capability_plan,
        model_binding=QueryEmbeddingModelBinding(
            model_id=uuid.uuid4(),
            provider_id=uuid.uuid4(),
            model_identifier="embed-safe",
        ),
        query="query",
    )
    assert router.resolve(request) == "capability"
    assert len(legacy.preflight_calls) == 1
    assert len(capability.preflight_calls) == 1
    assert capability.resolve_calls[0].plan.state == "capability"
    assert legacy_plan.capability_required is False


@pytest.mark.parametrize("malformed", [None, 0, 1, "true", []])
def test_query_embedding_router_rejects_malformed_activation(malformed):
    router = QueryEmbeddingExecutionRuntimeRouter(
        legacy_strategy=_Strategy("legacy"),
        capability_strategy=_Strategy("capability"),
    )

    with pytest.raises(QueryEmbeddingConfigurationError):
        router.preflight(_preflight(required=malformed))


def test_legacy_query_embedding_adapter_hides_client_behind_single_use_lease(
    monkeypatch,
):
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    model_binding = QueryEmbeddingModelBinding(
        model_id=uuid.uuid4(),
        provider_id=uuid.uuid4(),
        model_identifier="embed-safe",
    )
    calls = []

    class _Client:
        def embed_sync(self, query):
            calls.append(query)
            return [0.1, 0.9]

    monkeypatch.setattr(
        "apps.workflow_engine.adapters.query_embedding_legacy."
        "LLMService.get_client_for_model_binding",
        lambda db, principal, binding, *, organization_id: (
            calls.append((db, principal, binding, organization_id)) or _Client()
        ),
    )
    runtime = LegacyQueryEmbeddingAdapter()
    plan = runtime.preflight(
        QueryEmbeddingPreflight(
            node_id="llm-1",
            organization_id=organization_id,
            legacy_credential_user_id=user_id,
            execution_context={"provider_execution_capability_required": False},
            runtime_control=None,
        )
    )
    session = object()
    lease = runtime.resolve(
        QueryEmbeddingRequest(
            plan=plan,
            model_binding=model_binding,
            query="query",
            shared_session=session,
        )
    )

    result = lease.invoke()

    assert result.vector == (0.1, 0.9)
    assert calls[0][0] is session
    assert calls[0][1] == user_id
    assert calls[0][2].model_id == model_binding.model_id
    assert calls[1] == "query"
    with pytest.raises(QueryEmbeddingConfigurationError):
        lease.invoke()


def test_legacy_query_embedding_redacts_provider_failure_from_exception_chain(
    monkeypatch,
):
    class _Client:
        def embed_sync(self, _query):
            raise RuntimeError("provider raw payload must not escape")

    monkeypatch.setattr(
        "apps.workflow_engine.adapters.query_embedding_legacy."
        "LLMService.get_client_for_model_binding",
        lambda *_args, **_kwargs: _Client(),
    )
    runtime = LegacyQueryEmbeddingAdapter()
    organization_id = uuid.uuid4()
    plan = runtime.preflight(
        QueryEmbeddingPreflight(
            node_id="llm-1",
            organization_id=organization_id,
            legacy_credential_user_id=uuid.uuid4(),
            execution_context={"provider_execution_capability_required": False},
            runtime_control=None,
        )
    )
    lease = runtime.resolve(
        QueryEmbeddingRequest(
            plan=plan,
            model_binding=QueryEmbeddingModelBinding(
                model_id=uuid.uuid4(),
                provider_id=uuid.uuid4(),
                model_identifier="embed-safe",
            ),
            query="query",
            shared_session=object(),
        )
    )

    with pytest.raises(QueryEmbeddingConfigurationError) as exc_info:
        lease.invoke()

    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), -float("inf")])
def test_query_embedding_result_rejects_non_finite_vector_values(invalid_value):
    with pytest.raises(QueryEmbeddingConfigurationError):
        QueryEmbeddingProviderResult(vector=(0.1, invalid_value), input_tokens=1)


def test_query_embedding_result_repr_redacts_raw_vector():
    result = QueryEmbeddingProviderResult(
        vector=(0.123456789, 0.987654321),
        input_tokens=2,
    )

    assert "0.123456789" not in repr(result)
    assert "0.987654321" not in repr(result)


def test_query_embedding_control_repr_redacts_credential_and_destination():
    credential_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    attribution = QueryEmbeddingAttribution(
        organization_id=uuid.uuid4(),
        model_id=uuid.uuid4(),
        provider_id=uuid.uuid4(),
        credential_id=credential_id,
        credential_principal_user_id=principal_id,
        provider_attempt_id=uuid.uuid4(),
        capability_id=uuid.uuid4(),
        capability_revision=1,
        pricing_revision="a" * 64,
        egress_revision="b" * 64,
        input_price_per_1k=Decimal("0.001"),
    )
    operation = QueryEmbeddingOperationRequest(
        attribution=attribution,
        provider_attempt_id=attribution.provider_attempt_id,
        requested_input_tokens=1,
        cost_cap_microusd=1,
    )
    scope = QueryEmbeddingEgressScope(
        organization_id=attribution.organization_id,
        provider_id=attribution.provider_id,
        model_id=attribution.model_id,
        capability_id=attribution.capability_id,
        capability_revision=1,
        egress_revision="b" * 64,
        provider_name="provider",
        provider_base_url="https://private-provider.example.test/v1",
    )

    diagnostic = f"{attribution!r} {operation!r} {scope!r}"
    assert str(credential_id) not in diagnostic
    assert str(principal_id) not in diagnostic
    assert "private-provider.example.test" not in diagnostic
