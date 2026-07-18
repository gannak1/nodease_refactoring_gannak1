from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from apps.shared.services.credential_encryption import EncryptedSecretEnvelope
from apps.shared.services.external_action_credential import (
    EXTERNAL_ACTION_CREDENTIAL_ALGORITHM,
    ExternalActionCredentialRuntimeError,
    ExternalActionCredentialSecretService,
    ExternalActionCredentialUseResolver,
    get_effective_external_action_credential_auth_state,
    get_effective_external_action_credential_auth_states,
)


def _credential(**overrides):
    values = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "provider": "github",
        "status": "active",
        "encrypted_secret": "synthetic-ciphertext",
        "encryption_key_version": "v1",
        "encryption_algorithm": EXTERNAL_ACTION_CREDENTIAL_ALGORITHM,
        "revision": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _db_returning(value):
    query = MagicMock()
    query.populate_existing.return_value = query
    query.filter.return_value = query
    query.first.return_value = value
    db = MagicMock()
    db.query.return_value = query
    return db


def test_secret_service_protects_valid_provider_secret_without_exposing_it():
    encryption = MagicMock(
        active_key_version="v1",
        algorithm=EXTERNAL_ACTION_CREDENTIAL_ALGORITHM,
    )
    envelope = EncryptedSecretEnvelope(
        ciphertext="synthetic-ciphertext",
        key_version="v1",
        algorithm=EXTERNAL_ACTION_CREDENTIAL_ALGORITHM,
    )
    encryption.encrypt.return_value = envelope

    result = ExternalActionCredentialSecretService(encryption).protect(
        "github", "synthetic-secret"
    )

    assert result == envelope
    encryption.encrypt.assert_called_once_with("synthetic-secret")


@patch(
    "apps.shared.services.external_action_credential."
    "has_external_action_credential_permission",
    return_value=True,
)
@patch(
    "apps.shared.services.external_action_credential."
    "get_external_action_credential_secret_service"
)
def test_resolver_returns_secret_only_after_matching_active_credential(
    secret_service_factory,
    _permission,
):
    credential = _credential()
    secret_service_factory.return_value.load.return_value = "synthetic-secret"

    resolved = ExternalActionCredentialUseResolver.resolve(
        _db_returning(credential),
        user_id=uuid4(),
        organization_id=credential.organization_id,
        credential_id=credential.id,
        expected_provider="github",
    )

    assert resolved.credential_id == credential.id
    assert resolved.revision == 3
    assert resolved.secret == "synthetic-secret"
    assert "synthetic-secret" not in repr(resolved)
    secret_service_factory.return_value.load.assert_called_once_with(credential, "github")


@patch(
    "apps.shared.services.external_action_credential."
    "record_resource_permission_denied"
)
@patch(
    "apps.shared.services.external_action_credential."
    "get_effective_external_action_credential_auth_state",
    return_value="none",
)
@patch(
    "apps.shared.services.external_action_credential."
    "has_external_action_credential_permission",
    return_value=False,
)
def test_resolver_denies_before_decryption_and_records_only_safe_audit_metadata(
    _permission,
    _auth_state,
    record_denial,
):
    credential = _credential()

    with (
        patch(
            "apps.shared.services.external_action_credential."
            "get_external_action_credential_secret_service"
        ) as secret_service_factory,
        pytest.raises(
            ExternalActionCredentialRuntimeError,
            match="^external_action_credential.unavailable$",
        ),
    ):
        ExternalActionCredentialUseResolver.resolve(
            _db_returning(credential),
            user_id=uuid4(),
            organization_id=credential.organization_id,
            credential_id=credential.id,
            expected_provider="github",
        )

    secret_service_factory.assert_not_called()
    assert record_denial.call_args.kwargs["metadata"] == {}


@patch(
    "apps.shared.services.external_action_credential."
    "has_external_action_credential_permission"
)
def test_revalidation_rejects_rotation_before_permission_or_provider_use(permission):
    credential = _credential(revision=3)

    with pytest.raises(
        ExternalActionCredentialRuntimeError,
        match="^external_action_credential.unavailable$",
    ):
        ExternalActionCredentialUseResolver.revalidate_use(
            _db_returning(credential),
            user_id=uuid4(),
            organization_id=credential.organization_id,
            credential_id=credential.id,
            expected_provider="github",
            expected_revision=2,
        )

    permission.assert_not_called()


def test_resolver_hides_missing_or_cross_organization_credential():
    with pytest.raises(
        ExternalActionCredentialRuntimeError,
        match="^external_action_credential.unavailable$",
    ):
        ExternalActionCredentialUseResolver.resolve(
            _db_returning(None),
            user_id=uuid4(),
            organization_id=uuid4(),
            credential_id=uuid4(),
            expected_provider="github",
        )


@patch(
    "apps.shared.services.external_action_credential."
    "get_organization_auth_state",
    return_value="manager",
)
def test_management_auth_lookup_includes_revoked_credential(_organization_auth_state):
    credential = _credential(status="revoked")
    db = _db_returning(credential)

    assert (
        get_effective_external_action_credential_auth_state(
            db,
            uuid4(),
            credential.id,
            organization_id=credential.organization_id,
            include_revoked=True,
        )
        == "manager"
    )

    predicates = [
        predicate
        for call in db.query.return_value.filter.call_args_list
        for predicate in call.args
    ]
    assert not any("external_action_credentials.status" in str(item) for item in predicates)


@patch(
    "apps.shared.services.external_action_credential."
    "get_organization_auth_state",
    return_value="manager",
)
def test_bulk_auth_state_resolver_uses_manager_override_without_per_resource_queries(
    _organization_auth_state,
):
    credential = _credential()
    query = MagicMock()
    query.filter.return_value = query
    query.all.return_value = [credential]
    db = MagicMock()
    db.query.return_value = query

    result = get_effective_external_action_credential_auth_states(
        db,
        uuid4(),
        [credential.id],
        credential.organization_id,
    )

    assert result == {credential.id: "manager"}
    assert db.query.call_count == 1


@patch(
    "apps.shared.services.external_action_credential."
    "get_organization_auth_state",
    return_value="manager",
)
def test_bulk_management_auth_state_resolver_includes_revoked_credential(
    _organization_auth_state,
):
    credential = _credential(status="revoked")
    query = MagicMock()
    query.filter.return_value = query
    query.all.return_value = [credential]
    db = MagicMock()
    db.query.return_value = query

    result = get_effective_external_action_credential_auth_states(
        db,
        uuid4(),
        [credential.id],
        credential.organization_id,
        include_revoked=True,
    )

    assert result == {credential.id: "manager"}
