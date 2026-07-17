"""Framework-independent public Conversation lifecycle application service.

The public adapter owns no database or HTTP details.  It receives a canonical
deployment binding from a port, persists only verifiers/ciphertext through a
single Unit of Work, and returns raw capabilities only to its caller.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.memory.application.ports import MemoryUnitOfWorkPort
from apps.memory.domain.conversation import (
    AudienceKind,
    ConversationPurgeJob,
    ConversationSession,
    PurgeStatus,
    SessionLifecycle,
)
from apps.memory.domain.errors import (
    AccessGrantNotUsableError,
    MemoryAdapterUnavailableError,
    PurgeReceiptNotUsableError,
    SecretReplayExpiredError,
    SessionNotActiveError,
)
from apps.memory.domain.public_access import (
    AccessGrantState,
    ConversationAccessGrant,
    ConversationIdempotency,
    EncryptedSecretReplay,
    IdempotencyStatus,
)


@dataclass(frozen=True, slots=True)
class PublicDeploymentBinding:
    organization_id: uuid.UUID
    app_id: uuid.UUID
    workflow_id: uuid.UUID
    deployment_id: uuid.UUID
    deployment_version: int
    mapping_version: str
    memory_policy_version: str
    memory_contract_version: str
    storage_generation: int


@dataclass(frozen=True, slots=True)
class PublicConversationPolicy:
    idle_lifetime: timedelta = timedelta(hours=24)
    absolute_lifetime: timedelta = timedelta(days=7)
    access_grant_lifetime: timedelta = timedelta(days=1)
    access_secret_replay_lifetime: timedelta = timedelta(minutes=10)
    purge_receipt_lifetime: timedelta = timedelta(days=7)
    purge_secret_replay_lifetime: timedelta = timedelta(hours=24)
    idempotency_retention: timedelta = timedelta(days=8)
    purge_max_attempts: int = 8

    def __post_init__(self) -> None:
        durations = (
            self.idle_lifetime,
            self.absolute_lifetime,
            self.access_grant_lifetime,
            self.access_secret_replay_lifetime,
            self.purge_receipt_lifetime,
            self.purge_secret_replay_lifetime,
            self.idempotency_retention,
        )
        if any(value <= timedelta(0) for value in durations):
            raise ValueError("public conversation lifetimes must be positive")
        if self.absolute_lifetime <= self.idle_lifetime:
            raise ValueError("absolute lifetime must exceed idle lifetime")
        if self.purge_receipt_lifetime > timedelta(days=8):
            raise ValueError("purge receipt lifetime must not exceed eight days")
        if self.purge_max_attempts < 1:
            raise ValueError("purge_max_attempts must be positive")


@dataclass(frozen=True, slots=True)
class IssuedSecret:
    raw_value: str
    verifier_hash: str
    verifier_key_version: str


@dataclass(frozen=True, slots=True)
class SecretCiphertext:
    ciphertext: bytes
    key_version: str


class PublicSecretIssuerPort(Protocol):
    def issue_access_grant(self) -> IssuedSecret: ...

    def access_grant_verifier(self, raw_value: str) -> tuple[str, str] | None: ...

    def issue_purge_receipt(self) -> IssuedSecret: ...

    def purge_receipt_verifier(self, raw_value: str) -> tuple[str, str] | None: ...


class SecretReplayCipherPort(Protocol):
    def encrypt(self, raw_value: str, *, associated_data_digest: str) -> SecretCiphertext: ...

    def decrypt(
        self,
        ciphertext: bytes,
        *,
        key_version: str,
        associated_data_digest: str,
    ) -> str | None: ...


class PublicConversationAuditPort(Protocol):
    def record(
        self,
        *,
        action: str,
        organization_id: uuid.UUID,
        deployment_id: uuid.UUID,
        session_id: uuid.UUID,
        purge_job_id: uuid.UUID | None = None,
    ) -> None: ...


class PublicConversationAdmissionPort(Protocol):
    def admit(
        self,
        *,
        operation: str,
        binding: "PublicDeploymentBinding",
        grant_id: uuid.UUID | None,
        network_address: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class IdempotencyReservation:
    record: ConversationIdempotency
    created: bool


class PublicConversationRepositoryPort(Protocol):
    def resolve_public_deployment(self, url_slug: str) -> PublicDeploymentBinding | None: ...

    def reserve_idempotency(
        self, record: ConversationIdempotency
    ) -> IdempotencyReservation: ...

    def save_idempotency(self, record: ConversationIdempotency) -> None: ...

    def add_session(self, session: ConversationSession) -> None: ...

    def lock_session(
        self, *, organization_id: uuid.UUID, session_id: uuid.UUID
    ) -> ConversationSession | None: ...

    def save_session(self, session: ConversationSession) -> None: ...

    def add_access_grant(self, grant: ConversationAccessGrant) -> None: ...

    def lock_access_grant(
        self, *, verifier_key_version: str, verifier_hash: str
    ) -> ConversationAccessGrant | None: ...

    def save_access_grant(self, grant: ConversationAccessGrant) -> None: ...

    def add_secret_replay(self, replay: EncryptedSecretReplay) -> None: ...

    def get_secret_replay(
        self, *, organization_id: uuid.UUID, replay_id: uuid.UUID
    ) -> EncryptedSecretReplay | None: ...

    def add_purge_job(self, job: ConversationPurgeJob) -> None: ...

    def find_purge_job(
        self, *, verifier_key_version: str, verifier_hash: str
    ) -> ConversationPurgeJob | None: ...

    def lock_purge_job_by_id(
        self, *, organization_id: uuid.UUID, purge_job_id: uuid.UUID
    ) -> ConversationPurgeJob | None: ...


@dataclass(frozen=True, slots=True)
class CreatePublicConversationCommand:
    url_slug: str
    idempotency_key_hash: str
    request_fingerprint: str
    now: datetime
    network_address: str = ""


@dataclass(frozen=True, slots=True)
class PublicConversationResult:
    lifecycle: SessionLifecycle
    lifecycle_revision: int
    memory_contract_version: str
    expires_at: datetime
    access_token: str
    replayed: bool
    previous_lifecycle: SessionLifecycle | None = None


@dataclass(frozen=True, slots=True)
class LifecycleCommand:
    url_slug: str
    access_token: str
    idempotency_key_hash: str
    request_fingerprint: str
    expected_lifecycle_revision: int
    now: datetime
    network_address: str = ""


@dataclass(frozen=True, slots=True)
class ClosePublicConversationResult:
    lifecycle: SessionLifecycle
    lifecycle_revision: int
    memory_contract_version: str
    expires_at: datetime
    replayed: bool


@dataclass(frozen=True, slots=True)
class DeletePublicConversationResult:
    lifecycle: SessionLifecycle
    lifecycle_revision: int
    purge_job_id: uuid.UUID
    purge_receipt: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class PublicTranscriptResult:
    lifecycle: SessionLifecycle
    lifecycle_revision: int
    entries: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class PublicPurgeStatusResult:
    status: PurgeStatus
    updated_at: datetime
    safe_failure_reason: str | None


class _TransactionalPublicUseCase:
    def __init__(
        self,
        *,
        repository: PublicConversationRepositoryPort,
        uow: MemoryUnitOfWorkPort,
        secrets: PublicSecretIssuerPort,
        replay_cipher: SecretReplayCipherPort,
        audit: PublicConversationAuditPort,
        policy: PublicConversationPolicy,
        admission: PublicConversationAdmissionPort | None = None,
    ) -> None:
        self.repository = repository
        self.uow = uow
        self.secrets = secrets
        self.replay_cipher = replay_cipher
        self.audit = audit
        self.policy = policy
        self.admission = admission

    def _execute(self, operation):
        self.uow.begin()
        try:
            result = operation()
            self.uow.commit()
            return result
        except Exception:
            self.uow.rollback()
            raise

    def _binding(self, url_slug: str) -> PublicDeploymentBinding:
        binding = self.repository.resolve_public_deployment(url_slug)
        if binding is None:
            raise AccessGrantNotUsableError()
        return binding

    def _grant_for_mutation(
        self,
        *,
        binding: PublicDeploymentBinding,
        raw_access_token: str,
        now: datetime,
    ) -> ConversationAccessGrant:
        verifier = self.secrets.access_grant_verifier(raw_access_token)
        if verifier is None:
            raise AccessGrantNotUsableError()
        grant = self.repository.lock_access_grant(
            verifier_key_version=verifier[0],
            verifier_hash=verifier[1],
        )
        if grant is None:
            raise AccessGrantNotUsableError()
        if (
            grant.verifier_key_version != verifier[0]
            or not hmac.compare_digest(grant.verifier_hash, verifier[1])
        ):
            raise AccessGrantNotUsableError()
        if (
            grant.deployment_id != binding.deployment_id
            or grant.deployment_version != binding.deployment_version
            or grant.audience_kind is not AudienceKind.PUBLIC_CHATBOT
        ):
            raise AccessGrantNotUsableError()
        if grant.state is AccessGrantState.EXPIRED or now >= grant.expires_at:
            raise AccessGrantNotUsableError()
        return grant

    def _session_for_grant(
        self,
        grant: ConversationAccessGrant,
        *,
        now: datetime,
    ) -> ConversationSession:
        session = self.repository.lock_session(
            organization_id=grant.organization_id,
            session_id=grant.session_id,
        )
        if session is None:
            raise AccessGrantNotUsableError()
        if (
            session.deployment_id != grant.deployment_id
            or session.deployment_version != grant.deployment_version
            or session.audience_kind is not AudienceKind.PUBLIC_CHATBOT
        ):
            raise AccessGrantNotUsableError()
        if now >= session.idle_expires_at or now >= session.absolute_expires_at:
            raise AccessGrantNotUsableError()
        return session

    def _reserve(
        self,
        *,
        organization_id: uuid.UUID,
        operation: str,
        scope_digest: str,
        idempotency_key_hash: str,
        request_fingerprint: str,
        now: datetime,
    ) -> IdempotencyReservation:
        return self.repository.reserve_idempotency(
            ConversationIdempotency.pending(
                record_id=uuid.uuid4(),
                organization_id=organization_id,
                operation=operation,
                scope_digest=scope_digest,
                idempotency_key_hash=idempotency_key_hash,
                request_fingerprint=request_fingerprint,
                retention_expires_at=now + self.policy.idempotency_retention,
                now=now,
            )
        )

    def _add_secret_replay(
        self,
        *,
        record: ConversationIdempotency,
        purpose: str,
        raw_secret: str,
        expires_at: datetime,
    ) -> EncryptedSecretReplay:
        associated_data_digest = _secret_replay_associated_data_digest(
            record=record,
            purpose=purpose,
        )
        ciphertext = self.replay_cipher.encrypt(
            raw_secret,
            associated_data_digest=associated_data_digest,
        )
        replay = EncryptedSecretReplay(
            id=uuid.uuid4(),
            organization_id=record.organization_id,
            idempotency_record_id=record.id,
            purpose=purpose,
            ciphertext=ciphertext.ciphertext,
            key_version=ciphertext.key_version,
            associated_data_digest=associated_data_digest,
            expires_at=expires_at,
            created_at=record.created_at,
        )
        self.repository.add_secret_replay(replay)
        return replay

    def _admit(
        self,
        *,
        operation: str,
        binding: PublicDeploymentBinding,
        grant_id: uuid.UUID | None,
        network_address: str,
    ) -> None:
        if self.admission is not None:
            self.admission.admit(
                operation=operation,
                binding=binding,
                grant_id=grant_id,
                network_address=network_address,
            )

    def _replay_secret(
        self,
        *,
        record: ConversationIdempotency,
        purpose: str,
        now: datetime,
    ) -> str:
        if (
            record.status is not IdempotencyStatus.COMPLETED
            or record.replay_record_reference is None
            or record.secret_replay_expires_at is None
            or now >= record.secret_replay_expires_at
        ):
            raise SecretReplayExpiredError()
        try:
            replay_id = uuid.UUID(record.replay_record_reference)
        except ValueError:
            raise MemoryAdapterUnavailableError() from None
        replay = self.repository.get_secret_replay(
            organization_id=record.organization_id,
            replay_id=replay_id,
        )
        if (
            replay is None
            or replay.idempotency_record_id != record.id
            or replay.purpose != purpose
            or now >= replay.expires_at
        ):
            raise SecretReplayExpiredError()
        raw_secret = self.replay_cipher.decrypt(
            replay.ciphertext,
            key_version=replay.key_version,
            associated_data_digest=_secret_replay_associated_data_digest(
                record=record,
                purpose=purpose,
            ),
        )
        if raw_secret is None:
            raise MemoryAdapterUnavailableError()
        return raw_secret


class CreatePublicConversationUseCase(_TransactionalPublicUseCase):
    def execute(
        self, command: CreatePublicConversationCommand
    ) -> PublicConversationResult:
        def operation() -> PublicConversationResult:
            binding = self._binding(command.url_slug)
            scope_digest = _scope_digest(
                operation="conversation.create",
                binding=binding,
            )
            reservation = self._reserve(
                organization_id=binding.organization_id,
                operation="conversation.create",
                scope_digest=scope_digest,
                idempotency_key_hash=command.idempotency_key_hash,
                request_fingerprint=command.request_fingerprint,
                now=command.now,
            )
            record = reservation.record
            if not reservation.created:
                record.require_matching_fingerprint(command.request_fingerprint)
                return self._replay_create(record=record, now=command.now)

            self._admit(
                operation="conversation.create",
                binding=binding,
                grant_id=None,
                network_address=command.network_address,
            )

            session = _new_session(
                binding=binding,
                policy=self.policy,
                now=command.now,
            )
            issued = self.secrets.issue_access_grant()
            grant = ConversationAccessGrant.issue(
                grant_id=uuid.uuid4(),
                organization_id=binding.organization_id,
                session_id=session.id,
                deployment_id=binding.deployment_id,
                deployment_version=binding.deployment_version,
                audience_kind=AudienceKind.PUBLIC_CHATBOT,
                verifier_hash=issued.verifier_hash,
                verifier_key_version=issued.verifier_key_version,
                expires_at=min(
                    session.absolute_expires_at,
                    command.now + self.policy.access_grant_lifetime,
                ),
                now=command.now,
            )
            replay = self._add_secret_replay(
                record=record,
                purpose="access_grant",
                raw_secret=issued.raw_value,
                expires_at=command.now + self.policy.access_secret_replay_lifetime,
            )
            grant.replay_record_reference = str(replay.id)
            record.complete(
                resource_type="conversation_session",
                resource_reference=str(session.id),
                replay_record_reference=str(replay.id),
                secret_replay_expires_at=replay.expires_at,
                safe_result_code="created",
                now=command.now,
            )
            self.repository.add_session(session)
            self.repository.add_access_grant(grant)
            self.repository.save_idempotency(record)
            self.audit.record(
                action="conversation.public.created",
                organization_id=binding.organization_id,
                deployment_id=binding.deployment_id,
                session_id=session.id,
            )
            return _conversation_result(
                session=session,
                access_token=issued.raw_value,
                replayed=False,
            )

        return self._execute(operation)

    def _replay_create(
        self,
        *,
        record: ConversationIdempotency,
        now: datetime,
    ) -> PublicConversationResult:
        session = _record_session(self.repository, record)
        access_token = self._replay_secret(
            record=record,
            purpose="access_grant",
            now=now,
        )
        return _conversation_result(
            session=session,
            access_token=access_token,
            replayed=True,
        )


class ClosePublicConversationUseCase(_TransactionalPublicUseCase):
    def execute(self, command: LifecycleCommand) -> ClosePublicConversationResult:
        def operation() -> ClosePublicConversationResult:
            binding = self._binding(command.url_slug)
            grant = self._grant_for_mutation(
                binding=binding,
                raw_access_token=command.access_token,
                now=command.now,
            )
            session = self._session_for_grant(grant, now=command.now)
            reservation = self._reserve(
                organization_id=binding.organization_id,
                operation="conversation.close",
                scope_digest=_scope_digest(
                    operation="conversation.close",
                    binding=binding,
                    grant=grant,
                    session=session,
                ),
                idempotency_key_hash=command.idempotency_key_hash,
                request_fingerprint=command.request_fingerprint,
                now=command.now,
            )
            if not reservation.created:
                reservation.record.require_matching_fingerprint(
                    command.request_fingerprint
                )
                replay_session = _record_session(self.repository, reservation.record)
                return _close_result(replay_session, replayed=True)

            self._admit(
                operation="conversation.close",
                binding=binding,
                grant_id=grant.id,
                network_address=command.network_address,
            )

            grant.require_active(
                deployment_id=binding.deployment_id,
                deployment_version=binding.deployment_version,
                audience_kind=AudienceKind.PUBLIC_CHATBOT,
                now=command.now,
            )
            session.close(
                expected_lifecycle_revision=command.expected_lifecycle_revision,
                now=command.now,
            )
            grant.restrict_to_transcript(now=command.now)
            reservation.record.complete(
                resource_type="conversation_session",
                resource_reference=str(session.id),
                replay_record_reference=None,
                secret_replay_expires_at=None,
                safe_result_code="closed",
                now=command.now,
            )
            self.repository.save_session(session)
            self.repository.save_access_grant(grant)
            self.repository.save_idempotency(reservation.record)
            self.audit.record(
                action="conversation.public.closed",
                organization_id=binding.organization_id,
                deployment_id=binding.deployment_id,
                session_id=session.id,
            )
            return _close_result(session, replayed=False)

        return self._execute(operation)


class ResetPublicConversationUseCase(_TransactionalPublicUseCase):
    def execute(self, command: LifecycleCommand) -> PublicConversationResult:
        def operation() -> PublicConversationResult:
            binding = self._binding(command.url_slug)
            old_grant = self._grant_for_mutation(
                binding=binding,
                raw_access_token=command.access_token,
                now=command.now,
            )
            old_session = self._session_for_grant(old_grant, now=command.now)
            reservation = self._reserve(
                organization_id=binding.organization_id,
                operation="conversation.reset",
                scope_digest=_scope_digest(
                    operation="conversation.reset",
                    binding=binding,
                    grant=old_grant,
                    session=old_session,
                ),
                idempotency_key_hash=command.idempotency_key_hash,
                request_fingerprint=command.request_fingerprint,
                now=command.now,
            )
            if not reservation.created:
                reservation.record.require_matching_fingerprint(
                    command.request_fingerprint
                )
                new_session = _record_session(self.repository, reservation.record)
                token = self._replay_secret(
                    record=reservation.record,
                    purpose="access_grant",
                    now=command.now,
                )
                return _conversation_result(
                    session=new_session,
                    access_token=token,
                    replayed=True,
                    previous_lifecycle=SessionLifecycle.CLOSED,
                )

            self._admit(
                operation="conversation.reset",
                binding=binding,
                grant_id=old_grant.id,
                network_address=command.network_address,
            )

            old_grant.require_active(
                deployment_id=binding.deployment_id,
                deployment_version=binding.deployment_version,
                audience_kind=AudienceKind.PUBLIC_CHATBOT,
                now=command.now,
            )
            old_session.close(
                expected_lifecycle_revision=command.expected_lifecycle_revision,
                now=command.now,
            )
            old_grant.revoke(now=command.now)
            new_session = _new_session(
                binding=binding,
                policy=self.policy,
                now=command.now,
            )
            issued = self.secrets.issue_access_grant()
            new_grant = ConversationAccessGrant.issue(
                grant_id=uuid.uuid4(),
                organization_id=binding.organization_id,
                session_id=new_session.id,
                deployment_id=binding.deployment_id,
                deployment_version=binding.deployment_version,
                audience_kind=AudienceKind.PUBLIC_CHATBOT,
                verifier_hash=issued.verifier_hash,
                verifier_key_version=issued.verifier_key_version,
                expires_at=min(
                    new_session.absolute_expires_at,
                    command.now + self.policy.access_grant_lifetime,
                ),
                now=command.now,
            )
            replay = self._add_secret_replay(
                record=reservation.record,
                purpose="access_grant",
                raw_secret=issued.raw_value,
                expires_at=command.now + self.policy.access_secret_replay_lifetime,
            )
            new_grant.replay_record_reference = str(replay.id)
            reservation.record.complete(
                resource_type="conversation_session",
                resource_reference=str(new_session.id),
                replay_record_reference=str(replay.id),
                secret_replay_expires_at=replay.expires_at,
                safe_result_code="reset",
                now=command.now,
            )
            self.repository.save_session(old_session)
            self.repository.save_access_grant(old_grant)
            self.repository.add_session(new_session)
            self.repository.add_access_grant(new_grant)
            self.repository.save_idempotency(reservation.record)
            self.audit.record(
                action="conversation.public.reset",
                organization_id=binding.organization_id,
                deployment_id=binding.deployment_id,
                session_id=old_session.id,
            )
            return _conversation_result(
                session=new_session,
                access_token=issued.raw_value,
                replayed=False,
                previous_lifecycle=old_session.lifecycle,
            )

        return self._execute(operation)


class DeletePublicConversationUseCase(_TransactionalPublicUseCase):
    def execute(self, command: LifecycleCommand) -> DeletePublicConversationResult:
        def operation() -> DeletePublicConversationResult:
            binding = self._binding(command.url_slug)
            grant = self._grant_for_mutation(
                binding=binding,
                raw_access_token=command.access_token,
                now=command.now,
            )
            session = self._session_for_grant(grant, now=command.now)
            reservation = self._reserve(
                organization_id=binding.organization_id,
                operation="conversation.delete",
                scope_digest=_scope_digest(
                    operation="conversation.delete",
                    binding=binding,
                    grant=grant,
                    session=session,
                ),
                idempotency_key_hash=command.idempotency_key_hash,
                request_fingerprint=command.request_fingerprint,
                now=command.now,
            )
            if not reservation.created:
                reservation.record.require_matching_fingerprint(
                    command.request_fingerprint
                )
                purge_job = _record_purge_job(self.repository, reservation.record)
                receipt = self._replay_secret(
                    record=reservation.record,
                    purpose="purge_receipt",
                    now=command.now,
                )
                return DeletePublicConversationResult(
                    lifecycle=SessionLifecycle.DELETE_PENDING,
                    lifecycle_revision=session.lifecycle_revision,
                    purge_job_id=purge_job.id,
                    purge_receipt=receipt,
                    replayed=True,
                )

            self._admit(
                operation="conversation.delete",
                binding=binding,
                grant_id=grant.id,
                network_address=command.network_address,
            )

            grant.require_active(
                deployment_id=binding.deployment_id,
                deployment_version=binding.deployment_version,
                audience_kind=AudienceKind.PUBLIC_CHATBOT,
                now=command.now,
            )
            issued = self.secrets.issue_purge_receipt()
            purge_job = ConversationPurgeJob.pending(
                purge_job_id=uuid.uuid4(),
                organization_id=binding.organization_id,
                session_id=session.id,
                session_reference_digest=hashlib.sha256(
                    str(session.id).encode("ascii")
                ).hexdigest(),
                receipt_verifier_hash=issued.verifier_hash,
                receipt_verifier_key_version=issued.verifier_key_version,
                receipt_expires_at=command.now + self.policy.purge_receipt_lifetime,
                max_attempts=self.policy.purge_max_attempts,
                now=command.now,
            )
            session.request_delete(
                expected_lifecycle_revision=command.expected_lifecycle_revision,
                now=command.now,
            )
            grant.revoke(now=command.now)
            replay = self._add_secret_replay(
                record=reservation.record,
                purpose="purge_receipt",
                raw_secret=issued.raw_value,
                expires_at=min(
                    purge_job.receipt_expires_at,
                    command.now + self.policy.purge_secret_replay_lifetime,
                ),
            )
            reservation.record.complete(
                resource_type="conversation_purge_job",
                resource_reference=str(purge_job.id),
                replay_record_reference=str(replay.id),
                secret_replay_expires_at=replay.expires_at,
                safe_result_code="delete_requested",
                now=command.now,
            )
            self.repository.save_session(session)
            self.repository.save_access_grant(grant)
            self.repository.add_purge_job(purge_job)
            self.repository.save_idempotency(reservation.record)
            self.audit.record(
                action="conversation.public.delete_requested",
                organization_id=binding.organization_id,
                deployment_id=binding.deployment_id,
                session_id=session.id,
                purge_job_id=purge_job.id,
            )
            return DeletePublicConversationResult(
                lifecycle=session.lifecycle,
                lifecycle_revision=session.lifecycle_revision,
                purge_job_id=purge_job.id,
                purge_receipt=issued.raw_value,
                replayed=False,
            )

        return self._execute(operation)


class GetPublicTranscriptUseCase(_TransactionalPublicUseCase):
    """Return the safe empty projection until MBA-318 writes public turns."""

    def execute(
        self,
        *,
        url_slug: str,
        access_token: str,
        now: datetime,
    ) -> PublicTranscriptResult:
        def operation() -> PublicTranscriptResult:
            binding = self._binding(url_slug)
            grant = self._grant_for_mutation(
                binding=binding,
                raw_access_token=access_token,
                now=now,
            )
            grant.require_transcript(
                deployment_id=binding.deployment_id,
                deployment_version=binding.deployment_version,
                audience_kind=AudienceKind.PUBLIC_CHATBOT,
                now=now,
            )
            session = self._session_for_grant(grant, now=now)
            if session.lifecycle not in {
                SessionLifecycle.ACTIVE,
                SessionLifecycle.CLOSED,
            }:
                raise AccessGrantNotUsableError()
            return PublicTranscriptResult(
                lifecycle=session.lifecycle,
                lifecycle_revision=session.lifecycle_revision,
                entries=(),
            )

        return self._execute(operation)


class GetPublicPurgeStatusUseCase(_TransactionalPublicUseCase):
    def execute(
        self,
        *,
        url_slug: str,
        purge_receipt: str,
        now: datetime,
    ) -> PublicPurgeStatusResult:
        def operation() -> PublicPurgeStatusResult:
            # Resolve first so a stale/unknown slug cannot become an oracle.
            binding = self._binding(url_slug)
            verifier = self.secrets.purge_receipt_verifier(purge_receipt)
            if verifier is None:
                raise PurgeReceiptNotUsableError()
            job = self.repository.find_purge_job(
                verifier_key_version=verifier[0],
                verifier_hash=verifier[1],
            )
            if job is None or now >= job.receipt_expires_at:
                raise PurgeReceiptNotUsableError()
            if (
                job.receipt_verifier_key_version != verifier[0]
                or not hmac.compare_digest(job.receipt_verifier_hash, verifier[1])
            ):
                raise PurgeReceiptNotUsableError()
            if job.session_id is None:
                raise PurgeReceiptNotUsableError()
            session = self.repository.lock_session(
                organization_id=job.organization_id,
                session_id=job.session_id,
            )
            if (
                session is None
                or session.deployment_id != binding.deployment_id
                or session.deployment_version != binding.deployment_version
                or session.audience_kind is not AudienceKind.PUBLIC_CHATBOT
            ):
                raise PurgeReceiptNotUsableError()
            return PublicPurgeStatusResult(
                status=job.status,
                updated_at=job.updated_at,
                safe_failure_reason=job.safe_failure_reason,
            )

        return self._execute(operation)


def _new_session(
    *,
    binding: PublicDeploymentBinding,
    policy: PublicConversationPolicy,
    now: datetime,
) -> ConversationSession:
    return ConversationSession.create(
        session_id=uuid.uuid4(),
        organization_id=binding.organization_id,
        app_id=binding.app_id,
        workflow_id=binding.workflow_id,
        deployment_id=binding.deployment_id,
        deployment_version=binding.deployment_version,
        deployment_snapshot_hash=None,
        mapping_version=binding.mapping_version,
        memory_policy_version=binding.memory_policy_version,
        memory_contract_version=binding.memory_contract_version,
        storage_generation=binding.storage_generation,
        audience_kind=AudienceKind.PUBLIC_CHATBOT,
        subject_type=None,
        subject_id=None,
        idle_expires_at=now + policy.idle_lifetime,
        absolute_expires_at=now + policy.absolute_lifetime,
        now=now,
    )


def _scope_digest(
    *,
    operation: str,
    binding: PublicDeploymentBinding,
    grant: ConversationAccessGrant | None = None,
    session: ConversationSession | None = None,
) -> str:
    data = {
        "operation": operation,
        "organization_id": str(binding.organization_id),
        "deployment_id": str(binding.deployment_id),
        "deployment_version": binding.deployment_version,
        "audience_kind": AudienceKind.PUBLIC_CHATBOT.value,
        "grant_id": str(grant.id) if grant is not None else None,
        "session_id": str(session.id) if session is not None else None,
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _secret_replay_associated_data_digest(
    *, record: ConversationIdempotency, purpose: str
) -> str:
    data = {
        "idempotency_record_id": str(record.id),
        "organization_id": str(record.organization_id),
        "operation": record.operation,
        "purpose": purpose,
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _record_session(
    repository: PublicConversationRepositoryPort,
    record: ConversationIdempotency,
) -> ConversationSession:
    if record.resource_type != "conversation_session" or not record.resource_reference:
        raise MemoryAdapterUnavailableError()
    try:
        session_id = uuid.UUID(record.resource_reference)
    except ValueError:
        raise MemoryAdapterUnavailableError() from None
    session = repository.lock_session(
        organization_id=record.organization_id,
        session_id=session_id,
    )
    if session is None:
        raise MemoryAdapterUnavailableError()
    return session


def _record_purge_job(
    repository: PublicConversationRepositoryPort,
    record: ConversationIdempotency,
) -> ConversationPurgeJob:
    if record.resource_type != "conversation_purge_job" or not record.resource_reference:
        raise MemoryAdapterUnavailableError()
    try:
        resource_id = uuid.UUID(record.resource_reference)
    except ValueError:
        raise MemoryAdapterUnavailableError() from None
    # This lookup runs only after a matching verifier-bound idempotency record;
    # its UUID is never a public capability.
    result = repository.lock_purge_job_by_id(
        organization_id=record.organization_id,
        purge_job_id=resource_id,
    )
    if result is None:
        raise MemoryAdapterUnavailableError()
    return result


def _conversation_result(
    *,
    session: ConversationSession,
    access_token: str,
    replayed: bool,
    previous_lifecycle: SessionLifecycle | None = None,
) -> PublicConversationResult:
    return PublicConversationResult(
        lifecycle=session.lifecycle,
        lifecycle_revision=session.lifecycle_revision,
        memory_contract_version=session.memory_contract_version,
        expires_at=session.absolute_expires_at,
        access_token=access_token,
        replayed=replayed,
        previous_lifecycle=previous_lifecycle,
    )


def _close_result(
    session: ConversationSession, *, replayed: bool
) -> ClosePublicConversationResult:
    return ClosePublicConversationResult(
        lifecycle=session.lifecycle,
        lifecycle_revision=session.lifecycle_revision,
        memory_contract_version=session.memory_contract_version,
        expires_at=session.absolute_expires_at,
        replayed=replayed,
    )


__all__ = [
    "ClosePublicConversationResult",
    "ClosePublicConversationUseCase",
    "CreatePublicConversationCommand",
    "CreatePublicConversationUseCase",
    "DeletePublicConversationResult",
    "DeletePublicConversationUseCase",
    "GetPublicPurgeStatusUseCase",
    "GetPublicTranscriptUseCase",
    "IdempotencyReservation",
    "IssuedSecret",
    "LifecycleCommand",
    "PublicConversationAuditPort",
    "PublicConversationAdmissionPort",
    "PublicConversationPolicy",
    "PublicConversationRepositoryPort",
    "PublicConversationResult",
    "PublicDeploymentBinding",
    "PublicPurgeStatusResult",
    "PublicSecretIssuerPort",
    "ResetPublicConversationUseCase",
    "SecretCiphertext",
    "SecretReplayCipherPort",
]
