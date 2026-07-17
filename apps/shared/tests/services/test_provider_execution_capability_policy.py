from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.shared.db.models.llm import (
    LLMDeploymentCredentialPolicy,
    ProviderExecutionCapabilityRecord,
)
from apps.shared.services import provider_execution_capability as capability_service
from apps.shared.services.provider_execution_capability import (
    DeploymentCredentialPolicyCommand,
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
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args):
        return self

    def with_for_update(self):
        return self

    def all(self):
        return self.rows


class _ReplacementDb:
    def __init__(self, active_rows):
        self.active_rows = active_rows
        self.added = None
        self.flush_states: list[tuple[bool, bool]] = []

    def query(self, *_args):
        return _ReplacementQuery(self.active_rows)

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

    monkeypatch.setattr(
        ProviderExecutionCapabilityService,
        "_canonical_deployment",
        staticmethod(
            lambda *_args, **_kwargs: (
                SimpleNamespace(id=deployment_id, version=2),
                SimpleNamespace(id=uuid.uuid4()),
                SimpleNamespace(id=workflow_id),
            )
        ),
    )
    monkeypatch.setattr(
        capability_service,
        "has_organization_manager_permission",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        ProviderExecutionCapabilityService,
        "_resolve_policy_selection",
        classmethod(
            lambda _cls, *_args, **_kwargs: (
                SimpleNamespace(id=model_id),
                SimpleNamespace(id=credential_id),
                SimpleNamespace(),
                SimpleNamespace(),
            )
        ),
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
