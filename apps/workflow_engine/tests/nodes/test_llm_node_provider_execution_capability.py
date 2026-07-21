from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from apps.shared.domain.workflow_execution_identity import InvocationSegment
from apps.workflow_engine.adapters.provider_execution_capability import (
    provider_visible_request_bounds,
)
from apps.workflow_engine.application.provider_execution import (
    LLMCredentialNotAvailableError,
    ProviderExecutionAttribution,
    ProviderExecutionAuditActor,
    ProviderExecutionAuditActorKind,
    ProviderExecutionConfigurationError,
    ProviderExecutionPlan,
)
from apps.workflow_engine.application.provider_usage import ProviderUsageRecord
from apps.workflow_engine.domain.execution import NodeExecutionControl
from apps.workflow_engine.domain.external_effect import ExternalEffectContext
from apps.workflow_engine.services import llm_service as workflow_llm_service
from apps.workflow_engine.services.llm_service import LLMService
from apps.workflow_engine.workflow.nodes.llm import llm_node as llm_node_module
from apps.workflow_engine.workflow.nodes.llm.entities import (
    KnowledgeBaseRef,
    LLMNodeData,
)
from apps.workflow_engine.workflow.nodes.llm.llm_node import (
    LLMNode,
)


class _Client:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invoke_sync(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return {
            "choices": [{"message": {"content": "safe capability result"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }



class _Lease:
    def __init__(self, *, client, attribution) -> None:
        self.client = client
        self.attribution = attribution

    def invoke(self):
        return self.client.invoke_sync(
            messages=[{"role": "user", "content": "safe"}],
            max_tokens=100,
        )


class _Runtime:
    def __init__(self, *, client, attribution) -> None:
        self.client = client
        self.attribution = attribution
        self.preflight_requests = []
        self.resolve_requests = []

    def preflight(self, request):
        self.preflight_requests.append(request)
        return ProviderExecutionPlan(
            fixed_model_id=request.configured_model_id,
            allow_legacy_memory_summary=False,
            routing_metadata={"provider_execution_capability": "required"},
            state=object(),
        )

    def resolve(self, request):
        self.resolve_requests.append(request)
        return _Lease(client=self.client, attribution=self.attribution)


class _DenyingRuntime:
    def __init__(self, *, audit_actor: ProviderExecutionAuditActor) -> None:
        self.audit_actor = audit_actor

    def preflight(self, request):
        return ProviderExecutionPlan(
            fixed_model_id=request.configured_model_id,
            allow_legacy_memory_summary=False,
            audit_actor=self.audit_actor,
            state=object(),
        )

    def resolve(self, _request):
        raise LLMCredentialNotAvailableError(
            "provider_capability_permission_denied",
            "Provider execution capability is not available.",
        )


class _UsageRecorder:
    def __init__(self) -> None:
        self.requests: list[ProviderUsageRecord] = []

    def record(self, request: ProviderUsageRecord) -> float:
        self.requests.append(request)
        return 0.0


def _provider_execution_requested_usage(*, messages, llm_params, issue_command):
    input_tokens, output_tokens, normalized = provider_visible_request_bounds(
        messages=tuple(messages),
        parameters=llm_params,
        output_token_cap=issue_command.output_token_cap,
    )
    llm_params.clear()
    llm_params.update(normalized)
    return input_tokens, output_tokens

def _node(*, context: dict) -> LLMNode:
    return LLMNode(
        "llm-1",
        LLMNodeData(
            title="LLM",
            model_id="gpt-safe",
            system_prompt="system",
            user_prompt="user",
        ),
        execution_context=context,
    )


def _control(*, organization_id: uuid.UUID, workflow_id: uuid.UUID):
    app_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    effect = ExternalEffectContext(
        organization_id=organization_id,
        app_id=app_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        node_invocation_id=uuid.uuid4(),
        node_id="llm-1",
    )
    return NodeExecutionControl(
        execution_id=execution_id,
        invocation_path_prefix=(InvocationSegment("root", "", "workflow"),),
        external_effect_context=effect,
        external_effect_enforced=True,
    )


def test_capability_required_llm_node_uses_provider_application_ports():
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    policy_principal_id = uuid.uuid4()
    attribution = ProviderExecutionAttribution(
        credential_id=uuid.uuid4(),
        credential_principal_user_id=policy_principal_id,
        organization_id=organization_id,
        model_id="gpt-safe",
        model_db_id=uuid.uuid4(),
        capability_id=uuid.uuid4(),
        capability_revision=1,
    )
    client = _Client()
    runtime = _Runtime(client=client, attribution=attribution)
    usage_recorder = _UsageRecorder()
    node = _node(
        context={
            "provider_execution_capability_required": True,
            "provider_execution_capability_limits": {
                "input_token_cap": 10_000,
                "output_token_cap": 100,
                "cost_cap_microusd": 50_000,
            },
            "deployment_id": str(uuid.uuid4()),
            "workflow_version": 2,
            "organization_id": str(organization_id),
            "workflow_id": str(workflow_id),
            "execution_subject": {"type": "user", "id": str(uuid.uuid4())},
        }
    )
    node.bind_provider_execution_runtime(runtime)
    node.bind_provider_usage_recorder(usage_recorder)

    control = _control(
        organization_id=organization_id,
        workflow_id=workflow_id,
    )
    result = node.execute({}, runtime_control=control)

    assert runtime.preflight_requests[0].runtime_control is control
    assert runtime.preflight_requests[0].knowledge_enabled is False
    assert runtime.resolve_requests[0].model_id == "gpt-safe"
    assert runtime.resolve_requests[0].shared_session is None
    assert client.calls[0]["kwargs"]["max_tokens"] == 100
    assert result["text"] == "safe capability result"
    assert result["metadata"]["model_routing"]["provider_execution_capability"] == "required"
    assert usage_recorder.requests[0].attribution == attribution
    assert usage_recorder.requests[0].attribution.credential_principal_user_id == (
        policy_principal_id
    )

def test_capability_required_llm_node_fails_before_client_when_trusted_control_missing(
    monkeypatch,
):
    node = _node(
        context={
            "db": object(),
            "provider_execution_capability_required": True,
            "provider_execution_capability_limits": {
                "input_token_cap": 10_000,
                "output_token_cap": 100,
                "cost_cap_microusd": 50_000,
            },
            "deployment_id": str(uuid.uuid4()),
            "workflow_version": 1,
            "organization_id": str(uuid.uuid4()),
            "workflow_id": str(uuid.uuid4()),
            "execution_subject": {"type": "user", "id": str(uuid.uuid4())},
        }
    )


    with pytest.raises(ProviderExecutionConfigurationError):
        node.execute({})


@pytest.mark.parametrize(
    ("actor_kind", "expected_recorder"),
    [
        (ProviderExecutionAuditActorKind.USER, "user"),
        (ProviderExecutionAuditActorKind.SYSTEM, "system"),
        (ProviderExecutionAuditActorKind.PUBLIC, "public"),
    ],
)
def test_capability_resolution_denial_uses_typed_audit_actor(
    monkeypatch,
    actor_kind,
    expected_recorder,
):
    actor_id = uuid.uuid4() if actor_kind is ProviderExecutionAuditActorKind.USER else None
    runtime = _DenyingRuntime(
        audit_actor=ProviderExecutionAuditActor(
            kind=actor_kind,
            reference_id=actor_id,
        )
    )
    node = _node(
        context={
            "organization_id": str(uuid.uuid4()),
            "workflow_id": str(uuid.uuid4()),
        }
    )
    node.bind_provider_execution_runtime(runtime)
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        llm_node_module,
        "record_resource_permission_denied",
        lambda **kwargs: calls.append(("user", kwargs)),
    )
    monkeypatch.setattr(
        llm_node_module,
        "record_system_resource_permission_denied",
        lambda **kwargs: calls.append(("system", kwargs)),
    )
    monkeypatch.setattr(
        llm_node_module,
        "record_public_resource_permission_denied",
        lambda **kwargs: calls.append(("public", kwargs)),
    )

    with pytest.raises(LLMCredentialNotAvailableError):
        node.execute({})

    assert len(calls) == 1
    recorder, audit = calls[0]
    assert recorder == expected_recorder
    if actor_kind is ProviderExecutionAuditActorKind.USER:
        assert audit["user_id"] == actor_id
    assert audit["metadata"]["reason"] == "provider_capability_permission_denied"


def test_capability_required_rag_fails_before_knowledge_or_provider_io(monkeypatch):
    node = _node(
        context={
            "db": object(),
            "provider_execution_capability_required": True,
        }
    )
    node.data.knowledgeBases = [
        KnowledgeBaseRef(id=str(uuid.uuid4()), name="Protected KB")
    ]
    monkeypatch.setattr(
        node,
        "_resolve_runtime_knowledge_candidates",
        lambda: pytest.fail("knowledge resolution must not run"),
    )

    monkeypatch.setattr(
        LLMService,
        "get_client_for_user",
        lambda *_args, **_kwargs: pytest.fail("legacy embedding client must not run"),
    )

    with pytest.raises(ProviderExecutionConfigurationError):
        node.execute({})


def test_capability_required_llm_node_rejects_provider_fallback_before_sdk_call(
    monkeypatch,
):
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    node = _node(
        context={
            "db": object(),
            "provider_execution_capability_required": True,
            "provider_execution_capability_limits": {
                "input_token_cap": 10_000,
                "output_token_cap": 100,
                "cost_cap_microusd": 50_000,
            },
            "deployment_id": str(uuid.uuid4()),
            "workflow_version": 1,
            "organization_id": str(organization_id),
            "workflow_id": str(workflow_id),
            "execution_subject": {"type": "user", "id": str(uuid.uuid4())},
        }
    )
    node.data.fallback_model_id = "fallback-model"


    with pytest.raises(ProviderExecutionConfigurationError):
        node.execute(
            {},
            runtime_control=_control(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
        )


def test_capability_required_legacy_memory_summary_is_skipped_without_fallback(
    monkeypatch,
):
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    attribution = ProviderExecutionAttribution(
        credential_id=uuid.uuid4(),
        credential_principal_user_id=uuid.uuid4(),
        organization_id=organization_id,
        model_id="gpt-safe",
        model_db_id=uuid.uuid4(),
        capability_id=uuid.uuid4(),
        capability_revision=1,
    )
    runtime = _Runtime(client=_Client(), attribution=attribution)
    node = _node(
        context={
            "provider_execution_capability_required": True,
            "provider_execution_capability_limits": {
                "input_token_cap": 10_000,
                "output_token_cap": 100,
                "cost_cap_microusd": 50_000,
            },
            "deployment_id": str(uuid.uuid4()),
            "workflow_version": 1,
            "organization_id": str(organization_id),
            "workflow_id": str(workflow_id),
            "provider_execution_audience": "anonymous_public",
            "memory_mode": True,
            "conversation_id": "conversation-safe",
        }
    )
    node.bind_provider_execution_runtime(runtime)
    node.bind_provider_usage_recorder(_UsageRecorder())
    monkeypatch.setattr(
        node,
        "_build_memory_summary",
        lambda: pytest.fail("legacy memory summary must not run"),
    )

    result = node.execute(
        {},
        runtime_control=_control(
            organization_id=organization_id,
            workflow_id=workflow_id,
        ),
    )

    assert runtime.preflight_requests[0].memory_summary_requested is True
    assert result["text"] == "safe capability result"

def test_capability_cost_uses_exact_model_uuid():
    model_db_id = uuid.uuid4()
    criteria: list[object] = []
    model = SimpleNamespace(
        id=model_db_id,
        input_price_1k=1.0,
        output_price_1k=2.0,
    )

    class _Query:
        def filter(self, *values):
            criteria.extend(values)
            return self

        def first(self):
            return model

    class _Db:
        def query(self, *_entities):
            return _Query()

    cost = LLMService.calculate_cost(
        _Db(),
        "duplicate-api-id",
        1_000,
        1_000,
        model_db_id=model_db_id,
    )

    assert criteria[0].left.name == "id"
    assert criteria[0].right.value == model_db_id
    assert cost == 3.0


def test_capability_usage_log_uses_exact_model_uuid(monkeypatch):
    model_db_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    user_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    criteria: list[object] = []
    added: list[object] = []
    model = SimpleNamespace(id=model_db_id)

    class _Query:
        def filter(self, *values):
            criteria.extend(values)
            return self

        def first(self):
            return model

    class _Db:
        def query(self, *_entities):
            return _Query()

        def add(self, value):
            added.append(value)

        def commit(self):
            return None

        def refresh(self, _value):
            return None

    monkeypatch.setattr(
        workflow_llm_service,
        "resolve_llm_usage_context",
        lambda *_args, **_kwargs: SimpleNamespace(
            organization_id=organization_id,
            workflow_id=workflow_id,
            workflow_run_id=None,
        ),
    )

    log = LLMService.log_usage(
        db=_Db(),
        user_id=user_id,
        model_id="duplicate-api-id",
        model_db_id=model_db_id,
        usage={"prompt_tokens": 1, "completion_tokens": 1},
        cost=0.1,
        organization_id=organization_id,
        workflow_id=workflow_id,
        credential_id=credential_id,
    )

    assert criteria[0].left.name == "id"
    assert criteria[0].right.value == model_db_id
    assert log is added[0]
    assert log.model_id == model_db_id


@pytest.mark.parametrize(
    ("parameters", "output_cap"),
    [
        ({"max_tokens": 0}, 10),
        ({"max_tokens": True}, 10),
        ({"max_completion_tokens": 5}, 10),
        ({"max_output_tokens": 5}, 10),
        ({}, 0),
    ],
)
def test_capability_request_rejects_ambiguous_or_invalid_output_limit(
    parameters,
    output_cap,
):
    issue_command = SimpleNamespace(output_token_cap=output_cap)

    with pytest.raises(ProviderExecutionConfigurationError):
        _provider_execution_requested_usage(
            messages=[{"role": "user", "content": "safe"}],
            llm_params=dict(parameters),
            issue_command=issue_command,
        )


def test_capability_request_rejects_request_owned_model_selection():
    with pytest.raises(ProviderExecutionConfigurationError):
        _provider_execution_requested_usage(
            messages=[{"role": "user", "content": "safe"}],
            llm_params={"model": "unapproved-model", "max_tokens": 5},
            issue_command=SimpleNamespace(output_token_cap=10),
        )


@pytest.mark.parametrize("completion_count", [0, 2, 100, True, "1"])
def test_capability_request_rejects_non_single_completion_count(completion_count):
    with pytest.raises(ProviderExecutionConfigurationError):
        _provider_execution_requested_usage(
            messages=[{"role": "user", "content": "safe"}],
            llm_params={"n": completion_count, "max_tokens": 5},
            issue_command=SimpleNamespace(output_token_cap=10),
        )


@pytest.mark.parametrize("best_of", [0, 2, 100, True, "1"])
def test_capability_request_rejects_non_single_best_of(best_of):
    with pytest.raises(ProviderExecutionConfigurationError):
        _provider_execution_requested_usage(
            messages=[{"role": "user", "content": "safe"}],
            llm_params={"best_of": best_of, "max_tokens": 5},
            issue_command=SimpleNamespace(output_token_cap=10),
        )


def test_capability_request_allows_explicit_single_completion():
    params = {"n": 1, "best_of": 1, "max_tokens": 5}

    _, output_tokens = _provider_execution_requested_usage(
        messages=[{"role": "user", "content": "safe"}],
        llm_params=params,
        issue_command=SimpleNamespace(output_token_cap=10),
    )

    assert output_tokens == 5
    assert params["n"] == 1
    assert params["best_of"] == 1


def test_capability_request_counts_provider_visible_parameters():
    messages = [{"role": "user", "content": "safe"}]
    base_input_tokens, _ = _provider_execution_requested_usage(
        messages=messages,
        llm_params={"max_tokens": 5},
        issue_command=SimpleNamespace(output_token_cap=10),
    )
    tool_input_tokens, _ = _provider_execution_requested_usage(
        messages=messages,
        llm_params={
            "max_tokens": 5,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "x" * 1024,
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                }
            ],
        },
        issue_command=SimpleNamespace(output_token_cap=10),
    )

    assert tool_input_tokens > base_input_tokens + 1024


def test_capability_request_rejects_unserializable_provider_parameter():
    with pytest.raises(ProviderExecutionConfigurationError):
        _provider_execution_requested_usage(
            messages=[{"role": "user", "content": "safe"}],
            llm_params={"max_tokens": 5, "tools": [object()]},
            issue_command=SimpleNamespace(output_token_cap=10),
        )
