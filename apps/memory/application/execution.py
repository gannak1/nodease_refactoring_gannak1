"""Memory-side safe projection for one Workflow-owned Conversation execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.memory.application.public_lifecycle import PublicDeploymentBinding
from apps.memory.domain.conversation import (
    AudienceKind,
    ConversationMemoryEntry,
    ConversationSession,
    ConversationTurn,
    DispatchStatus,
    EntryLifecycle,
    EntryType,
    MemoryTurnDispatchJob,
    ProtectedContent,
    TurnStatus,
)
from apps.memory.domain.errors import (
    AccessGrantNotUsableError,
    DispatchStateConflictError,
    EntryNotFoundError,
    StaleTurnVersionError,
)
from apps.memory.domain.public_access import AccessGrantState, ConversationAccessGrant


@dataclass(frozen=True, slots=True)
class ResolveConversationExecutionCommand:
    organization_id: uuid.UUID
    dispatch_id: uuid.UUID
    dispatch_claim_generation: int
    broker_message_id: str
    turn_id: uuid.UUID
    memory_contract_version: str
    storage_generation: int
    minimum_worker_capability: str


@dataclass(frozen=True, slots=True)
class ConversationExecutionScope:
    deployment: PublicDeploymentBinding
    grant: ConversationAccessGrant
    session: ConversationSession
    turn: ConversationTurn
    dispatch: MemoryTurnDispatchJob


@dataclass(frozen=True, slots=True)
class ResolvedConversationExecution:
    organization_id: uuid.UUID
    app_id: uuid.UUID
    workflow_id: uuid.UUID
    deployment_id: uuid.UUID
    deployment_version: int
    session_id: uuid.UUID
    turn_id: uuid.UUID
    dispatch_id: uuid.UUID
    dispatch_claim_generation: int
    broker_message_id: str
    request_fingerprint: str
    lifecycle_revision: int
    turn_version: int
    memory_contract_version: str
    mapping_version: str
    memory_policy_version: str
    storage_generation: int
    minimum_worker_capability: str
    start_node_id: str
    input_variable: str
    llm_node_id: str
    answer_node_id: str
    output_variable: str
    max_turns: int
    max_context_tokens: int


@dataclass(frozen=True, slots=True)
class ObserveConversationExecutionAdmittedCommand:
    binding: ResolvedConversationExecution
    workflow_admission_id: uuid.UUID
    claim_generation: int
    broker_message_id: str


@dataclass(frozen=True, slots=True)
class ObserveConversationExecutionRunningCommand:
    binding: ResolvedConversationExecution
    workflow_admission_id: uuid.UUID
    execution_id: uuid.UUID
    attempt_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ConversationExecutionObservation:
    lifecycle_revision: int
    turn_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class ReadCurrentTurnInputCommand:
    binding: ResolvedConversationExecution
    execution_id: uuid.UUID
    attempt_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class CurrentTurnInput:
    entry_id: uuid.UUID
    model_content: ProtectedContent


class ConversationExecutionMemoryRepositoryPort(Protocol):
    def current_time(self) -> datetime: ...

    def resolve_execution_scope(
        self,
        command: ResolveConversationExecutionCommand,
        *,
        for_update: bool,
    ) -> ConversationExecutionScope | None: ...

    def save_session(self, session: ConversationSession) -> None: ...

    def save_turn(self, turn: ConversationTurn) -> None: ...

    def save_dispatch_job(self, dispatch: MemoryTurnDispatchJob) -> None: ...

    def get_entry(
        self,
        *,
        organization_id: uuid.UUID,
        session_id: uuid.UUID,
        entry_id: uuid.UUID,
    ) -> ConversationMemoryEntry | None: ...


class _ExecutionUseCase:
    def __init__(self, *, repository, uow) -> None:
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


class ResolveConversationExecutionUseCase(_ExecutionUseCase):
    def execute(
        self,
        command: ResolveConversationExecutionCommand,
    ) -> ResolvedConversationExecution:
        def operation() -> ResolvedConversationExecution:
            scope = self.repository.resolve_execution_scope(
                command,
                for_update=False,
            )
            if scope is None:
                raise AccessGrantNotUsableError()
            now = self.repository.current_time()
            _require_scope(scope, command=command, now=now)
            return _resolved(scope, broker_message_id=command.broker_message_id)

        return self._execute(operation)


class ObserveConversationExecutionAdmittedUseCase(_ExecutionUseCase):
    def execute(
        self,
        command: ObserveConversationExecutionAdmittedCommand,
    ) -> ConversationExecutionObservation:
        def operation() -> ConversationExecutionObservation:
            resolve_command = resolve_command_for_binding(
                command.binding,
                claim_generation=command.claim_generation,
                broker_message_id=command.broker_message_id,
            )
            scope = self.repository.resolve_execution_scope(
                resolve_command,
                for_update=True,
            )
            if scope is None:
                raise AccessGrantNotUsableError()
            now = self.repository.current_time()
            _require_scope(scope, command=resolve_command, now=now)
            _require_same_resolved(scope, command.binding)
            admission_reference = str(command.workflow_admission_id)
            already_acknowledged = (
                scope.dispatch.status is DispatchStatus.ACKNOWLEDGED
                and scope.dispatch.workflow_admission_reference
                == admission_reference
            )
            if scope.turn.status is TurnStatus.PENDING_DISPATCH:
                scope.turn.mark_queued(
                    expected_version=scope.turn.version,
                    now=now,
                )
                self.repository.save_turn(scope.turn)
            elif scope.turn.status not in {
                TurnStatus.QUEUED,
                TurnStatus.RUNNING,
            }:
                raise StaleTurnVersionError()
            dispatch_replayed = scope.dispatch.acknowledge(
                claim_generation=command.claim_generation,
                broker_message_id=command.broker_message_id,
                workflow_admission_reference=admission_reference,
                now=now,
            )
            self.repository.save_dispatch_job(scope.dispatch)
            return ConversationExecutionObservation(
                lifecycle_revision=scope.session.lifecycle_revision,
                turn_version=scope.turn.version,
                replayed=already_acknowledged and dispatch_replayed,
            )

        return self._execute(operation)


class ObserveConversationExecutionRunningUseCase(_ExecutionUseCase):
    def execute(
        self,
        command: ObserveConversationExecutionRunningCommand,
    ) -> ConversationExecutionObservation:
        def operation() -> ConversationExecutionObservation:
            resolve_command = resolve_command_for_binding(
                command.binding,
                claim_generation=command.binding.dispatch_claim_generation,
                broker_message_id=command.binding.broker_message_id,
            )
            scope = self.repository.resolve_execution_scope(
                resolve_command,
                for_update=True,
            )
            if scope is None:
                raise AccessGrantNotUsableError()
            now = self.repository.current_time()
            require_runtime_binding(scope, command.binding, now=now)
            if (
                scope.dispatch.status is not DispatchStatus.ACKNOWLEDGED
                or scope.dispatch.workflow_admission_reference
                != str(command.workflow_admission_id)
            ):
                raise DispatchStateConflictError()
            if scope.turn.status is TurnStatus.RUNNING:
                if (
                    scope.turn.execution_id == command.execution_id
                    and scope.turn.latest_attempt_id == command.attempt_id
                ):
                    return ConversationExecutionObservation(
                        lifecycle_revision=scope.session.lifecycle_revision,
                        turn_version=scope.turn.version,
                        replayed=True,
                    )
                scope.turn.handoff_running_attempt(
                    expected_version=scope.turn.version,
                    execution_id=command.execution_id,
                    attempt_id=command.attempt_id,
                    now=now,
                )
                self.repository.save_turn(scope.turn)
                return ConversationExecutionObservation(
                    lifecycle_revision=scope.session.lifecycle_revision,
                    turn_version=scope.turn.version,
                    replayed=False,
                )
            if scope.turn.status is not TurnStatus.QUEUED:
                raise StaleTurnVersionError()
            scope.turn.mark_running(
                expected_version=scope.turn.version,
                execution_id=command.execution_id,
                attempt_id=command.attempt_id,
                now=now,
            )
            self.repository.save_turn(scope.turn)
            return ConversationExecutionObservation(
                lifecycle_revision=scope.session.lifecycle_revision,
                turn_version=scope.turn.version,
                replayed=False,
            )

        return self._execute(operation)


class ReadCurrentTurnInputUseCase(_ExecutionUseCase):
    def execute(self, command: ReadCurrentTurnInputCommand) -> CurrentTurnInput:
        def operation() -> CurrentTurnInput:
            resolve_command = resolve_command_for_binding(
                command.binding,
                claim_generation=command.binding.dispatch_claim_generation,
                broker_message_id=command.binding.broker_message_id,
            )
            scope = self.repository.resolve_execution_scope(
                resolve_command,
                for_update=False,
            )
            if scope is None:
                raise AccessGrantNotUsableError()
            require_runtime_binding(
                scope,
                command.binding,
                now=self.repository.current_time(),
            )
            if (
                scope.turn.status is not TurnStatus.RUNNING
                or scope.turn.execution_id != command.execution_id
                or scope.turn.latest_attempt_id != command.attempt_id
            ):
                raise StaleTurnVersionError()
            entry = self.repository.get_entry(
                organization_id=scope.session.organization_id,
                session_id=scope.session.id,
                entry_id=scope.turn.user_entry_id,
            )
            if (
                entry is None
                or entry.turn_id != scope.turn.id
                or entry.entry_type is not EntryType.USER_TURN
                or entry.lifecycle is not EntryLifecycle.PROVISIONAL
                or entry.content is None
                or entry.content.model is None
            ):
                raise EntryNotFoundError()
            return CurrentTurnInput(
                entry_id=entry.id,
                model_content=entry.content.model,
            )

        return self._execute(operation)


def _require_scope(
    scope: ConversationExecutionScope,
    *,
    command: ResolveConversationExecutionCommand,
    now: datetime,
) -> None:
    require_runtime_binding(scope, None, now=now)
    if (
        scope.turn.organization_id != command.organization_id
        or scope.turn.id != command.turn_id
        or scope.turn.dispatch_id != command.dispatch_id
        or scope.dispatch.id != command.dispatch_id
        or scope.dispatch.turn_id != command.turn_id
        or scope.dispatch.claim_generation != command.dispatch_claim_generation
        or scope.dispatch.memory_contract_version
        != command.memory_contract_version
        or scope.dispatch.storage_generation != command.storage_generation
        or scope.dispatch.minimum_worker_capability
        != command.minimum_worker_capability
        or scope.dispatch.status
        not in {
            DispatchStatus.CLAIMED,
            DispatchStatus.PUBLISHED,
            DispatchStatus.ACKNOWLEDGED,
        }
        or (
            scope.dispatch.broker_message_id is not None
            and scope.dispatch.broker_message_id != command.broker_message_id
        )
    ):
        raise DispatchStateConflictError()


def require_runtime_binding(
    scope: ConversationExecutionScope,
    binding: ResolvedConversationExecution | None,
    *,
    now: datetime,
) -> None:
    deployment = scope.deployment
    grant = scope.grant
    session = scope.session
    turn = scope.turn
    grant.require_active(
        deployment_id=deployment.deployment_id,
        deployment_version=deployment.deployment_version,
        audience_kind=AudienceKind.PUBLIC_CHATBOT,
        now=now,
    )
    if grant.state is not AccessGrantState.ACTIVE:
        raise AccessGrantNotUsableError()
    session.require_active(
        expected_lifecycle_revision=turn.started_lifecycle_revision,
        now=now,
    )
    if (
        not deployment.runtime_contract_ready
        or turn.access_grant_id != grant.id
        or turn.session_id != session.id
        or scope.dispatch.session_id != session.id
        or session.organization_id != deployment.organization_id
        or session.app_id != deployment.app_id
        or session.workflow_id != deployment.workflow_id
        or session.deployment_id != deployment.deployment_id
        or session.deployment_version != deployment.deployment_version
        or session.mapping_version != deployment.mapping_version
        or session.memory_policy_version != deployment.memory_policy_version
        or session.memory_contract_version != deployment.memory_contract_version
        or session.storage_generation != deployment.storage_generation
        or session.audience_kind is not AudienceKind.PUBLIC_CHATBOT
    ):
        raise AccessGrantNotUsableError()
    if binding is not None:
        current = _resolved(scope, broker_message_id=binding.broker_message_id)
        if (
            _immutable_binding_identity(current)
            != _immutable_binding_identity(binding)
            or current.lifecycle_revision != binding.lifecycle_revision
            or current.turn_version != binding.turn_version
        ):
            raise AccessGrantNotUsableError()


def _resolved(
    scope: ConversationExecutionScope,
    *,
    broker_message_id: str | None = None,
) -> ResolvedConversationExecution:
    deployment = scope.deployment
    required = (
        deployment.runtime_start_node_id,
        deployment.runtime_input_variable,
        deployment.runtime_llm_node_id,
        deployment.runtime_answer_node_id,
        deployment.runtime_output_variable,
        deployment.runtime_max_turns,
        deployment.runtime_max_context_tokens,
    )
    if any(value is None for value in required):
        raise AccessGrantNotUsableError()
    return ResolvedConversationExecution(
        organization_id=deployment.organization_id,
        app_id=deployment.app_id,
        workflow_id=deployment.workflow_id,
        deployment_id=deployment.deployment_id,
        deployment_version=deployment.deployment_version,
        session_id=scope.session.id,
        turn_id=scope.turn.id,
        dispatch_id=scope.dispatch.id,
        dispatch_claim_generation=scope.dispatch.claim_generation,
        broker_message_id=str(
            scope.dispatch.broker_message_id or broker_message_id or ""
        ),
        request_fingerprint=scope.turn.request_identity.request_fingerprint,
        lifecycle_revision=scope.session.lifecycle_revision,
        turn_version=scope.turn.version,
        memory_contract_version=deployment.memory_contract_version,
        mapping_version=deployment.mapping_version,
        memory_policy_version=deployment.memory_policy_version,
        storage_generation=deployment.storage_generation,
        minimum_worker_capability=scope.dispatch.minimum_worker_capability,
        start_node_id=str(deployment.runtime_start_node_id),
        input_variable=str(deployment.runtime_input_variable),
        llm_node_id=str(deployment.runtime_llm_node_id),
        answer_node_id=str(deployment.runtime_answer_node_id),
        output_variable=str(deployment.runtime_output_variable),
        max_turns=int(deployment.runtime_max_turns),
        max_context_tokens=int(deployment.runtime_max_context_tokens),
    )


def _require_same_resolved(
    scope: ConversationExecutionScope,
    expected: ResolvedConversationExecution,
) -> None:
    current = _resolved(scope, broker_message_id=expected.broker_message_id)
    if current != expected:
        # Turn version can advance only through the operation currently being
        # observed; at admission it must still match the resolved snapshot.
        raise AccessGrantNotUsableError()


def _immutable_binding_identity(
    binding: ResolvedConversationExecution,
) -> tuple[object, ...]:
    return (
        binding.organization_id,
        binding.app_id,
        binding.workflow_id,
        binding.deployment_id,
        binding.deployment_version,
        binding.session_id,
        binding.turn_id,
        binding.dispatch_id,
        binding.dispatch_claim_generation,
        binding.broker_message_id,
        binding.request_fingerprint,
        binding.memory_contract_version,
        binding.mapping_version,
        binding.memory_policy_version,
        binding.storage_generation,
        binding.minimum_worker_capability,
        binding.start_node_id,
        binding.input_variable,
        binding.llm_node_id,
        binding.answer_node_id,
        binding.output_variable,
        binding.max_turns,
        binding.max_context_tokens,
    )


def resolve_command_for_binding(
    binding: ResolvedConversationExecution,
    *,
    claim_generation: int | None = None,
    broker_message_id: str | None = None,
) -> ResolveConversationExecutionCommand:
    return ResolveConversationExecutionCommand(
        organization_id=binding.organization_id,
        dispatch_id=binding.dispatch_id,
        turn_id=binding.turn_id,
        dispatch_claim_generation=(
            binding.dispatch_claim_generation
            if claim_generation is None
            else claim_generation
        ),
        broker_message_id=(
            binding.broker_message_id
            if broker_message_id is None
            else broker_message_id
        ),
        memory_contract_version=binding.memory_contract_version,
        storage_generation=binding.storage_generation,
        minimum_worker_capability=binding.minimum_worker_capability,
    )


__all__ = [
    "ConversationExecutionMemoryRepositoryPort",
    "ConversationExecutionObservation",
    "ConversationExecutionScope",
    "CurrentTurnInput",
    "ObserveConversationExecutionAdmittedCommand",
    "ObserveConversationExecutionAdmittedUseCase",
    "ObserveConversationExecutionRunningCommand",
    "ObserveConversationExecutionRunningUseCase",
    "ReadCurrentTurnInputCommand",
    "ReadCurrentTurnInputUseCase",
    "ResolveConversationExecutionCommand",
    "ResolveConversationExecutionUseCase",
    "ResolvedConversationExecution",
    "require_runtime_binding",
    "resolve_command_for_binding",
]
