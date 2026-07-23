from __future__ import annotations

import uuid

import pytest
from apps.shared.domain.conversation_memory_task import (
    ConversationTurnTaskContractError,
    ConversationTurnTaskEnvelope,
)


def _envelope() -> ConversationTurnTaskEnvelope:
    return ConversationTurnTaskEnvelope(
        organization_id=uuid.uuid4(),
        dispatch_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        claim_generation=1,
        broker_message_id="conversation-turn-message",
        memory_contract_version="conversation-memory-v1",
        storage_generation=1,
        minimum_worker_capability="memory-runtime-v1",
    )


def test_reference_only_envelope_round_trips_exact_fields() -> None:
    envelope = _envelope()

    payload = envelope.to_payload()

    assert ConversationTurnTaskEnvelope.from_payload(payload) == envelope
    assert not set(payload).intersection(
        {"input", "inputs", "content", "context", "access_token", "grant_id"}
    )


@pytest.mark.parametrize("field", ["inputs", "content", "access_token", "graph"])
def test_payload_rejects_raw_or_unknown_fields(field: str) -> None:
    payload = _envelope().to_payload()
    payload[field] = "sensitive"

    with pytest.raises(ConversationTurnTaskContractError):
        ConversationTurnTaskEnvelope.from_payload(payload)
