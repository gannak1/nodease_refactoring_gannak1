from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from apps.shared.domain.conversation_memory_task import ConversationTurnTaskEnvelope
from apps.workflow_engine.application.conversation_memory_execution import (
    ConversationExecutionBinding,
    ConversationExecutionGraph,
    ConversationMemoryCheckpoint,
    ConversationMemoryContextBuild,
    ConversationMemoryContextClaim,
    ConversationProviderPreparation,
    ConversationProviderResult,
    ExecuteConversationTurnCommand,
    ExecuteConversationTurnUseCase,
)
from apps.workflow_engine.application.conversation_memory_admission import (
    ConversationExecutionState,
)
from apps.workflow_engine.application.provider_execution import (
    ProviderInvocationOutcomeUnknownError,
)


NOW = datetime(2026, 7, 22, 16, tzinfo=timezone.utc)


def _graph() -> tuple[dict, dict]:
    graph = {
        "nodes": [
            {
                "id": "start",
                "type": "startNode",
                "data": {
                    "variables": [
                        {
                            "id": "question",
                            "name": "question",
                            "type": "paragraph",
                            "required": True,
                            "max_length": 16_384,
                        }
                    ]
                },
            },
            {
                "id": "llm",
                "type": "llmNode",
                "data": {
                    "model_id": "fixed-model",
                    "task_type": "generate",
                    "system_prompt": "Answer safely.",
                    "user_prompt": "Question: {{ question }}",
                    "referenced_variables": [
                        {
                            "name": "question",
                            "value_selector": ["start", "question"],
                        }
                    ],
                    "parameters": {"temperature": 0.2, "n": 1},
                    "memory": {
                        "enabled": True,
                        "channel": "conversation",
                        "readSource": "conversation_turns",
                        "writeMode": "none",
                        "maxTurns": 5,
                        "maxContextTokens": 1_200,
                        "strategy": "window",
                        "failurePolicy": "fail_node",
                    },
                },
            },
            {
                "id": "answer",
                "type": "answerNode",
                "data": {
                    "outputs": [
                        {
                            "variable": "answer",
                            "value_selector": ["llm", "text"],
                        }
                    ]
                },
            },
        ],
        "edges": [
            {"id": "start-llm", "source": "start", "target": "llm"},
            {"id": "llm-answer", "source": "llm", "target": "answer"},
        ],
    }
    config = {
        "conversation_memory": {
            "contract_version": "conversation-memory-v1",
            "storage_generation": 1,
            "mapping_version": "conversation-mapping-v1",
            "memory_policy_version": "memory-policy-v1",
            "input": {"node_id": "start", "variable": "question"},
            "output": {"node_id": "answer", "variable": "answer"},
        }
    }
    return graph, config


def _binding() -> ConversationExecutionBinding:
    return ConversationExecutionBinding(
        organization_id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        deployment_id=uuid.uuid4(),
        deployment_version=2,
        session_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        dispatch_id=uuid.uuid4(),
        dispatch_claim_generation=1,
        broker_message_id="message-1",
        request_fingerprint="a" * 64,
        lifecycle_revision=1,
        turn_version=1,
        memory_contract_version="conversation-memory-v1",
        mapping_version="conversation-mapping-v1",
        memory_policy_version="memory-policy-v1",
        storage_generation=1,
        minimum_worker_capability="memory-runtime-v1",
        start_node_id="start",
        input_variable="question",
        llm_node_id="llm",
        answer_node_id="answer",
        output_variable="answer",
        max_turns=5,
        max_context_tokens=1_200,
    )


class _Clock:
    def now(self):
        return NOW


class _GraphStore:
    def __init__(self, binding, graph=None):
        self.binding = binding
        values = _graph()
        self.value = ConversationExecutionGraph(
            graph=graph or values[0],
            deployment_config=values[1],
        )

    def load(self, binding):
        assert binding.deployment_id == self.binding.deployment_id
        return self.value


class _Admission:
    def __init__(self, binding):
        self.binding = binding
        self.admission_id = uuid.uuid4()
        self.execution_id = uuid.uuid4()
        self.attempt_id = uuid.uuid4()
        self.state = ConversationExecutionState.ADMITTED
        self.events = []

    def admit(self, binding, *, now):
        self.events.append("admit")
        return type(
            "Admitted",
            (),
            {
                "admission_id": self.admission_id,
                "execution_id": self.execution_id,
                "state": self.state,
                "replayed": False,
            },
        )()

    def claim(self, binding, *, owner, attempt_id, lease_deadline, now):
        self.events.append("claim")
        self.attempt_id = attempt_id
        self.state = ConversationExecutionState.LEASED
        return type(
            "Claimed",
            (),
            {
                "admission_id": self.admission_id,
                "execution_id": self.execution_id,
                "attempt_id": attempt_id,
                "lease_generation": 1,
            },
        )()

    def require_fence(self, binding, *, owner, lease_generation, now):
        self.events.append("fence")

    def finish(self, binding, **kwargs):
        self.events.append(f"finish:{kwargs['outcome']}")
        self.state = ConversationExecutionState(kwargs["outcome"])


class _Memory:
    def __init__(self, binding):
        self.binding = binding
        self.events = []
        self.context_attempt_id = uuid.uuid4()
        self.checkpoint_value = None

    def resolve(self, envelope):
        self.events.append("resolve")
        return self.binding

    def observe_admitted(self, binding, **_kwargs):
        self.events.append("admitted")
        self.binding = replace(binding, turn_version=binding.turn_version + 1)
        return self.binding

    def observe_running(self, binding, **_kwargs):
        self.events.append("running")
        self.binding = replace(binding, turn_version=binding.turn_version + 1)
        return self.binding

    def read_current_input(self, binding, **_kwargs):
        self.events.append("read_input")
        return "current question"

    def build_context(self, binding, **_kwargs):
        self.events.append("build_context")
        return ConversationMemoryContextBuild(uuid.uuid4(), uuid.uuid4())

    def claim_context(self, binding, **_kwargs):
        self.events.append("claim_context")
        return ConversationMemoryContextClaim(
            attempt_id=self.context_attempt_id,
            attempt_version=1,
            history_block="<UNTRUSTED_CONVERSATION_HISTORY version=\"1\">\n"
            '{"role":"user","content":"previous"}\n'
            '{"role":"assistant","content":"prior answer"}\n'
            "</UNTRUSTED_CONVERSATION_HISTORY>",
        )

    def validate_current(self, binding, **_kwargs):
        self.events.append("validate_current")

    def recover_checkpoint(self, binding, **_kwargs):
        self.events.append("recover_checkpoint")
        return self.checkpoint_value

    def mark_provider_started(self, binding, **kwargs):
        self.events.append(f"memory_start:{kwargs['usage_reference']}")
        return 2

    def finish_context_attempt(self, binding, **kwargs):
        self.events.append(f"context_finish:{kwargs['outcome']}")

    def checkpoint(self, binding, **kwargs):
        self.events.append("checkpoint")
        assert kwargs["assistant_text"] == "provider answer"
        self.checkpoint_value = ConversationMemoryCheckpoint(
            entry_id=uuid.uuid4(),
            content_digest="c" * 64,
            context_attempt_id=kwargs["context_attempt_id"],
            context_attempt_version=kwargs["context_attempt_version"],
            usage_reference=kwargs["usage_reference"],
            lifecycle_revision=binding.lifecycle_revision,
            turn_version=binding.turn_version,
            state=object(),
        )
        return self.checkpoint_value

    def complete(self, binding, **_kwargs):
        self.events.append("complete")

    def fail(self, binding, **kwargs):
        self.events.append(f"fail:{kwargs['safe_reason_code']}")


class _Provider:
    def __init__(
        self,
        *,
        error=None,
        success_error=None,
        success_error_committed=True,
    ):
        self.error = error
        self.success_error = success_error
        self.success_error_committed = success_error_committed
        self.events = []
        self.messages = None
        self.terminal_success = False
        self.preparation = ConversationProviderPreparation(
            capability_reference="capability-1",
            capability_revision="3",
            provider_attempt_id=uuid.uuid4(),
            expires_at=NOW + timedelta(minutes=2),
            state=object(),
        )

    def prepare(self, **_kwargs):
        self.events.append("prepare")
        return self.preparation

    def generate(self, *, messages, before_provider_start, **_kwargs):
        self.events.append("intent")
        self.messages = messages
        before_provider_start("usage-operation-1")
        self.events.append("usage_started")
        if self.error is not None:
            raise self.error
        self.events.append("provider_io")
        return ConversationProviderResult(
            text="provider answer",
            usage={"prompt_tokens": 4, "completion_tokens": 2},
            state=object(),
        )

    def record_success(self, result):
        self.events.append("usage_success")
        if self.success_error is not None:
            error = self.success_error
            self.success_error = None
            self.terminal_success = self.success_error_committed
            raise error
        self.terminal_success = True

    def resume_checkpoint(self, checkpoint, **_kwargs):
        if not self.terminal_success:
            self.events.append("usage_outcome_unknown")
        self.events.append("resume_checkpoint")


class _Observer:
    def __init__(self):
        self.events = []

    def record(self, **kwargs):
        self.events.append(kwargs["event"])


def _envelope(binding):
    return ConversationTurnTaskEnvelope(
        organization_id=binding.organization_id,
        dispatch_id=binding.dispatch_id,
        turn_id=binding.turn_id,
        claim_generation=1,
        broker_message_id="message-1",
        memory_contract_version="conversation-memory-v1",
        storage_generation=1,
        minimum_worker_capability="memory-runtime-v1",
    )


def _use_case(binding, *, provider=None):
    memory = _Memory(binding)
    admission = _Admission(binding)
    provider = provider or _Provider()
    return (
        ExecuteConversationTurnUseCase(
            memory=memory,
            admissions=admission,
            graphs=_GraphStore(binding),
            provider=provider,
            observer=_Observer(),
            clock=_Clock(),
            worker_capability="memory-runtime-v1",
            lease_duration=timedelta(seconds=30),
            context_lease_duration=timedelta(seconds=20),
        ),
        memory,
        admission,
        provider,
    )


def test_vertical_execution_orders_fences_and_keeps_history_untrusted() -> None:
    binding = _binding()
    use_case, memory, admission, provider = _use_case(binding)

    result = use_case.execute(
        ExecuteConversationTurnCommand(
            envelope=_envelope(binding),
            worker_owner="worker-a",
            delivery_attempt_id=uuid.uuid4(),
        )
    )

    assert result.state is ConversationExecutionState.COMPLETED
    assert provider.messages[0]["role"] == "system"
    assert provider.messages[0]["content"].endswith("Answer safely.")
    assert "untrusted" in provider.messages[0]["content"].lower()
    assert provider.messages[-1] == {
        "role": "user",
        "content": "Question: current question",
    }
    assert provider.messages[-2]["role"] == "user"
    assert "UNTRUSTED_CONVERSATION_HISTORY" in provider.messages[-2]["content"]
    assert memory.events.index("validate_current") < memory.events.index(
        "memory_start:usage-operation-1"
    )
    assert memory.events.index("checkpoint") < memory.events.index("complete")
    assert admission.events.index("fence") < admission.events.index(
        "finish:completed"
    )
    assert provider.events == [
        "prepare",
        "intent",
        "usage_started",
        "provider_io",
        "usage_success",
    ]


def test_crash_after_terminal_usage_commit_completes_from_checkpoint_without_provider_io() -> None:
    binding = _binding()
    provider = _Provider(success_error=RuntimeError("fault_after_usage_commit"))
    use_case, memory, admission, _provider = _use_case(binding, provider=provider)
    command = ExecuteConversationTurnCommand(
        envelope=_envelope(binding),
        worker_owner="worker-a",
        delivery_attempt_id=uuid.uuid4(),
    )

    with pytest.raises(RuntimeError, match="fault_after_usage_commit"):
        use_case.execute(command)

    assert memory.checkpoint_value is not None
    assert provider.events.count("provider_io") == 1
    first_attempt_id = admission.attempt_id

    result = use_case.execute(replace(command, delivery_attempt_id=uuid.uuid4()))

    assert result.state is ConversationExecutionState.COMPLETED
    assert admission.attempt_id == first_attempt_id
    assert provider.events.count("provider_io") == 1
    assert provider.events.count("intent") == 1
    assert provider.events[-1] == "resume_checkpoint"
    assert "complete" in memory.events


def test_crash_between_checkpoint_and_usage_terminal_recovers_without_provider_io() -> None:
    binding = _binding()
    provider = _Provider(
        success_error=RuntimeError("fault_before_usage_terminal"),
        success_error_committed=False,
    )
    use_case, memory, _admission, _provider = _use_case(
        binding,
        provider=provider,
    )
    command = ExecuteConversationTurnCommand(
        envelope=_envelope(binding),
        worker_owner="worker-a",
        delivery_attempt_id=uuid.uuid4(),
    )

    with pytest.raises(RuntimeError, match="fault_before_usage_terminal"):
        use_case.execute(command)

    result = use_case.execute(command)

    assert result.state is ConversationExecutionState.COMPLETED
    assert provider.events.count("provider_io") == 1
    assert provider.events.count("intent") == 1
    assert "usage_outcome_unknown" in provider.events
    assert "complete" in memory.events


def test_terminal_context_attempt_checkpoint_completes_without_rewriting_outcome() -> None:
    binding = _binding()
    use_case, memory, _admission, provider = _use_case(binding)
    memory.checkpoint_value = ConversationMemoryCheckpoint(
        entry_id=uuid.uuid4(),
        content_digest="c" * 64,
        context_attempt_id=memory.context_attempt_id,
        context_attempt_version=3,
        usage_reference="usage-operation-1",
        lifecycle_revision=binding.lifecycle_revision,
        turn_version=binding.turn_version,
        state=object(),
        context_attempt_outcome="outcome_unknown",
    )

    result = use_case.execute(
        ExecuteConversationTurnCommand(
            envelope=_envelope(binding),
            worker_owner="worker-a",
            delivery_attempt_id=uuid.uuid4(),
        )
    )

    assert result.state is ConversationExecutionState.COMPLETED
    assert provider.events == ["usage_outcome_unknown", "resume_checkpoint"]
    assert "context_finish:succeeded" not in memory.events
    assert "complete" in memory.events


def test_outcome_unknown_never_replays_provider_and_releases_turn_safely() -> None:
    binding = _binding()
    provider = _Provider(error=ProviderInvocationOutcomeUnknownError())
    use_case, memory, admission, _provider = _use_case(binding, provider=provider)

    with pytest.raises(ProviderInvocationOutcomeUnknownError):
        use_case.execute(
            ExecuteConversationTurnCommand(
                envelope=_envelope(binding),
                worker_owner="worker-a",
                delivery_attempt_id=uuid.uuid4(),
            )
        )

    assert provider.events.count("intent") == 1
    assert provider.events.count("usage_started") == 1
    assert "provider_io" not in provider.events
    assert "context_finish:outcome_unknown" in memory.events
    assert "fail:provider_outcome_unknown" in memory.events
    assert admission.events[-1] == "finish:outcome_unknown"


def test_task_hint_mismatch_fails_before_admission_or_provider_prepare() -> None:
    binding = _binding()
    use_case, memory, admission, provider = _use_case(binding)
    envelope = replace(_envelope(binding), turn_id=uuid.uuid4())

    with pytest.raises(ValueError, match="memory.execution_binding_mismatch"):
        use_case.execute(
            ExecuteConversationTurnCommand(
                envelope=envelope,
                worker_owner="worker-a",
                delivery_attempt_id=uuid.uuid4(),
            )
        )

    assert memory.events == ["resolve"]
    assert admission.events == []
    assert provider.events == []
