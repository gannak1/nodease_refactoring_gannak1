import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from apps.gateway.services.workflow_service import WorkflowService
from apps.shared.schemas.workflow import NodeSchema, Position, WorkflowDraftRequest


def _request(data: dict) -> WorkflowDraftRequest:
    return WorkflowDraftRequest(
        nodes=[
            NodeSchema(
                id="mail-1",
                type="mailNode",
                position=Position(x=0, y=0),
                data=data,
            )
        ]
    )


def test_draft_rejects_legacy_mail_secret_without_echoing_value():
    secret = "synthetic-legacy-secret"

    with pytest.raises(HTTPException) as exc:
        WorkflowService.validate_mail_credential_references(
            MagicMock(),
            _request(
                {
                    "title": "Legacy Mail",
                    "email": "mailbox@example.test",
                    "password": secret,
                }
            ),
            user_id=str(uuid.uuid4()),
            organization_id=uuid.uuid4(),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "mail.credential_reference_required"
    assert secret not in str(exc.value)


def test_unresolved_mail_reference_can_be_saved_for_preview():
    db = MagicMock()

    WorkflowService.validate_mail_credential_references(
        db,
        _request(
            {
                "title": "Mail",
                "credential_id": None,
                "configuration_state": "unresolved",
            }
        ),
        user_id=str(uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    db.query.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        {"title": "Mail", "credential_id": None, "app_password": "synthetic-only"},
        {
            "title": "Mail",
            "credential_id": None,
            "parameters": {"secret": "synthetic-only"},
        },
    ],
)
def test_draft_rejects_alternate_mail_secret_storage(data):
    with pytest.raises(HTTPException) as exc:
        WorkflowService.validate_mail_credential_references(
            MagicMock(),
            _request(data),
            user_id=str(uuid.uuid4()),
            organization_id=uuid.uuid4(),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "mail.credential_reference_required"
    assert "synthetic-only" not in str(exc.value)


@patch("apps.gateway.services.workflow_service.record_resource_permission_denied")
@patch(
    "apps.gateway.services.workflow_service.get_effective_mail_credential_auth_state",
    return_value="none",
)
@patch(
    "apps.gateway.services.workflow_service.has_mail_credential_permission",
    return_value=False,
)
def test_draft_rechecks_mail_credential_use_permission(
    _permission, _auth_state, record_denial
):
    organization_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=credential_id
    )

    with pytest.raises(HTTPException) as exc:
        WorkflowService.validate_mail_credential_references(
            db,
            _request({"title": "Mail", "credential_id": str(credential_id)}),
            user_id=str(uuid.uuid4()),
            organization_id=organization_id,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "mail.credential_permission_denied"
    record_denial.assert_called_once()


def test_draft_hides_cross_organization_or_missing_credential():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc:
        WorkflowService.validate_mail_credential_references(
            db,
            _request({"title": "Mail", "credential_id": str(uuid.uuid4())}),
            user_id=str(uuid.uuid4()),
            organization_id=uuid.uuid4(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "resource.not_found"


def test_raw_agent_builder_graph_rejects_legacy_inline_secret():
    secret = "synthetic-agent-builder-legacy-secret"

    with pytest.raises(HTTPException) as exc:
        WorkflowService.validate_mail_credential_references(
            MagicMock(),
            {
                "nodes": [
                    {
                        "id": "mail-1",
                        "type": "mailNode",
                        "data": {"credential_id": None, "password": secret},
                    }
                ],
                "edges": [],
            },
            user_id=str(uuid.uuid4()),
            organization_id=uuid.uuid4(),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "mail.credential_reference_required"
    assert secret not in str(exc.value)


def test_raw_deployment_graph_rejects_non_object_mail_data():
    with pytest.raises(HTTPException) as exc:
        WorkflowService.validate_mail_credential_references(
            MagicMock(),
            {
                "nodes": [
                    {
                        "id": "mail-1",
                        "type": "mailNode",
                        "data": "synthetic-only",
                    }
                ],
                "edges": [],
            },
            user_id=str(uuid.uuid4()),
            organization_id=uuid.uuid4(),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "mail.credential_reference_required"
    assert "synthetic-only" not in str(exc.value)
