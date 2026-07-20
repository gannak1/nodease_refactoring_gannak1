from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from apps.shared.domain.provider_execution_capability import RuntimePrincipal
from apps.shared.domain.workflow_execution_identity import InvocationSegment
from apps.shared.services.provider_execution_capability import (
    ProviderExecutionPolicyError,
)
from apps.workflow_engine.adapters.provider_execution_capability import (
    CapabilityProviderExecutionAdapter,
    provider_visible_request_bounds,
)
from apps.workflow_engine.application.provider_execution import (
    ProviderExecutionConfigurationError,
    ProviderExecutionPreflight,
    ProviderExecutionRequest,
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


class _Client:
    def __init__(self, session: _Session) -> None:
        self.session = session
        self.calls = 0

    def invoke_sync(self, *, messages, **parameters):
        assert self.session.commits == 1
        assert self.session.closes == 1
        self.calls += 1
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }


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


def _capability_context(
    *,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID,
) -> dict:
    return {
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


def test_capability_runtime_commits_and_closes_control_uow_before_provider_io():
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    policy_principal_id = uuid.uuid4()
    model_db_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    session = _Session()
    captured: dict = {}

    capability = SimpleNamespace(id=uuid.uuid4(), revision=3)

    class _CapabilityService:
        @staticmethod
        def issue_capability(_db, *, command):
            captured["issue"] = command
            return capability

        @staticmethod
        def admit_capability(_db, *, command):
            captured["admission"] = command
            return SimpleNamespace(
                credential=SimpleNamespace(id=credential_id),
                provider=SimpleNamespace(
                    name="provider",
                    base_url="https://catalog.example.test/v1",
                ),
                model=SimpleNamespace(
                    id=model_db_id,
                    model_id_for_api_call="gpt-safe",
                ),
                capability=SimpleNamespace(
                    credential_principal=RuntimePrincipal.user(policy_principal_id)
                ),
            )

    client = _Client(session)
    runtime = CapabilityProviderExecutionAdapter(
        session_factory=lambda: session,
        capability_service=_CapabilityService,
        credential_loader=lambda _credential: {"apiKey": "[REDACTED]"},
        client_factory=lambda **_kwargs: client,
    )
    context = _capability_context(
        organization_id=organization_id,
        workflow_id=workflow_id,
    )
    plan = runtime.preflight(
        ProviderExecutionPreflight(
            node_id="llm-1",
            configured_model_id="gpt-safe",
            auto_model_routing=False,
            fallback_model_id=None,
            knowledge_enabled=False,
            memory_summary_requested=False,
            client_override=None,
            execution_context=context,
            runtime_control=_control(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
        )
    )

    lease = runtime.resolve(
        ProviderExecutionRequest(
            plan=plan,
            model_id="gpt-safe",
            messages=({"role": "user", "content": "safe"},),
            parameters={},
            shared_session=object(),
        )
    )

    assert session.commits == 1
    assert session.closes == 1
    assert lease.attribution.model_db_id == model_db_id
    assert lease.attribution.credential_principal_user_id == policy_principal_id
    assert captured["issue"].binding.node_id == "llm-1"
    assert captured["admission"].requested_output_tokens == 100
    assert lease.invoke()["choices"][0]["message"]["content"] == "ok"
    assert client.calls == 1


def test_capability_runtime_does_not_materialize_client_after_admission_failure():
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    session = _Session()

    class _CapabilityService:
        @staticmethod
        def issue_capability(_db, *, command):
            return SimpleNamespace(id=uuid.uuid4(), revision=1)

        @staticmethod
        def admit_capability(_db, *, command):
            raise ProviderExecutionPolicyError("capability_stale")

    runtime = CapabilityProviderExecutionAdapter(
        session_factory=lambda: session,
        capability_service=_CapabilityService,
        client_factory=lambda **_kwargs: pytest.fail(
            "provider client must not be materialized"
        ),
    )
    plan = runtime.preflight(
        ProviderExecutionPreflight(
            node_id="llm-1",
            configured_model_id="gpt-safe",
            auto_model_routing=False,
            fallback_model_id=None,
            knowledge_enabled=False,
            memory_summary_requested=False,
            client_override=None,
            execution_context=_capability_context(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
            runtime_control=_control(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
        )
    )

    with pytest.raises(Exception) as exc_info:
        runtime.resolve(
            ProviderExecutionRequest(
                plan=plan,
                model_id="gpt-safe",
                messages=({"role": "user", "content": "safe"},),
                parameters={"max_tokens": 5},
                shared_session=object(),
            )
        )

    assert getattr(exc_info.value, "reason", None) == (
        "provider_capability_capability_stale"
    )
    assert session.commits == 0
    assert session.closes == 1


@pytest.mark.parametrize(
    ("admitted_model_id", "credential_principal", "expected_reason"),
    [
        (
            "different-model",
            RuntimePrincipal.user(uuid.uuid4()),
            "provider_capability_model_mismatch",
        ),
        (
            "gpt-safe",
            RuntimePrincipal.system_actor(),
            "provider_capability_attribution_invalid",
        ),
    ],
)
def test_capability_runtime_rejects_invalid_admission_before_materialization(
    admitted_model_id,
    credential_principal,
    expected_reason,
):
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    session = _Session()
    materialization_calls = 0

    class _CapabilityService:
        @staticmethod
        def issue_capability(_db, *, command):
            return SimpleNamespace(id=uuid.uuid4(), revision=1)

        @staticmethod
        def admit_capability(_db, *, command):
            return SimpleNamespace(
                credential=SimpleNamespace(id=uuid.uuid4()),
                provider=SimpleNamespace(
                    name="provider",
                    base_url="https://catalog.example.test/v1",
                ),
                model=SimpleNamespace(
                    id=uuid.uuid4(),
                    model_id_for_api_call=admitted_model_id,
                ),
                capability=SimpleNamespace(
                    credential_principal=credential_principal,
                ),
            )

    def credential_loader(_credential):
        nonlocal materialization_calls
        materialization_calls += 1
        return {"apiKey": "[REDACTED]"}

    runtime = CapabilityProviderExecutionAdapter(
        session_factory=lambda: session,
        capability_service=_CapabilityService,
        credential_loader=credential_loader,
        client_factory=lambda **_kwargs: pytest.fail(
            "provider client must not be materialized"
        ),
    )
    plan = runtime.preflight(
        ProviderExecutionPreflight(
            node_id="llm-1",
            configured_model_id="gpt-safe",
            auto_model_routing=False,
            fallback_model_id=None,
            knowledge_enabled=False,
            memory_summary_requested=False,
            client_override=None,
            execution_context=_capability_context(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
            runtime_control=_control(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
        )
    )

    with pytest.raises(Exception) as exc_info:
        runtime.resolve(
            ProviderExecutionRequest(
                plan=plan,
                model_id="gpt-safe",
                messages=({"role": "user", "content": "safe"},),
                parameters={"max_tokens": 5},
                shared_session=object(),
            )
        )

    assert getattr(exc_info.value, "reason", None) == expected_reason

    assert materialization_calls == 0
    assert session.commits == 0
    assert session.closes == 1


def test_capability_runtime_hides_config_failure_and_does_not_commit():
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    session = _Session()

    class _CapabilityService:
        @staticmethod
        def issue_capability(_db, *, command):
            return SimpleNamespace(id=uuid.uuid4(), revision=1)

        @staticmethod
        def admit_capability(_db, *, command):
            return SimpleNamespace(
                credential=SimpleNamespace(id=uuid.uuid4()),
                provider=SimpleNamespace(
                    name="provider",
                    base_url="https://catalog.example.test/v1",
                ),
                model=SimpleNamespace(
                    id=uuid.uuid4(),
                    model_id_for_api_call="gpt-safe",
                ),
                capability=SimpleNamespace(
                    credential_principal=RuntimePrincipal.user(uuid.uuid4())
                ),
            )

    runtime = CapabilityProviderExecutionAdapter(
        session_factory=lambda: session,
        capability_service=_CapabilityService,
        credential_loader=lambda _credential: (_ for _ in ()).throw(
            ValueError("internal")
        ),
        client_factory=lambda **_kwargs: pytest.fail(
            "provider client must not be materialized"
        ),
    )
    plan = runtime.preflight(
        ProviderExecutionPreflight(
            node_id="llm-1",
            configured_model_id="gpt-safe",
            auto_model_routing=False,
            fallback_model_id=None,
            knowledge_enabled=False,
            memory_summary_requested=False,
            client_override=None,
            execution_context=_capability_context(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
            runtime_control=_control(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
        )
    )

    with pytest.raises(Exception) as exc_info:
        runtime.resolve(
            ProviderExecutionRequest(
                plan=plan,
                model_id="gpt-safe",
                messages=({"role": "user", "content": "safe"},),
                parameters={"max_tokens": 5},
                shared_session=object(),
            )
        )

    assert getattr(exc_info.value, "reason", None) == "credential_config_invalid"
    assert exc_info.value.__cause__ is None
    assert session.commits == 0
    assert session.closes == 1


def test_capability_preflight_rejects_rag_before_session_or_provider_io():
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    calls = 0

    def session_factory():
        nonlocal calls
        calls += 1
        return _Session()

    runtime = CapabilityProviderExecutionAdapter(session_factory=session_factory)

    with pytest.raises(ProviderExecutionConfigurationError):
        runtime.preflight(
            ProviderExecutionPreflight(
                node_id="llm-1",
                configured_model_id="gpt-safe",
                auto_model_routing=False,
                fallback_model_id=None,
                knowledge_enabled=True,
                memory_summary_requested=False,
                client_override=None,
                execution_context=_capability_context(
                    organization_id=organization_id,
                    workflow_id=workflow_id,
                ),
                runtime_control=_control(
                    organization_id=organization_id,
                    workflow_id=workflow_id,
                ),
            )
        )

    assert calls == 0


def test_capability_runtime_rejects_shared_workflow_session():
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    shared_session = _Session()
    runtime = CapabilityProviderExecutionAdapter(
        session_factory=lambda: shared_session,
    )
    plan = runtime.preflight(
        ProviderExecutionPreflight(
            node_id="llm-1",
            configured_model_id="gpt-safe",
            auto_model_routing=False,
            fallback_model_id=None,
            knowledge_enabled=False,
            memory_summary_requested=False,
            client_override=None,
            execution_context=_capability_context(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
            runtime_control=_control(
                organization_id=organization_id,
                workflow_id=workflow_id,
            ),
        )
    )

    with pytest.raises(ProviderExecutionConfigurationError):
        runtime.resolve(
            ProviderExecutionRequest(
                plan=plan,
                model_id="gpt-safe",
                messages=({"role": "user", "content": "safe"},),
                parameters={},
                shared_session=shared_session,
            )
        )

    assert shared_session.commits == 0
    assert shared_session.closes == 0


@pytest.mark.parametrize(
    "parameters",
    [
        {"model": "unapproved", "max_tokens": 5},
        {"n": 2, "max_tokens": 5},
        {"best_of": 2, "max_tokens": 5},
        {"max_completion_tokens": 5},
        {"max_output_tokens": 5},
    ],
)
def test_provider_visible_request_bounds_rejects_override_surfaces(parameters):
    with pytest.raises(ProviderExecutionConfigurationError):
        provider_visible_request_bounds(
            messages=({"role": "user", "content": "safe"},),
            parameters=parameters,
            output_token_cap=10,
        )
