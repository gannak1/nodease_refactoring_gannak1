from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from apps.workflow_engine.adapters.conversation_memory_provider import (
    ConversationMemoryProviderAdapter,
    ConversationProviderLimits,
)
from apps.workflow_engine.application.conversation_memory_execution import (
    ConversationExecutionBinding,
)
from apps.workflow_engine.application.provider_execution import (
    ProviderInvocationOutcomeUnknownError,
)


NOW = datetime(2026, 7, 23, 9, tzinfo=timezone.utc)


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
        turn_version=3,
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


class _Lease:
    def __init__(self, events):
        self.events = events
        self.attribution = SimpleNamespace(usage_context=object())

    def finalize_request(self):
        self.events.append("final_admission")
        return self.attribution

    def revalidate_current_binding(self):
        self.events.append("current_binding")
        return self.attribution

    def invoke(self):
        self.events.append("provider_io")
        return {
            "choices": [{"message": {"content": "answer"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }


class _Runtime:
    def __init__(self, events):
        self.events = events
        self.lease = _Lease(events)

    def preflight(self, _request):
        return object()

    def prepare(self, _request):
        return SimpleNamespace(
            capability_id=uuid.uuid4(),
            capability_revision=3,
            provider_attempt_id=uuid.uuid4(),
            expires_at=NOW + timedelta(minutes=2),
        )

    def resolve(self, _request):
        return self.lease


class _UsageAttempt:
    durable = True
    operation_reference = "usage-operation-1"

    def __init__(self, events):
        self.events = events

    def mark_provider_started(self):
        self.events.append("usage_started")

    def record_success(self, *, usage, latency_ms):
        self.events.append("usage_success")
        return 0.0

    def mark_outcome_unknown(self, *, reason_code):
        self.events.append(f"usage_unknown:{reason_code}")


class _UsageRecorder:
    def __init__(self, events):
        self.events = events
        self.attempt = _UsageAttempt(events)

    def begin(self, _request):
        self.events.append("intent")
        return self.attempt


def test_current_capability_binding_is_revalidated_after_intent_before_any_send_marker() -> None:
    events = []
    runtime = _Runtime(events)
    adapter = ConversationMemoryProviderAdapter(
        runtime=runtime,
        usage_recorder=_UsageRecorder(events),
        limits=ConversationProviderLimits(
            input_token_cap=2_000,
            output_token_cap=500,
            cost_cap_microusd=10_000,
        ),
    )
    binding = _binding()
    preparation = adapter.prepare(
        binding=binding,
        admission_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        node_invocation_id=uuid.uuid4(),
        node_data={"model_id": "fixed-model"},
        deployment_config={},
    )

    result = adapter.generate(
        binding=binding,
        admission_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        node_invocation_id=uuid.uuid4(),
        node_data={"model_id": "fixed-model", "parameters": {"max_tokens": 20}},
        preparation=preparation,
        messages=({"role": "user", "content": "question"},),
        before_provider_start=lambda _reference: events.append("memory_marker"),
    )

    assert result.text == "answer"
    assert events == [
        "final_admission",
        "intent",
        "current_binding",
        "memory_marker",
        "usage_started",
        "provider_io",
    ]
    adapter.record_success(result)
    assert events[-1] == "usage_success"


def test_malformed_provider_response_is_immediately_durable_outcome_unknown() -> None:
    events = []
    runtime = _Runtime(events)
    runtime.lease.invoke = lambda: {"choices": []}
    adapter = ConversationMemoryProviderAdapter(
        runtime=runtime,
        usage_recorder=_UsageRecorder(events),
        limits=ConversationProviderLimits(
            input_token_cap=2_000,
            output_token_cap=500,
            cost_cap_microusd=10_000,
        ),
    )
    binding = _binding()
    preparation = adapter.prepare(
        binding=binding,
        admission_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        node_invocation_id=uuid.uuid4(),
        node_data={"model_id": "fixed-model"},
        deployment_config={},
    )

    import pytest

    with pytest.raises(ProviderInvocationOutcomeUnknownError):
        adapter.generate(
            binding=binding,
            admission_id=uuid.uuid4(),
            execution_id=uuid.uuid4(),
            node_invocation_id=uuid.uuid4(),
            node_data={
                "model_id": "fixed-model",
                "parameters": {"max_tokens": 20},
            },
            preparation=preparation,
            messages=({"role": "user", "content": "question"},),
            before_provider_start=lambda _reference: events.append(
                "memory_marker"
            ),
        )

    assert events[-1] == "usage_unknown:provider_call_failed"
    assert "usage_success" not in events
