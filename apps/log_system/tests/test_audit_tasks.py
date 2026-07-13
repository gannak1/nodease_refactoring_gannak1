from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from apps.log_system import audit_tasks
from apps.shared.db.models.audit_log import AuditLog
from apps.shared.db.models.security_alert import SecurityAlertReconciliationWatermark
from sqlalchemy.exc import IntegrityError


@pytest.fixture(autouse=True)
def _isolate_celery_broker(monkeypatch):
    monkeypatch.setattr(audit_tasks.celery_app, "send_task", lambda *args, **kwargs: None)


class _Session:
    def __init__(
        self,
        *,
        existing=None,
        commit_error=None,
        winner_after_rollback=None,
        events=None,
    ):
        self.existing = existing
        self.commit_error = commit_error
        self.winner_after_rollback = winner_after_rollback
        self.events = events
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def get(self, model, identity):
        assert model is AuditLog
        if self.existing is not None and self.existing.id == identity:
            return self.existing
        return None

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1
        if self.events is not None:
            self.events.append("commit")
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self):
        self.rollbacks += 1
        if self.winner_after_rollback is not None:
            self.existing = self.winner_after_rollback

    def close(self):
        self.closed += 1


def _data(audit_id):
    return {
        "id": str(audit_id),
        "occurred_at": "2026-07-12T00:00:00+00:00",
        "actor_id": str(uuid4()),
        "actor_type": "user",
        "category": "action",
        "action": "permission.denied",
        "target_type": "workflow",
        "target_id": str(uuid4()),
        "status": "failure",
        "audit_metadata": {"organization_id": str(uuid4())},
    }


def test_record_audit_uses_publisher_supplied_id(monkeypatch):
    session = _Session()
    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: session)
    audit_id = uuid4()

    result = audit_tasks.record_audit_log.run(_data(audit_id))

    assert result == {
        "status": "success",
        "action": "permission.denied",
        "audit_id": str(audit_id),
    }
    assert session.added[0].id == audit_id
    assert session.commits == 1
    assert session.closed == 1


def test_record_audit_redelivery_is_idempotent(monkeypatch):
    audit_id = uuid4()
    existing = AuditLog(id=audit_id)
    session = _Session(existing=existing)
    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: session)

    result = audit_tasks.record_audit_log.run(_data(audit_id))

    assert result == {
        "status": "duplicate",
        "action": "permission.denied",
        "audit_id": str(audit_id),
    }
    assert session.added == []
    assert session.commits == 0
    assert session.closed == 1


def test_concurrent_duplicate_insert_treats_committed_winner_as_success(monkeypatch):
    audit_id = uuid4()
    winner = AuditLog(id=audit_id)
    session = _Session(
        commit_error=IntegrityError("insert", {}, RuntimeError("duplicate")),
        winner_after_rollback=winner,
    )
    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: session)

    result = audit_tasks.record_audit_log.run(_data(audit_id))

    assert result["status"] == "duplicate"
    assert result["audit_id"] == str(audit_id)
    assert session.commits == 1
    assert session.rollbacks == 1
    assert session.closed == 1


def test_record_audit_dispatches_realtime_security_alert_after_commit(monkeypatch):
    events = []
    audit_id = uuid4()
    session = _Session(events=events)
    dispatched = []
    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        audit_tasks.celery_app,
        "send_task",
        lambda name, *, args: (
            events.append("dispatch"),
            dispatched.append((name, args)),
        ),
    )

    audit_tasks.record_audit_log.run(_data(audit_id))

    assert events == ["commit", "dispatch"]
    assert dispatched == [("security_alert.detect", [str(audit_id)])]


def test_record_audit_redelivery_redispatches_realtime_security_alert(monkeypatch):
    audit_id = uuid4()
    session = _Session(existing=AuditLog(id=audit_id))
    dispatched = []
    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        audit_tasks.celery_app,
        "send_task",
        lambda name, *, args: dispatched.append((name, args)),
    )

    audit_tasks.record_audit_log.run(_data(audit_id))

    assert dispatched == [("security_alert.detect", [str(audit_id)])]


def test_realtime_security_alert_consumer_task_is_registered():
    assert "security_alert.detect" in audit_tasks.celery_app.tasks


def test_security_alert_detect_returns_missing_for_unknown_audit(monkeypatch):
    audit_id = uuid4()
    session = _Session()
    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: session)

    result = audit_tasks.detect_security_alert.run(str(audit_id))

    assert result == {"status": "missing", "audit_id": str(audit_id)}
    assert session.closed == 1


def test_sal_tc_w001_fifth_denial_is_evaluated_and_aggregated(monkeypatch):
    now = datetime(2026, 7, 12, 0, 10, tzinfo=timezone.utc)
    activation_started_at = now - timedelta(minutes=10)
    actor_id = uuid4()
    organization_id = uuid4()
    audits = [
        AuditLog(
            id=uuid4(),
            occurred_at=now - timedelta(seconds=30 * (4 - index)),
            actor_id=actor_id,
            actor_type="user",
            category="action",
            action="permission.denied",
            target_type="workflow",
            target_id=str(uuid4()),
            status="failure",
            audit_metadata={"organization_id": str(organization_id)},
        )
        for index in range(5)
    ]
    current = audits[-1]
    candidate = SimpleNamespace(
        rule_id="repeated_permission_denied",
        detection_key="threshold-key",
    )
    alert = SimpleNamespace(id=uuid4())
    session = _Session(existing=current)
    evaluated = []
    aggregated = []
    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        audit_tasks,
        "_load_security_alert_detection_context",
        lambda db, audit_id: (current, audits, activation_started_at),
        raising=False,
    )
    monkeypatch.setattr(
        audit_tasks,
        "evaluate_security_alert_rules",
        lambda **kwargs: (evaluated.append(kwargs), (candidate,))[1],
        raising=False,
    )
    monkeypatch.setattr(
        audit_tasks,
        "build_security_alert_cooldown_candidates",
        lambda **kwargs: (),
    )
    monkeypatch.setattr(
        audit_tasks,
        "aggregate_security_alert_detection",
        lambda db, **kwargs: (aggregated.append((db, kwargs)), alert)[1],
        raising=False,
    )

    result = audit_tasks.detect_security_alert.run(str(current.id))

    assert evaluated == [
        {
            "current_event": current,
            "window_events": audits,
            "activation_started_at": activation_started_at,
        }
    ]
    assert aggregated == [
        (
            session,
            {
                "candidate": candidate,
                "audit_logs": audits,
                "detected_at": current.occurred_at,
            },
        )
    ]
    assert result == {
        "status": "processed",
        "audit_id": str(current.id),
        "candidate_count": 1,
    }
    assert session.commits == 1
    assert session.closed == 1


def test_cooldown_candidate_is_aggregated_without_threshold_candidate(monkeypatch):
    now = datetime(2026, 7, 12, 0, 10, tzinfo=timezone.utc)
    current = AuditLog(
        id=uuid4(),
        occurred_at=now,
        actor_id=uuid4(),
        actor_type="user",
        category="action",
        action="permission.denied",
        target_type="workflow",
        target_id=str(uuid4()),
        status="failure",
        audit_metadata={"organization_id": str(uuid4())},
    )
    cooldown_candidate = SimpleNamespace(
        rule_id="repeated_permission_denied",
        detection_key="cooldown-key",
    )
    aggregated = []
    monkeypatch.setattr(
        audit_tasks,
        "evaluate_security_alert_rules",
        lambda **kwargs: (),
    )
    monkeypatch.setattr(
        audit_tasks,
        "build_security_alert_cooldown_candidates",
        lambda **kwargs: (cooldown_candidate,),
        raising=False,
    )
    monkeypatch.setattr(
        audit_tasks,
        "aggregate_security_alert_detection",
        lambda db, **kwargs: aggregated.append((db, kwargs)),
    )
    db = object()

    candidate_count = audit_tasks._evaluate_and_aggregate_security_alerts(
        db,
        current_event=current,
        window_events=[current],
        activation_started_at=now - timedelta(minutes=10),
    )

    assert candidate_count == 0
    assert aggregated == [
        (
            db,
            {
                "candidate": cooldown_candidate,
                "audit_logs": [current],
                "detected_at": now,
            },
        )
    ]


def test_detection_context_loads_ten_minute_window_from_activation_watermark():
    now = datetime(2026, 7, 12, 0, 10, tzinfo=timezone.utc)
    activation_started_at = now - timedelta(minutes=7)
    actor_id = uuid4()
    organization_id = uuid4()
    audits = [
        AuditLog(
            id=uuid4(),
            occurred_at=now - timedelta(minutes=4 - index),
            actor_id=actor_id,
            actor_type="user",
            category="action",
            action="permission.denied",
            target_type="workflow",
            target_id=str(uuid4()),
            status="failure",
            audit_metadata={"organization_id": str(organization_id)},
        )
        for index in range(5)
    ]
    current = audits[-1]
    watermark = SecurityAlertReconciliationWatermark(
        processor_name="security-alert-v1",
        activation_started_at=activation_started_at,
    )

    class _WindowQuery:
        def __init__(self):
            self.filters = []
            self.ordering = ()

        def filter(self, *conditions):
            self.filters.extend(conditions)
            return self

        def order_by(self, *columns):
            self.ordering = columns
            return self

        def all(self):
            return audits

    class _WindowSession:
        def __init__(self):
            self.query_value = _WindowQuery()

        def get(self, model, identity):
            if model is AuditLog and identity == current.id:
                return current
            if model is SecurityAlertReconciliationWatermark:
                return watermark
            return None

        def query(self, model):
            assert model is AuditLog
            return self.query_value

    session = _WindowSession()

    loaded = audit_tasks._load_security_alert_detection_context(session, current.id)

    assert loaded == (current, audits, activation_started_at)
    assert session.query_value.filters
    assert session.query_value.ordering == (AuditLog.occurred_at, AuditLog.id)


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "success"},
        {"actor_type": "system"},
        {"action": "workflow.executed"},
    ],
)
def test_ineligible_current_event_skips_window_query(overrides):
    now = datetime(2026, 7, 12, 0, 10, tzinfo=timezone.utc)
    organization_id = uuid4()
    values = {
        "actor_type": "user",
        "action": "permission.denied",
        "status": "failure",
        **overrides,
    }
    current = AuditLog(
        id=uuid4(),
        occurred_at=now,
        actor_id=uuid4(),
        actor_type=values["actor_type"],
        category="action",
        action=values["action"],
        target_type="workflow",
        target_id=str(uuid4()),
        status=values["status"],
        audit_metadata={"organization_id": str(organization_id)},
    )
    watermark = SecurityAlertReconciliationWatermark(
        processor_name="security-alert-v1",
        activation_started_at=now - timedelta(minutes=10),
    )

    class _UnexpectedWindowQuery:
        def filter(self, *conditions):
            return self

        def order_by(self, *columns):
            return self

        def all(self):
            return []

    class _EligibilitySession:
        def __init__(self):
            self.window_queries = 0

        def get(self, model, identity):
            if model is AuditLog and identity == current.id:
                return current
            if model is SecurityAlertReconciliationWatermark:
                return watermark
            return None

        def query(self, model):
            assert model is AuditLog
            self.window_queries += 1
            return _UnexpectedWindowQuery()

    session = _EligibilitySession()

    result = audit_tasks._process_security_alert_audit(session, current.id)

    assert result == 0
    assert session.window_queries == 0


def test_security_alert_detection_is_routed_to_log_queue():
    route = audit_tasks.celery_app.amqp.router.route(
        {},
        "security_alert.detect",
        args=[],
        kwargs={},
    )

    assert route["queue"].name == "log"


def test_security_alert_detection_retries_without_exposing_failure_details(
    monkeypatch,
    caplog,
):
    current = AuditLog(
        id=uuid4(),
        occurred_at=datetime(2026, 7, 12, 0, 10, tzinfo=timezone.utc),
    )
    session = _Session(existing=current)
    secret_marker = "secret-marker-detection-123"
    failure = RuntimeError(secret_marker)
    retries = []

    class _RetryRequested(Exception):
        pass

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        audit_tasks,
        "_load_security_alert_detection_context",
        lambda db, audit_id: (
            current,
            [current],
            current.occurred_at - timedelta(minutes=10),
        ),
    )
    monkeypatch.setattr(
        audit_tasks,
        "evaluate_security_alert_rules",
        lambda **kwargs: (SimpleNamespace(rule_id="repeated_permission_denied"),),
    )
    monkeypatch.setattr(
        audit_tasks,
        "aggregate_security_alert_detection",
        lambda *args, **kwargs: (_ for _ in ()).throw(failure),
    )

    def request_retry(**kwargs):
        retries.append(kwargs)
        raise _RetryRequested

    monkeypatch.setattr(audit_tasks.detect_security_alert, "retry", request_retry)

    with pytest.raises(_RetryRequested):
        audit_tasks.detect_security_alert.run(str(current.id))

    assert len(retries) == 1
    assert retries[0]["countdown"] == 1
    assert retries[0]["exc"] is not failure
    assert secret_marker not in str(retries[0]["exc"])
    assert secret_marker not in caplog.text
    assert session.rollbacks == 1
    assert session.closed == 1


def test_security_alert_reconciliation_retries_without_exposing_failure_details(
    monkeypatch,
    caplog,
):
    session = _Session()
    secret_marker = "secret-marker-reconciliation-456"
    failure = RuntimeError(secret_marker)
    retries = []

    class _RetryRequested(Exception):
        pass

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        audit_tasks,
        "reconcile_security_alert_batch",
        lambda *args, **kwargs: (_ for _ in ()).throw(failure),
    )

    def request_retry(**kwargs):
        retries.append(kwargs)
        raise _RetryRequested

    monkeypatch.setattr(
        audit_tasks.reconcile_security_alerts,
        "retry",
        request_retry,
    )

    with pytest.raises(_RetryRequested):
        audit_tasks.reconcile_security_alerts.run()

    assert len(retries) == 1
    assert retries[0]["countdown"] == 1
    assert retries[0]["exc"] is not failure
    assert secret_marker not in str(retries[0]["exc"])
    assert secret_marker not in caplog.text
    assert session.rollbacks == 1
    assert session.closed == 1


def test_security_alert_reconciliation_task_is_registered_on_log_queue():
    task_name = "security_alert.reconcile"

    assert task_name in audit_tasks.celery_app.tasks
    route = audit_tasks.celery_app.amqp.router.route(
        {},
        task_name,
        args=[],
        kwargs={},
    )
    assert route["queue"].name == "log"


def test_security_alert_reconciliation_has_one_minute_beat_schedule():
    entries = [
        entry
        for entry in (audit_tasks.celery_app.conf.beat_schedule or {}).values()
        if entry.get("task") == "security_alert.reconcile"
    ]

    assert entries == [
        {
            "task": "security_alert.reconcile",
            "schedule": 60.0,
            "options": {"queue": "log"},
        }
    ]
