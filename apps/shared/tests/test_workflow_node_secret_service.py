from __future__ import annotations

from unittest.mock import Mock
from uuid import uuid4

import pytest
from apps.shared.db.models.workflow_node_secret import WorkflowNodeSecret
from apps.shared.schemas.workflow import WorkflowNodeSecretWriteRequest
from apps.shared.services.credential_encryption import CredentialEncryptionService
from apps.shared.services.workflow_node_secret_service import (
    WorkflowNodeSecretError,
    WorkflowNodeSecretService,
    is_workflow_node_secret_reference,
    migrate_legacy_workflow_graph_secrets,
    redact_legacy_workflow_node_secrets,
    validate_workflow_node_secret_persistence_boundary,
)
from cryptography.fernet import Fernet


def _encryption() -> CredentialEncryptionService:
    return CredentialEncryptionService(
        {"test": Fernet.generate_key().decode("ascii")},
        "test",
        subject_label="Workflow node secret",
    )


def test_secret_write_schema_redacts_value_from_dump_and_repr() -> None:
    raw_value = "synthetic-input-value"
    request = WorkflowNodeSecretWriteRequest(
        node_id="slack-1",
        node_type="slackPostNode",
        parameter_key="bot_token",
        secret_value=raw_value,
    )

    assert raw_value not in repr(request)
    assert raw_value not in str(request.model_dump(mode="json"))


def test_create_reference_encrypts_value_and_returns_only_opaque_reference() -> None:
    db = Mock()
    workflow_id = uuid4()
    organization_id = uuid4()
    user_id = uuid4()
    submitted_value = f"synthetic-{uuid4()}"

    reference = WorkflowNodeSecretService.create_reference(
        db,
        encryption=_encryption(),
        workflow_id=workflow_id,
        organization_id=organization_id,
        user_id=user_id,
        node_id="slack-1",
        node_type="slackPostNode",
        parameter_key="bot_token",
        secret_value=submitted_value,
    )

    row = db.add.call_args.args[0]
    assert is_workflow_node_secret_reference(reference)
    assert submitted_value not in reference
    assert submitted_value not in row.encrypted_secret
    assert row.workflow_id == workflow_id
    assert row.organization_id == organization_id
    assert row.node_type == "slackPostNode"
    assert row.parameter_key == "bot_token"


def test_resolve_rejects_reference_from_another_workflow() -> None:
    row = Mock(
        id=uuid4(),
        workflow_id=uuid4(),
        organization_id=uuid4(),
        node_id="github-1",
        node_type="githubNode",
        parameter_key="api_token",
        status="active",
        encrypted_secret="ciphertext",
        encryption_key_version="test",
        encryption_algorithm="fernet-v1",
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = row

    with pytest.raises(WorkflowNodeSecretError, match="not available"):
        WorkflowNodeSecretService.resolve_reference(
            db,
            encryption=_encryption(),
            reference=f"workflow-node-secret://{row.id}",
            workflow_id=uuid4(),
            organization_id=row.organization_id,
            node_id="github-1",
            node_type="githubNode",
            parameter_key="api_token",
        )


def test_persistence_boundary_rejects_raw_secret_in_nested_graph() -> None:
    graph = {
        "nodes": [
            {
                "id": "loop-1",
                "type": "loopNode",
                "data": {
                    "subGraph": {
                        "nodes": [
                            {
                                "id": "github-1",
                                "type": "githubNode",
                                "data": {"api_token": "synthetic-raw-value"},
                            }
                        ]
                    }
                },
            }
        ]
    }

    with pytest.raises(WorkflowNodeSecretError, match="reference"):
        validate_workflow_node_secret_persistence_boundary(graph["nodes"])


def test_persistence_boundary_accepts_only_opaque_references() -> None:
    validate_workflow_node_secret_persistence_boundary(
        [
            {
                "id": "slack-1",
                "type": "slackPostNode",
                "data": {
                    "authConfig": {
                        "token": (
                            "workflow-node-secret://"
                            "00000000-0000-4000-8000-000000000001"
                        )
                    }
                },
            },
            {
                "id": "slack-2",
                "type": "slackPostNode",
                "data": {"url": None, "authConfig": {}},
            },
        ]
    )



@pytest.mark.parametrize(
    "data",
    [
        {
            "slackMode": "api",
            "url": "https://hooks.slack.test/services/legacy",
            "authConfig": {},
        },
        {
            "slackMode": "webhook",
            "url": None,
            "authConfig": {"token": "synthetic-inactive-token"},
        },
    ],
)
def test_persistence_boundary_rejects_inactive_slack_plaintext(data) -> None:
    with pytest.raises(WorkflowNodeSecretError, match="reference"):
        validate_workflow_node_secret_persistence_boundary(
            [{"id": "slack-1", "type": "slackPostNode", "data": data}]
        )


def test_legacy_graph_migration_replaces_raw_values_without_returning_them() -> None:
    db = Mock()
    workflow_id = uuid4()
    organization_id = uuid4()
    user_id = uuid4()
    raw_token = f"synthetic-{uuid4()}"
    graph = {
        "nodes": [
            {
                "id": "github-1",
                "type": "githubNode",
                "data": {"api_token": raw_token},
            }
        ],
        "edges": [],
    }

    migrated, changed = migrate_legacy_workflow_graph_secrets(
        db,
        graph=graph,
        encryption=_encryption(),
        workflow_id=workflow_id,
        organization_id=organization_id,
        user_id=user_id,
    )

    assert changed is True
    assert raw_token not in str(migrated)
    assert is_workflow_node_secret_reference(
        migrated["nodes"][0]["data"]["api_token"]
    )
    assert graph["nodes"][0]["data"]["api_token"] == raw_token


def test_response_redaction_keeps_references_and_drops_legacy_plaintext() -> None:
    reference = (
        "workflow-node-secret://00000000-0000-4000-8000-000000000001"
    )
    graph = {
        "nodes": [
            {
                "id": "slack-raw",
                "type": "slackPostNode",
                "data": {
                    "slackMode": "api",
                    "url": "https://hooks.slack.test/services/legacy",
                    "authConfig": {"token": "synthetic-raw-value"},
                },
            },
            {
                "id": "github-ref",
                "type": "githubNode",
                "data": {"api_token": reference},
            },
        ],
        "edges": [],
    }

    redacted = redact_legacy_workflow_node_secrets(graph)

    assert "token" not in redacted["nodes"][0]["data"]["authConfig"]
    assert "url" not in redacted["nodes"][0]["data"]
    assert redacted["nodes"][1]["data"]["api_token"] == reference
    assert graph["nodes"][0]["data"]["authConfig"]["token"] == (
        "synthetic-raw-value"
    )


def test_model_enforces_workflow_organization_scope_with_composite_fk() -> None:
    foreign_key_column_sets = {
        tuple(element.parent.name for element in constraint.elements)
        for constraint in WorkflowNodeSecret.__table__.foreign_key_constraints
    }

    assert ("workflow_id", "organization_id") in foreign_key_column_sets
