from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransaction

from apps.memory.domain.conversation import (
    AudienceKind,
    ConversationMemoryEntry,
    ConversationPurgeJob,
    ConversationSession,
    ConversationTurn,
    DispatchStatus,
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
    ActiveTurnConflictError,
    DispatchStateConflictError,
    DuplicateRequestConflictError,
    MemoryAdapterUnavailableError,
    StaleRevisionError,
)
from apps.shared.db.models.conversation_memory import (
    ConversationMemoryEntryRecord,
    ConversationPurgeJobRecord,
    ConversationSessionRecord,
    ConversationTurnRecord,
    MemoryTurnDispatchJobRecord,
)


@dataclass(frozen=True, slots=True)
class _SessionBaseline:
    lifecycle_revision: int
    content_revision: int


@dataclass(frozen=True, slots=True)
class _TurnBaseline:
    version: int


@dataclass(frozen=True, slots=True)
class _EntryBaseline:
    lifecycle: str
    content_revision: int | None


@dataclass(frozen=True, slots=True)
class _DispatchBaseline:
    status: str
    claim_generation: int
    attempt_count: int


class SqlAlchemyConversationMemoryRepository:
    """Memory-owned persistence adapter over the shared SQLAlchemy registry."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._session_baselines: dict[
            tuple[uuid.UUID, uuid.UUID], _SessionBaseline
        ] = {}
        self._turn_baselines: dict[
            tuple[uuid.UUID, uuid.UUID, uuid.UUID], _TurnBaseline
        ] = {}
        self._entry_baselines: dict[
            tuple[uuid.UUID, uuid.UUID, uuid.UUID], _EntryBaseline
        ] = {}
        self._dispatch_baselines: dict[
            tuple[uuid.UUID, uuid.UUID], _DispatchBaseline
        ] = {}

    def add_session(self, session: ConversationSession) -> None:
        self._session.add(_session_record(session))

    def lock_session(
        self,
        *,
        organization_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> ConversationSession | None:
        statement = (
            select(ConversationSessionRecord)
            .where(
                ConversationSessionRecord.organization_id == organization_id,
                ConversationSessionRecord.id == session_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        record = _execute(self._session, statement).scalar_one_or_none()
        if record is None:
            return None
        domain = _session_domain(record)
        self._session_baselines[(organization_id, session_id)] = _SessionBaseline(
            lifecycle_revision=record.lifecycle_revision,
            content_revision=record.content_revision,
        )
        return domain

    def save_session(self, session: ConversationSession) -> None:
        key = (session.organization_id, session.id)
        baseline = self._session_baselines.get(key)
        if baseline is None:
            raise StaleRevisionError()
        statement = (
            update(ConversationSessionRecord)
            .where(
                ConversationSessionRecord.organization_id == session.organization_id,
                ConversationSessionRecord.id == session.id,
                ConversationSessionRecord.lifecycle_revision
                == baseline.lifecycle_revision,
                ConversationSessionRecord.content_revision == baseline.content_revision,
            )
            .values(
                lifecycle=session.lifecycle.value,
                lifecycle_revision=session.lifecycle_revision,
                content_revision=session.content_revision,
                active_turn_id=session.active_turn_id,
                next_turn_sequence=session.next_turn_sequence,
                idle_expires_at=session.idle_expires_at,
                absolute_expires_at=session.absolute_expires_at,
                closed_at=session.closed_at,
                delete_requested_at=session.delete_requested_at,
                deleted_at=session.deleted_at,
                updated_at=session.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        _require_single_row(_execute(self._session, statement))
        self._session_baselines[key] = _SessionBaseline(
            lifecycle_revision=session.lifecycle_revision,
            content_revision=session.content_revision,
        )

    def find_turn_by_request(
        self,
        *,
        organization_id: uuid.UUID,
        session_id: uuid.UUID,
        idempotency_key_hash: str,
    ) -> ConversationTurn | None:
        statement = select(ConversationTurnRecord).where(
            ConversationTurnRecord.organization_id == organization_id,
            ConversationTurnRecord.session_id == session_id,
            ConversationTurnRecord.request_idempotency_hash == idempotency_key_hash,
        )
        record = _execute(self._session, statement).scalar_one_or_none()
        return _turn_domain(record) if record is not None else None

    def add_turn(self, turn: ConversationTurn) -> None:
        self._session.add(_turn_record(turn))

    def lock_turn(
        self,
        *,
        organization_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
    ) -> ConversationTurn | None:
        statement = (
            select(ConversationTurnRecord)
            .where(
                ConversationTurnRecord.organization_id == organization_id,
                ConversationTurnRecord.session_id == session_id,
                ConversationTurnRecord.id == turn_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        record = _execute(self._session, statement).scalar_one_or_none()
        if record is None:
            return None
        domain = _turn_domain(record)
        self._turn_baselines[(organization_id, session_id, turn_id)] = _TurnBaseline(
            version=record.version
        )
        return domain

    def save_turn(self, turn: ConversationTurn) -> None:
        key = (turn.organization_id, turn.session_id, turn.id)
        baseline = self._turn_baselines.get(key)
        if baseline is None:
            raise StaleRevisionError()
        statement = (
            update(ConversationTurnRecord)
            .where(
                ConversationTurnRecord.organization_id == turn.organization_id,
                ConversationTurnRecord.session_id == turn.session_id,
                ConversationTurnRecord.id == turn.id,
                ConversationTurnRecord.version == baseline.version,
            )
            .values(
                version=turn.version,
                status=turn.status.value,
                assistant_entry_id=turn.assistant_entry_id,
                execution_id=turn.execution_id,
                latest_attempt_id=turn.latest_attempt_id,
                safe_failure_reason=turn.safe_failure_reason,
                started_at=turn.started_at,
                completed_at=turn.completed_at,
                updated_at=turn.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        _require_single_row(_execute(self._session, statement))
        self._turn_baselines[key] = _TurnBaseline(version=turn.version)

    def add_entry(self, entry: ConversationMemoryEntry) -> None:
        self._session.add(_entry_record(entry))

    def get_entry(
        self,
        *,
        organization_id: uuid.UUID,
        session_id: uuid.UUID,
        entry_id: uuid.UUID,
    ) -> ConversationMemoryEntry | None:
        statement = (
            select(ConversationMemoryEntryRecord)
            .where(
                ConversationMemoryEntryRecord.organization_id == organization_id,
                ConversationMemoryEntryRecord.session_id == session_id,
                ConversationMemoryEntryRecord.id == entry_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        record = _execute(self._session, statement).scalar_one_or_none()
        if record is None:
            return None
        domain = _entry_domain(record)
        self._entry_baselines[(organization_id, session_id, entry_id)] = _EntryBaseline(
            lifecycle=record.lifecycle,
            content_revision=record.content_revision,
        )
        return domain

    def save_entry(self, entry: ConversationMemoryEntry) -> None:
        key = (entry.organization_id, entry.session_id, entry.id)
        baseline = self._entry_baselines.get(key)
        if baseline is None:
            raise StaleRevisionError()
        content_revision_predicate = (
            ConversationMemoryEntryRecord.content_revision.is_(None)
            if baseline.content_revision is None
            else ConversationMemoryEntryRecord.content_revision
            == baseline.content_revision
        )
        statement = (
            update(ConversationMemoryEntryRecord)
            .where(
                ConversationMemoryEntryRecord.organization_id == entry.organization_id,
                ConversationMemoryEntryRecord.session_id == entry.session_id,
                ConversationMemoryEntryRecord.id == entry.id,
                ConversationMemoryEntryRecord.lifecycle == baseline.lifecycle,
                content_revision_predicate,
            )
            .values(
                lifecycle=entry.lifecycle.value,
                content_revision=entry.content_revision,
                invalidated_at=entry.invalidated_at,
                expires_at=entry.expires_at,
                updated_at=entry.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        _require_single_row(_execute(self._session, statement))
        self._entry_baselines[key] = _EntryBaseline(
            lifecycle=entry.lifecycle.value,
            content_revision=entry.content_revision,
        )

    def add_dispatch_job(self, job: MemoryTurnDispatchJob) -> None:
        self._session.add(_dispatch_record(job))

    def lock_dispatch_job(
        self,
        *,
        organization_id: uuid.UUID,
        dispatch_id: uuid.UUID,
    ) -> MemoryTurnDispatchJob | None:
        statement = (
            select(MemoryTurnDispatchJobRecord)
            .where(
                MemoryTurnDispatchJobRecord.organization_id == organization_id,
                MemoryTurnDispatchJobRecord.id == dispatch_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        record = _execute(self._session, statement).scalar_one_or_none()
        if record is None:
            return None
        domain = _dispatch_domain(record)
        self._dispatch_baselines[(organization_id, dispatch_id)] = _DispatchBaseline(
            status=record.status,
            claim_generation=record.claim_generation,
            attempt_count=record.attempt_count,
        )
        return domain

    def save_dispatch_job(self, job: MemoryTurnDispatchJob) -> None:
        key = (job.organization_id, job.id)
        baseline = self._dispatch_baselines.get(key)
        if baseline is None:
            raise DispatchStateConflictError()
        statement = (
            update(MemoryTurnDispatchJobRecord)
            .where(
                MemoryTurnDispatchJobRecord.organization_id == job.organization_id,
                MemoryTurnDispatchJobRecord.id == job.id,
                MemoryTurnDispatchJobRecord.status == baseline.status,
                MemoryTurnDispatchJobRecord.claim_generation
                == baseline.claim_generation,
                MemoryTurnDispatchJobRecord.attempt_count == baseline.attempt_count,
            )
            .values(
                status=job.status.value,
                claim_generation=job.claim_generation,
                claim_owner=job.claim_owner,
                claim_deadline_at=job.claim_deadline_at,
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
                next_attempt_at=job.next_attempt_at,
                broker_message_id=job.broker_message_id,
                workflow_admission_reference=job.workflow_admission_reference,
                safe_failure_reason=job.safe_failure_reason,
                published_at=job.published_at,
                acknowledged_at=job.acknowledged_at,
                terminal_at=job.terminal_at,
                updated_at=job.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        _require_single_row(
            _execute(self._session, statement),
            error_type=DispatchStateConflictError,
        )
        self._dispatch_baselines[key] = _DispatchBaseline(
            status=job.status.value,
            claim_generation=job.claim_generation,
            attempt_count=job.attempt_count,
        )

    def add_purge_job(self, job: ConversationPurgeJob) -> None:
        self._session.add(_purge_record(job))


class SqlAlchemyMemoryUnitOfWork:
    """Owns the transaction used by one Memory mutation use case."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._transaction: SessionTransaction | None = None

    def begin(self) -> None:
        if self._transaction is not None:
            raise RuntimeError("memory unit of work is already active")
        try:
            self._transaction = self._session.begin()
        except SQLAlchemyError:
            raise MemoryAdapterUnavailableError() from None

    def commit(self) -> None:
        transaction = self._require_transaction()
        try:
            transaction.commit()
        except SQLAlchemyError as exc:
            _raise_safe_persistence_error(exc)
        self._transaction = None

    def rollback(self) -> None:
        transaction = self._require_transaction()
        try:
            try:
                transaction.rollback()
            except SQLAlchemyError:
                raise MemoryAdapterUnavailableError() from None
        finally:
            self._transaction = None

    def _require_transaction(self) -> SessionTransaction:
        if self._transaction is None:
            raise RuntimeError("memory unit of work is not active")
        return self._transaction


def _require_single_row(
    result: Any,
    *,
    error_type: type[StaleRevisionError] = StaleRevisionError,
) -> None:
    if result.rowcount != 1:
        raise error_type()


def _execute(session: Session, statement):
    try:
        return session.execute(statement)
    except SQLAlchemyError as exc:
        _raise_safe_persistence_error(exc)


def _raise_safe_persistence_error(exc: SQLAlchemyError) -> None:
    if isinstance(exc, IntegrityError):
        constraint_name = getattr(getattr(exc, "orig", None), "diag", None)
        constraint_name = getattr(constraint_name, "constraint_name", None)
        if constraint_name == "uq_conv_turns_one_active":
            raise ActiveTurnConflictError() from None
        if constraint_name == "uq_conv_turns_session_request":
            raise DuplicateRequestConflictError() from None
    raise MemoryAdapterUnavailableError() from None


def _session_record(session: ConversationSession) -> ConversationSessionRecord:
    return ConversationSessionRecord(
        id=session.id,
        organization_id=session.organization_id,
        app_id=session.app_id,
        workflow_id=session.workflow_id,
        deployment_id=session.deployment_id,
        deployment_version=session.deployment_version,
        deployment_snapshot_hash=session.deployment_snapshot_hash,
        mapping_version=session.mapping_version,
        memory_policy_version=session.memory_policy_version,
        memory_contract_version=session.memory_contract_version,
        storage_generation=session.storage_generation,
        audience_kind=session.audience_kind.value,
        subject_type=session.subject_type,
        subject_id=session.subject_id,
        lifecycle=session.lifecycle.value,
        lifecycle_revision=session.lifecycle_revision,
        content_revision=session.content_revision,
        active_turn_id=session.active_turn_id,
        next_turn_sequence=session.next_turn_sequence,
        idle_expires_at=session.idle_expires_at,
        absolute_expires_at=session.absolute_expires_at,
        closed_at=session.closed_at,
        delete_requested_at=session.delete_requested_at,
        deleted_at=session.deleted_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _session_domain(record: ConversationSessionRecord) -> ConversationSession:
    return ConversationSession(
        id=record.id,
        organization_id=record.organization_id,
        app_id=record.app_id,
        workflow_id=record.workflow_id,
        deployment_id=record.deployment_id,
        deployment_version=record.deployment_version,
        deployment_snapshot_hash=record.deployment_snapshot_hash,
        mapping_version=record.mapping_version,
        memory_policy_version=record.memory_policy_version,
        memory_contract_version=record.memory_contract_version,
        storage_generation=record.storage_generation,
        audience_kind=AudienceKind(record.audience_kind),
        subject_type=record.subject_type,
        subject_id=record.subject_id,
        lifecycle=SessionLifecycle(record.lifecycle),
        lifecycle_revision=record.lifecycle_revision,
        content_revision=record.content_revision,
        active_turn_id=record.active_turn_id,
        next_turn_sequence=record.next_turn_sequence,
        idle_expires_at=record.idle_expires_at,
        absolute_expires_at=record.absolute_expires_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        closed_at=record.closed_at,
        delete_requested_at=record.delete_requested_at,
        deleted_at=record.deleted_at,
    )


def _turn_record(turn: ConversationTurn) -> ConversationTurnRecord:
    return ConversationTurnRecord(
        id=turn.id,
        organization_id=turn.organization_id,
        session_id=turn.session_id,
        sequence=turn.sequence,
        version=turn.version,
        started_lifecycle_revision=turn.started_lifecycle_revision,
        request_idempotency_hash=turn.request_identity.idempotency_key_hash,
        request_fingerprint=turn.request_identity.request_fingerprint,
        status=turn.status.value,
        user_entry_id=turn.user_entry_id,
        assistant_entry_id=turn.assistant_entry_id,
        dispatch_id=turn.dispatch_id,
        execution_id=turn.execution_id,
        latest_attempt_id=turn.latest_attempt_id,
        safe_failure_reason=turn.safe_failure_reason,
        started_at=turn.started_at,
        completed_at=turn.completed_at,
        created_at=turn.created_at,
        updated_at=turn.updated_at,
    )


def _turn_domain(record: ConversationTurnRecord) -> ConversationTurn:
    return ConversationTurn(
        id=record.id,
        organization_id=record.organization_id,
        session_id=record.session_id,
        sequence=record.sequence,
        version=record.version,
        started_lifecycle_revision=record.started_lifecycle_revision,
        request_identity=RequestIdentity(
            idempotency_key_hash=record.request_idempotency_hash,
            request_fingerprint=record.request_fingerprint,
        ),
        status=TurnStatus(record.status),
        user_entry_id=record.user_entry_id,
        dispatch_id=record.dispatch_id,
        assistant_entry_id=record.assistant_entry_id,
        execution_id=record.execution_id,
        latest_attempt_id=record.latest_attempt_id,
        safe_failure_reason=record.safe_failure_reason,
        created_at=record.created_at,
        updated_at=record.updated_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


def _entry_record(entry: ConversationMemoryEntry) -> ConversationMemoryEntryRecord:
    content = entry.content
    display = content.display if content is not None else None
    model = content.model if content is not None else None
    return ConversationMemoryEntryRecord(
        id=entry.id,
        organization_id=entry.organization_id,
        session_id=entry.session_id,
        turn_id=entry.turn_id,
        sequence=entry.sequence,
        entry_type=entry.entry_type.value,
        lifecycle=entry.lifecycle.value,
        channel=entry.channel,
        producer_node_id=entry.producer_node_id,
        display_ciphertext=display.ciphertext if display is not None else None,
        display_key_version=display.key_version if display is not None else None,
        display_format_version=(
            display.format_version if display is not None else None
        ),
        display_content_digest=(
            display.content_digest if display is not None else None
        ),
        display_plaintext_byte_length=(
            display.plaintext_byte_length if display is not None else None
        ),
        model_ciphertext=model.ciphertext if model is not None else None,
        model_key_version=model.key_version if model is not None else None,
        model_format_version=model.format_version if model is not None else None,
        model_content_digest=(model.content_digest if model is not None else None),
        model_plaintext_byte_length=(
            model.plaintext_byte_length if model is not None else None
        ),
        content_revision=entry.content_revision,
        idempotency_key_hash=entry.idempotency_key_hash,
        sensitivity="unclassified",
        expires_at=entry.expires_at,
        invalidated_at=entry.invalidated_at,
        erased_at=None if content is not None else entry.updated_at,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _entry_domain(record: ConversationMemoryEntryRecord) -> ConversationMemoryEntry:
    display = _projection_domain(record, "display")
    model = _projection_domain(record, "model")
    content = (
        ProtectedEntryContent(display=display, model=model)
        if display is not None or model is not None
        else None
    )
    return ConversationMemoryEntry(
        id=record.id,
        organization_id=record.organization_id,
        session_id=record.session_id,
        turn_id=record.turn_id,
        sequence=record.sequence,
        entry_type=EntryType(record.entry_type),
        lifecycle=EntryLifecycle(record.lifecycle),
        channel=record.channel,
        producer_node_id=record.producer_node_id,
        content=content,
        content_revision=record.content_revision,
        idempotency_key_hash=record.idempotency_key_hash,
        created_at=record.created_at,
        updated_at=record.updated_at,
        invalidated_at=record.invalidated_at,
        expires_at=record.expires_at,
    )


def _projection_domain(
    record: ConversationMemoryEntryRecord,
    projection: str,
) -> ProtectedContent | None:
    ciphertext = getattr(record, f"{projection}_ciphertext")
    if ciphertext is None:
        return None
    return ProtectedContent(
        ciphertext=bytes(ciphertext),
        key_version=getattr(record, f"{projection}_key_version"),
        format_version=getattr(record, f"{projection}_format_version"),
        content_digest=getattr(record, f"{projection}_content_digest"),
        plaintext_byte_length=getattr(
            record,
            f"{projection}_plaintext_byte_length",
        ),
    )


def _dispatch_record(job: MemoryTurnDispatchJob) -> MemoryTurnDispatchJobRecord:
    return MemoryTurnDispatchJobRecord(
        id=job.id,
        organization_id=job.organization_id,
        session_id=job.session_id,
        turn_id=job.turn_id,
        memory_contract_version=job.memory_contract_version,
        storage_generation=job.storage_generation,
        minimum_worker_capability=job.minimum_worker_capability,
        status=job.status.value,
        claim_generation=job.claim_generation,
        claim_owner=job.claim_owner,
        claim_deadline_at=job.claim_deadline_at,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        next_attempt_at=job.next_attempt_at,
        broker_message_id=job.broker_message_id,
        workflow_admission_reference=job.workflow_admission_reference,
        safe_failure_reason=job.safe_failure_reason,
        published_at=job.published_at,
        acknowledged_at=job.acknowledged_at,
        terminal_at=job.terminal_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _dispatch_domain(record: MemoryTurnDispatchJobRecord) -> MemoryTurnDispatchJob:
    return MemoryTurnDispatchJob(
        id=record.id,
        organization_id=record.organization_id,
        session_id=record.session_id,
        turn_id=record.turn_id,
        memory_contract_version=record.memory_contract_version,
        storage_generation=record.storage_generation,
        minimum_worker_capability=record.minimum_worker_capability,
        status=DispatchStatus(record.status),
        claim_generation=record.claim_generation,
        claim_owner=record.claim_owner,
        claim_deadline_at=record.claim_deadline_at,
        attempt_count=record.attempt_count,
        max_attempts=record.max_attempts,
        next_attempt_at=record.next_attempt_at,
        broker_message_id=record.broker_message_id,
        workflow_admission_reference=record.workflow_admission_reference,
        safe_failure_reason=record.safe_failure_reason,
        created_at=record.created_at,
        updated_at=record.updated_at,
        published_at=record.published_at,
        acknowledged_at=record.acknowledged_at,
        terminal_at=record.terminal_at,
    )


def _purge_record(job: ConversationPurgeJob) -> ConversationPurgeJobRecord:
    return ConversationPurgeJobRecord(
        id=job.id,
        organization_id=job.organization_id,
        session_id=job.session_id,
        session_reference_digest=job.session_reference_digest,
        receipt_verifier_hash=job.receipt_verifier_hash,
        receipt_verifier_key_version=job.receipt_verifier_key_version,
        receipt_expires_at=job.receipt_expires_at,
        status=job.status.value,
        claim_generation=job.claim_generation,
        claim_owner=None,
        claim_deadline_at=None,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        next_attempt_at=None,
        safe_failure_reason=job.safe_failure_reason,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
