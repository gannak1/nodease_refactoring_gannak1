from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from apps.memory.application.context import (
    ContextAttemptState,
    MemoryContextProviderAttempt,
)
from apps.memory.application.ports import (
    ConversationMemoryRepositoryPort,
    MemoryUnitOfWorkPort,
)
from apps.memory.domain.conversation import (
    AudienceKind,
    ConversationMemoryEntry,
    ConversationPurgeJob,
    ConversationSession,
    ConversationTurn,
    EntryLifecycle,
    EntryType,
    MemoryTurnDispatchJob,
    ProtectedContent,
    ProtectedEntryContent,
    RequestIdentity,
    SessionLifecycle,
    TurnStatus,
)
from apps.memory.domain.errors import (
    EntryNotFoundError,
    SessionNotFoundError,
    StaleLifecycleRevisionError,
    StaleTurnVersionError,
)


@dataclass(frozen=True, slots=True)
class CreateSessionCommand:
    session_id: uuid.UUID
    organization_id: uuid.UUID
    app_id: uuid.UUID
    workflow_id: uuid.UUID
    deployment_id: uuid.UUID
    deployment_version: int | None
    deployment_snapshot_hash: str | None
    mapping_version: str
    memory_policy_version: str
    memory_contract_version: str
    storage_generation: int
    audience_kind: AudienceKind
    subject_type: str | None
    subject_id: uuid.UUID | None
    idle_expires_at: datetime
    absolute_expires_at: datetime
    now: datetime


@dataclass(frozen=True, slots=True)
class CreateSessionResult:
    session: ConversationSession


@dataclass(frozen=True, slots=True)
class StartTurnCommand:
    organization_id: uuid.UUID
    session_id: uuid.UUID
    expected_lifecycle_revision: int
    turn_id: uuid.UUID
    user_entry_id: uuid.UUID
    dispatch_id: uuid.UUID
    idempotency_key_hash: str
    request_fingerprint: str
    user_content: ProtectedEntryContent
    channel: str
    minimum_worker_capability: str
    max_dispatch_attempts: int
    now: datetime
    access_grant_id: uuid.UUID | None = None
    request_fingerprint_key_version: str | None = None


@dataclass(frozen=True, slots=True)
class StartTurnResult:
    session_id: uuid.UUID
    turn_id: uuid.UUID
    dispatch_id: uuid.UUID
    turn_sequence: int
    turn_version: int
    lifecycle_revision: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class CompleteTurnCommand:
    organization_id: uuid.UUID
    session_id: uuid.UUID
    turn_id: uuid.UUID
    expected_lifecycle_revision: int
    expected_turn_version: int
    outcome: Literal["completed", "failed", "cancelled"]
    assistant_entry_id: uuid.UUID | None
    assistant_content: ProtectedEntryContent | None
    safe_failure_reason: str | None
    now: datetime

    def __post_init__(self) -> None:
        if self.outcome not in {"completed", "failed", "cancelled"}:
            raise ValueError("outcome is invalid")


@dataclass(frozen=True, slots=True)
class CompleteTurnResult:
    session_id: uuid.UUID
    turn_id: uuid.UUID
    lifecycle: SessionLifecycle
    content_revision: int
    turn_version: int


@dataclass(frozen=True, slots=True)
class CheckpointAssistantResultCommand:
    organization_id: uuid.UUID
    session_id: uuid.UUID
    turn_id: uuid.UUID
    expected_lifecycle_revision: int
    expected_turn_version: int
    execution_id: uuid.UUID
    attempt_id: uuid.UUID
    assistant_entry_id: uuid.UUID
    assistant_content: ProtectedEntryContent
    now: datetime


@dataclass(frozen=True, slots=True)
class CheckpointAssistantResult:
    assistant_entry_id: uuid.UUID
    content_digest: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class RecoverAssistantCheckpointCommand:
    organization_id: uuid.UUID
    session_id: uuid.UUID
    turn_id: uuid.UUID
    execution_id: uuid.UUID
    attempt_id: uuid.UUID
    provider_attempt_id: uuid.UUID
    assistant_entry_id: uuid.UUID
    now: datetime


@dataclass(frozen=True, slots=True)
class RecoverAssistantCheckpointResult:
    assistant_entry_id: uuid.UUID
    assistant_content: ProtectedEntryContent
    content_digest: str
    expected_lifecycle_revision: int
    expected_turn_version: int
    context_attempt_id: uuid.UUID
    context_attempt_version: int
    context_attempt_outcome: str
    usage_reference: str


@dataclass(frozen=True, slots=True)
class CloseSessionCommand:
    organization_id: uuid.UUID
    session_id: uuid.UUID
    expected_lifecycle_revision: int
    now: datetime


@dataclass(frozen=True, slots=True)
class CloseSessionResult:
    session_id: uuid.UUID
    lifecycle: SessionLifecycle
    lifecycle_revision: int


@dataclass(frozen=True, slots=True)
class RequestDeleteCommand:
    organization_id: uuid.UUID
    session_id: uuid.UUID
    expected_lifecycle_revision: int
    purge_job_id: uuid.UUID
    receipt_verifier_hash: str
    receipt_verifier_key_version: str
    receipt_expires_at: datetime
    max_attempts: int
    now: datetime


@dataclass(frozen=True, slots=True)
class RequestDeleteResult:
    session_id: uuid.UUID
    lifecycle: SessionLifecycle
    lifecycle_revision: int
    purge_job_id: uuid.UUID


class _TransactionalUseCase:
    def __init__(
        self,
        *,
        repository: ConversationMemoryRepositoryPort,
        uow: MemoryUnitOfWorkPort,
    ) -> None:
        self.repository = repository
        self.uow = uow

    def _execute(self, operation):
        self.uow.begin()
        try:
            result = operation()
            self.uow.commit()
            return result
        except Exception:
            self.uow.rollback()
            raise


class CreateSessionUseCase(_TransactionalUseCase):
    def execute(self, command: CreateSessionCommand) -> CreateSessionResult:
        def operation() -> CreateSessionResult:
            session = ConversationSession.create(
                session_id=command.session_id,
                organization_id=command.organization_id,
                app_id=command.app_id,
                workflow_id=command.workflow_id,
                deployment_id=command.deployment_id,
                deployment_version=command.deployment_version,
                deployment_snapshot_hash=command.deployment_snapshot_hash,
                mapping_version=command.mapping_version,
                memory_policy_version=command.memory_policy_version,
                memory_contract_version=command.memory_contract_version,
                storage_generation=command.storage_generation,
                audience_kind=command.audience_kind,
                subject_type=command.subject_type,
                subject_id=command.subject_id,
                idle_expires_at=command.idle_expires_at,
                absolute_expires_at=command.absolute_expires_at,
                now=command.now,
            )
            self.repository.add_session(session)
            return CreateSessionResult(session=session)

        return self._execute(operation)


class StartTurnUseCase(_TransactionalUseCase):
    def execute(self, command: StartTurnCommand) -> StartTurnResult:
        def operation() -> StartTurnResult:
            request_identity = RequestIdentity(
                idempotency_key_hash=command.idempotency_key_hash,
                request_fingerprint=command.request_fingerprint,
            )
            session = self.repository.lock_session(
                organization_id=command.organization_id,
                session_id=command.session_id,
            )
            if session is None:
                raise SessionNotFoundError()

            existing = self.repository.find_turn_by_request(
                organization_id=command.organization_id,
                session_id=command.session_id,
                idempotency_key_hash=request_identity.idempotency_key_hash,
            )
            if existing is not None:
                existing.request_identity.ensure_replay_matches(
                    request_identity.request_fingerprint
                )
                return StartTurnResult(
                    session_id=session.id,
                    turn_id=existing.id,
                    dispatch_id=existing.dispatch_id,
                    turn_sequence=existing.sequence,
                    turn_version=existing.version,
                    lifecycle_revision=session.lifecycle_revision,
                    replayed=True,
                )

            sequence = session.claim_turn(
                turn_id=command.turn_id,
                expected_lifecycle_revision=command.expected_lifecycle_revision,
                now=command.now,
            )
            turn = ConversationTurn.start(
                turn_id=command.turn_id,
                organization_id=command.organization_id,
                session_id=command.session_id,
                sequence=sequence,
                started_lifecycle_revision=session.lifecycle_revision,
                request_identity=request_identity,
                user_entry_id=command.user_entry_id,
                dispatch_id=command.dispatch_id,
                access_grant_id=command.access_grant_id,
                request_fingerprint_key_version=(
                    command.request_fingerprint_key_version
                ),
                now=command.now,
            )
            entry = ConversationMemoryEntry.provisional_user(
                entry_id=command.user_entry_id,
                organization_id=command.organization_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
                sequence=(sequence * 2) - 1,
                channel=command.channel,
                content=command.user_content,
                idempotency_key_hash=request_identity.idempotency_key_hash,
                now=command.now,
            )
            dispatch = MemoryTurnDispatchJob.pending(
                dispatch_id=command.dispatch_id,
                organization_id=command.organization_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
                memory_contract_version=session.memory_contract_version,
                storage_generation=session.storage_generation,
                minimum_worker_capability=command.minimum_worker_capability,
                max_attempts=command.max_dispatch_attempts,
                now=command.now,
            )
            self.repository.save_session(session)
            self.repository.add_turn(turn)
            self.repository.add_entry(entry)
            self.repository.add_dispatch_job(dispatch)
            return StartTurnResult(
                session_id=session.id,
                turn_id=turn.id,
                dispatch_id=dispatch.id,
                turn_sequence=turn.sequence,
                turn_version=turn.version,
                lifecycle_revision=session.lifecycle_revision,
                replayed=False,
            )

        return self._execute(operation)


class CheckpointAssistantResultUseCase(_TransactionalUseCase):
    """Persist provider output before terminalization so retries never resend."""

    def execute(
        self,
        command: CheckpointAssistantResultCommand,
    ) -> CheckpointAssistantResult:
        def operation() -> CheckpointAssistantResult:
            session = self.repository.lock_session(
                organization_id=command.organization_id,
                session_id=command.session_id,
            )
            if session is None:
                raise SessionNotFoundError()
            session.require_active(
                expected_lifecycle_revision=command.expected_lifecycle_revision,
                now=command.now,
            )
            turn = self.repository.lock_turn(
                organization_id=command.organization_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
            )
            if turn is None:
                raise SessionNotFoundError()
            if (
                turn.status is not TurnStatus.RUNNING
                or turn.version != command.expected_turn_version
                or turn.execution_id != command.execution_id
                or turn.latest_attempt_id != command.attempt_id
            ):
                raise StaleTurnVersionError()
            user_entry = self.repository.get_entry(
                organization_id=command.organization_id,
                session_id=command.session_id,
                entry_id=turn.user_entry_id,
            )
            if user_entry is None:
                raise EntryNotFoundError()
            existing = self.repository.get_entry(
                organization_id=command.organization_id,
                session_id=command.session_id,
                entry_id=command.assistant_entry_id,
            )
            if existing is not None:
                if (
                    existing.turn_id != turn.id
                    or existing.entry_type is not EntryType.ASSISTANT_TURN
                    or existing.lifecycle is not EntryLifecycle.PROVISIONAL
                    or not _same_protected_content_identity(
                        existing.content,
                        command.assistant_content,
                    )
                ):
                    raise StaleTurnVersionError()
                return CheckpointAssistantResult(
                    assistant_entry_id=existing.id,
                    content_digest=_entry_content_identity_digest(existing.content),
                    replayed=True,
                )
            entry = ConversationMemoryEntry.provisional_assistant(
                entry_id=command.assistant_entry_id,
                organization_id=command.organization_id,
                session_id=command.session_id,
                turn_id=turn.id,
                sequence=turn.sequence * 2,
                channel=user_entry.channel,
                content=command.assistant_content,
                idempotency_key_hash=_assistant_entry_key(turn.id),
                now=command.now,
            )
            self.repository.add_entry(entry)
            return CheckpointAssistantResult(
                assistant_entry_id=entry.id,
                content_digest=_entry_content_identity_digest(entry.content),
                replayed=False,
            )

        return self._execute(operation)


class RecoverAssistantCheckpointUseCase(_TransactionalUseCase):
    """Return a bound protected checkpoint without revealing assistant text."""

    def execute(
        self,
        command: RecoverAssistantCheckpointCommand,
    ) -> RecoverAssistantCheckpointResult | None:
        def operation() -> RecoverAssistantCheckpointResult | None:
            session = self.repository.lock_session(
                organization_id=command.organization_id,
                session_id=command.session_id,
            )
            turn = self.repository.lock_turn(
                organization_id=command.organization_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
            )
            if session is None or turn is None:
                raise SessionNotFoundError()
            expected_attempt_id = uuid.uuid5(
                command.execution_id,
                "conversation-execution-attempt-v1",
            )
            expected_entry_id = uuid.uuid5(
                command.execution_id,
                "conversation-assistant-checkpoint-v1",
            )
            if (
                command.attempt_id != expected_attempt_id
                or command.assistant_entry_id != expected_entry_id
            ):
                raise StaleTurnVersionError()

            entry = self.repository.get_entry(
                organization_id=command.organization_id,
                session_id=command.session_id,
                entry_id=command.assistant_entry_id,
            )
            if entry is None:
                first_delivery = (
                    turn.status
                    in {
                        TurnStatus.PENDING_DISPATCH,
                        TurnStatus.QUEUED,
                    }
                    and turn.execution_id is None
                    and turn.latest_attempt_id is None
                )
                same_running_attempt = (
                    turn.status is TurnStatus.RUNNING
                    and turn.execution_id == command.execution_id
                    and turn.latest_attempt_id == command.attempt_id
                )
                if first_delivery or same_running_attempt:
                    return None
                raise StaleTurnVersionError()
            if (
                turn.execution_id != command.execution_id
                or turn.latest_attempt_id != command.attempt_id
            ):
                raise StaleTurnVersionError()

            if turn.status is TurnStatus.RUNNING:
                session.require_active(
                    expected_lifecycle_revision=session.lifecycle_revision,
                    now=command.now,
                )
                expected_turn_version = turn.version
                required_entry_lifecycle = EntryLifecycle.PROVISIONAL
            elif (
                turn.status is TurnStatus.COMPLETED
                and turn.assistant_entry_id == command.assistant_entry_id
                and turn.version > 1
            ):
                expected_turn_version = turn.version - 1
                required_entry_lifecycle = EntryLifecycle.APPROVED
            else:
                raise StaleTurnVersionError()

            if (
                entry.turn_id != turn.id
                or entry.entry_type is not EntryType.ASSISTANT_TURN
                or entry.lifecycle is not required_entry_lifecycle
                or entry.content is None
            ):
                raise StaleTurnVersionError()

            context_attempt: MemoryContextProviderAttempt | None = (
                self.repository.lock_context_attempt(command.provider_attempt_id)
            )
            if (
                context_attempt is None
                or context_attempt.id != command.provider_attempt_id
                or context_attempt.organization_id != command.organization_id
                or context_attempt.session_id != command.session_id
                or context_attempt.turn_id != command.turn_id
                or context_attempt.status
                not in {
                    ContextAttemptState.PROVIDER_STARTED,
                    ContextAttemptState.SUCCEEDED,
                    ContextAttemptState.OUTCOME_UNKNOWN,
                }
                or context_attempt.usage_reference is None
            ):
                raise StaleTurnVersionError()

            return RecoverAssistantCheckpointResult(
                assistant_entry_id=entry.id,
                assistant_content=entry.content,
                content_digest=_entry_content_identity_digest(entry.content),
                expected_lifecycle_revision=session.lifecycle_revision,
                expected_turn_version=expected_turn_version,
                context_attempt_id=context_attempt.id,
                context_attempt_version=context_attempt.version,
                context_attempt_outcome=context_attempt.status.value,
                usage_reference=context_attempt.usage_reference,
            )

        return self._execute(operation)


class CompleteTurnUseCase(_TransactionalUseCase):
    def execute(self, command: CompleteTurnCommand) -> CompleteTurnResult:
        def operation() -> CompleteTurnResult:
            session = self.repository.lock_session(
                organization_id=command.organization_id,
                session_id=command.session_id,
            )
            if session is None:
                raise SessionNotFoundError()
            turn = self.repository.lock_turn(
                organization_id=command.organization_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
            )
            if turn is None:
                raise SessionNotFoundError()
            user_entry = self.repository.get_entry(
                organization_id=command.organization_id,
                session_id=command.session_id,
                entry_id=turn.user_entry_id,
            )
            if user_entry is None:
                raise EntryNotFoundError()

            replay = _terminal_complete_turn_replay(
                repository=self.repository,
                command=command,
                session=session,
                turn=turn,
                user_entry=user_entry,
            )
            if replay is not None:
                return replay

            if command.outcome == "completed":
                if (
                    command.assistant_entry_id is None
                    or command.assistant_content is None
                ):
                    raise ValueError(
                        "completed turn requires protected assistant content"
                    )
                turn.complete(
                    expected_version=command.expected_turn_version,
                    assistant_entry_id=command.assistant_entry_id,
                    now=command.now,
                )
                session.release_turn(
                    turn_id=turn.id,
                    expected_lifecycle_revision=command.expected_lifecycle_revision,
                    content_changed=True,
                    now=command.now,
                )
                user_entry.approve(
                    content_revision=session.content_revision,
                    now=command.now,
                )
                assistant_entry = self.repository.get_entry(
                    organization_id=command.organization_id,
                    session_id=command.session_id,
                    entry_id=command.assistant_entry_id,
                )
                if assistant_entry is None:
                    # Compatibility for existing internal callers.  The public
                    # runtime always checkpoints before reaching this branch.
                    assistant_entry = ConversationMemoryEntry.approved_assistant(
                        entry_id=command.assistant_entry_id,
                        organization_id=command.organization_id,
                        session_id=command.session_id,
                        turn_id=turn.id,
                        sequence=turn.sequence * 2,
                        channel=user_entry.channel,
                        content=command.assistant_content,
                        content_revision=session.content_revision,
                        idempotency_key_hash=_assistant_entry_key(turn.id),
                        now=command.now,
                    )
                    self.repository.add_entry(assistant_entry)
                else:
                    if (
                        assistant_entry.turn_id != turn.id
                        or assistant_entry.entry_type is not EntryType.ASSISTANT_TURN
                        or assistant_entry.lifecycle is not EntryLifecycle.PROVISIONAL
                        or not _same_protected_content_identity(
                            assistant_entry.content,
                            command.assistant_content,
                        )
                    ):
                        raise StaleTurnVersionError()
                    assistant_entry.approve(
                        content_revision=session.content_revision,
                        now=command.now,
                    )
                    self.repository.save_entry(assistant_entry)
            else:
                assistant_entry = None
                if command.assistant_entry_id is not None:
                    if command.assistant_content is None:
                        raise ValueError(
                            "assistant checkpoint identity requires protected content"
                        )
                    assistant_entry = self.repository.get_entry(
                        organization_id=command.organization_id,
                        session_id=command.session_id,
                        entry_id=command.assistant_entry_id,
                    )
                    if (
                        assistant_entry is None
                        or assistant_entry.turn_id != turn.id
                        or assistant_entry.entry_type is not EntryType.ASSISTANT_TURN
                        or assistant_entry.lifecycle is not EntryLifecycle.PROVISIONAL
                        or not _same_protected_content_identity(
                            assistant_entry.content,
                            command.assistant_content,
                        )
                    ):
                        raise StaleTurnVersionError()
                elif command.assistant_content is not None:
                    raise ValueError(
                        "assistant checkpoint content requires an entry identity"
                    )
                if not command.safe_failure_reason:
                    raise ValueError("terminal failure requires safe reason")
                if command.outcome == "failed":
                    turn.fail(
                        expected_version=command.expected_turn_version,
                        safe_reason_code=command.safe_failure_reason,
                        now=command.now,
                    )
                else:
                    turn.cancel(
                        expected_version=command.expected_turn_version,
                        safe_reason_code=command.safe_failure_reason,
                        now=command.now,
                    )
                session.release_turn(
                    turn_id=turn.id,
                    expected_lifecycle_revision=command.expected_lifecycle_revision,
                    content_changed=False,
                    now=command.now,
                )
                user_entry.reject(now=command.now)
                if assistant_entry is not None:
                    assistant_entry.reject(now=command.now)
                    self.repository.save_entry(assistant_entry)

            self.repository.save_turn(turn)
            self.repository.save_session(session)
            self.repository.save_entry(user_entry)
            return CompleteTurnResult(
                session_id=session.id,
                turn_id=turn.id,
                lifecycle=session.lifecycle,
                content_revision=session.content_revision,
                turn_version=turn.version,
            )

        return self._execute(operation)


def _terminal_complete_turn_replay(
    *,
    repository: ConversationMemoryRepositoryPort,
    command: CompleteTurnCommand,
    session: ConversationSession,
    turn: ConversationTurn,
    user_entry: ConversationMemoryEntry,
) -> CompleteTurnResult | None:
    if not turn.terminal:
        return None
    if session.lifecycle_revision != command.expected_lifecycle_revision:
        raise StaleLifecycleRevisionError()
    if turn.version != command.expected_turn_version + 1:
        raise StaleTurnVersionError()
    if turn.status is not TurnStatus(command.outcome):
        raise StaleTurnVersionError()
    if session.active_turn_id == turn.id:
        raise StaleTurnVersionError()

    content_revision = session.content_revision
    if command.outcome == "completed":
        if command.assistant_entry_id is None or command.assistant_content is None:
            raise StaleTurnVersionError()
        if turn.assistant_entry_id != command.assistant_entry_id:
            raise StaleTurnVersionError()
        assistant_entry = repository.get_entry(
            organization_id=command.organization_id,
            session_id=command.session_id,
            entry_id=command.assistant_entry_id,
        )
        if assistant_entry is None:
            raise EntryNotFoundError()
        if (
            user_entry.lifecycle is not EntryLifecycle.APPROVED
            or user_entry.content_revision is None
            or assistant_entry.turn_id != turn.id
            or assistant_entry.entry_type is not EntryType.ASSISTANT_TURN
            or assistant_entry.lifecycle is not EntryLifecycle.APPROVED
            or assistant_entry.content_revision is None
            or assistant_entry.content_revision != user_entry.content_revision
            or not _same_protected_content_identity(
                assistant_entry.content,
                command.assistant_content,
            )
        ):
            raise StaleTurnVersionError()
        content_revision = assistant_entry.content_revision
    elif (
        command.assistant_entry_id is not None
        or command.assistant_content is not None
        or not command.safe_failure_reason
        or turn.assistant_entry_id is not None
        or turn.safe_failure_reason != command.safe_failure_reason
        or user_entry.lifecycle is not EntryLifecycle.REJECTED
        or user_entry.content_revision is not None
    ):
        raise StaleTurnVersionError()

    return CompleteTurnResult(
        session_id=session.id,
        turn_id=turn.id,
        lifecycle=session.lifecycle,
        content_revision=content_revision,
        turn_version=turn.version,
    )


def _same_protected_content_identity(
    stored: ProtectedEntryContent | None,
    requested: ProtectedEntryContent,
) -> bool:
    if stored is None:
        return False
    return _protected_projection_identity(
        stored.display
    ) == _protected_projection_identity(
        requested.display
    ) and _protected_projection_identity(
        stored.model
    ) == _protected_projection_identity(requested.model)


def _protected_projection_identity(
    projection: ProtectedContent | None,
) -> tuple[str, str, int] | None:
    if projection is None:
        return None
    return (
        projection.format_version,
        projection.content_digest,
        projection.plaintext_byte_length,
    )


def _entry_content_identity_digest(
    content: ProtectedEntryContent | None,
) -> str:
    if content is None:
        raise ValueError("protected entry content is required")
    payload = "|".join(
        "-" if value is None else ":".join(map(str, value))
        for value in (
            _protected_projection_identity(content.display),
            _protected_projection_identity(content.model),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CloseSessionUseCase(_TransactionalUseCase):
    def execute(self, command: CloseSessionCommand) -> CloseSessionResult:
        def operation() -> CloseSessionResult:
            session = self.repository.lock_session(
                organization_id=command.organization_id,
                session_id=command.session_id,
            )
            if session is None:
                raise SessionNotFoundError()
            session.close(
                expected_lifecycle_revision=command.expected_lifecycle_revision,
                now=command.now,
            )
            self.repository.save_session(session)
            return CloseSessionResult(
                session_id=session.id,
                lifecycle=session.lifecycle,
                lifecycle_revision=session.lifecycle_revision,
            )

        return self._execute(operation)


class RequestDeleteUseCase(_TransactionalUseCase):
    def execute(self, command: RequestDeleteCommand) -> RequestDeleteResult:
        def operation() -> RequestDeleteResult:
            session = self.repository.lock_session(
                organization_id=command.organization_id,
                session_id=command.session_id,
            )
            if session is None:
                raise SessionNotFoundError()
            session.request_delete(
                expected_lifecycle_revision=command.expected_lifecycle_revision,
                now=command.now,
            )
            purge_job = ConversationPurgeJob.pending(
                purge_job_id=command.purge_job_id,
                organization_id=command.organization_id,
                session_id=command.session_id,
                session_reference_digest=_session_reference_digest(
                    command.organization_id,
                    command.session_id,
                ),
                app_id=session.app_id,
                deployment_id=session.deployment_id,
                deployment_version=session.deployment_version,
                audience_kind=session.audience_kind,
                receipt_verifier_hash=command.receipt_verifier_hash,
                receipt_verifier_key_version=command.receipt_verifier_key_version,
                receipt_expires_at=command.receipt_expires_at,
                max_attempts=command.max_attempts,
                now=command.now,
            )
            self.repository.save_session(session)
            self.repository.add_purge_job(purge_job)
            return RequestDeleteResult(
                session_id=session.id,
                lifecycle=session.lifecycle,
                lifecycle_revision=session.lifecycle_revision,
                purge_job_id=purge_job.id,
            )

        return self._execute(operation)


def _assistant_entry_key(turn_id: uuid.UUID) -> str:
    return hashlib.sha256(f"assistant:{turn_id}".encode("ascii")).hexdigest()


def _session_reference_digest(
    organization_id: uuid.UUID,
    session_id: uuid.UUID,
) -> str:
    return hashlib.sha256(f"{organization_id}:{session_id}".encode("ascii")).hexdigest()
