from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from apps.gateway.middleware.public_conversation_cors import (
    PublicConversationCorsBoundaryMiddleware,
)


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://parent.example"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Added after CORS so it is the outer boundary in the production stack.
    app.add_middleware(PublicConversationCorsBoundaryMiddleware)

    @app.post("/api/v1/run-public/chat/conversations")
    def conversation_create():
        return {"ok": True}

    @app.post("/api/v1/run-public/chat")
    def legacy_public_run():
        return {"ok": True}

    return TestClient(app)


def test_public_conversation_preflight_is_not_a_cors_grant():
    response = _client().options(
        "/api/v1/run-public/chat/conversations",
        headers={
            "Origin": "https://parent.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 404
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


def test_trailing_slash_create_preflight_is_not_a_cors_grant():
    response = _client().options(
        "/api/v1/run-public/chat/conversations/",
        headers={
            "Origin": "https://parent.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 404
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


def test_public_conversation_response_never_inherits_global_cors_or_vary_origin():
    response = _client().post(
        "/api/v1/run-public/chat/conversations",
        headers={"Origin": "https://parent.example"},
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers
    assert "origin" not in response.headers.get("vary", "").lower()


def test_legacy_public_run_route_is_not_changed_by_target_cors_boundary():
    response = _client().post(
        "/api/v1/run-public/chat",
        headers={"Origin": "https://parent.example"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://parent.example"
