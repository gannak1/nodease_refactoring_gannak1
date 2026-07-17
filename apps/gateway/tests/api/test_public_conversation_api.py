from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.gateway.api.deps import get_db
from apps.gateway.api.v1.endpoints import public_conversation, run
from apps.memory.application.public_lifecycle import (
    ClosePublicConversationResult,
    PublicConversationResult,
)
from apps.memory.domain.conversation import SessionLifecycle


def _key() -> str:
    return secrets.token_urlsafe(24)


class _Create:
    def __init__(self) -> None:
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        return PublicConversationResult(
            lifecycle=SessionLifecycle.ACTIVE,
            lifecycle_revision=1,
            memory_contract_version="conversation-memory-v1",
            expires_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
            access_token=f"cag_v1_{secrets.token_urlsafe(32)}",
            replayed=False,
        )


class _Close:
    def __init__(self) -> None:
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        return ClosePublicConversationResult(
            lifecycle=SessionLifecycle.CLOSED,
            lifecycle_revision=2,
            memory_contract_version="conversation-memory-v1",
            expires_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
            replayed=False,
        )


class _Application:
    def __init__(self) -> None:
        self.create = _Create()
        self.close = _Close()


def _client(monkeypatch, application: _Application) -> TestClient:
    app = FastAPI()
    app.include_router(public_conversation.router)
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(public_conversation, "_application", lambda _db: application)
    return TestClient(app)


def test_create_returns_only_public_safe_fields_and_no_store_headers(monkeypatch):
    application = _Application()
    client = _client(monkeypatch, application)
    client.cookies.set("session", "authenticated-cookie-is-not-a-principal")
    response = client.post(
        "/run-public/public-chatbot/conversations",
        json={},
        headers={"Idempotency-Key": _key()},
    )

    assert response.status_code == 201
    conversation = response.json()["conversation"]
    assert set(conversation) == {
        "access_token",
        "lifecycle_revision",
        "memory_contract_version",
        "expires_at",
    }
    assert "session_id" not in conversation
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["etag"] == '"lifecycle-revision-1"'
    assert application.create.commands[0].network_address == "testclient"


def test_lifecycle_requires_exact_if_match_before_application_mutation(monkeypatch):
    application = _Application()
    response = _client(monkeypatch, application).post(
        "/run-public/public-chatbot/conversation/close",
        json={},
        headers={
            "Authorization": f"Conversation cag_v1_{secrets.token_urlsafe(32)}",
            "Idempotency-Key": _key(),
        },
    )

    assert response.status_code == 428
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.json()["detail"]["code"] == "memory.lifecycle_precondition_required"
    assert application.close.commands == []


def test_bearer_or_cookie_cannot_be_interpreted_as_public_conversation_grant(monkeypatch):
    application = _Application()
    client = _client(monkeypatch, application)
    client.cookies.set("session", "authenticated-cookie-is-not-a-principal")
    response = client.post(
        "/run-public/public-chatbot/conversation/close",
        json={},
        headers={
            "Authorization": "Bearer authenticated-token",
            "Idempotency-Key": _key(),
            "If-Match": '"lifecycle-revision-1"',
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}
    assert application.close.commands == []


def test_legacy_public_run_rejects_target_conversation_envelope_before_runtime():
    app = FastAPI()
    app.include_router(run.router)
    app.dependency_overrides[get_db] = lambda: object()

    response = TestClient(app).post(
        "/run-public/public-chatbot",
        json={"conversation": {}},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "memory.feature_unavailable"
