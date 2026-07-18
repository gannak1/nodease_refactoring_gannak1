from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.shared.audit.actions import AuditAction
from apps.shared.audit.context import get_current_metadata
from apps.shared.audit.manual_ownership import register_manual_audit_ownership
from apps.shared.db.models.audit_log import (
    ActorType,
    AuditCategory,
    AuditLog,
    AuditStatus,
)
from apps.shared.db.models.external_action_credential import (
    EXTERNAL_ACTION_CREDENTIAL_ACTIVE,
    EXTERNAL_ACTION_CREDENTIAL_REVOKED,
    ExternalActionCredential,
)
from apps.shared.db.models.organization_membership import (
    ORGANIZATION_AUTH_MEMBER,
    ORGANIZATION_MEMBERSHIP_ACTIVE,
    OrganizationMembership,
)
from apps.shared.db.models.team import (
    Team,
    TeamExternalActionCredentialPermission,
    TeamMembership,
    UserExternalActionCredentialPermission,
)
from apps.shared.db.models.user import User
from apps.shared.permissions import (
    AUTH_STATE_MANAGER,
    AUTH_STATE_NONE,
    external_action_credential_auth_state_allows,
    stronger_resource_auth_state,
)
from apps.shared.schemas.external_action_credential import (
    ExternalActionCredentialCreate,
    ExternalActionCredentialOptionResponse,
    ExternalActionCredentialPermissionGrant,
    ExternalActionCredentialPermissionResponse,
    ExternalActionCredentialResponse,
    ExternalActionCredentialUpdate,
)
from apps.shared.schemas.team import (
    ResourcePermissionEntry,
    ResourcePermissionListResponse,
)
from apps.shared.services.external_action_credential import (
    ExternalActionCredentialError,
    get_effective_external_action_credential_auth_state,
    get_external_action_credential_secret_service,
    has_external_action_credential_permission,
)
from apps.shared.services.permission_audit import record_resource_permission_denied
from apps.shared.services.permissions import get_organization_auth_state


class ExternalActionCredentialServiceError(Exception):
    status_code = 400
    code = "external_action_credential.invalid"
    detail = "External action credential request is invalid."


class ExternalActionCredentialNotFound(ExternalActionCredentialServiceError):
    status_code = 404
    code = "external_action_credential.not_found"
    detail = "External action credential was not found."


class ExternalActionCredentialPermissionDenied(ExternalActionCredentialServiceError):
    status_code = 403
    code = "external_action_credential.permission_denied"
    detail = "External action credential access is not allowed."


class ExternalActionCredentialRevisionConflict(ExternalActionCredentialServiceError):
    status_code = 409
    code = "external_action_credential.revision_conflict"
    detail = "External action credential has changed."


class ExternalActionCredentialRevoked(ExternalActionCredentialServiceError):
    status_code = 409
    code = "external_action_credential.revoked"
    detail = "External action credential is not active."


class ExternalActionCredentialTargetNotFound(ExternalActionCredentialServiceError):
    status_code = 404
    code = "external_action_credential.permission_target_not_found"
    detail = "Permission target was not found."


class ExternalActionCredentialPersistenceFailed(ExternalActionCredentialServiceError):
    status_code = 503
    code = "external_action_credential.persistence_failed"
    detail = "External action credential could not be saved."


class ExternalActionCredentialService:
    """Management boundary for encrypted external workflow credentials."""

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        payload: ExternalActionCredentialCreate,
    ) -> ExternalActionCredentialResponse:
        self._require_organization_manager(actor_id, organization_id)
        try:
            envelope = get_external_action_credential_secret_service().protect(
                payload.provider,
                payload.secret.get_secret_value(),
            )
        except ExternalActionCredentialError as exc:
            raise ExternalActionCredentialServiceError() from exc

        credential = ExternalActionCredential(
            organization_id=organization_id,
            credential_name=payload.credential_name,
            provider=payload.provider,
            encrypted_secret=envelope.ciphertext,
            encryption_key_version=envelope.key_version,
            encryption_algorithm=envelope.algorithm,
            revision=1,
            status=EXTERNAL_ACTION_CREDENTIAL_ACTIVE,
            created_by=actor_id,
        )
        register_manual_audit_ownership(self.db, credential, "created")
        self.db.add(credential)
        self.db.flush()
        self._add_audit(
            action=AuditAction.EXTERNAL_ACTION_CREDENTIAL_CREATE,
            actor_id=actor_id,
            organization_id=organization_id,
            credential=credential,
        )
        self._commit()
        self.db.refresh(credential)
        return self._response(credential)

    def list_available(
        self, actor_id: uuid.UUID, organization_id: uuid.UUID
    ) -> list[ExternalActionCredentialOptionResponse]:
        credentials = (
            self.db.query(ExternalActionCredential)
            .filter(
                ExternalActionCredential.organization_id == organization_id,
                ExternalActionCredential.status == EXTERNAL_ACTION_CREDENTIAL_ACTIVE,
            )
            .order_by(
                ExternalActionCredential.credential_name.asc(),
                ExternalActionCredential.id.asc(),
            )
            .all()
        )
        organization_auth_state = get_organization_auth_state(
            self.db, actor_id, organization_id
        )
        if organization_auth_state == AUTH_STATE_MANAGER:
            return [self._option(credential) for credential in credentials]
        if organization_auth_state != ORGANIZATION_AUTH_MEMBER:
            return []

        effective_states: dict[uuid.UUID, str] = {}
        direct_rows = (
            self.db.query(
                UserExternalActionCredentialPermission.external_action_credential_id,
                UserExternalActionCredentialPermission.auth_state,
            )
            .filter(
                UserExternalActionCredentialPermission.grantee_organization_id
                == organization_id,
                UserExternalActionCredentialPermission.user_id == actor_id,
            )
            .all()
        )
        team_rows = (
            self.db.query(
                TeamExternalActionCredentialPermission.external_action_credential_id,
                TeamExternalActionCredentialPermission.auth_state,
            )
            .join(
                TeamMembership,
                TeamMembership.team_id
                == TeamExternalActionCredentialPermission.team_id,
            )
            .join(Team, Team.id == TeamExternalActionCredentialPermission.team_id)
            .filter(
                TeamMembership.user_id == actor_id,
                TeamMembership.grantee_organization_id == organization_id,
                TeamExternalActionCredentialPermission.grantee_organization_id
                == organization_id,
                Team.organization_id == organization_id,
                Team.is_active.is_(True),
            )
            .all()
        )
        for resource_id, auth_state in [*direct_rows, *team_rows]:
            effective_states[resource_id] = stronger_resource_auth_state(
                effective_states.get(resource_id, AUTH_STATE_NONE),
                auth_state,
            )
        return [
            self._option(credential)
            for credential in credentials
            if external_action_credential_auth_state_allows(
                effective_states.get(credential.id, AUTH_STATE_NONE), "use"
            )
        ]

    def get(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
    ) -> ExternalActionCredentialResponse:
        credential = self._get_scoped(organization_id, credential_id)
        self._require(actor_id, organization_id, credential, "read")
        return self._response(credential)

    def update(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        payload: ExternalActionCredentialUpdate,
    ) -> ExternalActionCredentialResponse:
        credential = self._get_scoped(organization_id, credential_id, for_update=True)
        self._require(actor_id, organization_id, credential, "manage")
        self._require_active(credential)
        if credential.revision != payload.expected_revision:
            raise ExternalActionCredentialRevisionConflict()

        register_manual_audit_ownership(self.db, credential, "updated")

        if payload.credential_name is not None:
            credential.credential_name = payload.credential_name
        if payload.secret is not None:
            try:
                envelope = get_external_action_credential_secret_service().protect(
                    credential.provider,
                    payload.secret.get_secret_value(),
                )
            except ExternalActionCredentialError as exc:
                raise ExternalActionCredentialServiceError() from exc
            credential.encrypted_secret = envelope.ciphertext
            credential.encryption_key_version = envelope.key_version
            credential.encryption_algorithm = envelope.algorithm
        credential.revision += 1
        credential.updated_at = datetime.now(timezone.utc)
        self._add_audit(
            action=AuditAction.EXTERNAL_ACTION_CREDENTIAL_UPDATE,
            actor_id=actor_id,
            organization_id=organization_id,
            credential=credential,
        )
        self._commit()
        self.db.refresh(credential)
        return self._response(credential)

    def revoke(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        *,
        expected_revision: int,
    ) -> ExternalActionCredentialResponse:
        credential = self._get_scoped(organization_id, credential_id, for_update=True)
        self._require(actor_id, organization_id, credential, "manage")
        self._require_active(credential)
        if credential.revision != expected_revision:
            raise ExternalActionCredentialRevisionConflict()
        register_manual_audit_ownership(self.db, credential, "updated")
        now = datetime.now(timezone.utc)
        credential.status = EXTERNAL_ACTION_CREDENTIAL_REVOKED
        credential.revoked_at = now
        credential.updated_at = now
        credential.revision += 1
        self._add_audit(
            action=AuditAction.EXTERNAL_ACTION_CREDENTIAL_REVOKE,
            actor_id=actor_id,
            organization_id=organization_id,
            credential=credential,
        )
        self._commit()
        self.db.refresh(credential)
        return self._response(credential)

    def list_permissions(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
    ) -> ResourcePermissionListResponse:
        credential = self._get_scoped(organization_id, credential_id)
        self._require(actor_id, organization_id, credential, "manage")
        team_rows = (
            self.db.query(TeamExternalActionCredentialPermission, Team.name)
            .join(Team, Team.id == TeamExternalActionCredentialPermission.team_id)
            .filter(
                TeamExternalActionCredentialPermission.grantee_organization_id
                == organization_id,
                TeamExternalActionCredentialPermission.external_action_credential_id
                == credential_id,
                Team.organization_id == organization_id,
            )
            .order_by(TeamExternalActionCredentialPermission.assigned_at.asc())
            .all()
        )
        user_rows = (
            self.db.query(UserExternalActionCredentialPermission, User.name)
            .join(User, User.id == UserExternalActionCredentialPermission.user_id)
            .filter(
                UserExternalActionCredentialPermission.grantee_organization_id
                == organization_id,
                UserExternalActionCredentialPermission.external_action_credential_id
                == credential_id,
            )
            .order_by(UserExternalActionCredentialPermission.assigned_at.asc())
            .all()
        )
        return ResourcePermissionListResponse(
            resource_type="external_action_credential",
            resource_id=credential_id,
            organization_id=organization_id,
            team_permissions=[
                ResourcePermissionEntry(
                    id=row.id,
                    grantee_type="team",
                    grantee_id=row.team_id,
                    grantee_name=name,
                    auth_state=row.auth_state,
                    assigned_at=row.assigned_at,
                )
                for row, name in team_rows
            ],
            user_permissions=[
                ResourcePermissionEntry(
                    id=row.id,
                    grantee_type="user",
                    grantee_id=row.user_id,
                    grantee_name=name,
                    auth_state=row.auth_state,
                    assigned_at=row.assigned_at,
                )
                for row, name in user_rows
            ],
        )

    def grant_user_permission(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: ExternalActionCredentialPermissionGrant,
    ) -> ExternalActionCredentialPermissionResponse:
        credential = self._get_scoped(organization_id, credential_id, for_update=True)
        self._require(actor_id, organization_id, credential, "manage")
        self._require_active(credential)
        membership = (
            self.db.query(OrganizationMembership)
            .join(User, User.id == OrganizationMembership.user_id)
            .filter(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.membership_state
                == ORGANIZATION_MEMBERSHIP_ACTIVE,
                User.deactivated_at.is_(None),
            )
            .with_for_update()
            .first()
        )
        if membership is None:
            raise ExternalActionCredentialTargetNotFound()
        row = (
            self.db.query(UserExternalActionCredentialPermission)
            .filter(
                UserExternalActionCredentialPermission.grantee_organization_id
                == organization_id,
                UserExternalActionCredentialPermission.external_action_credential_id
                == credential_id,
                UserExternalActionCredentialPermission.user_id == user_id,
            )
            .first()
        )
        if row is None:
            row = UserExternalActionCredentialPermission(
                grantee_organization_id=organization_id,
                external_action_credential_id=credential_id,
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
            AuditAction.PERMISSION_GRANT,
            actor_id,
            organization_id,
            credential,
            "user",
            user_id,
            payload.auth_state,
        )
        self._commit()
        self.db.refresh(row)
        return ExternalActionCredentialPermissionResponse.model_validate(row)

    def grant_team_permission(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        team_id: uuid.UUID,
        payload: ExternalActionCredentialPermissionGrant,
    ) -> ExternalActionCredentialPermissionResponse:
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
            raise ExternalActionCredentialTargetNotFound()
        row = (
            self.db.query(TeamExternalActionCredentialPermission)
            .filter(
                TeamExternalActionCredentialPermission.grantee_organization_id
                == organization_id,
                TeamExternalActionCredentialPermission.external_action_credential_id
                == credential_id,
                TeamExternalActionCredentialPermission.team_id == team_id,
            )
            .first()
        )
        if row is None:
            row = TeamExternalActionCredentialPermission(
                grantee_organization_id=organization_id,
                external_action_credential_id=credential_id,
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
            AuditAction.PERMISSION_GRANT,
            actor_id,
            organization_id,
            credential,
            "team",
            team_id,
            payload.auth_state,
        )
        self._commit()
        self.db.refresh(row)
        return ExternalActionCredentialPermissionResponse.model_validate(row)

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
            self.db.query(UserExternalActionCredentialPermission)
            .filter(
                UserExternalActionCredentialPermission.grantee_organization_id
                == organization_id,
                UserExternalActionCredentialPermission.external_action_credential_id
                == credential_id,
                UserExternalActionCredentialPermission.user_id == user_id,
            )
            .delete(synchronize_session=False)
        )
        if not deleted:
            raise ExternalActionCredentialTargetNotFound()
        self._add_permission_audit(
            AuditAction.PERMISSION_REVOKE,
            actor_id,
            organization_id,
            credential,
            "user",
            user_id,
            None,
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
            self.db.query(TeamExternalActionCredentialPermission)
            .filter(
                TeamExternalActionCredentialPermission.grantee_organization_id
                == organization_id,
                TeamExternalActionCredentialPermission.external_action_credential_id
                == credential_id,
                TeamExternalActionCredentialPermission.team_id == team_id,
            )
            .delete(synchronize_session=False)
        )
        if not deleted:
            raise ExternalActionCredentialTargetNotFound()
        self._add_permission_audit(
            AuditAction.PERMISSION_REVOKE,
            actor_id,
            organization_id,
            credential,
            "team",
            team_id,
            None,
        )
        self._commit()

    def _require_organization_manager(
        self, actor_id: uuid.UUID, organization_id: uuid.UUID
    ) -> None:
        if get_organization_auth_state(self.db, actor_id, organization_id) != AUTH_STATE_MANAGER:
            raise ExternalActionCredentialPermissionDenied()

    def _get_scoped(
        self,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> ExternalActionCredential:
        query = self.db.query(ExternalActionCredential).filter(
            ExternalActionCredential.id == credential_id,
            ExternalActionCredential.organization_id == organization_id,
        )
        if for_update:
            query = query.with_for_update()
        credential = query.first()
        if credential is None:
            raise ExternalActionCredentialNotFound()
        return credential

    def _require(
        self,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential: ExternalActionCredential,
        action: str,
    ) -> None:
        if has_external_action_credential_permission(
            self.db,
            actor_id,
            credential.id,
            action,
            organization_id=organization_id,
        ):
            return
        record_resource_permission_denied(
            user_id=actor_id,
            resource_type="external_action_credential",
            resource_id=credential.id,
            action=action,
            effective_auth_state=get_effective_external_action_credential_auth_state(
                self.db,
                actor_id,
                credential.id,
                organization_id=organization_id,
            ),
            organization_id=organization_id,
            metadata=self._safe_request_metadata(),
        )
        raise ExternalActionCredentialNotFound()

    @staticmethod
    def _safe_request_metadata() -> dict[str, object]:
        request_metadata = get_current_metadata()
        return {
            key: request_metadata[key]
            for key in ("request_id", "correlation_id", "ip", "user_agent")
            if request_metadata.get(key) is not None
        }

    @staticmethod
    def _require_active(credential: ExternalActionCredential) -> None:
        if credential.status != EXTERNAL_ACTION_CREDENTIAL_ACTIVE:
            raise ExternalActionCredentialRevoked()

    @staticmethod
    def _response(
        credential: ExternalActionCredential,
    ) -> ExternalActionCredentialResponse:
        return ExternalActionCredentialResponse(
            id=credential.id,
            organization_id=credential.organization_id,
            credential_name=credential.credential_name,
            provider=credential.provider,
            status=credential.status,
            revision=credential.revision,
            created_at=credential.created_at,
            updated_at=credential.updated_at,
            revoked_at=credential.revoked_at,
        )

    @staticmethod
    def _option(
        credential: ExternalActionCredential,
    ) -> ExternalActionCredentialOptionResponse:
        return ExternalActionCredentialOptionResponse(
            id=credential.id,
            credential_name=credential.credential_name,
            provider=credential.provider,
            revision=credential.revision,
            status=credential.status,
        )

    def _add_permission_audit(
        self,
        action: str,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential: ExternalActionCredential,
        grantee_type: str,
        grantee_id: uuid.UUID,
        auth_state: str | None,
    ) -> None:
        metadata: dict[str, object] = {
            "credential_id": str(credential.id),
            "provider": credential.provider,
            "revision": credential.revision,
            "grantee_type": grantee_type,
            "grantee_id": str(grantee_id),
        }
        if auth_state is not None:
            metadata["auth_state"] = auth_state
        self._add_audit(
            action=action,
            actor_id=actor_id,
            organization_id=organization_id,
            credential=credential,
            metadata=metadata,
        )

    def _add_audit(
        self,
        *,
        action: str,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential: ExternalActionCredential,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.db.add(
            AuditLog(
                action=action,
                category=AuditCategory.ACTION,
                actor_id=actor_id,
                actor_type=ActorType.USER,
                target_type="external_action_credential",
                target_id=str(credential.id),
                before=None,
                after=None,
                status=AuditStatus.SUCCESS,
                audit_metadata={
                    **self._safe_request_metadata(),
                    "organization_id": str(organization_id),
                    "provider": credential.provider,
                    "credential_revision": credential.revision,
                    **(metadata or {}),
                },
            )
        )

    def _commit(self) -> None:
        try:
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise ExternalActionCredentialPersistenceFailed() from exc
