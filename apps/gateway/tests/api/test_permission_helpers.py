import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.gateway.auth import permissions
from apps.gateway.auth.permissions import ensure_workflow_permission
from apps.shared.audit.actions import AuditAction


class FakeQuery:
    def __init__(self, workflow):
        self.workflow = workflow

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.workflow


class FakeDb:
    def __init__(self, workflow):
        self.workflow = workflow

    def query(self, *args, **kwargs):
        return FakeQuery(self.workflow)


def test_workflow_permission_denied_records_permission_audit(monkeypatch):
    workflow = SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4())
    user = SimpleNamespace(id=uuid.uuid4())
    events = []

    monkeypatch.setattr(
        permissions,
        "get_effective_workflow_auth_state",
        lambda db, user_id, workflow_id, organization_id=None: "viewer",
    )
    monkeypatch.setattr(
        permissions,
        "has_workflow_permission",
        lambda db, user_id, workflow_id, action, organization_id=None: False,
    )
    monkeypatch.setattr(
        permissions,
        "has_organization_scope_access",
        lambda db, user_id, organization_id: True,
    )
    monkeypatch.setattr(
        permissions,
        "record_audit",
        lambda **event: events.append(event),
    )

    with pytest.raises(HTTPException) as exc_info:
        ensure_workflow_permission(FakeDb(workflow), user, workflow.id, "write")

    assert exc_info.value.status_code == 403
    assert getattr(exc_info.value, "audit_recorded", False) is True
    assert events[0]["action"] == AuditAction.PERMISSION_DENIED
    assert events[0]["target_type"] == "workflow"
    assert events[0]["target_id"] == workflow.id
    assert events[0]["status"] == "failure"
    assert events[0]["metadata"]["policy_result"] == "deny"
    assert events[0]["metadata"]["resource_type"] == "workflow"
    assert events[0]["metadata"]["resource_id"] == str(workflow.id)
    assert events[0]["metadata"]["required_permission"] == "write"
    assert events[0]["metadata"]["permission_action"] == "write"
    assert events[0]["metadata"]["effective_auth_state"] == "viewer"


def test_workflow_permission_denied_outside_organization_scope_is_404(monkeypatch):
    workflow = SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4())
    user = SimpleNamespace(id=uuid.uuid4())
    events = []

    monkeypatch.setattr(
        permissions,
        "get_effective_workflow_auth_state",
        lambda db, user_id, workflow_id, organization_id=None: "none",
    )
    monkeypatch.setattr(
        permissions,
        "has_workflow_permission",
        lambda db, user_id, workflow_id, action, organization_id=None: False,
    )
    monkeypatch.setattr(
        permissions,
        "has_organization_scope_access",
        lambda db, user_id, organization_id: False,
    )
    monkeypatch.setattr(
        permissions,
        "record_audit",
        lambda **event: events.append(event),
    )

    with pytest.raises(HTTPException) as exc_info:
        ensure_workflow_permission(FakeDb(workflow), user, workflow.id, "read")

    assert exc_info.value.status_code == 404
    assert getattr(exc_info.value, "audit_recorded", False) is False
    assert events == []
