from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from apps.gateway.adapters.queue import conversation_turn_publisher as adapter


NOW = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


class _Session:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Celery:
    def __init__(self) -> None:
        self.calls = []

    def send_task(self, name, args=None, kwargs=None, **options):
        self.calls.append((name, args, kwargs, options))
        return SimpleNamespace(id="broker-result-id")


def test_publisher_claims_then_sends_only_the_reference_envelope(monkeypatch) -> None:
    events = []

    class _Claim:
        def __init__(self, **_kwargs) -> None:
            pass

        def execute(self, command):
            events.append(("claim", command))
            return SimpleNamespace(claim_generation=2)

    class _Mark:
        def __init__(self, **_kwargs) -> None:
            pass

        def execute(self, command):
            events.append(("mark", command))

    monkeypatch.setattr(adapter, "ClaimTurnDispatchUseCase", _Claim)
    monkeypatch.setattr(adapter, "MarkTurnDispatchPublishedUseCase", _Mark)
    monkeypatch.setattr(
        adapter,
        "SqlAlchemyConversationMemoryRepository",
        lambda _session: object(),
    )
    monkeypatch.setattr(adapter, "SqlAlchemyMemoryUnitOfWork", lambda _session: object())
    session = _Session()
    celery = _Celery()
    values = {
        "organization_id": uuid.uuid4(),
        "dispatch_id": uuid.uuid4(),
        "turn_id": uuid.uuid4(),
        "memory_contract_version": "conversation-memory-v1",
        "storage_generation": 1,
        "minimum_worker_capability": "memory-runtime-v1",
    }

    adapter.CeleryConversationTurnPublisher(
        celery_app=celery,
        session_factory=lambda: session,
        clock=lambda: NOW,
    ).publish(**values)

    name, args, _kwargs, options = celery.calls[0]
    assert name == "workflow.execute_conversation_turn"
    assert set(args[0]) == {
        "envelope_version",
        "organization_id",
        "dispatch_id",
        "turn_id",
        "claim_generation",
        "broker_message_id",
        "memory_contract_version",
        "storage_generation",
        "minimum_worker_capability",
    }
    assert args[0]["claim_generation"] == 2
    assert options["ignore_result"] is True
    assert [event[0] for event in events] == ["claim", "mark"]
    assert session.closed is True
