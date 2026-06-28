import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.gateway.services import team_service
from apps.gateway.services.team_service import TeamService
from apps.shared.audit.actions import AuditAction
from apps.shared.schemas.team import (
    ResourcePermissionGrantRequest,
    ResourcePermissionRevokeRequest,
    TeamCreateRequest,
)


class FakeQuery:
    def __init__(self, db):
        self.db = db

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.db.first_values.pop(0)


class FakeDb:
    def __init__(self, first_values=None):
        self.first_values = list(first_values or [])
        self.deleted = []
        self.committed = False

    def query(self, *args, **kwargs):
        return FakeQuery(self)

    def add(self, row):
        self.added = row

    def delete(self, row):
        self.deleted.append(row)

    def commit(self):
        self.committed = True

    def refresh(self, row):
        self.refreshed = row


def test_workflow_resource_manager_can_grant_permission(monkeypatch):
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    grantee_id = uuid.uuid4()
    permission_row = SimpleNamespace(id=uuid.uuid4(), auth_state="viewer")
    db = FakeDb(
        first_values=[
            SimpleNamespace(id=workflow_id, organization_id=organization_id),
            SimpleNamespace(id=uuid.uuid4()),
            permission_row,
        ]
    )
    user = SimpleNamespace(id=uuid.uuid4())
    events = []

    monkeypatch.setattr(team_service, "has_organization_manager_permission", lambda *a: False)
    monkeypatch.setattr(
        team_service,
        "get_effective_workflow_auth_state",
        lambda *a, **k: "manager",
    )
    monkeypatch.setattr(team_service, "record_audit", lambda **event: events.append(event))

    row = TeamService.grant_resource_permission(
        db,
        user,
        ResourcePermissionGrantRequest(
            organization_id=organization_id,
            resource_type="workflow",
            resource_id=workflow_id,
            grantee_type="user",
            grantee_id=grantee_id,
            auth_state="builder",
        ),
    )

    assert row is permission_row
    assert row.auth_state == "builder"
    assert db.committed is True
    assert events[0]["action"] == AuditAction.PERMISSION_GRANT
    assert events[0]["metadata"]["grant_subject_type"] == "user"
    assert events[0]["metadata"]["grant_subject_id"] == str(grantee_id)
    assert events[0]["metadata"]["resource_type"] == "workflow"
    assert events[0]["metadata"]["auth_state"] == "builder"


def test_user_grant_requires_grantee_organization_membership(monkeypatch):
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    grantee_id = uuid.uuid4()
    db = FakeDb(
        first_values=[
            SimpleNamespace(id=workflow_id, organization_id=organization_id),
            None,
        ]
    )
    user = SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(team_service, "has_organization_manager_permission", lambda *a: True)

    with pytest.raises(HTTPException) as exc_info:
        TeamService.grant_resource_permission(
            db,
            user,
            ResourcePermissionGrantRequest(
                organization_id=organization_id,
                resource_type="workflow",
                resource_id=workflow_id,
                grantee_type="user",
                grantee_id=grantee_id,
                auth_state="viewer",
            ),
        )

    assert exc_info.value.status_code == 400


def test_team_grant_rejects_inactive_team(monkeypatch):
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    team_id = uuid.uuid4()
    db = FakeDb(
        first_values=[
            SimpleNamespace(id=workflow_id, organization_id=organization_id),
            SimpleNamespace(
                id=team_id,
                organization_id=organization_id,
                is_active=False,
            ),
        ]
    )
    user = SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(team_service, "has_organization_manager_permission", lambda *a: True)

    with pytest.raises(HTTPException) as exc_info:
        TeamService.grant_resource_permission(
            db,
            user,
            ResourcePermissionGrantRequest(
                organization_id=organization_id,
                resource_type="workflow",
                resource_id=workflow_id,
                grantee_type="team",
                grantee_id=team_id,
                auth_state="viewer",
            ),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Team is inactive"


def test_llm_resource_manager_can_revoke_permission(monkeypatch):
    organization_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    grantee_id = uuid.uuid4()
    permission_row = SimpleNamespace(id=uuid.uuid4())
    db = FakeDb(
        first_values=[
            SimpleNamespace(id=credential_id, organization_id=organization_id),
            permission_row,
        ]
    )
    user = SimpleNamespace(id=uuid.uuid4())
    events = []

    monkeypatch.setattr(team_service, "has_organization_manager_permission", lambda *a: False)
    monkeypatch.setattr(
        team_service,
        "get_effective_llm_credential_auth_state",
        lambda *a, **k: "manager",
    )
    monkeypatch.setattr(team_service, "record_audit", lambda **event: events.append(event))

    result = TeamService.revoke_resource_permission(
        db,
        user,
        ResourcePermissionRevokeRequest(
            organization_id=organization_id,
            resource_type="llm_credential",
            resource_id=credential_id,
            grantee_type="user",
            grantee_id=grantee_id,
        ),
    )

    assert result == {"status": "revoked"}
    assert db.deleted == [permission_row]
    assert db.committed is True
    assert events[0]["action"] == AuditAction.PERMISSION_REVOKE
    assert events[0]["metadata"]["grant_subject_type"] == "user"
    assert events[0]["metadata"]["grant_subject_id"] == str(grantee_id)
    assert events[0]["metadata"]["resource_type"] == "llm_credential"


def test_team_create_still_requires_organization_manager(monkeypatch):
    organization_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4())
    denied = []

    monkeypatch.setattr(team_service, "has_organization_manager_permission", lambda *a: False)
    monkeypatch.setattr(
        team_service,
        "record_permission_denied",
        lambda *args, **kwargs: denied.append(args),
    )

    with pytest.raises(HTTPException) as exc_info:
        TeamService.create_team(
            FakeDb(),
            user,
            TeamCreateRequest(organization_id=organization_id, name="Builders"),
        )

    assert exc_info.value.status_code == 403
    assert denied[0][1] == "organization"
