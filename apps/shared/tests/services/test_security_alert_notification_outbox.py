from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4


def _module():
    return importlib.import_module(
        "apps.shared.services.security_alert_notification_outbox"
    )


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def one_or_none(self):
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self):
        self.rows = []
        self.flushes = 0

    def query(self, model):
        return _Query(self.rows)

    def add(self, row):
        self.rows.append(row)

    def flush(self):
        self.flushes += 1


def test_enqueue_is_idempotent_and_stores_no_notification_payload():
    module = _module()
    db = _Db()
    service = module.SecurityAlertNotificationOutboxService(db)
    organization_id = uuid4()

    first = service.enqueue(
        organization_id=organization_id,
        idempotency_key="audit:123:notifications.changed",
    )
    second = service.enqueue(
        organization_id=organization_id,
        idempotency_key="audit:123:notifications.changed",
    )

    assert second is first
    assert len(db.rows) == 1
    assert first.organization_id == organization_id
    assert first.event_type == "notifications.changed"
    assert first.status == "pending"
    assert first.max_attempts == 5
    assert not hasattr(first, "payload")
    assert not hasattr(first, "recipient_ids")


def test_retry_is_scheduled_then_fifth_failure_is_dead_lettered():
    module = _module()
    now = datetime(2026, 7, 13, 5, 0, tzinfo=timezone.utc)
    service = module.SecurityAlertNotificationOutboxService(_Db())
    event = SimpleNamespace(
        status="leased",
        owner_token="worker-1",
        lease_expires_at=now + timedelta(minutes=5),
        attempt_count=1,
        max_attempts=5,
        retryable=True,
        next_retry_at=None,
        safe_reason_code=None,
        delivered_at=None,
        dead_lettered_at=None,
        updated_at=None,
    )

    service.mark_retry_or_dead_letter(
        event,
        safe_reason_code="notification.delivery_failed",
        now=now,
        retry_after_seconds=60,
    )

    assert event.status == "retry_scheduled"
    assert event.next_retry_at == now + timedelta(seconds=60)
    assert event.safe_reason_code == "notification.delivery_failed"
    assert event.owner_token is None
    assert event.lease_expires_at is None

    event.status = "leased"
    event.attempt_count = 5
    service.mark_retry_or_dead_letter(
        event,
        safe_reason_code="notification.delivery_failed",
        now=now,
    )

    assert event.status == "dead_lettered"
    assert event.next_retry_at is None
    assert event.dead_lettered_at == now


def test_processor_delivers_current_manager_refresh_and_marks_success(monkeypatch):
    module = _module()
    organization_id = uuid4()
    event = SimpleNamespace(
        organization_id=organization_id,
        event_type="notifications.changed",
    )
    succeeded = []

    class Outbox:
        def __init__(self, db):
            self.db = db

        def recover_stale_leases(self):
            return 0

        def lease_due_events(self, *, owner_token, limit):
            assert owner_token == "worker-1"
            return [event]

        def mark_succeeded(self, row):
            succeeded.append(row)

        def mark_retry_or_dead_letter(self, row, *, safe_reason_code):
            raise AssertionError(safe_reason_code)

    monkeypatch.setattr(module, "SecurityAlertNotificationOutboxService", Outbox)
    delivered = []
    db = object()
    processor = module.SecurityAlertNotificationOutboxProcessor(
        db,
        deliver=lambda scoped_db, scoped_org_id: delivered.append(
            (scoped_db, scoped_org_id)
        ),
    )

    result = processor.process_due_events(owner_token="worker-1", limit=10)

    assert result.processed_count == 1
    assert result.recovered_count == 0
    assert delivered == [(db, organization_id)]
    assert succeeded == [event]


def test_processor_converts_delivery_exception_to_safe_retry_reason(monkeypatch):
    module = _module()
    event = SimpleNamespace(
        organization_id=uuid4(),
        event_type="notifications.changed",
    )
    failed = []

    class Outbox:
        def __init__(self, db):
            pass

        def recover_stale_leases(self):
            return 0

        def lease_due_events(self, *, owner_token, limit):
            return [event]

        def mark_succeeded(self, row):
            raise AssertionError("failure must not be marked as succeeded")

        def mark_retry_or_dead_letter(self, row, *, safe_reason_code):
            failed.append((row, safe_reason_code))

    monkeypatch.setattr(module, "SecurityAlertNotificationOutboxService", Outbox)
    secret = "raw-redis-secret"

    def fail_delivery(db, organization_id):
        raise RuntimeError(secret)

    result = module.SecurityAlertNotificationOutboxProcessor(
        object(),
        deliver=fail_delivery,
    ).process_due_events(owner_token="worker-1")

    assert result.processed_count == 0
    assert failed == [(event, "notification.delivery_failed")]
    assert secret not in failed[0][1]
