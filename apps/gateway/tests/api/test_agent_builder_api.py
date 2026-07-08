import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.gateway.api.v1.endpoints import agent_builder as agent_builder_endpoint
from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.main import app
from apps.shared.schemas.agent_builder import (
    AgentBuilderApplyResponse,
    AgentBuilderMessageResponse,
    AgentBuilderSessionResponse,
)


def test_agent_builder_session_uses_header_resolved_organization(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    captured = {}

    monkeypatch.setattr(
        agent_builder_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, current_user_id: organization_id,
    )

    class FakeService:
        def __init__(self, db, *, user, organization_id):
            captured["user_id"] = user.id
            captured["organization_id"] = organization_id

        def create_or_restore_session(self, payload):
            captured["payload_has_organization_id"] = hasattr(payload, "organization_id")
            return AgentBuilderSessionResponse(
                session_id=uuid.uuid4(),
                app_id=payload.app_id,
                status="active",
            )

    monkeypatch.setattr(agent_builder_endpoint, "AgentBuilderService", FakeService)
    app.dependency_overrides[agent_builder_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            "/api/v1/agent-builder/sessions",
            json={
                "app_id": str(uuid.uuid4()),
                "organization_id": str(uuid.uuid4()),
            },
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert captured["user_id"] == user_id
    assert captured["organization_id"] == organization_id
    assert captured["payload_has_organization_id"] is False


def test_agent_builder_message_contract_does_not_accept_body_organization(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    captured = {}

    monkeypatch.setattr(
        agent_builder_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, current_user_id: organization_id,
    )

    class FakeService:
        def __init__(self, db, *, user, organization_id):
            captured["organization_id"] = organization_id

        def submit_message(self, session_id_arg, payload):
            captured["session_id"] = session_id_arg
            captured["payload_has_organization_id"] = hasattr(payload, "organization_id")
            captured["message"] = payload.message
            return AgentBuilderMessageResponse(
                request_id=uuid.uuid4(),
                status="validation_failed",
                warnings=["테스트"],
            )

    monkeypatch.setattr(agent_builder_endpoint, "AgentBuilderService", FakeService)
    app.dependency_overrides[agent_builder_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            f"/api/v1/agent-builder/sessions/{session_id}/messages",
            json={
                "message": "휴가 정책 기반 workflow를 만들어줘",
                "organization_id": str(uuid.uuid4()),
            },
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert captured["organization_id"] == organization_id
    assert captured["session_id"] == session_id
    assert captured["payload_has_organization_id"] is False
    assert captured["message"] == "휴가 정책 기반 workflow를 만들어줘"


def test_agent_builder_message_rejects_raw_graph_payload_without_echo(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    called = {"submit": False}

    monkeypatch.setattr(
        agent_builder_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, current_user_id: organization_id,
    )

    class FakeService:
        def __init__(self, db, *, user, organization_id):
            pass

        def submit_message(self, session_id_arg, payload):
            called["submit"] = True
            raise AssertionError("raw graph payload must not reach service")

    monkeypatch.setattr(agent_builder_endpoint, "AgentBuilderService", FakeService)
    app.dependency_overrides[agent_builder_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            f"/api/v1/agent-builder/sessions/{session_id}/messages",
            json={
                "message": "create workflow",
                "client_graph_snapshot": {
                    "nodes": [{"data": {"api_key": "secret-token-123"}}]
                },
            },
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 422
    assert called["submit"] is False
    assert "secret-token-123" not in response.text


def test_agent_builder_apply_rejects_raw_graph_payload_without_echo(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    draft_id = uuid.uuid4()
    called = {"apply": False}

    monkeypatch.setattr(
        agent_builder_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, current_user_id: organization_id,
    )

    class FakeService:
        def __init__(self, db, *, user, organization_id):
            pass

        def apply_draft(self, draft_id_arg, payload):
            called["apply"] = True
            raise AssertionError("raw graph payload must not reach service")

    monkeypatch.setattr(agent_builder_endpoint, "AgentBuilderService", FakeService)
    app.dependency_overrides[agent_builder_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            f"/api/v1/agent-builder/drafts/{draft_id}/apply",
            json={
                "action": "apply_and_save",
                "previewGraph": {
                    "nodes": [{"data": {"api_key": "secret-token-123"}}]
                },
            },
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 422
    assert called["apply"] is False
    assert "secret-token-123" not in response.text


def test_agent_builder_apply_response_can_save_only_with_audit_recorded(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    draft_id = uuid.uuid4()
    workflow_id = uuid.uuid4()

    monkeypatch.setattr(
        agent_builder_endpoint,
        "resolve_active_organization_id",
        lambda db, request, raw, current_user_id: organization_id,
    )

    class FakeService:
        def __init__(self, db, *, user, organization_id):
            pass

        def apply_draft(self, draft_id_arg, payload):
            assert draft_id_arg == draft_id
            return AgentBuilderApplyResponse(
                apply_id=uuid.uuid4(),
                outcome="saved",
                saved_workflow_id=workflow_id,
                audit_recorded=True,
            )

    monkeypatch.setattr(agent_builder_endpoint, "AgentBuilderService", FakeService)
    app.dependency_overrides[agent_builder_endpoint.get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        response = TestClient(app).post(
            f"/api/v1/agent-builder/drafts/{draft_id}/apply",
            json={"action": "apply_and_save"},
            headers={"X-Organization-Id": str(organization_id)},
        )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "saved"
    assert body["audit_recorded"] is True
