from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from apps.shared.db.models.audit_log import AuditLog
from sqlalchemy.exc import IntegrityError


def _module():
    return importlib.import_module("apps.shared.services.audit_event_outbox")


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def with_for_update(self, **kwargs):
        return self

    def one_or_none(self):
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.flushes = 0

    def query(self, model):
        return _Query(self.rows)

    def flush(self):
        self.flushes += 1


class _ProcessorDb:
    def __init__(self, events):
        self.events = events

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")


def _leased_event(*, attempt_count=1):
    now = datetime(2026, 7, 16, 3, 0, tzinfo=timezone.utc)
    audit_id = uuid4()
    return SimpleNamespace(
        id=uuid4(),
        payload={
            "id": str(audit_id),
            "occurred_at": now.isoformat(),
            "actor_id": str(uuid4()),
            "actor_type": "user",
            "category": "action",
            "action": "permission.denied",
            "target_type": "workflow",
            "target_id": str(uuid4()),
            "status": "failure",
            "audit_metadata": {"organization_id": str(uuid4())},
        },
        status="leased",
        owner_token="worker-1",
        lease_expires_at=now + timedelta(minutes=5),
        attempt_count=attempt_count,
        max_attempts=5,
        retryable=True,
        next_retry_at=None,
        safe_reason_code=None,
        delivered_at=None,
        dead_lettered_at=None,
        updated_at=None,
    )


def test_retry_is_scheduled_then_fifth_failure_is_dead_lettered():
    module = _module()
    now = datetime(2026, 7, 16, 3, 0, tzinfo=timezone.utc)
    event = _leased_event()
    service = module.AuditEventOutboxService(_Db([event]))

    assert service.mark_retry_or_dead_letter(
        event,
        owner_token="worker-1",
        safe_reason_code="audit.persistence_failed",
        now=now,
        retry_after_seconds=60,
    ) is True
    assert event.status == "retry_scheduled"
    assert event.next_retry_at == now + timedelta(seconds=60)
    assert event.owner_token is None
    assert event.lease_expires_at is None

    event.status = "leased"
    event.owner_token = "worker-1"
    event.attempt_count = 5
    assert service.mark_retry_or_dead_letter(
        event,
        owner_token="worker-1",
        safe_reason_code="audit.persistence_failed",
        now=now,
    ) is True
    assert event.status == "dead_lettered"
    assert event.next_retry_at is None
    assert event.dead_lettered_at == now


def test_stale_owner_cannot_overwrite_terminal_state():
    module = _module()
    now = datetime(2026, 7, 16, 3, 0, tzinfo=timezone.utc)
    event = _leased_event(attempt_count=2)
    event.status = "succeeded"
    event.owner_token = None
    event.delivered_at = now
    service = module.AuditEventOutboxService(_Db())

    assert service.mark_succeeded(
        event,
        owner_token="stale-worker",
        now=now + timedelta(minutes=1),
    ) is False
    assert service.mark_retry_or_dead_letter(
        event,
        owner_token="stale-worker",
        safe_reason_code="audit.persistence_failed",
        now=now + timedelta(minutes=1),
    ) is False
    assert event.status == "succeeded"
    assert event.delivered_at == now


def test_processor_commits_lease_then_audit_and_success_together(monkeypatch):
    module = _module()
    event = _leased_event()
    events = []

    class Outbox:
        def __init__(self, db):
            pass

        def recover_stale_leases(self):
            return 1

        def lease_due_events(self, *, owner_token, limit):
            events.append("lease")
            return [event]

        def mark_succeeded(self, row, *, owner_token):
            assert row is event
            events.append("succeeded")
            return True

        def mark_retry_or_dead_letter(self, *args, **kwargs):
            raise AssertionError("successful persistence must not retry")

    monkeypatch.setattr(module, "AuditEventOutboxService", Outbox)
    audit_id = uuid4()
    processor = module.AuditEventOutboxProcessor(
        _ProcessorDb(events),
        persist_audit=lambda db, payload: (
            events.append("persist"),
            audit_id,
        )[1],
        after_commit=lambda persisted_id: events.append(("dispatch", persisted_id)),
    )

    result = processor.process_due_events(owner_token="worker-1", limit=10)

    assert result.processed_count == 1
    assert result.recovered_count == 1
    assert events == [
        "lease",
        "commit",
        "persist",
        "succeeded",
        "commit",
        ("dispatch", audit_id),
    ]


def test_processor_converts_persistence_error_to_safe_retry(monkeypatch):
    module = _module()
    event = _leased_event()
    events = []

    class Outbox:
        def __init__(self, db):
            pass

        def recover_stale_leases(self):
            return 0

        def lease_due_events(self, *, owner_token, limit):
            events.append("lease")
            return [event]

        def mark_succeeded(self, *args, **kwargs):
            raise AssertionError("failed persistence must not succeed")

        def mark_retry_or_dead_letter(
            self, row, *, owner_token, safe_reason_code
        ):
            assert row is event
            assert owner_token == "worker-1"
            events.append(("retry", safe_reason_code))
            return True

    monkeypatch.setattr(module, "AuditEventOutboxService", Outbox)
    secret = "raw-database-secret"

    def fail(db, payload):
        events.append("persist")
        raise RuntimeError(secret)

    result = module.AuditEventOutboxProcessor(
        _ProcessorDb(events),
        persist_audit=fail,
    ).process_due_events(owner_token="worker-1")

    assert result.processed_count == 0
    assert events == [
        "lease",
        "commit",
        "persist",
        "rollback",
        ("retry", "audit.persistence_failed"),
        "commit",
    ]
    assert secret not in events[4][1]


def test_processor_treats_concurrent_legacy_insert_as_idempotent_success(
    monkeypatch,
):
    module = _module()
    event = _leased_event()
    events = []

    class Db(_ProcessorDb):
        def get(self, model, identity):
            assert model is AuditLog
            assert identity == uuid4_value
            return SimpleNamespace(id=identity)

    class Outbox:
        def __init__(self, db):
            pass

        def recover_stale_leases(self):
            return 0

        def lease_due_events(self, *, owner_token, limit):
            return [event]

        def mark_succeeded(self, row, *, owner_token):
            assert owner_token == "worker-1"
            events.append("succeeded")
            return True

    uuid4_value = module.audit_id_from_payload(event.payload)
    monkeypatch.setattr(module, "AuditEventOutboxService", Outbox)

    def lose_insert_race(db, payload):
        events.append("persist")
        raise IntegrityError("insert", {}, RuntimeError("duplicate"))

    result = module.AuditEventOutboxProcessor(
        Db(events),
        persist_audit=lose_insert_race,
        after_commit=lambda persisted_id: events.append(("dispatch", persisted_id)),
    ).process_due_events(owner_token="worker-1")

    assert result.processed_count == 1
    assert events == [
        "commit",
        "persist",
        "rollback",
        "succeeded",
        "commit",
        ("dispatch", uuid4_value),
    ]


def test_after_commit_failure_does_not_undo_persisted_audit(monkeypatch):
    module = _module()
    event = _leased_event()
    events = []

    class Outbox:
        def __init__(self, db):
            pass

        def recover_stale_leases(self):
            return 0

        def lease_due_events(self, *, owner_token, limit):
            return [event]

        def mark_succeeded(self, row, *, owner_token):
            return True

    monkeypatch.setattr(module, "AuditEventOutboxService", Outbox)

    def fail_dispatch(audit_id):
        events.append("dispatch")
        raise RuntimeError("raw-redis-secret")

    result = module.AuditEventOutboxProcessor(
        _ProcessorDb(events),
        persist_audit=lambda db, payload: uuid4(),
        after_commit=fail_dispatch,
    ).process_due_events(owner_token="worker-1")

    assert result.processed_count == 1
    assert events == ["commit", "commit", "dispatch"]


def test_payload_is_mapped_to_audit_log_with_fixed_id():
    module = _module()
    event = _leased_event()

    audit = module.build_audit_log(event.payload)

    assert str(audit.id) == event.payload["id"]
    assert audit.action == "permission.denied"
    assert audit.actor_type == "user"
    assert audit.category == "action"
    assert audit.status == "failure"
    assert audit.audit_metadata == event.payload["audit_metadata"]
