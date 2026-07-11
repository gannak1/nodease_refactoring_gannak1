from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from apps.shared.audit.context import get_current_metadata
from apps.shared.db.models.mail_credential import (
    MAIL_CREDENTIAL_ACTIVE,
    MailCredential,
)
from apps.shared.services.credential_encryption import (
    CredentialEncryptionError,
    EncryptedSecretEnvelope,
    get_credential_encryption_service,
)
from apps.shared.services.egress_guard import (
    EgressGuardError,
    ensure_network_target_allowed,
)
from apps.shared.services.permission_audit import record_resource_permission_denied
from apps.shared.services.permissions import (
    get_effective_mail_credential_auth_state,
    has_mail_credential_permission,
)


class MailCredentialRuntimeError(RuntimeError):
    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ResolvedMailCredential:
    credential_id: uuid.UUID
    email_address: str
    imap_host: str
    imap_port: int
    resolved_ip: str
    use_ssl: bool
    secret: str = field(repr=False)


class MailCredentialResolver:
    @staticmethod
    def resolve(
        db: Session,
        *,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
    ) -> ResolvedMailCredential:
        credential = (
            db.query(MailCredential)
            .filter(
                MailCredential.id == credential_id,
                MailCredential.organization_id == organization_id,
            )
            .first()
        )
        if credential is None or credential.status != MAIL_CREDENTIAL_ACTIVE:
            raise MailCredentialRuntimeError("mail.credential_not_available")

        if not has_mail_credential_permission(
            db,
            user_id,
            credential.id,
            "use",
            organization_id=organization_id,
        ):
            record_resource_permission_denied(
                user_id=user_id,
                resource_type="mail_credential",
                resource_id=credential.id,
                action="use",
                effective_auth_state=get_effective_mail_credential_auth_state(
                    db,
                    user_id,
                    credential.id,
                    organization_id=organization_id,
                ),
                organization_id=organization_id,
                metadata=get_current_metadata(),
            )
            raise MailCredentialRuntimeError("mail.credential_permission_denied")

        expected_port = 993 if credential.use_ssl else 143
        if credential.imap_port != expected_port:
            raise MailCredentialRuntimeError("mail.egress_target_denied")

        try:
            canonical_host, safe_port, resolved_ip = ensure_network_target_allowed(
                credential.imap_host,
                credential.imap_port,
                allowed_ports=frozenset({143, 993}),
            )
        except EgressGuardError as exc:
            raise MailCredentialRuntimeError("mail.egress_target_denied") from exc

        try:
            secret = get_credential_encryption_service().decrypt(
                EncryptedSecretEnvelope(
                    ciphertext=credential.encrypted_secret,
                    key_version=credential.encryption_key_version,
                    algorithm=credential.encryption_algorithm,
                )
            )
        except CredentialEncryptionError as exc:
            raise MailCredentialRuntimeError(
                "mail.credential_decryption_failed"
            ) from exc

        return ResolvedMailCredential(
            credential_id=credential.id,
            email_address=credential.email_address,
            imap_host=canonical_host,
            imap_port=safe_port,
            resolved_ip=resolved_ip,
            use_ssl=credential.use_ssl,
            secret=secret,
        )
