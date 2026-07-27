from __future__ import annotations

import uuid
from types import SimpleNamespace

from starlette.requests import Request

from apps.gateway.api.v1.endpoints import agent_builder as endpoint
from apps.gateway.services import agent_builder_service as service_module
from apps.gateway.services.agent_builder_service import AgentBuilderService
from apps.shared.schemas.agent_builder import AgentBuilderSessionCreateRequest


class _Query:
    def __init__(self, result: object) -> None:
        self._result = result

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._result


class _Db:
    def __init__(self, existing_session: object) -> None:
        self.existing_session = existing_session
        self.added: list[object] = []

    def query(self, *_args, **_kwargs):
        return _Query(self.existing_session)

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid.uuid4()

    def commit(self) -> None:
        return None

    def refresh(self, _value: object) -> None:
        return None


def _request(host: str, fresh_header: bool) -> Request:
    headers = []
    if fresh_header:
        headers.append((b"x-agent-builder-benchmark-fresh-session", b"true"))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/agent-builder/sessions",
            "headers": headers,
            "client": (host, 12345),
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


def test_forced_benchmark_session_does_not_reuse_active_session(monkeypatch) -> None:
    user = SimpleNamespace(id=uuid.uuid4())
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    workflow = SimpleNamespace(
        id=workflow_id,
        app_id=uuid.uuid4(),
        organization_id=organization_id,
    )
    existing = SimpleNamespace(id=uuid.uuid4())
    db = _Db(existing)
    service = AgentBuilderService(db, user=user, organization_id=organization_id)
    monkeypatch.setattr(service, "_workflow_in_active_org", lambda _id: workflow)
    monkeypatch.setattr(
        service_module, "ensure_workflow_permission", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(service_module, "add_action_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_session_response", lambda session: session)

    response = service.create_or_restore_session(
        AgentBuilderSessionCreateRequest(workflow_id=workflow_id),
        force_new=True,
    )

    assert response is db.added[0]
    assert response is not existing


def test_fresh_session_header_is_honored_only_for_enabled_loopback_benchmark(
    monkeypatch,
) -> None:
    calls: list[bool] = []
    orchestration = SimpleNamespace(
        create_or_restore_session=lambda _payload, *, force_new=False: calls.append(
            force_new
        )
        or SimpleNamespace()
    )
    composition = SimpleNamespace(orchestration=lambda: orchestration)
    monkeypatch.setattr(endpoint, "_composition", lambda **_kwargs: composition)
    monkeypatch.setenv("AGENT_BUILDER_CACHE_BENCHMARK_DIAGNOSTICS_ENABLED", "true")
    monkeypatch.setenv("NODE_ENV", "development")
    payload = AgentBuilderSessionCreateRequest(workflow_id=uuid.uuid4())

    endpoint.create_or_restore_session(
        payload,
        _request("127.0.0.1", fresh_header=True),
        str(uuid.uuid4()),
        SimpleNamespace(),
        SimpleNamespace(id=uuid.uuid4()),
    )
    endpoint.create_or_restore_session(
        payload,
        _request("192.0.2.1", fresh_header=True),
        str(uuid.uuid4()),
        SimpleNamespace(),
        SimpleNamespace(id=uuid.uuid4()),
    )

    assert calls == [True, False]
