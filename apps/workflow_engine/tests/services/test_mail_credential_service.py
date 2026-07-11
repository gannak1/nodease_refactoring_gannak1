import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.shared.services.credential_encryption import EncryptedSecretEnvelope
from apps.workflow_engine.services.mail_credential_service import (
    MailCredentialResolver,
    MailCredentialRuntimeError,
)


def _credential(**overrides):
    values = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "status": "active",
        "email_address": "mailbox@example.test",
        "imap_host": "imap.example.test",
        "imap_port": 993,
        "use_ssl": True,
        "encrypted_secret": "synthetic-ciphertext",
        "encryption_key_version": "v1",
        "encryption_algorithm": "fernet-v1",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _db_returning(value):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = value
    return db


@patch(
    "apps.workflow_engine.services.mail_credential_service."
    "has_mail_credential_permission",
    return_value=True,
)
@patch(
    "apps.workflow_engine.services.mail_credential_service."
    "ensure_network_target_allowed",
    return_value=("imap.example.test", 993, "203.0.113.10"),
)
@patch(
    "apps.workflow_engine.services.mail_credential_service."
    "get_credential_encryption_service"
)
def test_resolver_returns_runtime_secret_only_after_permission(
    encryption_factory, _egress, _permission
):
    credential = _credential()
    encryption_factory.return_value.decrypt.return_value = "synthetic-mail-secret"

    resolved = MailCredentialResolver.resolve(
        _db_returning(credential),
        user_id=uuid.uuid4(),
        organization_id=credential.organization_id,
        credential_id=credential.id,
    )

    assert resolved.credential_id == credential.id
    assert resolved.secret == "synthetic-mail-secret"
    assert resolved.resolved_ip == "203.0.113.10"
    assert "synthetic-mail-secret" not in repr(resolved)
    encryption_factory.return_value.decrypt.assert_called_once_with(
        EncryptedSecretEnvelope(
            ciphertext=credential.encrypted_secret,
            key_version="v1",
            algorithm="fernet-v1",
        )
    )


def test_resolver_rejects_missing_or_cross_organization_credential():
    with pytest.raises(
        MailCredentialRuntimeError, match="^mail.credential_not_available$"
    ):
        MailCredentialResolver.resolve(
            _db_returning(None),
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
        )


@patch(
    "apps.workflow_engine.services.mail_credential_service."
    "record_resource_permission_denied"
)
@patch(
    "apps.workflow_engine.services.mail_credential_service."
    "get_effective_mail_credential_auth_state",
    return_value="none",
)
@patch(
    "apps.workflow_engine.services.mail_credential_service."
    "has_mail_credential_permission",
    return_value=False,
)
def test_resolver_denies_use_before_decryption(_permission, _auth_state, record_denial):
    credential = _credential()

    with (
        patch(
            "apps.workflow_engine.services.mail_credential_service."
            "get_credential_encryption_service"
        ) as encryption_factory,
        pytest.raises(
            MailCredentialRuntimeError,
            match="^mail.credential_permission_denied$",
        ),
    ):
        MailCredentialResolver.resolve(
            _db_returning(credential),
            user_id=uuid.uuid4(),
            organization_id=credential.organization_id,
            credential_id=credential.id,
        )

    encryption_factory.assert_not_called()
    record_denial.assert_called_once()
