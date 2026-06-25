import uuid
from types import SimpleNamespace

from apps.shared.services.tracing.access import TraceAccessService
from apps.shared.services.tracing.policy import ResolvedVisibilityPolicy
from apps.shared.services.tracing.query import TraceQueryService
from apps.shared.services.tracing.rbac import TraceRbacService


def setup_function():
    TraceRbacService.reset_provider()


def teardown_function():
    TraceRbacService.reset_provider()


def test_run_user_id_does_not_grant_app_owner_access(monkeypatch):
    user_id = uuid.uuid4()
    app_id = uuid.uuid4()
    run = SimpleNamespace(id=uuid.uuid4(), user_id=user_id, app_id=app_id)
    user = SimpleNamespace(id=user_id)

    monkeypatch.setattr(
        TraceAccessService, "resolve_trace_app_id", lambda db, trace: app_id
    )
    monkeypatch.setattr(TraceAccessService, "is_app_owner", lambda db, app, actor: False)
    monkeypatch.setattr(
        "apps.shared.services.tracing.access.TracePolicyService.resolve_visibility_policy",
        lambda db, app_id=None: ResolvedVisibilityPolicy(),
    )

    decision = TraceAccessService.check_trace_access(None, run, user)

    assert decision.allowed is False
    assert decision.reason_code == "regular_user_trace_access_denied"


def test_app_owner_metadata_access_uses_app_relationship(monkeypatch):
    user_id = uuid.uuid4()
    app_id = uuid.uuid4()
    run = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), app_id=app_id)
    user = SimpleNamespace(id=user_id)

    monkeypatch.setattr(
        TraceAccessService, "resolve_trace_app_id", lambda db, trace: app_id
    )
    monkeypatch.setattr(TraceAccessService, "is_app_owner", lambda db, app, actor: True)
    monkeypatch.setattr(
        "apps.shared.services.tracing.access.TracePolicyService.resolve_visibility_policy",
        lambda db, app_id=None: ResolvedVisibilityPolicy(),
    )

    decision = TraceAccessService.check_trace_access(None, run, user)

    assert decision.allowed is True
    assert decision.reason_code == "app_owner"


def test_raw_access_denied_by_default_for_system_admin(monkeypatch):
    app_id = uuid.uuid4()
    run = SimpleNamespace(id=uuid.uuid4(), app_id=app_id)
    user = SimpleNamespace(id=uuid.uuid4())

    class TestAdminProvider:
        def is_system_admin(self, db, actor):
            return actor is user

    TraceRbacService.configure_provider(TestAdminProvider())

    monkeypatch.setattr(
        TraceAccessService, "resolve_trace_app_id", lambda db, trace: app_id
    )
    monkeypatch.setattr(TraceAccessService, "is_app_owner", lambda db, app, actor: False)
    monkeypatch.setattr(
        "apps.shared.services.tracing.access.TracePolicyService.resolve_visibility_policy",
        lambda db, app_id=None: ResolvedVisibilityPolicy(),
    )

    decision = TraceAccessService.check_trace_access(None, run, user, view_level="raw")

    assert decision.allowed is False
    assert decision.reason_code == "admin_raw_payload_access_disabled"


def test_system_admin_requires_rbac_provider():
    user = SimpleNamespace(id=uuid.uuid4(), role="admin", is_system_admin=True)

    assert TraceAccessService.is_system_admin(None, user) is False


def test_llm_span_hides_io_without_prompt_completion_policy(monkeypatch):
    span = SimpleNamespace(
        id=uuid.uuid4(),
        workflow_run_id=uuid.uuid4(),
        node_id="llm-1",
        node_type="llmNode",
        status="success",
        started_at=None,
        finished_at=None,
        duration=None,
        inputs={"prompt": "hello"},
        outputs={"text": "world"},
        process_data={},
        trace_metadata={},
        redaction_applied=True,
        pii_detected=False,
        sequence=1,
        retry_count=0,
    )
    run = SimpleNamespace(id=span.workflow_run_id)
    user = SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(
        TraceAccessService,
        "check_trace_access",
        lambda db, trace, actor, view_level="metadata", payload_kind=None: SimpleNamespace(
            allowed=payload_kind not in {"prompt", "completion"}
        ),
    )

    detail = TraceQueryService.span_detail(
        span, view_level="redacted", db=object(), run=run, user=user
    )

    assert detail["inputs"] is None
    assert detail["outputs"] is None


def test_metadata_span_hides_process_data():
    span = SimpleNamespace(
        id=uuid.uuid4(),
        workflow_run_id=uuid.uuid4(),
        node_id="http-1",
        node_type="httpRequestNode",
        status="success",
        started_at=None,
        finished_at=None,
        duration=None,
        inputs={"url": "https://example.test"},
        outputs={"status": 200},
        process_data={"credential_id": str(uuid.uuid4())},
        trace_metadata={},
        redaction_applied=True,
        pii_detected=False,
        sequence=1,
        retry_count=0,
    )

    detail = TraceQueryService.span_detail(span, view_level="metadata")

    assert detail["inputs"] is None
    assert detail["outputs"] is None
    assert detail["process_data"] is None


def test_raw_access_event_keeps_actor_ref(monkeypatch):
    events = []

    class FakeSession:
        def add(self, event):
            events.append(event)

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    actor_id = uuid.uuid4()
    monkeypatch.setattr(
        "apps.shared.services.tracing.access.SessionLocal", lambda: FakeSession()
    )

    TraceAccessService.record_payload_access_event(
        None,
        workflow_run_id=uuid.uuid4(),
        actor_user_id=actor_id,
        view_level="raw",
        allowed=True,
        reason_code="system_admin_raw",
        payload_id=uuid.uuid4(),
    )

    assert events[0].actor_user_id == actor_id
    assert events[0].actor_user_ref
    assert str(actor_id) not in events[0].actor_user_ref
