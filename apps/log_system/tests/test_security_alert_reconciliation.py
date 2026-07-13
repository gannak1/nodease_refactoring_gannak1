from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID


@dataclass(frozen=True)
class _Audit:
    id: UUID
    occurred_at: datetime


@dataclass
class _Watermark:
    activation_started_at: datetime
    cursor_occurred_at: datetime | None = None
    cursor_audit_log_id: UUID | None = None


class _Repository:
    def __init__(self, *, watermark: _Watermark, audits: list[_Audit]):
        self.watermark = watermark
        self.audits = audits
        self.scan_starts = []
        self.processed_ids = set()
        self.process_attempts = []
        self.commits = 0

    def load_security_alert_watermark(self, *, processor_name):
        assert processor_name == "security-alert-v1"
        return self.watermark

    def scan_security_alert_audits(self, *, started_at):
        self.scan_starts.append(started_at)
        return sorted(
            (audit for audit in self.audits if audit.occurred_at >= started_at),
            key=lambda audit: (audit.occurred_at, audit.id),
        )

    def process_security_alert_audit(self, audit):
        self.process_attempts.append(audit.id)
        self.processed_ids.add(audit.id)

    def advance_security_alert_watermark(self, *, occurred_at, audit_log_id):
        self.watermark.cursor_occurred_at = occurred_at
        self.watermark.cursor_audit_log_id = audit_log_id

    def commit(self):
        self.commits += 1


_NOW = datetime(2026, 7, 12, 0, 10, tzinfo=timezone.utc)
_OVERLAP = timedelta(minutes=1)


def _id(number: int) -> UUID:
    return UUID(int=number)


def _audit(*, seconds: int, audit_id: int) -> _Audit:
    return _Audit(id=_id(audit_id), occurred_at=_NOW + timedelta(seconds=seconds))


def _reconcile(repository: _Repository):
    module = importlib.import_module(
        "apps.shared.services.security_alert_reconciliation"
    )
    return module.reconcile_security_alert_batch(
        repository,
        processor_name="security-alert-v1",
        overlap=_OVERLAP,
    )


def test_sal_tc_w010_reconciliation_recovers_missed_realtime_audits():
    audits = [_audit(seconds=index, audit_id=index + 1) for index in range(5)]
    repository = _Repository(
        watermark=_Watermark(activation_started_at=_NOW),
        audits=audits,
    )

    result = _reconcile(repository)

    assert repository.processed_ids == {audit.id for audit in audits}
    assert repository.watermark.cursor_occurred_at == audits[-1].occurred_at
    assert repository.watermark.cursor_audit_log_id == audits[-1].id
    assert repository.commits == 1
    assert result.processed_count == 5


def test_sal_tc_w011_overlap_reprocessing_does_not_duplicate_occurrences():
    audits = [_audit(seconds=index, audit_id=index + 1) for index in range(5)]
    repository = _Repository(
        watermark=_Watermark(activation_started_at=_NOW),
        audits=audits,
    )

    _reconcile(repository)
    _reconcile(repository)

    assert repository.processed_ids == {audit.id for audit in audits}
    assert len(repository.process_attempts) > len(repository.processed_ids)
    assert repository.commits == 2


def test_sal_tc_w012_same_timestamp_cursor_uses_audit_uuid_order():
    audits = [
        _audit(seconds=0, audit_id=3),
        _audit(seconds=0, audit_id=1),
        _audit(seconds=0, audit_id=2),
    ]
    repository = _Repository(
        watermark=_Watermark(
            activation_started_at=_NOW - timedelta(minutes=1),
            cursor_occurred_at=_NOW,
            cursor_audit_log_id=_id(2),
        ),
        audits=audits,
    )

    _reconcile(repository)

    assert repository.process_attempts == [_id(1), _id(2), _id(3)]
    assert repository.watermark.cursor_occurred_at == _NOW
    assert repository.watermark.cursor_audit_log_id == _id(3)


def test_sal_tc_w013_activation_boundary_excludes_only_older_audits():
    activation_started_at = _NOW
    before = _audit(seconds=-1, audit_id=1)
    exact = _audit(seconds=0, audit_id=2)
    after = _audit(seconds=1, audit_id=3)
    repository = _Repository(
        watermark=_Watermark(activation_started_at=activation_started_at),
        audits=[before, exact, after],
    )

    _reconcile(repository)

    assert repository.scan_starts == [activation_started_at]
    assert repository.processed_ids == {exact.id, after.id}
    assert before.id not in repository.process_attempts
