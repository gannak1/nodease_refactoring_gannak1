from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from apps.shared.domain.provider_execution_capability import (
    CapabilityPurpose,
    ProviderExecutionBinding,
    RuntimePrincipal,
)
from apps.shared.domain.workflow_execution_identity import InvocationSegment
from apps.workflow_engine.domain.execution import NodeExecutionControl
from apps.workflow_engine.domain.external_effect import ExternalEffectContext
from apps.workflow_engine.services import llm_service as workflow_llm_service
from apps.workflow_engine.services.llm_service import (
    LLMCredentialNotAvailableError,
    LLMRuntimeSelection,
    LLMService,
)
from apps.workflow_engine.workflow.nodes.llm.entities import LLMNodeData
from apps.workflow_engine.workflow.nodes.llm.llm_node import (
    LLMNode,
    ProviderExecutionCapabilityConfigurationError,
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


def test_capability_required_llm_node_uses_policy_runtime_and_not_legacy_fallback(
    monkeypatch,
):
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    deployment_id = uuid.uuid4()
    execution_subject_id = uuid.uuid4()
    policy_principal_id = uuid.uuid4()
    captured: dict = {}
    usage_calls: list[dict] = []
    client = _Client()
    class _ProviderDb:
        def __init__(self):
            self.closes = 0

        def close(self):
            self.closes += 1

    workflow_db = _ProviderDb()
    provider_db = _ProviderDb()
    sessions = iter((workflow_db, provider_db))
    node = _node(
        context={
            "db_session_factory": lambda: next(sessions),
            "provider_execution_capability_required": True,
            "provider_execution_capability_limits": {
                "input_token_cap": 10_000,
                "output_token_cap": 100,
                "cost_cap_microusd": 50_000,
            },
            "deployment_id": str(deployment_id),
            "workflow_version": 2,
            "organization_id": str(organization_id),
            "workflow_id": str(workflow_id),
            "execution_subject": {"type": "user", "id": str(execution_subject_id)},
        }
    )

    def capability_client(
        _db,
        *,
        issue_command,
        requested_input_tokens,
        requested_output_tokens,
    ):
        assert _db is provider_db
        assert _db is not workflow_db
        captured["command"] = issue_command
        captured["requested_input_tokens"] = requested_input_tokens
        captured["requested_output_tokens"] = requested_output_tokens
        return LLMRuntimeSelection(
            client=client,
            credential_id=uuid.uuid4(),
            model_id="gpt-safe",
            organization_id=organization_id,
            capability_id=uuid.uuid4(),
            capability_revision=1,
            credential_principal_user_id=policy_principal_id,
        )

    monkeypatch.setattr(
        LLMService,
        "get_runtime_client_for_provider_execution",
        capability_client,
    )
    monkeypatch.setattr(
        LLMService,
        "get_runtime_client_for_user",
        lambda *_args, **_kwargs: pytest.fail("legacy selection must not run"),
    )
    monkeypatch.setattr(LLMService, "calculate_cost", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(
        LLMService,
        "log_usage",
        lambda **kwargs: usage_calls.append(kwargs),
    )

    result = node.execute(
        {},
        runtime_control=_control(
            organization_id=organization_id,
            workflow_id=workflow_id,
        ),
    )

    command = captured["command"]
    assert command.binding.organization_id == organization_id
    assert command.binding.workflow_id == workflow_id
    assert command.binding.deployment_id == deployment_id
    assert command.binding.deployment_version == 2
    assert command.binding.node_id == "llm-1"
    assert command.binding.purpose is CapabilityPurpose.MAIN_GENERATION
    assert command.execution_subject.reference_id == execution_subject_id
    assert command.billing_principal.reference_id == organization_id
    assert command.input_token_cap == 10_000
    assert command.output_token_cap == 100
    assert command.cost_cap_microusd == 50_000
    assert 0 < captured["requested_input_tokens"] <= command.input_token_cap
    assert captured["requested_output_tokens"] == command.output_token_cap
    assert client.calls[0]["kwargs"]["max_tokens"] == command.output_token_cap
    assert result["text"] == "safe capability result"
    assert result["metadata"]["model_routing"]["provider_execution_capability"] == "required"
    assert usage_calls[0]["user_id"] == policy_principal_id
    assert workflow_db.closes == 1
    assert provider_db.closes == 1


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
    monkeypatch.setattr(
        LLMService,
        "get_runtime_client_for_provider_execution",
        lambda *_args, **_kwargs: pytest.fail("provider client must not be created"),
    )

    with pytest.raises(ProviderExecutionCapabilityConfigurationError):
        node.execute({})


def test_capability_control_session_rejects_shared_workflow_session():
    workflow_db = object()
    node = _node(context={"db_session_factory": lambda: workflow_db})

    with pytest.raises(ProviderExecutionCapabilityConfigurationError):
        node._borrow_provider_execution_db_session(workflow_db)


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
    monkeypatch.setattr(
        LLMService,
        "get_runtime_client_for_provider_execution",
        lambda *_args, **_kwargs: pytest.fail("provider client must not be created"),
    )

    with pytest.raises(ProviderExecutionCapabilityConfigurationError):
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
    captured_purposes: list[CapabilityPurpose] = []
    client = _Client()
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
            "provider_execution_audience": "anonymous_public",
            "memory_mode": True,
            "conversation_id": "conversation-safe",
        }
    )

    def capability_client(
        _db,
        *,
        issue_command,
        requested_input_tokens,
        requested_output_tokens,
    ):
        captured_purposes.append(issue_command.binding.purpose)
        assert requested_input_tokens > 0
        assert requested_output_tokens == issue_command.output_token_cap
        return LLMRuntimeSelection(
            client=client,
            credential_id=uuid.uuid4(),
            model_id="gpt-safe",
            organization_id=organization_id,
            capability_id=uuid.uuid4(),
            capability_revision=1,
            credential_principal_user_id=uuid.uuid4(),
        )

    monkeypatch.setattr(
        LLMService,
        "get_runtime_client_for_provider_execution",
        capability_client,
    )
    monkeypatch.setattr(
        LLMService,
        "get_runtime_client_for_user",
        lambda *_args, **_kwargs: pytest.fail("legacy summary selection must not run"),
    )
    monkeypatch.setattr(LLMService, "calculate_cost", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(LLMService, "log_usage", lambda **_kwargs: None)

    result = node.execute(
        {},
        runtime_control=_control(
            organization_id=organization_id,
            workflow_id=workflow_id,
        ),
    )

    assert captured_purposes == [CapabilityPurpose.MAIN_GENERATION]
    assert result["text"] == "safe capability result"


def test_provider_runtime_does_not_materialize_client_after_admission_failure(
    monkeypatch,
):
    organization_id = uuid.uuid4()
    binding = ProviderExecutionBinding(
        organization_id=organization_id,
        workflow_id=uuid.uuid4(),
        deployment_id=uuid.uuid4(),
        deployment_version=1,
        node_id="llm-1",
        node_invocation_id=uuid.uuid4(),
        execution_admission_id=uuid.uuid4(),
        provider_attempt_id=uuid.uuid4(),
        purpose=CapabilityPurpose.MAIN_GENERATION,
    )
    issue_command = workflow_llm_service.ProviderExecutionCapabilityIssueCommand(
        binding=binding,
        execution_subject=RuntimePrincipal.anonymous_public(),
        billing_principal=RuntimePrincipal.organization(organization_id),
        audit_actor=RuntimePrincipal.public_actor(),
        input_token_cap=100,
        output_token_cap=10,
        cost_cap_microusd=1_000,
    )
    monkeypatch.setattr(
        workflow_llm_service.ProviderExecutionCapabilityService,
        "issue_capability",
        lambda *_args, **_kwargs: type("Capability", (), {"id": uuid.uuid4(), "revision": 1})(),
    )
    monkeypatch.setattr(
        workflow_llm_service.ProviderExecutionCapabilityService,
        "admit_capability",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            workflow_llm_service.ProviderExecutionPolicyError("capability_stale")
        ),
    )
    monkeypatch.setattr(
        workflow_llm_service,
        "get_llm_client",
        lambda **_kwargs: pytest.fail("provider client must not be materialized"),
    )

    with pytest.raises(LLMCredentialNotAvailableError) as exc_info:
        LLMService.get_runtime_client_for_provider_execution(
            object(),
            issue_command=issue_command,
            requested_input_tokens=10,
            requested_output_tokens=5,
        )

    assert exc_info.value.reason == "provider_capability_capability_stale"


def test_provider_runtime_uses_shared_config_and_commits_before_return(monkeypatch):
    organization_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    credential = SimpleNamespace(id=uuid.uuid4(), encrypted_config="not-json")
    capability = SimpleNamespace(id=uuid.uuid4(), revision=3)
    binding = ProviderExecutionBinding(
        organization_id=organization_id,
        workflow_id=uuid.uuid4(),
        deployment_id=uuid.uuid4(),
        deployment_version=1,
        node_id="llm-1",
        node_invocation_id=uuid.uuid4(),
        execution_admission_id=uuid.uuid4(),
        provider_attempt_id=uuid.uuid4(),
        purpose=CapabilityPurpose.MAIN_GENERATION,
    )
    execution_user_id = uuid.uuid4()
    issue_command = workflow_llm_service.ProviderExecutionCapabilityIssueCommand(
        binding=binding,
        execution_subject=RuntimePrincipal.user(execution_user_id),
        billing_principal=RuntimePrincipal.organization(organization_id),
        audit_actor=RuntimePrincipal.user(execution_user_id),
        input_token_cap=200,
        output_token_cap=20,
        cost_cap_microusd=2_000,
    )
    loaded: list[object] = []
    admitted: list[object] = []

    class _Db:
        commits = 0

        def commit(self):
            self.commits += 1

    db = _Db()
    monkeypatch.setattr(
        workflow_llm_service.ProviderExecutionCapabilityService,
        "issue_capability",
        lambda *_args, **_kwargs: capability,
    )

    def admit(*_args, **kwargs):
        admitted.append(kwargs["command"])
        return SimpleNamespace(
            credential=credential,
            provider=SimpleNamespace(name="provider"),
            model=SimpleNamespace(model_id_for_api_call="gpt-safe"),
            capability=SimpleNamespace(
                credential_principal=RuntimePrincipal.user(principal_id)
            ),
        )

    monkeypatch.setattr(
        workflow_llm_service.ProviderExecutionCapabilityService,
        "admit_capability",
        admit,
    )

    def load_config(row):
        loaded.append(row)
        return {"apiKey": "[REDACTED]", "baseUrl": None}

    monkeypatch.setattr(
        workflow_llm_service,
        "load_llm_credential_config",
        load_config,
    )
    provider_client = object()
    monkeypatch.setattr(
        workflow_llm_service,
        "get_llm_client",
        lambda **_kwargs: provider_client,
    )

    selection = LLMService.get_runtime_client_for_provider_execution(
        db,
        issue_command=issue_command,
        requested_input_tokens=120,
        requested_output_tokens=12,
    )

    assert loaded == [credential]
    assert admitted[0].requested_input_tokens == 120
    assert admitted[0].requested_output_tokens == 12
    assert db.commits == 1
    assert selection.client is provider_client
    assert selection.capability_id == capability.id
    assert selection.credential_principal_user_id == principal_id


def test_provider_runtime_hides_config_failure_and_does_not_commit(monkeypatch):
    organization_id = uuid.uuid4()
    binding = ProviderExecutionBinding(
        organization_id=organization_id,
        workflow_id=uuid.uuid4(),
        deployment_id=uuid.uuid4(),
        deployment_version=1,
        node_id="llm-1",
        node_invocation_id=uuid.uuid4(),
        execution_admission_id=uuid.uuid4(),
        provider_attempt_id=uuid.uuid4(),
        purpose=CapabilityPurpose.MAIN_GENERATION,
    )
    issue_command = workflow_llm_service.ProviderExecutionCapabilityIssueCommand(
        binding=binding,
        execution_subject=RuntimePrincipal.anonymous_public(),
        billing_principal=RuntimePrincipal.organization(organization_id),
        audit_actor=RuntimePrincipal.public_actor(),
        input_token_cap=100,
        output_token_cap=10,
        cost_cap_microusd=1_000,
    )
    capability = SimpleNamespace(id=uuid.uuid4(), revision=1)
    lease = SimpleNamespace(credential=SimpleNamespace(id=uuid.uuid4()))

    class _Db:
        commits = 0

        def commit(self):
            self.commits += 1

    db = _Db()
    monkeypatch.setattr(
        workflow_llm_service.ProviderExecutionCapabilityService,
        "issue_capability",
        lambda *_args, **_kwargs: capability,
    )
    monkeypatch.setattr(
        workflow_llm_service.ProviderExecutionCapabilityService,
        "admit_capability",
        lambda *_args, **_kwargs: lease,
    )
    monkeypatch.setattr(
        workflow_llm_service,
        "load_llm_credential_config",
        lambda _row: (_ for _ in ()).throw(ValueError("internal")),
    )
    monkeypatch.setattr(
        workflow_llm_service,
        "get_llm_client",
        lambda **_kwargs: pytest.fail("client must not be materialized"),
    )

    with pytest.raises(LLMCredentialNotAvailableError) as exc_info:
        LLMService.get_runtime_client_for_provider_execution(
            db,
            issue_command=issue_command,
            requested_input_tokens=10,
            requested_output_tokens=5,
        )

    assert exc_info.value.reason == "credential_config_invalid"
    assert exc_info.value.__cause__ is None
    assert db.commits == 0


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

    with pytest.raises(ProviderExecutionCapabilityConfigurationError):
        LLMNode._provider_execution_requested_usage(
            messages=[{"role": "user", "content": "safe"}],
            llm_params=dict(parameters),
            issue_command=issue_command,
        )


def test_capability_request_rejects_request_owned_model_selection():
    with pytest.raises(ProviderExecutionCapabilityConfigurationError):
        LLMNode._provider_execution_requested_usage(
            messages=[{"role": "user", "content": "safe"}],
            llm_params={"model": "unapproved-model", "max_tokens": 5},
            issue_command=SimpleNamespace(output_token_cap=10),
        )


@pytest.mark.parametrize("completion_count", [0, 2, 100, True, "1"])
def test_capability_request_rejects_non_single_completion_count(completion_count):
    with pytest.raises(ProviderExecutionCapabilityConfigurationError):
        LLMNode._provider_execution_requested_usage(
            messages=[{"role": "user", "content": "safe"}],
            llm_params={"n": completion_count, "max_tokens": 5},
            issue_command=SimpleNamespace(output_token_cap=10),
        )


def test_capability_request_allows_explicit_single_completion():
    params = {"n": 1, "max_tokens": 5}

    _, output_tokens = LLMNode._provider_execution_requested_usage(
        messages=[{"role": "user", "content": "safe"}],
        llm_params=params,
        issue_command=SimpleNamespace(output_token_cap=10),
    )

    assert output_tokens == 5
    assert params["n"] == 1
