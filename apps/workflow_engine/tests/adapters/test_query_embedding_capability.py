from __future__ import annotations

import uuid
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.shared.domain.provider_execution_capability import (
    CapabilityPurpose,
    RuntimePrincipal,
)
from apps.shared.domain.workflow_execution_identity import InvocationSegment
from apps.workflow_engine.adapters.query_embedding_capability import (
    CapabilityQueryEmbeddingAdapter,
)
from apps.workflow_engine.application.query_embedding_execution import (
    QueryEmbeddingConfigurationError,
    QueryEmbeddingModelBinding,
    QueryEmbeddingPreflight,
    QueryEmbeddingProviderResult,
    QueryEmbeddingRequest,
)
from apps.workflow_engine.domain.execution import NodeExecutionControl
from apps.workflow_engine.domain.external_effect import ExternalEffectContext


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.closes = 0

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closes += 1


class _Operation:
    def __init__(self, *, session: _Session, fail_start: bool = False) -> None:
        self.session = session
        self.fail_start = fail_start
        self.started = 0
        self.successes: list[int] = []
        self.unknown = 0

    def mark_provider_started(self) -> None:
        assert self.session.commits == 1
        assert self.session.closes == 1
        if self.fail_start:
            raise RuntimeError("ledger unavailable")
        self.started += 1

    def complete_success(self, *, input_tokens: int) -> None:
        self.successes.append(input_tokens)

    def complete_outcome_unknown(self) -> None:
        self.unknown += 1

    def complete_before_effect_failure(self) -> None:
        return None


class _Ledger:
    def __init__(self, *, session: _Session, fail_start: bool = False) -> None:
        self.session = session
        self.fail_start = fail_start
        self.requests = []
        self.operations: list[_Operation] = []

    def begin(self, request):
        self.requests.append(request)
        operation = _Operation(session=self.session, fail_start=self.fail_start)
        self.operations.append(operation)
        return operation


class _GuardedEgressLease:
    def __init__(self, *, operation: _Operation) -> None:
        self.operation = operation
        self.calls = 0

    def invoke(self, query: str) -> QueryEmbeddingProviderResult:
        assert self.operation.started == 1
        self.calls += 1
        return QueryEmbeddingProviderResult(
            vector=(0.25, 0.75),
            input_tokens=len(query.encode("utf-8")),
        )


class _Egress:
    def __init__(self, *, ledger: _Ledger) -> None:
        self.ledger = ledger
        self.scopes = []
        self.leases: list[_GuardedEgressLease] = []

    def authorize(self, *, scope, client):
        assert client == "provider-client"
        self.scopes.append(scope)
        lease = _GuardedEgressLease(operation=self.ledger.operations[-1])
        self.leases.append(lease)
        return lease


def _control(*, organization_id: uuid.UUID, workflow_id: uuid.UUID):
    execution_id = uuid.uuid4()
    return NodeExecutionControl(
        execution_id=execution_id,
        invocation_path_prefix=(InvocationSegment("root", "", "workflow"),),
        external_effect_context=ExternalEffectContext(
            organization_id=organization_id,
            app_id=uuid.uuid4(),
            workflow_id=workflow_id,
            execution_id=execution_id,
            node_invocation_id=uuid.uuid4(),
            node_id="llm-1",
        ),
        external_effect_enforced=True,
    )


def _context(*, organization_id: uuid.UUID, workflow_id: uuid.UUID) -> dict:
    return {
        "provider_execution_capability_required": True,
        "query_embedding_capability_limits": {
            "query_byte_cap": 2_048,
            "input_token_cap": 2_048,
            "cost_cap_microusd": 10_000,
        },
        "deployment_id": str(uuid.uuid4()),
        "workflow_version": 2,
        "organization_id": str(organization_id),
        "workflow_id": str(workflow_id),
        "execution_subject": {"type": "user", "id": str(uuid.uuid4())},
    }


def _runtime(*, provider_id: uuid.UUID, fail_start: bool = False):
    session = _Session()
    ledger = _Ledger(session=session, fail_start=fail_start)
    egress = _Egress(ledger=ledger)
    captured = {}
    capability = SimpleNamespace(id=uuid.uuid4(), revision=4)
    policy_principal_id = uuid.uuid4()

    class _CapabilityService:
        @staticmethod
        def issue_capability(_db, *, command):
            captured["issue"] = command
            return capability

        @staticmethod
        def admit_capability(_db, *, command):
            captured["admission"] = command
            return SimpleNamespace(
                credential=SimpleNamespace(id=uuid.uuid4()),
                provider=SimpleNamespace(
                    id=provider_id,
                    name="provider",
                    base_url="https://catalog.example.test/v1",
                ),
                model=SimpleNamespace(
                    id=command.policy_model_id,
                    provider_id=provider_id,
                    model_id_for_api_call="embed-safe",
                    type="embedding",
                    input_price_1k=Decimal("0.001"),
                    output_price_1k=Decimal("0"),
                ),
                capability=SimpleNamespace(
                    id=capability.id,
                    revision=capability.revision,
                    credential_principal=RuntimePrincipal.user(policy_principal_id),
                    pricing_revision="d" * 64,
                    egress_revision="e" * 64,
                ),
            )

    runtime = CapabilityQueryEmbeddingAdapter(
        session_factory=lambda: session,
        capability_service=_CapabilityService,
        credential_loader=lambda _credential: {"apiKey": "[REDACTED]"},
        client_factory=lambda **_kwargs: "provider-client",
        operation_ledger=ledger,
        egress_runtime=egress,
    )
    return runtime, session, ledger, egress, captured


def test_query_embedding_capability_commits_before_ledger_and_guarded_egress():
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    model_id = uuid.uuid4()
    provider_id = uuid.uuid4()
    runtime, session, ledger, egress, captured = _runtime(
        provider_id=provider_id
    )
    plan = runtime.preflight(
        QueryEmbeddingPreflight(
            node_id="llm-1",
            organization_id=organization_id,
            legacy_credential_user_id=None,
            execution_context=_context(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
            runtime_control=_control(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
        )
    )
    binding = QueryEmbeddingModelBinding(
        model_id=model_id,
        provider_id=provider_id,
        model_identifier="embed-safe",
    )
    lease = runtime.resolve(
        QueryEmbeddingRequest(
            plan=plan,
            model_binding=binding,
            query="bounded query",
            shared_session=object(),
        )
    )

    assert session.commits == 1
    assert session.closes == 1
    assert captured["issue"].binding.purpose is CapabilityPurpose.QUERY_EMBEDDING
    assert captured["issue"].policy_model_id == model_id
    assert captured["issue"].output_token_cap == 0
    assert captured["admission"].policy_model_id == model_id
    assert captured["admission"].requested_output_tokens == 0
    assert ledger.requests[0].provider_attempt_id == (
        captured["issue"].binding.provider_attempt_id
    )
    assert egress.scopes[0].model_id == model_id

    result = lease.invoke()

    assert result.vector == (0.25, 0.75)
    assert ledger.operations[0].successes == [len("bounded query".encode("utf-8"))]
    assert egress.leases[0].calls == 1
    with pytest.raises(QueryEmbeddingConfigurationError):
        lease.invoke()


def test_query_embedding_rejects_usage_above_admitted_input_bound():
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    provider_id = uuid.uuid4()
    runtime, _session, ledger, egress, _captured = _runtime(
        provider_id=provider_id
    )
    plan = runtime.preflight(
        QueryEmbeddingPreflight(
            node_id="llm-1",
            organization_id=organization_id,
            legacy_credential_user_id=None,
            execution_context=_context(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
            runtime_control=_control(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
        )
    )
    query = "bounded query"
    lease = runtime.resolve(
        QueryEmbeddingRequest(
            plan=plan,
            model_binding=QueryEmbeddingModelBinding(
                model_id=uuid.uuid4(),
                provider_id=provider_id,
                model_identifier="embed-safe",
            ),
            query=query,
            shared_session=object(),
        )
    )
    egress.leases[0].invoke = lambda _query: QueryEmbeddingProviderResult(
        vector=(0.25, 0.75),
        input_tokens=len(query.encode("utf-8")) + 1,
    )

    with pytest.raises(QueryEmbeddingConfigurationError):
        lease.invoke()

    assert ledger.operations[0].successes == []
    assert ledger.operations[0].unknown == 1


def test_query_embedding_redacts_provider_failure_from_exception_chain():
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    provider_id = uuid.uuid4()
    runtime, _session, ledger, egress, _captured = _runtime(
        provider_id=provider_id
    )
    plan = runtime.preflight(
        QueryEmbeddingPreflight(
            node_id="llm-1",
            organization_id=organization_id,
            legacy_credential_user_id=None,
            execution_context=_context(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
            runtime_control=_control(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
        )
    )
    lease = runtime.resolve(
        QueryEmbeddingRequest(
            plan=plan,
            model_binding=QueryEmbeddingModelBinding(
                model_id=uuid.uuid4(),
                provider_id=provider_id,
                model_identifier="embed-safe",
            ),
            query="bounded query",
            shared_session=object(),
        )
    )

    def fail_provider(_query):
        raise RuntimeError("provider raw payload must not escape")

    egress.leases[0].invoke = fail_provider

    with pytest.raises(QueryEmbeddingConfigurationError) as exc_info:
        lease.invoke()

    assert exc_info.value.__cause__ is None
    assert ledger.operations[0].unknown == 1


def test_query_embedding_provider_start_failure_never_reaches_egress():
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    provider_id = uuid.uuid4()
    runtime, _session, ledger, egress, _captured = _runtime(
        provider_id=provider_id,
        fail_start=True,
    )
    plan = runtime.preflight(
        QueryEmbeddingPreflight(
            node_id="llm-1",
            organization_id=organization_id,
            legacy_credential_user_id=None,
            execution_context=_context(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
            runtime_control=_control(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
        )
    )
    lease = runtime.resolve(
        QueryEmbeddingRequest(
            plan=plan,
            model_binding=QueryEmbeddingModelBinding(
                model_id=uuid.uuid4(),
                provider_id=provider_id,
                model_identifier="embed-safe",
            ),
            query="bounded query",
            shared_session=object(),
        )
    )

    with pytest.raises(QueryEmbeddingConfigurationError):
        lease.invoke()

    assert ledger.operations[0].started == 0
    assert egress.leases[0].calls == 0


@pytest.mark.parametrize("invalid_boundary", ["legacy_principal", "execution_id"])
def test_query_embedding_preflight_rejects_mixed_or_mismatched_control(
    invalid_boundary,
):
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    runtime, _session, _ledger, _egress, _captured = _runtime(
        provider_id=uuid.uuid4()
    )
    control = _control(
        organization_id=organization_id,
        workflow_id=workflow_id,
    )
    legacy_principal = None
    if invalid_boundary == "legacy_principal":
        legacy_principal = uuid.uuid4()
    else:
        control = replace(
            control,
            execution_id=uuid.uuid4(),
        )

    with pytest.raises(QueryEmbeddingConfigurationError):
        runtime.preflight(
            QueryEmbeddingPreflight(
                node_id="llm-1",
                organization_id=organization_id,
                legacy_credential_user_id=legacy_principal,
                execution_context=_context(
                    organization_id=organization_id,
                    workflow_id=workflow_id,
                ),
                runtime_control=control,
            )
        )


@pytest.mark.parametrize("missing", ["operation_ledger", "egress_runtime"])
def test_query_embedding_capability_requires_durable_ledger_and_egress(missing):
    kwargs = {
        "session_factory": lambda: pytest.fail("preflight must not open a session"),
        "operation_ledger": object(),
        "egress_runtime": object(),
    }
    kwargs[missing] = None
    runtime = CapabilityQueryEmbeddingAdapter(**kwargs)

    with pytest.raises(QueryEmbeddingConfigurationError):
        runtime.preflight(
            QueryEmbeddingPreflight(
                node_id="llm-1",
                organization_id=uuid.uuid4(),
                legacy_credential_user_id=None,
                execution_context={
                    "provider_execution_capability_required": True,
                },
                runtime_control=None,
            )
        )
