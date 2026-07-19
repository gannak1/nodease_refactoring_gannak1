from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from apps.shared.db.models.llm import (
    LLMCredential,
    LLMDeploymentCredentialPolicy,
    LLMModel,
    LLMProvider,
    LLMRelCredentialModel,
    ProviderExecutionCapabilityRecord,
)
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.organization_membership import OrganizationMembership
from apps.shared.db.models.team import (
    Team,
    TeamLLMPermission,
    TeamMembership,
    UserLLMPermission,
)
from apps.shared.db.models.user import User
from apps.shared.domain.provider_execution_capability import (
    CapabilityPurpose,
    ProviderExecutionBinding,
    RuntimePrincipal,
)
from apps.shared.services import provider_execution_capability as capability_service
from apps.shared.services.provider_execution_capability import (
    DeploymentCredentialPolicyCommand,
    ProviderExecutionCapabilityAdmissionCommand,
    ProviderExecutionCapabilityIssueCommand,
    ProviderExecutionCapabilityService,
    ProviderExecutionPolicyError,
    deployment_llm_node_model_id,
)


def _graph(*, data: dict | None = None) -> dict:
    return {
        "nodes": [
            {
                "id": "llm-1",
                "type": "llmNode",
                "data": data or {"model_id": "gpt-safe"},
            }
        ],
        "edges": [],
    }


def test_policy_reads_only_the_model_identifier_from_an_llm_graph_node():
    assert deployment_llm_node_model_id(_graph(), "llm-1") == "gpt-safe"


def test_policy_rejects_node_id_that_cannot_be_persisted():
    maximum_node_id = "n" * 255
    graph = _graph()
    graph["nodes"][0]["id"] = maximum_node_id

    assert deployment_llm_node_model_id(graph, maximum_node_id) == "gpt-safe"

    oversized_node_id = maximum_node_id + "n"
    graph["nodes"][0]["id"] = oversized_node_id
    with pytest.raises(ProviderExecutionPolicyError) as exc_info:
        deployment_llm_node_model_id(graph, oversized_node_id)

    assert exc_info.value.code == "configuration_required"


@pytest.mark.parametrize(
    "data",
    [
        {"model_id": "gpt-safe", "credential_id": "do-not-use"},
        {"model_id": "gpt-safe", "credentialId": "do-not-use"},
        {"model_id": "gpt-safe", "auto_model_routing": True},
        {"model_id": "gpt-safe", "fallback_model_id": "another-model"},
        {"model_id": ""},
    ],
)
def test_policy_rejects_direct_credential_and_implicit_selection(data):
    with pytest.raises(ProviderExecutionPolicyError) as exc_info:
        deployment_llm_node_model_id(_graph(data=data), "llm-1")

    assert exc_info.value.code == "configuration_required"
    assert "do-not-use" not in str(exc_info.value)


def test_policy_rejects_duplicate_or_wrong_node_without_disclosure():
    graph = _graph()
    graph["nodes"].append(dict(graph["nodes"][0]))

    with pytest.raises(ProviderExecutionPolicyError) as exc_info:
        deployment_llm_node_model_id(graph, "llm-1")

    assert exc_info.value.code == "configuration_required"


class _ReplacementQuery:
    def __init__(self, rows, lock_order):
        self.rows = rows
        self.lock_order = lock_order

    def filter(self, *_args):
        return self

    def with_for_update(self):
        self.lock_order.append("policy")
        return self

    def all(self):
        return self.rows


class _ReplacementDb:
    def __init__(self, active_rows):
        self.active_rows = active_rows
        self.added = None
        self.flush_states: list[tuple[bool, bool]] = []
        self.lock_order: list[str] = []

    def query(self, *_args):
        return _ReplacementQuery(self.active_rows, self.lock_order)

    def add(self, value):
        self.added = value

    def flush(self):
        self.flush_states.append(
            (self.active_rows[0].is_active, self.added is not None)
        )
        if self.added is not None:
            now = datetime.now(timezone.utc)
            self.added.created_at = now
            self.added.updated_at = now


def test_policy_replacement_flushes_superseded_active_row_before_insert(monkeypatch):
    organization_id = uuid.uuid4()
    deployment_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    model_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    old_policy = SimpleNamespace(is_active=True, policy_revision=7)
    db = _ReplacementDb([old_policy])

    canonical_calls: list[dict] = []
    manager_checks: list[uuid.UUID] = []
    selection_lock_modes: list[bool | None] = []

    def canonical_deployment(*_args, **kwargs):
        canonical_calls.append(kwargs)
        db.lock_order.append("deployment")
        return (
            SimpleNamespace(id=deployment_id, version=2),
            SimpleNamespace(id=uuid.uuid4()),
            SimpleNamespace(id=workflow_id),
        )

    monkeypatch.setattr(
        ProviderExecutionCapabilityService,
        "_canonical_deployment",
        staticmethod(canonical_deployment),
    )
    monkeypatch.setattr(
        capability_service,
        "has_organization_manager_permission",
        lambda _db, checked_actor_id, _organization_id: (
            manager_checks.append(checked_actor_id) or True
        ),
    )

    def resolve_policy_selection(_cls, *_args, **kwargs):
        db.lock_order.append("authorization")
        selection_lock_modes.append(kwargs.get("lock_authorization_rows"))
        return (
            SimpleNamespace(id=model_id),
            SimpleNamespace(id=credential_id),
            SimpleNamespace(),
            SimpleNamespace(),
        )

    monkeypatch.setattr(
        ProviderExecutionCapabilityService,
        "_resolve_policy_selection",
        classmethod(resolve_policy_selection),
    )

    policy = ProviderExecutionCapabilityService.replace_deployment_policy(
        db,
        actor_id=actor_id,
        command=DeploymentCredentialPolicyCommand(
            organization_id=organization_id,
            deployment_id=deployment_id,
            node_id="llm-1",
            model_id=model_id,
            credential_id=credential_id,
        ),
    )

    assert old_policy.is_active is False
    assert db.flush_states == [(False, False), (False, True)]
    assert policy.policy_revision == 8
    assert policy.credential_id == credential_id
    assert canonical_calls[0]["lock"] is True
    assert db.lock_order == ["deployment", "policy", "authorization"]
    assert selection_lock_modes == [True]
    assert manager_checks == [actor_id, actor_id]


def test_active_policy_unique_index_is_scoped_to_deployment_node():
    index = next(
        index
        for index in LLMDeploymentCredentialPolicy.__table__.indexes
        if index.name == "uq_llm_deploy_credential_policy_active"
    )

    assert [column.name for column in index.columns] == [
        "organization_id",
        "deployment_id",
        "deployment_version",
        "node_id",
    ]


def test_request_cost_uses_canonical_pricing_and_rounds_up():
    model = SimpleNamespace(
        input_price_1k=Decimal("0.001001"),
        output_price_1k=Decimal("0.002001"),
    )

    assert ProviderExecutionCapabilityService._request_cost_microusd(
        model,
        input_tokens=1,
        output_tokens=1,
    ) == 4


def test_request_cost_fails_closed_without_complete_pricing():
    model = SimpleNamespace(input_price_1k=None, output_price_1k=Decimal("0.1"))

    with pytest.raises(ProviderExecutionPolicyError) as exc_info:
        ProviderExecutionCapabilityService._request_cost_microusd(
            model,
            input_tokens=1,
            output_tokens=1,
        )

    assert exc_info.value.code == "configuration_required"


def test_existing_attempt_cannot_replace_runtime_principals():
    organization_id = uuid.uuid4()
    stored_user_id = uuid.uuid4()
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
    record = SimpleNamespace(
        execution_subject_kind="user",
        execution_subject_id=stored_user_id,
        billing_principal_kind="organization",
        billing_principal_id=organization_id,
        audit_actor_kind="user",
        audit_actor_id=stored_user_id,
    )
    command = ProviderExecutionCapabilityIssueCommand(
        binding=binding,
        execution_subject=RuntimePrincipal.system_actor(),
        billing_principal=RuntimePrincipal.organization(organization_id),
        audit_actor=RuntimePrincipal.system_actor(),
        input_token_cap=100,
        output_token_cap=10,
        cost_cap_microusd=1_000,
    )

    assert not ProviderExecutionCapabilityService._record_matches_issue_identity(
        record,
        command,
    )


def test_admission_locks_policy_before_capability_record(monkeypatch):
    organization_id = uuid.uuid4()
    model_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    provider_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    policy_id = uuid.uuid4()
    capability_id = uuid.uuid4()
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
    order: list[str] = []
    validation_times: list[datetime] = []
    lock_modes: dict[str, bool | None] = {}
    injected_now = datetime(2026, 7, 19, 1, 2, 2, tzinfo=timezone.utc)
    database_now = datetime(2026, 7, 19, 1, 2, 3, tzinfo=timezone.utc)
    policy = SimpleNamespace(
        id=policy_id,
        policy_revision=2,
        model_id=model_id,
        credential_id=credential_id,
        credential_principal_user_id=principal_id,
    )
    record = SimpleNamespace(
        policy_id=policy_id,
        policy_revision=2,
        model_id=model_id,
        credential_id=credential_id,
        provider_id=provider_id,
        credential_principal_user_id=principal_id,
        permission_revision="a" * 64,
        relation_revision="b" * 64,
        egress_revision="c" * 64,
        pricing_revision="d" * 64,
    )
    capability = SimpleNamespace(
        input_token_cap=100,
        output_token_cap=10,
        cost_cap_microusd=10_000,
        require_usable=lambda **kwargs: validation_times.append(kwargs["now"]),
    )
    model = SimpleNamespace(
        id=model_id,
        input_price_1k=Decimal("0.001"),
        output_price_1k=Decimal("0.002"),
    )
    credential = SimpleNamespace(id=credential_id)
    provider = SimpleNamespace(id=provider_id)
    relation = SimpleNamespace()

    class _CapabilityQuery:
        def filter(self, *_args):
            return self

        def with_for_update(self):
            order.append("capability")
            return self

        def one_or_none(self):
            return record

    class _Db:
        def query(self, *_args):
            return _CapabilityQuery()

    def canonical(*_args, **_kwargs):
        order.append("deployment")
        return (
            SimpleNamespace(id=binding.deployment_id, version=1),
            SimpleNamespace(id=uuid.uuid4()),
            SimpleNamespace(id=binding.workflow_id),
        )

    def active_policy(*_args, **_kwargs):
        order.append("policy")
        return policy

    monkeypatch.setattr(
        ProviderExecutionCapabilityService,
        "_canonical_deployment",
        staticmethod(canonical),
    )
    monkeypatch.setattr(
        ProviderExecutionCapabilityService,
        "_assert_binding_matches_deployment",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        ProviderExecutionCapabilityService,
        "_active_policy_for_binding",
        classmethod(lambda _cls, *_args, **kwargs: active_policy(**kwargs)),
    )
    monkeypatch.setattr(
        ProviderExecutionCapabilityService,
        "_domain_capability",
        staticmethod(lambda _record: capability),
    )
    monkeypatch.setattr(
        ProviderExecutionCapabilityService,
        "_resolve_policy_selection",
        classmethod(
            lambda _cls, *_args, **kwargs: (
                lock_modes.update(
                    selection=kwargs.get("lock_authorization_rows")
                )
                or (model, credential, provider, relation)
            )
        ),
    )
    monkeypatch.setattr(
        ProviderExecutionCapabilityService,
        "_current_revisions",
        classmethod(
            lambda _cls, *_args, **kwargs: (
                lock_modes.update(
                    permission=kwargs.get("lock_permission_rows")
                )
                or {
                    "permission": record.permission_revision,
                    "relation": record.relation_revision,
                    "egress": record.egress_revision,
                    "pricing": record.pricing_revision,
                }
            )
        ),
    )
    monkeypatch.setattr(
        ProviderExecutionCapabilityService,
        "_database_clock_now",
        staticmethod(lambda _db: order.append("database_clock") or database_now),
        raising=False,
    )

    lease = ProviderExecutionCapabilityService.admit_capability(
        _Db(),
        command=ProviderExecutionCapabilityAdmissionCommand(
            capability_id=capability_id,
            capability_revision=1,
            binding=binding,
            requested_input_tokens=10,
            requested_output_tokens=5,
        ),
        now=injected_now,
    )

    assert order == ["deployment", "policy", "capability", "database_clock"]
    assert lock_modes == {"selection": True, "permission": True}
    assert validation_times == [injected_now, database_now]
    assert lease.credential is credential


def test_database_clock_now_uses_wall_clock_timestamp():
    statements: list[object] = []
    database_now = datetime(2026, 7, 19, 1, 2, 3)

    class _Result:
        def scalar_one(self):
            return database_now

    class _Db:
        def execute(self, statement):
            statements.append(statement)
            return _Result()

    result = ProviderExecutionCapabilityService._database_clock_now(_Db())

    assert "clock_timestamp" in str(statements[0])
    assert result == database_now.replace(tzinfo=timezone.utc)


def test_policy_selection_locks_runtime_authorization_rows(monkeypatch):
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    app_id = uuid.uuid4()
    provider_id = uuid.uuid4()
    model_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    model = SimpleNamespace(
        id=model_id,
        provider_id=provider_id,
        model_id_for_api_call="gpt-safe",
        is_active=True,
    )
    provider = SimpleNamespace(id=provider_id)
    credential = SimpleNamespace(
        id=credential_id,
        organization_id=organization_id,
        provider_id=provider_id,
        is_valid=True,
    )
    relation = SimpleNamespace(
        credential_id=credential_id,
        model_id=model_id,
        is_verified=True,
    )
    rows = {
        LLMModel: [model],
        LLMProvider: [provider],
        LLMCredential: [credential],
        LLMRelCredentialModel: [relation],
    }
    locked: list[type] = []
    permission_lock_modes: list[bool] = []

    class _Query:
        def __init__(self, entity):
            self.entity = entity

        def filter(self, *_args):
            return self

        def with_for_update(self):
            locked.append(self.entity)
            return self

        def one_or_none(self):
            values = rows[self.entity]
            return values[0] if values else None

        def all(self):
            return rows[self.entity]

    class _Db:
        def query(self, entity):
            return _Query(entity)

    monkeypatch.setattr(
        capability_service,
        "deployment_llm_node_model_id",
        lambda *_args, **_kwargs: "gpt-safe",
    )
    monkeypatch.setattr(
        capability_service,
        "has_llm_credential_permission",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        ProviderExecutionCapabilityService,
        "_permission_revision",
        staticmethod(
            lambda *_args, **kwargs: (
                permission_lock_modes.append(kwargs["lock_rows"]) or "a" * 64
            )
        ),
    )

    selection = ProviderExecutionCapabilityService._resolve_policy_selection(
        _Db(),
        deployment=SimpleNamespace(app_id=app_id, graph_snapshot={}),
        app=SimpleNamespace(
            id=app_id,
            workflow_id=workflow_id,
            organization_id=organization_id,
        ),
        workflow=SimpleNamespace(id=workflow_id, organization_id=organization_id),
        organization_id=organization_id,
        node_id="llm-1",
        model_id=model_id,
        credential_id=credential_id,
        credential_principal_user_id=principal_id,
        lock_authorization_rows=True,
    )

    assert selection == (model, credential, provider, relation)
    assert locked == [LLMModel, LLMProvider, LLMCredential, LLMRelCredentialModel]
    assert permission_lock_modes == [True]


def test_permission_revision_locks_every_existing_permission_source(monkeypatch):
    locked: list[tuple[type, ...]] = []

    class _Query:
        def __init__(self, entities):
            self.entities = entities

        def filter(self, *_args):
            return self

        def join(self, *_args):
            return self

        def with_for_update(self):
            locked.append(self.entities)
            return self

        def one_or_none(self):
            return None

        def all(self):
            return []

    class _Db:
        def query(self, *entities):
            return _Query(entities)

    monkeypatch.setattr(
        capability_service,
        "get_effective_llm_credential_auth_state",
        lambda *_args, **_kwargs: "none",
    )

    revision = ProviderExecutionCapabilityService._permission_revision(
        _Db(),
        organization_id=uuid.uuid4(),
        credential_id=uuid.uuid4(),
        credential_principal_user_id=uuid.uuid4(),
        lock_rows=True,
    )

    assert len(revision) == 64
    assert locked == [
        (Organization,),
        (User,),
        (OrganizationMembership,),
        (UserLLMPermission,),
        (TeamLLMPermission, TeamMembership, Team),
    ]


def test_permission_revision_fingerprints_user_and_organization_state(monkeypatch):
    organization_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    organization = SimpleNamespace(
        id=organization_id,
        is_active=True,
        created_by=principal_id,
        managed_by=None,
        deactivated_at=None,
        updated_at=created_at,
    )
    user = SimpleNamespace(
        id=principal_id,
        deactivated_at=None,
        updated_at=created_at,
    )

    class _Query:
        def __init__(self, entities):
            self.entities = entities

        def filter(self, *_args):
            return self

        def join(self, *_args):
            return self

        def one_or_none(self):
            if self.entities == (Organization,):
                return organization
            if self.entities == (User,):
                return user
            return None

        def all(self):
            return []

    class _Db:
        def query(self, *entities):
            return _Query(entities)

    monkeypatch.setattr(
        capability_service,
        "get_effective_llm_credential_auth_state",
        lambda *_args, **_kwargs: "manager",
    )

    active_revision = ProviderExecutionCapabilityService._permission_revision(
        _Db(),
        organization_id=organization_id,
        credential_id=credential_id,
        credential_principal_user_id=principal_id,
    )
    organization.is_active = False
    inactive_organization_revision = (
        ProviderExecutionCapabilityService._permission_revision(
            _Db(),
            organization_id=organization_id,
            credential_id=credential_id,
            credential_principal_user_id=principal_id,
        )
    )
    organization.is_active = True
    user.deactivated_at = created_at
    inactive_user_revision = ProviderExecutionCapabilityService._permission_revision(
        _Db(),
        organization_id=organization_id,
        credential_id=credential_id,
        credential_principal_user_id=principal_id,
    )

    assert inactive_organization_revision != active_revision
    assert inactive_user_revision != active_revision


def test_policy_and_capability_are_cascaded_with_deleted_deployment_control():
    def ondelete_for(table, targets):
        constraint = next(
            constraint
            for constraint in table.foreign_key_constraints
            if tuple(element.target_fullname for element in constraint.elements) == targets
        )
        return constraint.ondelete

    assert ondelete_for(
        LLMDeploymentCredentialPolicy.__table__,
        ("workflows.id",),
    ) == "CASCADE"
    assert ondelete_for(
        LLMDeploymentCredentialPolicy.__table__,
        ("workflow_deployments.id",),
    ) == "CASCADE"
    assert ondelete_for(
        ProviderExecutionCapabilityRecord.__table__,
        (
            "llm_deployment_credential_policies.id",
            "llm_deployment_credential_policies.organization_id",
        ),
    ) == "CASCADE"
    assert ondelete_for(
        ProviderExecutionCapabilityRecord.__table__,
        ("workflows.id",),
    ) == "CASCADE"
    assert ondelete_for(
        ProviderExecutionCapabilityRecord.__table__,
        ("workflow_deployments.id",),
    ) == "CASCADE"
