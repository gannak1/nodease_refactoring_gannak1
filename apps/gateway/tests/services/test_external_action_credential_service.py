from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from apps.gateway.services.external_action_credential_service import (
    ExternalActionCredentialNotFound,
    ExternalActionCredentialRevoked,
    ExternalActionCredentialTargetNotFound,
    ExternalActionCredentialService,
)
from apps.shared.audit.context import clear_current_metadata, set_current_metadata
from apps.shared.schemas.external_action_credential import (
    ExternalActionCredentialPermissionGrant,
    ExternalActionCredentialUpdate,
)


NOW = datetime(2026, 7, 18, tzinfo=timezone.utc)


def _credential(**overrides):
    values = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "credential_name": "운영 Slack 알림",
        "provider": "slack_api",
        "status": "active",
        "revision": 1,
        "created_at": NOW,
        "updated_at": NOW,
        "revoked_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_safe_response_never_serializes_secret_or_encryption_fields():
    payload = ExternalActionCredentialService._response(_credential()).model_dump()

    assert set(payload) == {
        "id",
        "organization_id",
        "credential_name",
        "provider",
        "status",
        "revision",
        "created_at",
        "updated_at",
        "revoked_at",
    }


@patch(
    "apps.gateway.services.external_action_credential_service."
    "has_external_action_credential_permission"
)
@patch(
    "apps.gateway.services.external_action_credential_service."
    "get_organization_auth_state",
    return_value="manager",
)
def test_picker_uses_manager_override_without_per_credential_permission_queries(
    _organization_auth_state,
    has_permission,
):
    credential = _credential()
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        credential
    ]

    result = ExternalActionCredentialService(db).list_available(
        uuid4(), credential.organization_id
    )

    assert [item.id for item in result] == [credential.id]
    has_permission.assert_not_called()


@patch(
    "apps.gateway.services.external_action_credential_service."
    "record_resource_permission_denied"
)
@patch(
    "apps.gateway.services.external_action_credential_service."
    "get_effective_external_action_credential_auth_state",
    return_value="viewer",
)
@patch(
    "apps.gateway.services.external_action_credential_service."
    "has_external_action_credential_permission",
    return_value=False,
)
def test_same_organization_denial_is_hidden_and_audit_metadata_is_allowlisted(
    _permission,
    _auth_state,
    record_denial,
):
    credential = _credential()
    service = ExternalActionCredentialService(MagicMock())
    token = set_current_metadata(
        {
            "request_id": "request-safe",
            "ip": "203.0.113.10",
            "user_agent": "test-agent",
            "method": "PATCH",
            "path": "/must-not-be-recorded",
        }
    )
    try:
        with pytest.raises(ExternalActionCredentialNotFound):
            service._require(
                uuid4(),
                credential.organization_id,
                credential,
                "manage",
            )
    finally:
        clear_current_metadata(token)

    assert record_denial.call_args.kwargs["metadata"] == {
        "request_id": "request-safe",
        "ip": "203.0.113.10",
        "user_agent": "test-agent",
    }


@patch(
    "apps.gateway.services.external_action_credential_service."
    "has_external_action_credential_permission",
    return_value=True,
)
def test_revoked_credential_allows_management_lookup_but_rejects_update(
    has_permission,
):
    credential = _credential(status="revoked")
    db = MagicMock()
    service = ExternalActionCredentialService(db)
    service._get_scoped = MagicMock(return_value=credential)

    with pytest.raises(ExternalActionCredentialRevoked):
        service.update(
            uuid4(),
            credential.organization_id,
            credential.id,
            ExternalActionCredentialUpdate(
                expected_revision=credential.revision,
                credential_name="교체 예정 Credential",
            ),
        )

    assert has_permission.call_args.kwargs["include_revoked"] is True
    db.commit.assert_not_called()


@patch(
    "apps.gateway.services.external_action_credential_service."
    "has_external_action_credential_permission",
    return_value=True,
)
def test_revoked_credential_allows_existing_user_permission_revoke(has_permission):
    credential = _credential(status="revoked")
    db = MagicMock()
    db.query.return_value.filter.return_value.delete.return_value = 1
    service = ExternalActionCredentialService(db)
    service._get_scoped = MagicMock(return_value=credential)

    service.revoke_user_permission(
        uuid4(),
        credential.organization_id,
        credential.id,
        uuid4(),
    )

    assert has_permission.call_args.kwargs["include_revoked"] is True
    db.commit.assert_called_once_with()


def test_grant_user_permission_locks_active_membership_and_rejects_deactivated_user():
    db = MagicMock()
    membership_query = MagicMock()
    db.query.return_value = membership_query
    membership_query.join.return_value = membership_query
    membership_query.filter.return_value = membership_query
    membership_query.with_for_update.return_value = membership_query
    membership_query.first.return_value = None
    credential = _credential()
    service = ExternalActionCredentialService(db)
    service._get_scoped = MagicMock(return_value=credential)
    service._require = MagicMock()

    with pytest.raises(ExternalActionCredentialTargetNotFound):
        service.grant_user_permission(
            uuid4(),
            credential.organization_id,
            credential.id,
            uuid4(),
            ExternalActionCredentialPermissionGrant(auth_state="operator"),
        )

    predicates = {str(predicate) for predicate in membership_query.filter.call_args.args}
    assert "users.deactivated_at IS NULL" in predicates
    membership_query.join.assert_called_once()
    membership_query.with_for_update.assert_called_once_with()
    db.commit.assert_not_called()
