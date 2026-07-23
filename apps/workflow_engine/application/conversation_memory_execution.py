"""Application orchestration for the initial public Conversation runtime.

The module owns ordering only.  Memory persistence, Workflow admission,
provider capability/usage and observer projection stay behind narrow ports.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Protocol

from apps.shared.domain.conversation_memory_runtime import (
    ConversationMemoryRuntimeContract,
    ConversationMemoryRuntimeContractError,
    validate_conversation_memory_runtime,
)
from apps.shared.domain.conversation_memory_task import ConversationTurnTaskEnvelope
from apps.shared.utils.prompt_injection_guard import (
    PLATFORM_UNTRUSTED_CONTEXT_GUARDRAIL_PROMPT,
)
from apps.workflow_engine.application.conversation_memory_admission import (
    ConversationExecutionState,
)
from apps.workflow_engine.application.provider_execution import (
    ProviderInvocationOutcomeUnknownError,
)

_TEMPLATE_VARIABLE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


class ConversationExecutionRuntimeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ConversationExecutionBinding:
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
class ConversationExecutionGraph:
    graph: Mapping[str, Any]
    deployment_config: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ConversationMemoryContextBuild:
    plan_id: uuid.UUID
    lease_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ConversationMemoryContextClaim:
    attempt_id: uuid.UUID
    attempt_version: int
    history_block: str


@dataclass(frozen=True, slots=True)
class ConversationProviderPreparation:
    capability_reference: str
    capability_revision: str
    provider_attempt_id: uuid.UUID
    expires_at: datetime
    state: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ConversationProviderResult:
    text: str
    usage: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ConversationMemoryCheckpoint:
    entry_id: uuid.UUID
    content_digest: str


@dataclass(frozen=True, slots=True)
class ExecuteConversationTurnCommand:
    envelope: ConversationTurnTaskEnvelope
    worker_owner: str
    delivery_attempt_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ExecuteConversationTurnResult:
    admission_id: uuid.UUID
    execution_id: uuid.UUID
    turn_id: uuid.UUID
    state: ConversationExecutionState


class ConversationMemoryRuntimePort(Protocol):
    def resolve(self, envelope: ConversationTurnTaskEnvelope) -> ConversationExecutionBinding: ...

    def observe_admitted(self, binding: ConversationExecutionBinding, **kwargs) -> ConversationExecutionBinding: ...

    def observe_running(self, binding: ConversationExecutionBinding, **kwargs) -> ConversationExecutionBinding: ...

    def read_current_input(self, binding: ConversationExecutionBinding, **kwargs) -> str: ...

    def build_context(self, binding: ConversationExecutionBinding, **kwargs) -> ConversationMemoryContextBuild: ...

    def claim_context(self, binding: ConversationExecutionBinding, **kwargs) -> ConversationMemoryContextClaim: ...

    def validate_current(self, binding: ConversationExecutionBinding, **kwargs) -> None: ...

    def mark_provider_started(self, binding: ConversationExecutionBinding, **kwargs) -> int: ...

    def finish_context_attempt(self, binding: ConversationExecutionBinding, **kwargs) -> None: ...

    def checkpoint(self, binding: ConversationExecutionBinding, **kwargs) -> ConversationMemoryCheckpoint: ...

    def complete(self, binding: ConversationExecutionBinding, **kwargs) -> None: ...

    def fail(self, binding: ConversationExecutionBinding, **kwargs) -> None: ...


class ConversationExecutionAdmissionPort(Protocol):
    def admit(self, binding: ConversationExecutionBinding, **kwargs): ...

    def claim(self, binding: ConversationExecutionBinding, **kwargs): ...

    def require_fence(self, binding: ConversationExecutionBinding, **kwargs) -> None: ...

    def finish(self, binding: ConversationExecutionBinding, **kwargs) -> None: ...


class ConversationExecutionGraphPort(Protocol):
    def load(self, binding: ConversationExecutionBinding) -> ConversationExecutionGraph: ...


class ConversationProviderPort(Protocol):
    def prepare(self, **kwargs) -> ConversationProviderPreparation: ...

    def generate(
        self,
        *,
        messages: tuple[Mapping[str, str], ...],
        before_provider_start: Callable[[str], None],
        **kwargs,
    ) -> ConversationProviderResult: ...


class ConversationObserverPort(Protocol):
    def record(self, **kwargs) -> None: ...


class ClockPort(Protocol):
    def now(self) -> datetime: ...


class ExecuteConversationTurnUseCase:
    def __init__(
        self,
        *,
        memory: ConversationMemoryRuntimePort,
        admissions: ConversationExecutionAdmissionPort,
        graphs: ConversationExecutionGraphPort,
        provider: ConversationProviderPort,
        observer: ConversationObserverPort,
        clock: ClockPort,
        worker_capability: str,
        lease_duration: timedelta,
        context_lease_duration: timedelta,
    ) -> None:
        self.memory = memory
        self.admissions = admissions
        self.graphs = graphs
        self.provider = provider
        self.observer = observer
        self.clock = clock
        self.worker_capability = worker_capability
        self.lease_duration = lease_duration
        self.context_lease_duration = context_lease_duration

    def execute(
        self,
        command: ExecuteConversationTurnCommand,
    ) -> ExecuteConversationTurnResult:
        envelope = command.envelope
        if envelope.minimum_worker_capability != self.worker_capability:
            raise ConversationExecutionRuntimeError("memory.worker_incompatible")
        binding = self.memory.resolve(envelope)
        self._require_envelope_binding(envelope, binding)
        graph = self.graphs.load(binding)
        self._require_graph_binding(graph, binding)
        now = self.clock.now()
        admitted = self.admissions.admit(binding, now=now)
        if admitted.state in {
            ConversationExecutionState.COMPLETED,
            ConversationExecutionState.FAILED,
            ConversationExecutionState.OUTCOME_UNKNOWN,
        }:
            return ExecuteConversationTurnResult(
                admission_id=admitted.admission_id,
                execution_id=admitted.execution_id,
                turn_id=binding.turn_id,
                state=admitted.state,
            )
        binding = self.memory.observe_admitted(
            binding,
            admission_id=admitted.admission_id,
            claim_generation=envelope.claim_generation,
            broker_message_id=envelope.broker_message_id,
        )
        self._observe("execution_admitted", binding, admitted.admission_id)
        now = self.clock.now()
        claimed = self.admissions.claim(
            binding,
            owner=command.worker_owner,
            attempt_id=command.delivery_attempt_id,
            lease_deadline=now + self.lease_duration,
            now=now,
        )
        binding = self.memory.observe_running(
            binding,
            admission_id=claimed.admission_id,
            execution_id=claimed.execution_id,
            attempt_id=claimed.attempt_id,
        )
        self._observe("execution_running", binding, claimed.admission_id)
        input_text = self.memory.read_current_input(
            binding,
            execution_id=claimed.execution_id,
            attempt_id=claimed.attempt_id,
        )
        node_invocation_id = uuid.uuid5(
            claimed.execution_id,
            f"conversation-node:{binding.llm_node_id}",
        )
        llm_data = _llm_data(graph.graph, binding.llm_node_id)
        preparation = self.provider.prepare(
            binding=binding,
            admission_id=claimed.admission_id,
            execution_id=claimed.execution_id,
            node_invocation_id=node_invocation_id,
            node_data=llm_data,
            deployment_config=graph.deployment_config,
        )
        context_build = self.memory.build_context(
            binding,
            node_invocation_id=node_invocation_id,
            capability_reference=preparation.capability_reference,
            capability_revision=preparation.capability_revision,
            provider_attempt_id=preparation.provider_attempt_id,
            expires_at=preparation.expires_at,
        )
        now = self.clock.now()
        context = self.memory.claim_context(
            binding,
            plan_id=context_build.plan_id,
            lease_id=context_build.lease_id,
            node_invocation_id=node_invocation_id,
            capability_reference=preparation.capability_reference,
            capability_revision=preparation.capability_revision,
            provider_attempt_id=preparation.provider_attempt_id,
            claim_deadline_at=min(
                preparation.expires_at,
                now + self.context_lease_duration,
            ),
        )
        messages = _messages(
            llm_data,
            variable=binding.input_variable,
            input_text=input_text,
            history_block=context.history_block,
        )
        context_attempt_version = context.attempt_version

        def before_provider_start(usage_reference: str) -> None:
            nonlocal context_attempt_version
            now_at_fence = self.clock.now()
            self.admissions.require_fence(
                binding,
                owner=command.worker_owner,
                lease_generation=claimed.lease_generation,
                now=now_at_fence,
            )
            self.memory.validate_current(
                binding,
                execution_id=claimed.execution_id,
                attempt_id=claimed.attempt_id,
            )
            context_attempt_version = self.memory.mark_provider_started(
                binding,
                context_attempt_id=context.attempt_id,
                expected_version=context_attempt_version,
                usage_reference=usage_reference,
            )

        try:
            provider_result = self.provider.generate(
                binding=binding,
                admission_id=claimed.admission_id,
                execution_id=claimed.execution_id,
                node_invocation_id=node_invocation_id,
                node_data=llm_data,
                preparation=preparation,
                messages=messages,
                before_provider_start=before_provider_start,
            )
        except ProviderInvocationOutcomeUnknownError:
            self.memory.finish_context_attempt(
                binding,
                context_attempt_id=context.attempt_id,
                expected_version=context_attempt_version,
                outcome="outcome_unknown",
                safe_failure_reason="provider_outcome_unknown",
            )
            self.memory.fail(
                binding,
                execution_id=claimed.execution_id,
                attempt_id=claimed.attempt_id,
                safe_reason_code="provider_outcome_unknown",
            )
            self.admissions.finish(
                binding,
                owner=command.worker_owner,
                lease_generation=claimed.lease_generation,
                outcome="outcome_unknown",
                result_entry_id=None,
                result_digest=None,
                safe_failure_reason="provider_outcome_unknown",
                now=self.clock.now(),
            )
            raise
        except Exception as exc:
            safe_reason = _safe_reason_code(exc, "provider_not_sent")
            self.memory.finish_context_attempt(
                binding,
                context_attempt_id=context.attempt_id,
                expected_version=context_attempt_version,
                outcome="failed",
                safe_failure_reason=safe_reason,
            )
            self.memory.fail(
                binding,
                execution_id=claimed.execution_id,
                attempt_id=claimed.attempt_id,
                safe_reason_code=safe_reason,
            )
            self.admissions.finish(
                binding,
                owner=command.worker_owner,
                lease_generation=claimed.lease_generation,
                outcome="failed",
                result_entry_id=None,
                result_digest=None,
                safe_failure_reason=safe_reason,
                now=self.clock.now(),
            )
            raise

        self.memory.finish_context_attempt(
            binding,
            context_attempt_id=context.attempt_id,
            expected_version=context_attempt_version,
            outcome="succeeded",
            safe_failure_reason=None,
        )
        self.admissions.require_fence(
            binding,
            owner=command.worker_owner,
            lease_generation=claimed.lease_generation,
            now=self.clock.now(),
        )
        checkpoint = self.memory.checkpoint(
            binding,
            execution_id=claimed.execution_id,
            attempt_id=claimed.attempt_id,
            assistant_text=provider_result.text,
        )
        self.memory.complete(
            binding,
            execution_id=claimed.execution_id,
            attempt_id=claimed.attempt_id,
            checkpoint=checkpoint,
        )
        self.admissions.finish(
            binding,
            owner=command.worker_owner,
            lease_generation=claimed.lease_generation,
            outcome="completed",
            result_entry_id=checkpoint.entry_id,
            result_digest=checkpoint.content_digest,
            safe_failure_reason=None,
            now=self.clock.now(),
        )
        self._observe("execution_completed", binding, claimed.admission_id)
        return ExecuteConversationTurnResult(
            admission_id=claimed.admission_id,
            execution_id=claimed.execution_id,
            turn_id=binding.turn_id,
            state=ConversationExecutionState.COMPLETED,
        )

    @staticmethod
    def _require_envelope_binding(
        envelope: ConversationTurnTaskEnvelope,
        binding: ConversationExecutionBinding,
    ) -> None:
        if (
            envelope.organization_id != binding.organization_id
            or envelope.dispatch_id != binding.dispatch_id
            or envelope.turn_id != binding.turn_id
            or envelope.claim_generation != binding.dispatch_claim_generation
            or envelope.broker_message_id != binding.broker_message_id
            or envelope.memory_contract_version != binding.memory_contract_version
            or envelope.storage_generation != binding.storage_generation
            or envelope.minimum_worker_capability
            != binding.minimum_worker_capability
        ):
            raise ValueError("memory.execution_binding_mismatch")

    @staticmethod
    def _require_graph_binding(
        graph: ConversationExecutionGraph,
        binding: ConversationExecutionBinding,
    ) -> ConversationMemoryRuntimeContract:
        try:
            contract = validate_conversation_memory_runtime(
                graph.graph,
                graph.deployment_config,
            )
        except ConversationMemoryRuntimeContractError as exc:
            raise ConversationExecutionRuntimeError(exc.code) from exc
        if contract is None or (
            contract.contract_version != binding.memory_contract_version
            or contract.storage_generation != binding.storage_generation
            or contract.mapping_version != binding.mapping_version
            or contract.memory_policy_version != binding.memory_policy_version
            or contract.start_node_id != binding.start_node_id
            or contract.input_variable != binding.input_variable
            or contract.llm_node_id != binding.llm_node_id
            or contract.answer_node_id != binding.answer_node_id
            or contract.output_variable != binding.output_variable
            or contract.memory.max_turns != binding.max_turns
            or contract.memory.max_context_tokens != binding.max_context_tokens
        ):
            raise ConversationExecutionRuntimeError("memory.runtime_binding_stale")
        return contract

    def _observe(self, event: str, binding, admission_id) -> None:
        try:
            self.observer.record(
                event=event,
                organization_id=binding.organization_id,
                admission_id=admission_id,
                turn_id=binding.turn_id,
            )
        except Exception:
            return


def _llm_data(graph: Mapping[str, Any], node_id: str) -> Mapping[str, Any]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        raise ConversationExecutionRuntimeError("memory.graph_unsupported")
    matches = [
        node.get("data")
        for node in nodes
        if isinstance(node, Mapping) and node.get("id") == node_id
    ]
    if len(matches) != 1 or not isinstance(matches[0], Mapping):
        raise ConversationExecutionRuntimeError("memory.graph_unsupported")
    return matches[0]


def _messages(
    node_data: Mapping[str, Any],
    *,
    variable: str,
    input_text: str,
    history_block: str,
) -> tuple[Mapping[str, str], ...]:
    if not isinstance(input_text, str) or not input_text:
        raise ConversationExecutionRuntimeError("memory.input_mapping_invalid")
    system_prompt = node_data.get("system_prompt") or ""
    user_prompt = node_data.get("user_prompt") or ""
    assistant_prompt = node_data.get("assistant_prompt") or ""
    if any(not isinstance(value, str) for value in (system_prompt, user_prompt, assistant_prompt)):
        raise ConversationExecutionRuntimeError("memory.llm_behavior_unsupported")
    if _TEMPLATE_VARIABLE.findall(system_prompt) or _TEMPLATE_VARIABLE.findall(
        assistant_prompt
    ):
        raise ConversationExecutionRuntimeError("memory.input_mapping_invalid")
    variables = _TEMPLATE_VARIABLE.findall(user_prompt)
    if set(variables) != {variable}:
        raise ConversationExecutionRuntimeError("memory.input_mapping_invalid")
    rendered_user = _TEMPLATE_VARIABLE.sub(
        lambda match: input_text if match.group(1) == variable else "",
        user_prompt,
    )
    messages: list[Mapping[str, str]] = []
    system_parts = [PLATFORM_UNTRUSTED_CONTEXT_GUARDRAIL_PROMPT]
    if system_prompt:
        system_parts.append(system_prompt)
    messages.append({"role": "system", "content": "\n\n".join(system_parts)})
    if history_block:
        messages.append({"role": "user", "content": history_block})
    messages.append({"role": "user", "content": rendered_user})
    if assistant_prompt:
        messages.append({"role": "assistant", "content": assistant_prompt})
    return tuple(messages)


def _safe_reason_code(error: Exception, default: str) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", code):
        return code
    return default


__all__ = [
    "ConversationExecutionBinding",
    "ConversationExecutionGraph",
    "ConversationExecutionRuntimeError",
    "ConversationMemoryCheckpoint",
    "ConversationMemoryContextBuild",
    "ConversationMemoryContextClaim",
    "ConversationProviderPreparation",
    "ConversationProviderResult",
    "ExecuteConversationTurnCommand",
    "ExecuteConversationTurnResult",
    "ExecuteConversationTurnUseCase",
]
