from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.memory.application.dispatch import (
    AcknowledgeTurnDispatchCommand,
    AcknowledgeTurnDispatchUseCase,
    ClaimTurnDispatchCommand,
    ClaimTurnDispatchUseCase,
    FinalizeTerminalTurnDispatchCommand,
    FinalizeTerminalTurnDispatchUseCase,
    MarkTurnDispatchPublishedCommand,
    MarkTurnDispatchPublishedUseCase,
    RecordTurnDispatchPublishFailureCommand,
    RecordTurnDispatchPublishFailureUseCase,
    RecoverExpiredTurnDispatchCommand,
    RecoverExpiredTurnDispatchUseCase,
)
from apps.memory.domain.conversation import (
    AudienceKind,
    ConversationMemoryEntry,
    ConversationSession,
    ConversationTurn,
    MemoryTurnDispatchJob,
    ProtectedContent,
    ProtectedEntryContent,
    RequestIdentity,
)
from apps.memory.domain.errors import DispatchStateConflictError


def _now() -> datetime:
    return datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


def _job(max_attempts: int = 2) -> MemoryTurnDispatchJob:
    return MemoryTurnDispatchJob.pending(
        dispatch_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        memory_contract_version="conversation-memory-v1",
        storage_generation=1,
        minimum_worker_capability="memory-runtime-v1",
        max_attempts=max_attempts,
        now=_now(),
    )


def _terminal_scope():
    session = ConversationSession.create(
        session_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        deployment_id=uuid.uuid4(),
        deployment_version=1,
        deployment_snapshot_hash=None,
        mapping_version="mapping-v1",
        memory_policy_version="memory-v1",
        memory_contract_version="conversation-memory-v1",
        storage_generation=1,
        audience_kind=AudienceKind.PUBLIC_CHATBOT,
        subject_type=None,
        subject_id=None,
        idle_expires_at=_now() + timedelta(hours=1),
        absolute_expires_at=_now() + timedelta(days=1),
        now=_now(),
    )
    turn_id = uuid.uuid4()
    sequence = session.claim_turn(
        turn_id=turn_id,
        expected_lifecycle_revision=1,
        now=_now(),
    )
    entry_id = uuid.uuid4()
    dispatch_id = uuid.uuid4()
    turn = ConversationTurn.start(
        turn_id=turn_id,
        organization_id=session.organization_id,
        session_id=session.id,
        sequence=sequence,
        started_lifecycle_revision=session.lifecycle_revision,
        request_identity=RequestIdentity(
            idempotency_key_hash="a" * 64,
            request_fingerprint="b" * 64,
        ),
        user_entry_id=entry_id,
        dispatch_id=dispatch_id,
        now=_now(),
    )
    protected = ProtectedContent(
        ciphertext=b"encrypted",
        key_version="key-v1",
        format_version="memory-envelope-v1",
        content_digest="c" * 64,
        plaintext_byte_length=5,
    )
    entry = ConversationMemoryEntry.provisional_user(
        entry_id=entry_id,
        organization_id=session.organization_id,
        session_id=session.id,
        turn_id=turn.id,
        sequence=1,
        channel="conversation",
        content=ProtectedEntryContent(display=protected, model=protected),
        idempotency_key_hash="a" * 64,
        now=_now(),
    )
    job = MemoryTurnDispatchJob.pending(
        dispatch_id=dispatch_id,
        organization_id=session.organization_id,
        session_id=session.id,
        turn_id=turn.id,
        memory_contract_version=session.memory_contract_version,
        storage_generation=session.storage_generation,
        minimum_worker_capability="memory-runtime-v1",
        max_attempts=1,
        now=_now(),
    )
    job.claim(
        owner="dispatcher-a",
        deadline=_now() + timedelta(seconds=30),
        now=_now(),
    )
    job.record_publish_failure(
        owner="dispatcher-a",
        claim_generation=1,
        safe_reason_code="memory.dispatch_publish_failed",
        now=_now() + timedelta(seconds=1),
    )
    return session, turn, entry, job


class _Repository:
    def __init__(
        self,
        job: MemoryTurnDispatchJob,
        *,
        session=None,
        turn=None,
        entry=None,
    ) -> None:
        self.job = job
        self.session = session
        self.turn = turn
        self.entry = entry
        self.save_count = 0

    def lock_dispatch_job(self, *, organization_id, dispatch_id):
        if self.job.organization_id != organization_id or self.job.id != dispatch_id:
            return None
        return self.job

    def save_dispatch_job(self, job):
        self.job = job
        self.save_count += 1

    def lock_session(self, *, organization_id, session_id):
        if (
            self.session is not None
            and self.session.organization_id == organization_id
            and self.session.id == session_id
        ):
            return self.session
        return None

    def lock_turn(self, *, organization_id, session_id, turn_id):
        if (
            self.turn is not None
            and self.turn.organization_id == organization_id
            and self.turn.session_id == session_id
            and self.turn.id == turn_id
        ):
            return self.turn
        return None

    def get_entry(self, *, organization_id, session_id, entry_id):
        if (
            self.entry is not None
            and self.entry.organization_id == organization_id
            and self.entry.session_id == session_id
            and self.entry.id == entry_id
        ):
            return self.entry
        return None

    def save_session(self, session):
        self.session = session

    def save_turn(self, turn):
        self.turn = turn

    def save_entry(self, entry):
        self.entry = entry


class _UnitOfWork:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository
        self.commit_count = 0
        self.rollback_count = 0
        self._snapshot = None

    def begin(self):
        self._snapshot = copy.deepcopy(
            (
                self.repository.job,
                self.repository.session,
                self.repository.turn,
                self.repository.entry,
            )
        )

    def commit(self):
        self.commit_count += 1
        self._snapshot = None

    def rollback(self):
        self.rollback_count += 1
        if self._snapshot is not None:
            (
                self.repository.job,
                self.repository.session,
                self.repository.turn,
                self.repository.entry,
            ) = self._snapshot
        self._snapshot = None


def test_claim_and_publish_dispatch_use_fenced_application_commands():
    job = _job()
    repository = _Repository(job)
    uow = _UnitOfWork(repository)

    claimed = ClaimTurnDispatchUseCase(repository=repository, uow=uow).execute(
        ClaimTurnDispatchCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            owner="dispatcher-a",
            deadline=_now() + timedelta(seconds=30),
            now=_now(),
        )
    )
    assert claimed.status.value == "claimed"
    assert claimed.claim_generation == 1

    published = MarkTurnDispatchPublishedUseCase(
        repository=repository,
        uow=uow,
    ).execute(
        MarkTurnDispatchPublishedCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            owner="dispatcher-a",
            claim_generation=1,
            broker_message_id="opaque-message-reference",
            now=_now() + timedelta(seconds=1),
        )
    )
    assert published.status.value == "published"
    assert repository.job.claim_owner is None
    assert uow.commit_count == 2


def test_stale_publish_rolls_back_without_exposing_adapter_state():
    job = _job()
    repository = _Repository(job)
    uow = _UnitOfWork(repository)
    ClaimTurnDispatchUseCase(repository=repository, uow=uow).execute(
        ClaimTurnDispatchCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            owner="dispatcher-a",
            deadline=_now() + timedelta(seconds=30),
            now=_now(),
        )
    )

    with pytest.raises(DispatchStateConflictError):
        MarkTurnDispatchPublishedUseCase(
            repository=repository,
            uow=uow,
        ).execute(
            MarkTurnDispatchPublishedCommand(
                organization_id=job.organization_id,
                dispatch_id=job.id,
                owner="dispatcher-a",
                claim_generation=0,
                broker_message_id="opaque-message-reference",
                now=_now() + timedelta(seconds=1),
            )
        )

    assert repository.job.status.value == "claimed"
    assert uow.rollback_count == 1


def test_expired_claim_recovery_is_a_transactional_application_command():
    job = _job()
    repository = _Repository(job)
    uow = _UnitOfWork(repository)
    deadline = _now() + timedelta(seconds=30)
    ClaimTurnDispatchUseCase(repository=repository, uow=uow).execute(
        ClaimTurnDispatchCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            owner="dispatcher-a",
            deadline=deadline,
            now=_now(),
        )
    )
    retry_at = deadline + timedelta(seconds=10)

    result = RecoverExpiredTurnDispatchUseCase(
        repository=repository,
        uow=uow,
    ).execute(
        RecoverExpiredTurnDispatchCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            now=deadline,
            retry_at=retry_at,
            safe_reason_code="memory.dispatch_claim_expired",
        )
    )

    assert result.status.value == "reconcile_required"
    assert result.next_attempt_at == retry_at
    assert repository.save_count == 2


def test_current_claim_publish_failure_releases_an_immediate_retry():
    job = _job()
    repository = _Repository(job)
    uow = _UnitOfWork(repository)
    ClaimTurnDispatchUseCase(repository=repository, uow=uow).execute(
        ClaimTurnDispatchCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            owner="dispatcher-a",
            deadline=_now() + timedelta(seconds=30),
            now=_now(),
        )
    )

    released = RecordTurnDispatchPublishFailureUseCase(
        repository=repository,
        uow=uow,
    ).execute(
        RecordTurnDispatchPublishFailureCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            owner="dispatcher-a",
            claim_generation=1,
            safe_reason_code="memory.dispatch_publish_failed",
            now=_now() + timedelta(seconds=1),
        )
    )

    assert released.status.value == "reconcile_required"
    assert job.claim_owner is None
    assert job.claim_deadline_at is None
    assert job.next_attempt_at == _now() + timedelta(seconds=1)
    retry = ClaimTurnDispatchUseCase(repository=repository, uow=uow).execute(
        ClaimTurnDispatchCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            owner="dispatcher-b",
            deadline=_now() + timedelta(seconds=31),
            now=_now() + timedelta(seconds=1),
        )
    )
    assert retry.claim_generation == 2


def test_current_claim_publish_failure_is_terminal_at_attempt_limit():
    job = _job(max_attempts=1)
    repository = _Repository(job)
    uow = _UnitOfWork(repository)
    ClaimTurnDispatchUseCase(repository=repository, uow=uow).execute(
        ClaimTurnDispatchCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            owner="dispatcher-a",
            deadline=_now() + timedelta(seconds=30),
            now=_now(),
        )
    )

    result = RecordTurnDispatchPublishFailureUseCase(
        repository=repository,
        uow=uow,
    ).execute(
        RecordTurnDispatchPublishFailureCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            owner="dispatcher-a",
            claim_generation=1,
            safe_reason_code="memory.dispatch_publish_failed",
            now=_now() + timedelta(seconds=1),
        )
    )

    assert result.status.value == "terminal"
    assert result.next_attempt_at is None


def test_terminal_publish_failure_finalizes_turn_entry_and_session_in_one_uow():
    session, turn, entry, job = _terminal_scope()
    repository = _Repository(
        job,
        session=session,
        turn=turn,
        entry=entry,
    )
    uow = _UnitOfWork(repository)

    result = FinalizeTerminalTurnDispatchUseCase(
        repository=repository,
        uow=uow,
    ).execute(
        FinalizeTerminalTurnDispatchCommand(
            organization_id=job.organization_id,
            session_id=job.session_id,
            turn_id=job.turn_id,
            dispatch_id=job.id,
            now=_now() + timedelta(seconds=2),
        )
    )

    assert result.replayed is False
    assert repository.turn.status.value == "failed"
    assert (
        repository.turn.safe_failure_reason
        == "memory.dispatch_publish_failed"
    )
    assert repository.entry.lifecycle.value == "rejected"
    assert repository.session.active_turn_id is None
    assert uow.commit_count == 1


def test_worker_ack_can_win_the_publish_confirmation_race_idempotently():
    job = _job()
    repository = _Repository(job)
    uow = _UnitOfWork(repository)
    ClaimTurnDispatchUseCase(repository=repository, uow=uow).execute(
        ClaimTurnDispatchCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            owner="dispatcher-a",
            deadline=_now() + timedelta(seconds=30),
            now=_now(),
        )
    )

    first = AcknowledgeTurnDispatchUseCase(repository=repository, uow=uow).execute(
        AcknowledgeTurnDispatchCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            claim_generation=1,
            broker_message_id="message-1",
            workflow_admission_reference="admission-1",
            now=_now() + timedelta(seconds=1),
        )
    )
    replay = AcknowledgeTurnDispatchUseCase(repository=repository, uow=uow).execute(
        AcknowledgeTurnDispatchCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            claim_generation=1,
            broker_message_id="message-1",
            workflow_admission_reference="admission-1",
            now=_now() + timedelta(seconds=2),
        )
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert repository.job.status.value == "acknowledged"
    assert repository.job.workflow_admission_reference == "admission-1"

    published = MarkTurnDispatchPublishedUseCase(
        repository=repository,
        uow=uow,
    ).execute(
        MarkTurnDispatchPublishedCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            owner="dispatcher-a",
            claim_generation=1,
            broker_message_id="message-1",
            now=_now() + timedelta(seconds=3),
        )
    )
    assert published.status.value == "acknowledged"

    recovered = RecordTurnDispatchPublishFailureUseCase(
        repository=repository,
        uow=uow,
    ).execute(
        RecordTurnDispatchPublishFailureCommand(
            organization_id=job.organization_id,
            dispatch_id=job.id,
            owner="dispatcher-a",
            claim_generation=1,
            safe_reason_code="memory.dispatch_publish_failed",
            now=_now() + timedelta(seconds=4),
        )
    )
    assert recovered.status.value == "acknowledged"
