from __future__ import annotations

import copy
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from apps.memory.application.execution import (
    ConversationExecutionScope,
    ObserveConversationExecutionAdmittedCommand,
    ObserveConversationExecutionAdmittedUseCase,
    ObserveConversationExecutionRunningCommand,
    ObserveConversationExecutionRunningUseCase,
    ReadCurrentTurnInputCommand,
    ReadCurrentTurnInputUseCase,
    ResolveConversationExecutionCommand,
    ResolveConversationExecutionUseCase,
)
from apps.memory.application.public_lifecycle import PublicDeploymentBinding
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
from apps.memory.domain.errors import AccessGrantNotUsableError, StaleTurnVersionError
from apps.memory.domain.public_access import ConversationAccessGrant


NOW = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


def _scope() -> ConversationExecutionScope:
    organization_id = uuid.uuid4()
    app_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    deployment_id = uuid.uuid4()
    session = ConversationSession.create(
        session_id=uuid.uuid4(),
        organization_id=organization_id,
        app_id=app_id,
        workflow_id=workflow_id,
        deployment_id=deployment_id,
        deployment_version=3,
        deployment_snapshot_hash=None,
        mapping_version="conversation-mapping-v1",
        memory_policy_version="memory-policy-v1",
        memory_contract_version="conversation-memory-v1",
        storage_generation=1,
        audience_kind=AudienceKind.PUBLIC_CHATBOT,
        subject_type=None,
        subject_id=None,
        idle_expires_at=NOW + timedelta(hours=1),
        absolute_expires_at=NOW + timedelta(days=1),
        now=NOW,
    )
    grant = ConversationAccessGrant.issue(
        grant_id=uuid.uuid4(),
        organization_id=organization_id,
        session_id=session.id,
        deployment_id=deployment_id,
        deployment_version=3,
        audience_kind=AudienceKind.PUBLIC_CHATBOT,
        verifier_hash="a" * 64,
        verifier_key_version="grant-v1",
        expires_at=NOW + timedelta(hours=1),
        now=NOW,
    )
    turn_id = uuid.uuid4()
    dispatch_id = uuid.uuid4()
    user_entry_id = uuid.uuid4()
    session.claim_turn(
        turn_id=turn_id,
        expected_lifecycle_revision=1,
        now=NOW,
    )
    turn = ConversationTurn.start(
        turn_id=turn_id,
        organization_id=organization_id,
        session_id=session.id,
        sequence=1,
        started_lifecycle_revision=1,
        request_identity=RequestIdentity("b" * 64, "c" * 64),
        user_entry_id=user_entry_id,
        dispatch_id=dispatch_id,
        access_grant_id=grant.id,
        request_fingerprint_key_version="admission-v1",
        now=NOW,
    )
    dispatch = MemoryTurnDispatchJob.pending(
        dispatch_id=dispatch_id,
        organization_id=organization_id,
        session_id=session.id,
        turn_id=turn_id,
        memory_contract_version="conversation-memory-v1",
        storage_generation=1,
        minimum_worker_capability="memory-runtime-v1",
        max_attempts=3,
        now=NOW,
    )
    dispatch.claim(
        owner="gateway",
        deadline=NOW + timedelta(seconds=30),
        now=NOW,
    )
    return ConversationExecutionScope(
        deployment=PublicDeploymentBinding(
            organization_id=organization_id,
            app_id=app_id,
            workflow_id=workflow_id,
            deployment_id=deployment_id,
            deployment_version=3,
            mapping_version="conversation-mapping-v1",
            memory_policy_version="memory-policy-v1",
            memory_contract_version="conversation-memory-v1",
            storage_generation=1,
            runtime_contract_ready=True,
            runtime_start_node_id="start",
            runtime_input_variable="question",
            runtime_llm_node_id="llm",
            runtime_answer_node_id="answer",
            runtime_output_variable="answer",
            runtime_max_turns=5,
            runtime_max_context_tokens=1200,
        ),
        grant=grant,
        session=session,
        turn=turn,
        dispatch=dispatch,
    )


class _Repository:
    def __init__(self, scope: ConversationExecutionScope) -> None:
        self.scope = scope
        self.resolve_for_update_calls: list[bool] = []
        protected = ProtectedContent(
            ciphertext=b"ciphertext",
            key_version="content-v1",
            format_version="memory-content-fernet-v1",
            content_digest="d" * 64,
            plaintext_byte_length=5,
        )
        self.entry = ConversationMemoryEntry.provisional_user(
            entry_id=scope.turn.user_entry_id,
            organization_id=scope.turn.organization_id,
            session_id=scope.session.id,
            turn_id=scope.turn.id,
            sequence=1,
            channel="conversation",
            content=ProtectedEntryContent(display=protected, model=protected),
            idempotency_key_hash="b" * 64,
            now=NOW,
        )

    def current_time(self):
        return NOW

    def resolve_execution_scope(self, _command, *, for_update):
        self.resolve_for_update_calls.append(for_update)
        return self.scope

    def save_session(self, session):
        self.scope = replace(self.scope, session=session)

    def save_turn(self, turn):
        self.scope = replace(self.scope, turn=turn)

    def save_dispatch_job(self, dispatch):
        self.scope = replace(self.scope, dispatch=dispatch)

    def get_entry(self, **_kwargs):
        return self.entry


class _Uow:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository
        self.snapshot = None

    def begin(self):
        self.snapshot = copy.deepcopy(self.repository.scope)

    def commit(self):
        self.snapshot = None

    def rollback(self):
        self.repository.scope = self.snapshot
        self.snapshot = None


def _resolve_command(scope: ConversationExecutionScope, message_id="message-1"):
    return ResolveConversationExecutionCommand(
        organization_id=scope.turn.organization_id,
        dispatch_id=scope.dispatch.id,
        turn_id=scope.turn.id,
        dispatch_claim_generation=scope.dispatch.claim_generation,
        broker_message_id=message_id,
        memory_contract_version="conversation-memory-v1",
        storage_generation=1,
        minimum_worker_capability="memory-runtime-v1",
    )


def test_resolve_admit_run_and_current_input_are_separate_fenced_steps() -> None:
    repository = _Repository(_scope())
    uow = _Uow(repository)
    binding = ResolveConversationExecutionUseCase(
        repository=repository,
        uow=uow,
    ).execute(_resolve_command(repository.scope))
    admission_id = uuid.uuid4()

    queued = ObserveConversationExecutionAdmittedUseCase(
        repository=repository,
        uow=uow,
    ).execute(
        ObserveConversationExecutionAdmittedCommand(
            binding=binding,
            workflow_admission_id=admission_id,
            claim_generation=1,
            broker_message_id="message-1",
        )
    )
    binding = replace(binding, turn_version=queued.turn_version)
    execution_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    running = ObserveConversationExecutionRunningUseCase(
        repository=repository,
        uow=uow,
    ).execute(
        ObserveConversationExecutionRunningCommand(
            binding=binding,
            workflow_admission_id=admission_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
        )
    )
    binding = replace(binding, turn_version=running.turn_version)
    current = ReadCurrentTurnInputUseCase(
        repository=repository,
        uow=uow,
    ).execute(
        ReadCurrentTurnInputCommand(
            binding=binding,
            execution_id=execution_id,
            attempt_id=attempt_id,
        )
    )

    assert queued.turn_version == 2
    assert running.turn_version == 3
    assert current.entry_id == repository.entry.id
    assert current.model_content.ciphertext == b"ciphertext"


def test_revoked_grant_blocks_redelivery_before_workflow_admission() -> None:
    repository = _Repository(_scope())
    repository.scope.grant.revoke(now=NOW)

    with pytest.raises(AccessGrantNotUsableError):
        ResolveConversationExecutionUseCase(
            repository=repository,
            uow=_Uow(repository),
        ).execute(_resolve_command(repository.scope))


def test_running_projection_hands_off_to_reclaimed_workflow_attempt() -> None:
    repository = _Repository(_scope())
    uow = _Uow(repository)
    binding = ResolveConversationExecutionUseCase(
        repository=repository,
        uow=uow,
    ).execute(_resolve_command(repository.scope))
    admission_id = uuid.uuid4()
    queued = ObserveConversationExecutionAdmittedUseCase(
        repository=repository,
        uow=uow,
    ).execute(
        ObserveConversationExecutionAdmittedCommand(
            binding=binding,
            workflow_admission_id=admission_id,
            claim_generation=1,
            broker_message_id="message-1",
        )
    )
    binding = replace(binding, turn_version=queued.turn_version)
    execution_id = uuid.uuid4()
    first_attempt_id = uuid.uuid4()
    running_use_case = ObserveConversationExecutionRunningUseCase(
        repository=repository,
        uow=uow,
    )
    first = running_use_case.execute(
        ObserveConversationExecutionRunningCommand(
            binding=binding,
            workflow_admission_id=admission_id,
            execution_id=execution_id,
            attempt_id=first_attempt_id,
        )
    )
    first_binding = replace(binding, turn_version=first.turn_version)

    replay = running_use_case.execute(
        ObserveConversationExecutionRunningCommand(
            binding=first_binding,
            workflow_admission_id=admission_id,
            execution_id=execution_id,
            attempt_id=first_attempt_id,
        )
    )

    replacement_attempt_id = uuid.uuid4()
    replacement = running_use_case.execute(
        ObserveConversationExecutionRunningCommand(
            binding=first_binding,
            workflow_admission_id=admission_id,
            execution_id=execution_id,
            attempt_id=replacement_attempt_id,
        )
    )
    replacement_binding = replace(binding, turn_version=replacement.turn_version)
    assert replay.replayed is True
    assert replay.turn_version == first.turn_version
    assert replacement.replayed is False
    assert replacement.turn_version == first.turn_version + 1
    assert repository.scope.turn.execution_id == execution_id
    assert repository.scope.turn.latest_attempt_id == replacement_attempt_id
    assert repository.resolve_for_update_calls[-3:] == [True, True, True]

    with pytest.raises(StaleTurnVersionError):
        ReadCurrentTurnInputUseCase(
            repository=repository,
            uow=uow,
        ).execute(
            ReadCurrentTurnInputCommand(
                binding=replacement_binding,
                execution_id=execution_id,
                attempt_id=first_attempt_id,
            )
        )

    with pytest.raises(AccessGrantNotUsableError):
        running_use_case.execute(
            ObserveConversationExecutionRunningCommand(
                binding=first_binding,
                workflow_admission_id=admission_id,
                execution_id=execution_id,
                attempt_id=first_attempt_id,
            )
        )

    repository.scope.turn.complete(
        expected_version=replacement.turn_version,
        assistant_entry_id=uuid.uuid4(),
        now=NOW,
    )
    terminal_binding = replace(
        binding,
        turn_version=repository.scope.turn.version,
    )
    with pytest.raises(StaleTurnVersionError):
        running_use_case.execute(
            ObserveConversationExecutionRunningCommand(
                binding=terminal_binding,
                workflow_admission_id=admission_id,
                execution_id=execution_id,
                attempt_id=uuid.uuid4(),
            )
        )
