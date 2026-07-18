from __future__ import annotations

import os
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from apps.shared.audit.context import get_current_metadata
from apps.shared.db.models.external_action_credential import (
    EXTERNAL_ACTION_CREDENTIAL_ACTIVE,
    EXTERNAL_ACTION_CREDENTIAL_PROVIDERS,
    EXTERNAL_ACTION_CREDENTIAL_REVOKED,
    ExternalActionCredential,
)
from apps.shared.db.models.organization_membership import ORGANIZATION_AUTH_MEMBER
from apps.shared.db.models.team import (
    Team,
    TeamExternalActionCredentialPermission,
    TeamMembership,
    UserExternalActionCredentialPermission,
)
from apps.shared.domain.slack_delivery import is_valid_commercial_slack_webhook_url
from apps.shared.permissions import (
    AUTH_STATE_MANAGER,
    AUTH_STATE_NONE,
    external_action_credential_auth_state_allows,
    stronger_resource_auth_state,
)
from apps.shared.services.credential_encryption import (
    DEFAULT_KEY_VERSION,
    FERNET_ENCRYPTION_ALGORITHM,
    CredentialEncryptionError,
    CredentialEncryptionService,
    EncryptedSecretEnvelope,
)
from apps.shared.services.permission_audit import record_resource_permission_denied
from apps.shared.services.permissions import coerce_uuid, get_organization_auth_state
from sqlalchemy.orm import Session

EXTERNAL_ACTION_CREDENTIAL_KEYRING_ENV = "EXTERNAL_ACTION_CREDENTIAL_ENCRYPTION_KEYS"
EXTERNAL_ACTION_CREDENTIAL_ACTIVE_KEY_VERSION_ENV = (
    "EXTERNAL_ACTION_CREDENTIAL_ACTIVE_KEY_VERSION"
)
EXTERNAL_ACTION_CREDENTIAL_ALGORITHM = FERNET_ENCRYPTION_ALGORITHM
EXTERNAL_ACTION_CREDENTIAL_KEY_VERSION_MAX_LENGTH = 64
EXTERNAL_ACTION_CREDENTIAL_UNAVAILABLE = "external_action_credential.unavailable"


class ExternalActionCredentialError(ValueError):
    """Safe credential error that never includes stored provider material."""


class ExternalActionCredentialRuntimeError(RuntimeError):
    def __init__(self, reason_code: str = EXTERNAL_ACTION_CREDENTIAL_UNAVAILABLE):
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ResolvedExternalActionCredential:
    credential_id: uuid.UUID
    provider: str
    revision: int
    secret: str = field(repr=False)


class ExternalActionCredentialSecretService:
    """One encryption and validation boundary for external action credentials."""

    def __init__(self, encryption: CredentialEncryptionService):
        active_key_version = encryption.active_key_version
        if (
            not isinstance(active_key_version, str)
            or not active_key_version.strip()
            or len(active_key_version) > EXTERNAL_ACTION_CREDENTIAL_KEY_VERSION_MAX_LENGTH
        ):
            raise ExternalActionCredentialError(
                "External action credential encryption keyring is invalid."
            )
        self._encryption = encryption

    @classmethod
    def from_environment(cls) -> "ExternalActionCredentialSecretService":
        raw_keyring = os.getenv(EXTERNAL_ACTION_CREDENTIAL_KEYRING_ENV)
        configured_active_version = os.getenv(
            EXTERNAL_ACTION_CREDENTIAL_ACTIVE_KEY_VERSION_ENV
        )
        if not raw_keyring and configured_active_version not in (
            None,
            DEFAULT_KEY_VERSION,
        ):
            raise ExternalActionCredentialError(
                "External action credential encryption keyring is unavailable."
            )
        try:
            return cls(
                CredentialEncryptionService.from_environment_variables(
                    keyring_environment_variable=EXTERNAL_ACTION_CREDENTIAL_KEYRING_ENV,
                    active_version_environment_variable=(
                        EXTERNAL_ACTION_CREDENTIAL_ACTIVE_KEY_VERSION_ENV
                    ),
                    subject_label="External action credential",
                    algorithm=EXTERNAL_ACTION_CREDENTIAL_ALGORITHM,
                )
            )
        except CredentialEncryptionError as exc:
            raise ExternalActionCredentialError(
                "External action credential encryption keyring is unavailable."
            ) from exc

    @property
    def active_key_version(self) -> str:
        return self._encryption.active_key_version

    @property
    def algorithm(self) -> str:
        return self._encryption.algorithm

    def protect(self, provider: str, secret: str) -> EncryptedSecretEnvelope:
        self.validate_provider_secret(provider, secret)
        try:
            return self._encryption.encrypt(secret)
        except CredentialEncryptionError as exc:
            raise ExternalActionCredentialError(
                "External action credential could not be protected."
            ) from exc

    def load(self, credential: ExternalActionCredential, expected_provider: str) -> str:
        if credential.provider != expected_provider:
            raise ExternalActionCredentialError(
                "External action credential is unavailable."
            )
        if not (
            isinstance(credential.encrypted_secret, str)
            and credential.encrypted_secret
            and isinstance(credential.encryption_key_version, str)
            and credential.encryption_key_version
            and isinstance(credential.encryption_algorithm, str)
            and credential.encryption_algorithm
        ):
            raise ExternalActionCredentialError(
                "External action credential is unavailable."
            )
        try:
            secret = self._encryption.decrypt(
                EncryptedSecretEnvelope(
                    ciphertext=credential.encrypted_secret,
                    key_version=credential.encryption_key_version,
                    algorithm=credential.encryption_algorithm,
                )
            )
        except CredentialEncryptionError as exc:
            raise ExternalActionCredentialError(
                "External action credential is unavailable."
            ) from exc
        self.validate_provider_secret(credential.provider, secret)
        return secret

    @staticmethod
    def validate_provider_secret(provider: str, secret: str) -> None:
        if provider not in EXTERNAL_ACTION_CREDENTIAL_PROVIDERS:
            raise ExternalActionCredentialError(
                "External action credential provider is invalid."
            )
        max_bytes = 2048 if provider == "slack_webhook" else 4096
        if (
            not isinstance(secret, str)
            or not secret
            or secret != secret.strip()
            or len(secret.encode("utf-8")) > max_bytes
            or any(char in secret for char in "\r\n\x00")
        ):
            raise ExternalActionCredentialError(
                "External action credential secret is invalid."
            )
        if provider == "slack_webhook" and not is_valid_commercial_slack_webhook_url(
            secret
        ):
            raise ExternalActionCredentialError(
                "External action credential secret is invalid."
            )


def get_external_action_credential_secret_service() -> (
    ExternalActionCredentialSecretService
):
    return ExternalActionCredentialSecretService.from_environment()


def require_external_action_credential_keyring_ready() -> None:
    """Validate the external action keyring without decrypting a credential."""
    get_external_action_credential_secret_service()


def get_effective_external_action_credential_auth_state(
    db: Session,
    user_id: Any,
    credential_id: Any,
    organization_id: Any = None,
    *,
    include_revoked: bool = False,
) -> str:
    user_uuid = coerce_uuid(user_id)
    credential_uuid = coerce_uuid(credential_id)
    organization_uuid = coerce_uuid(organization_id)
    if user_uuid is None or credential_uuid is None:
        return AUTH_STATE_NONE

    filters = [ExternalActionCredential.id == credential_uuid]
    if not include_revoked:
        filters.append(
            ExternalActionCredential.status == EXTERNAL_ACTION_CREDENTIAL_ACTIVE
        )
    query = db.query(ExternalActionCredential).filter(*filters)
    if organization_uuid is not None:
        query = query.filter(ExternalActionCredential.organization_id == organization_uuid)
    credential = query.first()
    if credential is None:
        return AUTH_STATE_NONE
    organization_uuid = credential.organization_id

    organization_auth_state = get_organization_auth_state(
        db, user_uuid, organization_uuid
    )
    if organization_auth_state == AUTH_STATE_MANAGER:
        return AUTH_STATE_MANAGER
    if organization_auth_state != ORGANIZATION_AUTH_MEMBER:
        return AUTH_STATE_NONE

    team_rows = (
        db.query(TeamExternalActionCredentialPermission.auth_state)
        .join(
            TeamMembership,
            TeamMembership.team_id == TeamExternalActionCredentialPermission.team_id,
        )
        .join(Team, Team.id == TeamExternalActionCredentialPermission.team_id)
        .filter(
            TeamMembership.user_id == user_uuid,
            TeamExternalActionCredentialPermission.external_action_credential_id
            == credential.id,
            Team.is_active.is_(True),
            TeamMembership.grantee_organization_id == organization_uuid,
            TeamExternalActionCredentialPermission.grantee_organization_id
            == organization_uuid,
            TeamMembership.grantee_organization_id
            == TeamExternalActionCredentialPermission.grantee_organization_id,
            Team.organization_id == organization_uuid,
        )
        .all()
    )
    direct_rows = (
        db.query(UserExternalActionCredentialPermission.auth_state)
        .filter(
            UserExternalActionCredentialPermission.user_id == user_uuid,
            UserExternalActionCredentialPermission.external_action_credential_id
            == credential.id,
            UserExternalActionCredentialPermission.grantee_organization_id
            == organization_uuid,
        )
        .all()
    )
    effective_state = AUTH_STATE_NONE
    for row in [*team_rows, *direct_rows]:
        state = getattr(row, "auth_state", row[0] if isinstance(row, tuple) else None)
        effective_state = stronger_resource_auth_state(effective_state, state)
    return effective_state


def get_effective_external_action_credential_auth_states(
    db: Session,
    user_id: Any,
    credential_ids: Iterable[Any],
    organization_id: Any,
    *,
    include_revoked: bool = False,
) -> dict[uuid.UUID, str]:
    """Resolve external action credential auth states with a fixed query count."""

    user_uuid = coerce_uuid(user_id)
    organization_uuid = coerce_uuid(organization_id)
    requested_ids = {
        credential_id
        for raw_id in credential_ids
        if (credential_id := coerce_uuid(raw_id)) is not None
    }
    if user_uuid is None or organization_uuid is None or not requested_ids:
        return {}

    lifecycle_filter = (
        ExternalActionCredential.status.in_(
            (
                EXTERNAL_ACTION_CREDENTIAL_ACTIVE,
                EXTERNAL_ACTION_CREDENTIAL_REVOKED,
            )
        )
        if include_revoked
        else ExternalActionCredential.status == EXTERNAL_ACTION_CREDENTIAL_ACTIVE
    )
    scoped_rows = (
        db.query(ExternalActionCredential.id, ExternalActionCredential.status)
        .filter(
            ExternalActionCredential.id.in_(requested_ids),
            ExternalActionCredential.organization_id == organization_uuid,
            lifecycle_filter,
        )
        .all()
    )
    allowed_statuses = {EXTERNAL_ACTION_CREDENTIAL_ACTIVE}
    if include_revoked:
        allowed_statuses.add(EXTERNAL_ACTION_CREDENTIAL_REVOKED)
    scoped_ids: set[uuid.UUID] = set()
    for row in scoped_rows:
        credential_id, status = _external_action_credential_scope_values(row)
        credential_uuid = coerce_uuid(credential_id)
        if credential_uuid is not None and status in allowed_statuses:
            scoped_ids.add(credential_uuid)
    if not scoped_ids:
        return {}

    organization_auth_state = get_organization_auth_state(
        db,
        user_uuid,
        organization_uuid,
    )
    if organization_auth_state == AUTH_STATE_MANAGER:
        return {credential_id: AUTH_STATE_MANAGER for credential_id in scoped_ids}
    if organization_auth_state != ORGANIZATION_AUTH_MEMBER:
        return {credential_id: AUTH_STATE_NONE for credential_id in scoped_ids}

    team_rows = (
        db.query(
            TeamExternalActionCredentialPermission.external_action_credential_id,
            TeamExternalActionCredentialPermission.auth_state,
        )
        .join(
            TeamMembership,
            TeamMembership.team_id == TeamExternalActionCredentialPermission.team_id,
        )
        .join(Team, Team.id == TeamExternalActionCredentialPermission.team_id)
        .filter(
            TeamMembership.user_id == user_uuid,
            TeamExternalActionCredentialPermission.external_action_credential_id.in_(
                scoped_ids
            ),
            Team.is_active.is_(True),
            TeamMembership.grantee_organization_id == organization_uuid,
            TeamExternalActionCredentialPermission.grantee_organization_id
            == organization_uuid,
            TeamMembership.grantee_organization_id
            == TeamExternalActionCredentialPermission.grantee_organization_id,
            Team.organization_id == organization_uuid,
        )
        .all()
    )
    direct_rows = (
        db.query(
            UserExternalActionCredentialPermission.external_action_credential_id,
            UserExternalActionCredentialPermission.auth_state,
        )
        .filter(
            UserExternalActionCredentialPermission.user_id == user_uuid,
            UserExternalActionCredentialPermission.external_action_credential_id.in_(
                scoped_ids
            ),
            UserExternalActionCredentialPermission.grantee_organization_id
            == organization_uuid,
        )
        .all()
    )

    result = {credential_id: AUTH_STATE_NONE for credential_id in scoped_ids}
    for row in (*team_rows, *direct_rows):
        credential_id, auth_state = _external_action_resource_auth_state_values(row)
        credential_uuid = coerce_uuid(credential_id)
        if credential_uuid not in result:
            continue
        result[credential_uuid] = stronger_resource_auth_state(
            result[credential_uuid],
            auth_state,
        )
    return result


def _external_action_credential_scope_values(row: Any) -> tuple[Any, str]:
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return (
            mapping.get("id"),
            mapping.get("status", EXTERNAL_ACTION_CREDENTIAL_ACTIVE),
        )
    if isinstance(row, tuple):
        return (
            row[0] if row else None,
            row[1] if len(row) >= 2 else EXTERNAL_ACTION_CREDENTIAL_ACTIVE,
        )
    return getattr(row, "id", row), getattr(
        row,
        "status",
        EXTERNAL_ACTION_CREDENTIAL_ACTIVE,
    )


def _external_action_resource_auth_state_values(row: Any) -> tuple[Any, Any]:
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return (
            mapping.get("external_action_credential_id"),
            mapping.get("auth_state", AUTH_STATE_NONE),
        )
    if isinstance(row, tuple) and len(row) >= 2:
        return row[0], row[1]
    return None, AUTH_STATE_NONE


def has_external_action_credential_permission(
    db: Session,
    user_id: Any,
    credential_id: Any,
    action: str,
    organization_id: Any = None,
    *,
    include_revoked: bool = False,
) -> bool:
    return external_action_credential_auth_state_allows(
        get_effective_external_action_credential_auth_state(
            db,
            user_id,
            credential_id,
            organization_id,
            include_revoked=include_revoked,
        ),
        action,
    )


class ExternalActionCredentialUseResolver:
    """Authoritative resolver for graph binding and provider-call admission."""

    @staticmethod
    def _audit_metadata() -> dict[str, Any]:
        """Keep correlation identifiers without copying credential material."""

        metadata = get_current_metadata()
        return {
            key: value
            for key, value in metadata.items()
            if key
            in {
                "request_id",
                "correlation_id",
                "workflow_id",
                "workflow_run_id",
                "workflow_node_run_id",
            }
        }

    @staticmethod
    def revalidate_use(
        db: Session,
        *,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        expected_provider: str,
        expected_revision: int | None = None,
    ) -> None:
        credential = (
            db.query(ExternalActionCredential)
            .populate_existing()
            .filter(
                ExternalActionCredential.id == credential_id,
                ExternalActionCredential.organization_id == organization_id,
                ExternalActionCredential.status == EXTERNAL_ACTION_CREDENTIAL_ACTIVE,
                ExternalActionCredential.provider == expected_provider,
            )
            .first()
        )
        if credential is None:
            raise ExternalActionCredentialRuntimeError()
        if (
            expected_revision is not None
            and credential.revision != expected_revision
        ):
            # Do not use a decrypted secret that was resolved before rotation.
            raise ExternalActionCredentialRuntimeError()
        if not has_external_action_credential_permission(
            db,
            user_id,
            credential_id,
            "use",
            organization_id=organization_id,
        ):
            record_resource_permission_denied(
                user_id=user_id,
                resource_type="external_action_credential",
                resource_id=credential.id,
                action="use",
                effective_auth_state=get_effective_external_action_credential_auth_state(
                    db,
                    user_id,
                    credential.id,
                    organization_id=organization_id,
                ),
                organization_id=organization_id,
                metadata=ExternalActionCredentialUseResolver._audit_metadata(),
            )
            raise ExternalActionCredentialRuntimeError()

    @staticmethod
    def resolve(
        db: Session,
        *,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        expected_provider: str,
    ) -> ResolvedExternalActionCredential:
        credential = (
            db.query(ExternalActionCredential)
            .populate_existing()
            .filter(
                ExternalActionCredential.id == credential_id,
                ExternalActionCredential.organization_id == organization_id,
                ExternalActionCredential.status == EXTERNAL_ACTION_CREDENTIAL_ACTIVE,
                ExternalActionCredential.provider == expected_provider,
            )
            .first()
        )
        if credential is None:
            raise ExternalActionCredentialRuntimeError()
        if not has_external_action_credential_permission(
            db,
            user_id,
            credential.id,
            "use",
            organization_id=organization_id,
        ):
            record_resource_permission_denied(
                user_id=user_id,
                resource_type="external_action_credential",
                resource_id=credential.id,
                action="use",
                effective_auth_state=get_effective_external_action_credential_auth_state(
                    db,
                    user_id,
                    credential.id,
                    organization_id=organization_id,
                ),
                organization_id=organization_id,
                metadata=ExternalActionCredentialUseResolver._audit_metadata(),
            )
            raise ExternalActionCredentialRuntimeError()
        try:
            secret = get_external_action_credential_secret_service().load(
                credential, expected_provider
            )
        except ExternalActionCredentialError as exc:
            raise ExternalActionCredentialRuntimeError() from exc
        return ResolvedExternalActionCredential(
            credential_id=credential.id,
            provider=credential.provider,
            revision=credential.revision,
            secret=secret,
        )
