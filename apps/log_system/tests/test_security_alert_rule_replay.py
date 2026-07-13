from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class _AuditEvent:
    id: UUID
    occurred_at: datetime
    actor_id: UUID
    actor_type: str
    category: str
    action: str
    target_type: str | None
    target_id: str | None
    status: str
    audit_metadata: dict[str, Any]


_NOW = datetime(2026, 7, 13, 0, 0, tzinfo=timezone.utc)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _denial(*, index: int, actor_id: UUID, organization_id: UUID) -> _AuditEvent:
    return _AuditEvent(
        id=uuid4(),
        occurred_at=_NOW + timedelta(seconds=index * 30),
        actor_id=actor_id,
        actor_type="user",
        category="action",
        action="permission.denied",
        target_type="workflow",
        target_id=str(uuid4()),
        status="failure",
        audit_metadata={"organization_id": str(organization_id)},
    )


def test_replay_reports_rule_matches_without_mutating_events():
    from apps.shared.services.security_alert_rule_replay import (
        replay_security_alert_rules,
    )

    actor_id = uuid4()
    organization_id = uuid4()
    events = [
        _denial(index=index, actor_id=actor_id, organization_id=organization_id)
        for index in range(5)
    ]
    before = [event.audit_metadata.copy() for event in events]

    result = replay_security_alert_rules(
        events,
        activation_started_at=_NOW - timedelta(minutes=1),
        evaluation_started_at=_NOW,
        evaluation_ended_at=_NOW + timedelta(minutes=5),
    )

    assert result.evaluated_event_count == 5
    assert result.matched_event_count == 1
    assert result.detection_count == 2
    assert result.detections_by_rule == {
        "multi_resource_permission_probe": 1,
        "repeated_permission_denied": 1,
        "repeated_policy_block": 0,
    }
    assert result.safe_dict() == {
        "dry_run": True,
        "evaluated_event_count": 5,
        "matched_event_count": 1,
        "detection_count": 2,
        "detections_by_rule": {
            "multi_resource_permission_probe": 1,
            "repeated_permission_denied": 1,
            "repeated_policy_block": 0,
        },
    }
    assert [event.audit_metadata for event in events] == before


def test_replay_uses_lookback_events_but_only_counts_requested_period():
    from apps.shared.services.security_alert_rule_replay import (
        replay_security_alert_rules,
    )

    actor_id = uuid4()
    organization_id = uuid4()
    events = [
        _denial(index=index, actor_id=actor_id, organization_id=organization_id)
        for index in range(5)
    ]
    evaluation_started_at = events[-1].occurred_at

    result = replay_security_alert_rules(
        events,
        activation_started_at=_NOW - timedelta(minutes=1),
        evaluation_started_at=evaluation_started_at,
        evaluation_ended_at=evaluation_started_at + timedelta(seconds=1),
    )

    assert result.evaluated_event_count == 1
    assert result.matched_event_count == 1
    assert result.detection_count == 2


def test_replay_cli_can_run_directly_from_repository_root():
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/replay_security_alert_rules.py",
            "--help",
        ],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--organization-id" in result.stdout


def test_replay_cli_is_read_only_and_prints_only_safe_aggregates(
    monkeypatch,
    capsys,
):
    from scripts import replay_security_alert_rules as command

    actor_id = uuid4()
    organization_id = uuid4()
    events = [
        _denial(index=index, actor_id=actor_id, organization_id=organization_id)
        for index in range(5)
    ]

    class _Query:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, value):
            assert value == 101
            return self

        def all(self):
            return events

    class _Session:
        def __init__(self):
            self.closed = False

        def query(self, model):
            return _Query()

        def close(self):
            self.closed = True

    session = _Session()
    monkeypatch.setattr(command, "SessionLocal", lambda: session)

    exit_code = command.main(
        [
            "--organization-id",
            str(organization_id),
            "--start-at",
            _NOW.isoformat(),
            "--end-at",
            (_NOW + timedelta(minutes=5)).isoformat(),
            "--limit",
            "100",
        ]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert session.closed is True
    assert payload == {
        "detection_count": 2,
        "detections_by_rule": {
            "multi_resource_permission_probe": 1,
            "repeated_permission_denied": 1,
            "repeated_policy_block": 0,
        },
        "dry_run": True,
        "evaluated_event_count": 5,
        "loaded_event_count": 5,
        "matched_event_count": 1,
        "truncated": False,
    }
    assert str(actor_id) not in output
    assert all(event.target_id not in output for event in events)
