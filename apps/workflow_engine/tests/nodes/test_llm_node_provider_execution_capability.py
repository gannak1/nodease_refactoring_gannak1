from __future__ import annotations

import uuid

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
    node = _node(
        context={
            "db": object(),
            "provider_execution_capability_required": True,
            "provider_execution_capability_limits": {
                "input_token_cap": 1000,
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

    def capability_client(_db, *, issue_command):
        captured["command"] = issue_command
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
    assert command.input_token_cap == 1000
    assert command.output_token_cap == 100
    assert command.cost_cap_microusd == 50_000
    assert result["text"] == "safe capability result"
    assert result["metadata"]["model_routing"]["provider_execution_capability"] == "required"
    assert usage_calls[0]["user_id"] == policy_principal_id


def test_capability_required_llm_node_fails_before_client_when_trusted_control_missing(
    monkeypatch,
):
    node = _node(
        context={
            "db": object(),
            "provider_execution_capability_required": True,
            "provider_execution_capability_limits": {
                "input_token_cap": 1000,
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
                "input_token_cap": 1000,
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
                "input_token_cap": 1000,
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

    def capability_client(_db, *, issue_command):
        captured_purposes.append(issue_command.binding.purpose)
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
        )

    assert exc_info.value.reason == "provider_capability_capability_stale"
