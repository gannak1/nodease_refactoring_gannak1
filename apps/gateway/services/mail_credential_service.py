from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from apps.shared.audit.actions import AuditAction
from apps.shared.audit.context import get_current_metadata
from apps.shared.audit.manual_ownership import register_manual_audit_ownership
from apps.shared.db.models.audit_log import (
    ActorType,
    AuditCategory,
    AuditLog,
    AuditStatus,
)
from apps.shared.db.models.mail_credential import (
    MAIL_CREDENTIAL_ACTIVE,
    MAIL_CREDENTIAL_REVOKED,
    MailCredential,
)
from apps.shared.db.models.organization_membership import (
    ORGANIZATION_AUTH_MANAGER,
    ORGANIZATION_AUTH_MEMBER,
    ORGANIZATION_MEMBERSHIP_ACTIVE,
    OrganizationMembership,
)
from apps.shared.db.models.team import (
    Team,
    TeamMailCredentialPermission,
    TeamMembership,
    UserMailCredentialPermission,
)
from apps.shared.db.models.user import User
from apps.shared.schemas.mail_credential import (
    MailCredentialCreate,
    MailCredentialOptionResponse,
    MailCredentialPermissionGrant,
    MailCredentialResponse,
    MailCredentialUpdate,
)
from apps.shared.services.credential_encryption import (
    CredentialEncryptionService,
    get_credential_encryption_service,
)
from apps.shared.services.egress_guard import (
    EgressGuardError,
    ensure_network_target_allowed,
)
from apps.shared.services.permission_audit import record_resource_permission_denied
from apps.shared.services.permissions import (
    get_effective_mail_credential_auth_state,
    get_organization_auth_state,
    has_mail_credential_permission,
    has_organization_manager_permission,
)
from apps.shared.permissions import (
    mail_credential_auth_state_allows,
    stronger_resource_auth_state,
)


class MailCredentialServiceError(Exception):
    status_code = 400
    code = "mail.credential_error"
    detail = "Mail credential request failed."


class MailCredentialNotFound(MailCredentialServiceError):
    status_code = 404
    code = "resource.not_found"
    detail = "Mail credential not found."


class MailCredentialPermissionDenied(MailCredentialServiceError):
    status_code = 403
    code = "permission.denied"
    detail = "Mail credential permission is required."


class MailCredentialTargetNotFound(MailCredentialServiceError):
    status_code = 404
    code = "resource.not_found"
    detail = "Permission target not found."


class MailCredentialEgressDenied(MailCredentialServiceError):
    status_code = 400
    code = "mail.egress_target_denied"
    detail = "Mail server target is not allowed."


class MailCredentialRevoked(MailCredentialServiceError):
    status_code = 409
    code = "mail.credential_revoked"
    detail = "Revoked Mail credential cannot be changed."


class MailCredentialPersistenceFailed(MailCredentialServiceError):
    status_code = 500
    code = "mail.credential_persistence_failed"
    detail = "Mail credential change could not be persisted."


def _email_preview(email_address: str) -> str:
    local, separator, domain = email_address.partition("@")
    if not separator:
        return "***"
    visible = local[:1] if local else ""
    return f"{visible}***@{domain}"


class MailCredentialService:
    def __init__(
        self,
        db: Session,
        *,
        encryption: CredentialEncryptionService | None = None,
    ) -> None:
        self.db = db
        self._encryption = encryption

    @property
    def encryption(self) -> CredentialEncryptionService:
        if self._encryption is None:
            self._encryption = get_credential_encryption_service()
        return self._encryption

    @staticmethod
    def to_response(credential: MailCredential) -> MailCredentialResponse:
        return MailCredentialResponse(
            id=credential.id,
            organization_id=credential.organization_id,
            credential_name=credential.credential_name,
            provider=credential.provider,
            email_preview=_email_preview(credential.email_address),
            auth_type=credential.auth_type,
            imap_host=credential.imap_host,
            imap_port=credential.imap_port,
            use_ssl=credential.use_ssl,
            status=credential.status,
            created_at=credential.created_at,
            updated_at=credential.updated_at,
            revoked_at=credential.revoked_at,
        )

    def create(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        payload: MailCredentialCreate,
    ) -> MailCredentialResponse:
        if not has_organization_manager_permission(self.db, actor_id, organization_id):
            self._record_denial(actor_id, organization_id, organization_id, "create")
            raise MailCredentialPermissionDenied()

        imap_host, imap_port = self._validated_endpoint(
            payload.imap_host, payload.imap_port, payload.use_ssl
        )
        envelope = self.encryption.encrypt(payload.secret.get_secret_value())
        credential = MailCredential(
            organization_id=organization_id,
            credential_name=payload.credential_name,
            provider=payload.provider,
            email_address=payload.email_address,
            auth_type=payload.auth_type,
            imap_host=imap_host,
            imap_port=imap_port,
            use_ssl=payload.use_ssl,
            encrypted_secret=envelope.ciphertext,
            encryption_key_version=envelope.key_version,
            encryption_algorithm=envelope.algorithm,
            status=MAIL_CREDENTIAL_ACTIVE,
            created_by=actor_id,
        )
        try:
            register_manual_audit_ownership(self.db, credential, "created")
            self.db.add(credential)
            self.db.flush()
            self._add_mutation_audit(
                action=AuditAction.MAIL_CREDENTIAL_CREATE,
                actor_id=actor_id,
                organization_id=organization_id,
                target_id=credential.id,
                metadata={
                    "provider": credential.provider,
                    "status": credential.status,
                },
            )
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise MailCredentialPersistenceFailed() from exc
        self.db.refresh(credential)
        return self.to_response(credential)

    def list_available(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> list[MailCredentialOptionResponse]:
        credentials = (
            self.db.query(MailCredential)
            .filter(
                MailCredential.organization_id == organization_id,
                MailCredential.status == MAIL_CREDENTIAL_ACTIVE,
            )
            .order_by(
                MailCredential.credential_name.asc(),
                MailCredential.id.asc(),
            )
            .all()
        )
        organization_auth_state = get_organization_auth_state(
            self.db, actor_id, organization_id
        )
        if organization_auth_state == ORGANIZATION_AUTH_MANAGER:
            return [self.to_option_response(credential) for credential in credentials]
        if organization_auth_state != ORGANIZATION_AUTH_MEMBER:
            return []

        effective_states: dict[uuid.UUID, str] = {}
        direct_rows = (
            self.db.query(
                UserMailCredentialPermission.mail_credential_id,
                UserMailCredentialPermission.auth_state,
            )
            .filter(
                UserMailCredentialPermission.grantee_organization_id == organization_id,
                UserMailCredentialPermission.user_id == actor_id,
            )
            .all()
        )
        team_rows = (
            self.db.query(
                TeamMailCredentialPermission.mail_credential_id,
                TeamMailCredentialPermission.auth_state,
            )
            .join(
                TeamMembership,
                TeamMembership.team_id == TeamMailCredentialPermission.team_id,
            )
            .join(Team, Team.id == TeamMailCredentialPermission.team_id)
            .filter(
                TeamMembership.user_id == actor_id,
                TeamMembership.grantee_organization_id == organization_id,
                TeamMailCredentialPermission.grantee_organization_id == organization_id,
                Team.organization_id == organization_id,
                Team.is_active.is_(True),
            )
            .all()
        )
        for credential_id, auth_state in [*direct_rows, *team_rows]:
            effective_states[credential_id] = stronger_resource_auth_state(
                effective_states.get(credential_id, "none"),
                auth_state,
            )
        return [
            self.to_option_response(credential)
            for credential in credentials
            if mail_credential_auth_state_allows(
                effective_states.get(credential.id, "none"), "use"
            )
        ]

    @staticmethod
    def to_option_response(credential: MailCredential) -> MailCredentialOptionResponse:
        return MailCredentialOptionResponse(
            id=credential.id,
            credential_name=credential.credential_name,
            provider=credential.provider,
            email_preview=_email_preview(credential.email_address),
            status=credential.status,
        )

    def get(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
    ) -> MailCredentialResponse:
        credential = self._get_scoped(organization_id, credential_id)
        self._require(actor_id, organization_id, credential, "read")
        return self.to_response(credential)

    def update(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        payload: MailCredentialUpdate,
    ) -> MailCredentialResponse:
        credential = self._get_scoped(organization_id, credential_id, for_update=True)
        self._require(actor_id, organization_id, credential, "manage")
        self._require_active(credential)
        register_manual_audit_ownership(self.db, credential, "updated")
        updates = payload.model_dump(exclude_unset=True, exclude={"secret"})
        if {"imap_host", "imap_port", "use_ssl"} & updates.keys():
            host, port = self._validated_endpoint(
                updates.get("imap_host", credential.imap_host),
                updates.get("imap_port", credential.imap_port),
                updates.get("use_ssl", credential.use_ssl),
            )
            updates["imap_host"] = host
            updates["imap_port"] = port
        for key, value in updates.items():
            setattr(credential, key, value)
        if "secret" in payload.model_fields_set and payload.secret is not None:
            envelope = self.encryption.encrypt(payload.secret.get_secret_value())
            credential.encrypted_secret = envelope.ciphertext
            credential.encryption_key_version = envelope.key_version
            credential.encryption_algorithm = envelope.algorithm
        credential.updated_at = datetime.now(timezone.utc)
        self._add_mutation_audit(
            action=AuditAction.MAIL_CREDENTIAL_UPDATE,
            actor_id=actor_id,
            organization_id=organization_id,
            target_id=credential.id,
            metadata={
                "provider": credential.provider,
                "status": credential.status,
                "changed_fields": sorted(payload.model_fields_set),
            },
        )
        self._commit()
        self.db.refresh(credential)
        return self.to_response(credential)

    def revoke(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
    ) -> MailCredentialResponse:
        credential = self._get_scoped(organization_id, credential_id, for_update=True)
        self._require(actor_id, organization_id, credential, "manage")
        if credential.status != MAIL_CREDENTIAL_REVOKED:
            register_manual_audit_ownership(self.db, credential, "updated")
            now = datetime.now(timezone.utc)
            credential.status = MAIL_CREDENTIAL_REVOKED
            credential.revoked_at = now
            credential.updated_at = now
            self._add_mutation_audit(
                action=AuditAction.MAIL_CREDENTIAL_REVOKE,
                actor_id=actor_id,
                organization_id=organization_id,
                target_id=credential.id,
                metadata={
                    "provider": credential.provider,
                    "status": credential.status,
                },
            )
            self._commit()
            self.db.refresh(credential)
        return self.to_response(credential)

    def list_permissions(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
    ) -> dict[str, object]:
        credential = self._get_scoped(organization_id, credential_id)
        self._require(actor_id, organization_id, credential, "manage")
        team_rows = (
            self.db.query(TeamMailCredentialPermission)
            .options(joinedload(TeamMailCredentialPermission.team))
            .join(Team, Team.id == TeamMailCredentialPermission.team_id)
            .filter(
                TeamMailCredentialPermission.grantee_organization_id == organization_id,
                TeamMailCredentialPermission.mail_credential_id == credential_id,
                Team.organization_id == organization_id,
                Team.is_active.is_(True),
            )
            .order_by(TeamMailCredentialPermission.id.asc())
            .all()
        )
        user_rows = (
            self.db.query(UserMailCredentialPermission)
            .options(joinedload(UserMailCredentialPermission.user))
            .join(User, User.id == UserMailCredentialPermission.user_id)
            .filter(
                UserMailCredentialPermission.grantee_organization_id == organization_id,
                UserMailCredentialPermission.mail_credential_id == credential_id,
                User.deactivated_at.is_(None),
            )
            .order_by(UserMailCredentialPermission.id.asc())
            .all()
        )
        return {
            "resource_type": "mail_credential",
            "resource_id": credential_id,
            "organization_id": organization_id,
            "team_permissions": [
                {
                    "id": row.id,
                    "grantee_type": "team",
                    "grantee_id": row.team_id,
                    "grantee_name": row.team.name,
                    "auth_state": row.auth_state,
                    "assigned_at": row.assigned_at,
                }
                for row in team_rows
            ],
            "user_permissions": [
                {
                    "id": row.id,
                    "grantee_type": "user",
                    "grantee_id": row.user_id,
                    "grantee_name": row.user.name or row.user.email,
                    "auth_state": row.auth_state,
                    "assigned_at": row.assigned_at,
                }
                for row in user_rows
            ],
        }

    def grant_user_permission(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: MailCredentialPermissionGrant,
    ) -> UserMailCredentialPermission:
        credential = self._get_scoped(organization_id, credential_id, for_update=True)
        self._require(actor_id, organization_id, credential, "manage")
        self._require_active(credential)
        membership = (
            self.db.query(OrganizationMembership)
            .filter(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.membership_state
                == ORGANIZATION_MEMBERSHIP_ACTIVE,
            )
            .first()
        )
        if membership is None:
            raise MailCredentialTargetNotFound()
        row = (
            self.db.query(UserMailCredentialPermission)
            .filter(
                UserMailCredentialPermission.grantee_organization_id == organization_id,
                UserMailCredentialPermission.mail_credential_id == credential_id,
                UserMailCredentialPermission.user_id == user_id,
            )
            .first()
        )
        if row is None:
            row = UserMailCredentialPermission(
                grantee_organization_id=organization_id,
                mail_credential_id=credential_id,
                user_id=user_id,
                auth_state=payload.auth_state,
                assigned_by=actor_id,
            )
            register_manual_audit_ownership(self.db, row, "created")
            self.db.add(row)
        else:
            register_manual_audit_ownership(self.db, row, "updated")
            row.auth_state = payload.auth_state
            row.assigned_by = actor_id
            row.assigned_at = datetime.now(timezone.utc)
        self._add_permission_audit(
            action=AuditAction.PERMISSION_GRANT,
            actor_id=actor_id,
            organization_id=organization_id,
            credential_id=credential.id,
            grantee_type="user",
            grantee_id=user_id,
            auth_state=payload.auth_state,
        )
        self._commit()
        self.db.refresh(row)
        return row

    def grant_team_permission(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        team_id: uuid.UUID,
        payload: MailCredentialPermissionGrant,
    ) -> TeamMailCredentialPermission:
        credential = self._get_scoped(organization_id, credential_id, for_update=True)
        self._require(actor_id, organization_id, credential, "manage")
        self._require_active(credential)
        team = (
            self.db.query(Team)
            .filter(
                Team.id == team_id,
                Team.organization_id == organization_id,
                Team.is_active.is_(True),
            )
            .first()
        )
        if team is None:
            raise MailCredentialTargetNotFound()
        row = (
            self.db.query(TeamMailCredentialPermission)
            .filter(
                TeamMailCredentialPermission.grantee_organization_id == organization_id,
                TeamMailCredentialPermission.mail_credential_id == credential_id,
                TeamMailCredentialPermission.team_id == team_id,
            )
            .first()
        )
        if row is None:
            row = TeamMailCredentialPermission(
                grantee_organization_id=organization_id,
                mail_credential_id=credential_id,
                team_id=team_id,
                auth_state=payload.auth_state,
                assigned_by=actor_id,
            )
            register_manual_audit_ownership(self.db, row, "created")
            self.db.add(row)
        else:
            register_manual_audit_ownership(self.db, row, "updated")
            row.auth_state = payload.auth_state
            row.assigned_by = actor_id
            row.assigned_at = datetime.now(timezone.utc)
        self._add_permission_audit(
            action=AuditAction.PERMISSION_GRANT,
            actor_id=actor_id,
            organization_id=organization_id,
            credential_id=credential.id,
            grantee_type="team",
            grantee_id=team_id,
            auth_state=payload.auth_state,
        )
        self._commit()
        self.db.refresh(row)
        return row

    def revoke_user_permission(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        credential = self._get_scoped(organization_id, credential_id, for_update=True)
        self._require(actor_id, organization_id, credential, "manage")
        deleted = (
            self.db.query(UserMailCredentialPermission)
            .filter(
                UserMailCredentialPermission.grantee_organization_id == organization_id,
                UserMailCredentialPermission.mail_credential_id == credential_id,
                UserMailCredentialPermission.user_id == user_id,
            )
            .delete(synchronize_session=False)
        )
        if not deleted:
            raise MailCredentialTargetNotFound()
        self._add_permission_audit(
            action=AuditAction.PERMISSION_REVOKE,
            actor_id=actor_id,
            organization_id=organization_id,
            credential_id=credential.id,
            grantee_type="user",
            grantee_id=user_id,
        )
        self._commit()

    def revoke_team_permission(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        team_id: uuid.UUID,
    ) -> None:
        credential = self._get_scoped(organization_id, credential_id, for_update=True)
        self._require(actor_id, organization_id, credential, "manage")
        deleted = (
            self.db.query(TeamMailCredentialPermission)
            .filter(
                TeamMailCredentialPermission.grantee_organization_id == organization_id,
                TeamMailCredentialPermission.mail_credential_id == credential_id,
                TeamMailCredentialPermission.team_id == team_id,
            )
            .delete(synchronize_session=False)
        )
        if not deleted:
            raise MailCredentialTargetNotFound()
        self._add_permission_audit(
            action=AuditAction.PERMISSION_REVOKE,
            actor_id=actor_id,
            organization_id=organization_id,
            credential_id=credential.id,
            grantee_type="team",
            grantee_id=team_id,
        )
        self._commit()

    def _add_permission_audit(
        self,
        *,
        action: str,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        grantee_type: str,
        grantee_id: uuid.UUID,
        auth_state: str | None = None,
    ) -> None:
        metadata: dict[str, object] = {
            "credential_id": str(credential_id),
            "grantee_type": grantee_type,
            "grantee_id": str(grantee_id),
        }
        if auth_state is not None:
            metadata["auth_state"] = auth_state
        self._add_mutation_audit(
            action=action,
            actor_id=actor_id,
            organization_id=organization_id,
            target_id=credential_id,
            metadata=metadata,
        )

    def _add_mutation_audit(
        self,
        *,
        action: str,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        target_id: uuid.UUID,
        metadata: dict[str, object],
    ) -> None:
        request_metadata = get_current_metadata()
        safe_metadata = {
            key: request_metadata[key]
            for key in ("request_id", "correlation_id", "ip", "user_agent")
            if request_metadata.get(key) is not None
        }
        safe_metadata.update(
            {
                "organization_id": str(organization_id),
                **metadata,
            }
        )
        self.db.add(
            AuditLog(
                action=action,
                category=AuditCategory.ACTION,
                actor_id=actor_id,
                actor_type=ActorType.USER,
                target_type="mail_credential",
                target_id=str(target_id),
                before=None,
                after=None,
                status=AuditStatus.SUCCESS,
                audit_metadata=safe_metadata,
            )
        )

    def _commit(self) -> None:
        try:
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise MailCredentialPersistenceFailed() from exc

    @staticmethod
    def _require_active(credential: MailCredential) -> None:
        if credential.status != MAIL_CREDENTIAL_ACTIVE:
            raise MailCredentialRevoked()

    def _get_scoped(
        self,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> MailCredential:
        query = self.db.query(MailCredential).filter(
            MailCredential.id == credential_id,
            MailCredential.organization_id == organization_id,
        )
        if for_update:
            query = query.with_for_update()
        credential = query.first()
        if credential is None:
            raise MailCredentialNotFound()
        return credential

    def _require(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential: MailCredential,
        action: str,
    ) -> None:
        if has_mail_credential_permission(
            self.db,
            actor_id,
            credential.id,
            action,
            organization_id=organization_id,
        ):
            return
        self._record_denial(actor_id, organization_id, credential.id, action)
        raise MailCredentialPermissionDenied()

    def _record_denial(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        resource_id: uuid.UUID,
        action: str,
    ) -> None:
        record_resource_permission_denied(
            user_id=actor_id,
            resource_type="mail_credential",
            resource_id=resource_id,
            action=action,
            effective_auth_state=get_effective_mail_credential_auth_state(
                self.db,
                actor_id,
                resource_id,
                organization_id=organization_id,
            ),
            organization_id=organization_id,
            metadata=get_current_metadata(),
        )

    @staticmethod
    def _validated_endpoint(host: str, port: int, use_ssl: bool) -> tuple[str, int]:
        expected_port = 993 if use_ssl else 143
        if port != expected_port:
            raise MailCredentialEgressDenied()
        try:
            canonical_host, safe_port, _resolved_ip = ensure_network_target_allowed(
                host,
                port,
                allowed_ports=frozenset({143, 993}),
            )
            return canonical_host, safe_port
        except EgressGuardError as exc:
            raise MailCredentialEgressDenied() from exc
