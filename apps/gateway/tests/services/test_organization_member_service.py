from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.operators import eq, in_op, is_

from apps.gateway.services.organization_member_service import OrganizationMemberService
from apps.shared.audit.actions import AuditAction
from apps.shared.db.models.audit_log import AuditLog
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.organization_membership import (
    ORGANIZATION_AUTH_MANAGER,
    ORGANIZATION_AUTH_MEMBER,
    ORGANIZATION_MEMBERSHIP_ACTIVE,
    ORGANIZATION_MEMBERSHIP_INVITED,
    ORGANIZATION_MEMBERSHIP_REMOVED,
    ORGANIZATION_MEMBERSHIP_SUSPENDED,
    OrganizationMembership,
)
from apps.shared.db.models.team import (
    TeamMembership,
    UserLLMPermission,
    UserWorkflowPermission,
)
from apps.shared.db.models.user import User
from apps.shared.schemas.organization_membership import (
    OrganizationMemberInviteRequest,
    OrganizationMemberUpdateRequest,
)


def test_list_active_organizations_uses_active_memberships_only():
    user = _user()
    active_org = _organization("Active", created_by=user.id)
    invited_org = _organization("Invited", created_by=user.id)
    db = _Db(
        users=[user],
        organizations=[active_org, invited_org],
        memberships=[
            _membership(user, active_org, ORGANIZATION_MEMBERSHIP_ACTIVE),
            _membership(user, invited_org, ORGANIZATION_MEMBERSHIP_INVITED),
        ],
    )

    result = OrganizationMemberService.list_active_organizations(db, user)

    assert [item.id for item in result] == [active_org.id]


def test_list_organization_memberships_uses_active_and_invited_memberships():
    user = _user()
    active_org = _organization("Active", created_by=user.id)
    invited_org = _organization("Invited", created_by=user.id)
    removed_org = _organization("Removed", created_by=user.id)
    db = _Db(
        users=[user],
        organizations=[active_org, invited_org, removed_org],
        memberships=[
            _membership(user, active_org, ORGANIZATION_MEMBERSHIP_ACTIVE),
            _membership(user, invited_org, ORGANIZATION_MEMBERSHIP_INVITED),
            _membership(user, removed_org, ORGANIZATION_MEMBERSHIP_REMOVED),
        ],
    )

    result = OrganizationMemberService.list_organization_memberships(db, user)

    assert [item.id for item in result] == [active_org.id, invited_org.id]
    assert result[0].membership_state == ORGANIZATION_MEMBERSHIP_ACTIVE
    assert result[1].membership_state == ORGANIZATION_MEMBERSHIP_INVITED


def test_member_list_defaults_to_non_removed_and_filters_state(monkeypatch):
    manager = _user()
    member = _user()
    removed = _user()
    org = _organization("Acme", created_by=manager.id)
    db = _Db(
        users=[manager, member, removed],
        organizations=[org],
        memberships=[
            _membership(manager, org, auth_state=ORGANIZATION_AUTH_MANAGER),
            _membership(member, org, ORGANIZATION_MEMBERSHIP_SUSPENDED),
            _membership(removed, org, ORGANIZATION_MEMBERSHIP_REMOVED),
        ],
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: True,
    )

    default_result = OrganizationMemberService.list_members(db, manager, org.id)
    removed_result = OrganizationMemberService.list_members(
        db,
        manager,
        org.id,
        state=ORGANIZATION_MEMBERSHIP_REMOVED,
    )

    assert {item.user_id for item in default_result} == {manager.id, member.id}
    assert [item.user_id for item in removed_result] == [removed.id]


def test_invite_is_idempotent_and_reinvite_removed_records_audit(monkeypatch):
    manager = _user()
    target = _user()
    org = _organization("Acme", created_by=manager.id)
    removed_membership = _membership(
        target,
        org,
        ORGANIZATION_MEMBERSHIP_REMOVED,
        accepted_at=_now(),
        removed_at=_now(),
    )
    db = _Db(
        users=[manager, target],
        organizations=[org],
        memberships=[
            _membership(manager, org, auth_state=ORGANIZATION_AUTH_MANAGER),
            removed_membership,
        ],
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: True,
    )

    response = OrganizationMemberService.invite_member(
        db,
        manager,
        org.id,
        OrganizationMemberInviteRequest(user_id=target.id),
    )
    again = OrganizationMemberService.invite_member(
        db,
        manager,
        org.id,
        OrganizationMemberInviteRequest(user_id=target.id),
    )

    assert response.id == removed_membership.id
    assert response.membership_state == ORGANIZATION_MEMBERSHIP_INVITED
    assert removed_membership.accepted_at is None
    assert removed_membership.removed_at is None
    assert again.id == removed_membership.id
    assert _audit_actions(db) == [AuditAction.ORGANIZATION_INVITE]
    assert "email" not in str(db.audit_logs[0].audit_metadata).lower()


def test_accept_update_guards_and_state_transitions(monkeypatch):
    manager = _user()
    target = _user()
    org = _organization("Acme", created_by=manager.id)
    target_membership = _membership(target, org, ORGANIZATION_MEMBERSHIP_INVITED)
    db = _Db(
        users=[manager, target],
        organizations=[org],
        memberships=[
            _membership(manager, org, auth_state=ORGANIZATION_AUTH_MANAGER),
            target_membership,
        ],
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: True,
    )

    with pytest.raises(HTTPException) as forced_accept:
        OrganizationMemberService.update_member(
            db,
            manager,
            org.id,
            target.id,
            OrganizationMemberUpdateRequest(membership_state=ORGANIZATION_MEMBERSHIP_ACTIVE),
        )

    accepted = OrganizationMemberService.accept_invitation(db, target, org.id)
    suspended = OrganizationMemberService.update_member(
        db,
        manager,
        org.id,
        target.id,
        OrganizationMemberUpdateRequest(membership_state=ORGANIZATION_MEMBERSHIP_SUSPENDED),
    )

    assert forced_accept.value.status_code == 409
    assert accepted.membership_state == ORGANIZATION_MEMBERSHIP_ACTIVE
    assert suspended.membership_state == ORGANIZATION_MEMBERSHIP_SUSPENDED
    assert _audit_actions(db) == [
        AuditAction.ORGANIZATION_MEMBER_ACCEPT,
        AuditAction.ORGANIZATION_MEMBER_UPDATE,
    ]


def test_last_manager_and_self_remove_are_blocked(monkeypatch):
    manager = _user()
    other = _user()
    org = _organization("Acme", created_by=manager.id)
    db = _Db(
        users=[manager, other],
        organizations=[org],
        memberships=[
            _membership(manager, org, auth_state=ORGANIZATION_AUTH_MANAGER),
            _membership(other, org),
        ],
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: True,
    )

    with pytest.raises(HTTPException) as self_remove:
        OrganizationMemberService.remove_member(db, manager, org.id, manager.id)
    with pytest.raises(HTTPException) as last_manager:
        OrganizationMemberService.update_member(
            db,
            manager,
            org.id,
            manager.id,
            OrganizationMemberUpdateRequest(organization_auth_state=ORGANIZATION_AUTH_MEMBER),
        )

    assert self_remove.value.status_code == 400
    assert last_manager.value.status_code in {400, 409}


def test_last_manager_guard_blocks_demote_by_another_manager(monkeypatch):
    actor = _user()
    target = _user()
    org = _organization("Acme", created_by=actor.id)
    db = _Db(
        users=[actor, target],
        organizations=[org],
        memberships=[
            _membership(actor, org),
            _membership(target, org, auth_state=ORGANIZATION_AUTH_MANAGER),
        ],
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: True,
    )

    with pytest.raises(HTTPException) as last_manager:
        OrganizationMemberService.update_member(
            db,
            actor,
            org.id,
            target.id,
            OrganizationMemberUpdateRequest(organization_auth_state=ORGANIZATION_AUTH_MEMBER),
        )

    assert last_manager.value.status_code == 409
    assert db.for_update_calls == 1
    assert db.for_update_order_by_args == [(OrganizationMembership.id,)]


@pytest.mark.parametrize(
    "update_request",
    [
        OrganizationMemberUpdateRequest(membership_state=ORGANIZATION_MEMBERSHIP_ACTIVE),
        OrganizationMemberUpdateRequest(
            membership_state=ORGANIZATION_MEMBERSHIP_SUSPENDED
        ),
        OrganizationMemberUpdateRequest(organization_auth_state=ORGANIZATION_AUTH_MANAGER),
    ],
)
def test_removed_member_cannot_be_patched(monkeypatch, update_request):
    manager = _user()
    target = _user()
    org = _organization("Acme", created_by=manager.id)
    db = _Db(
        users=[manager, target],
        organizations=[org],
        memberships=[
            _membership(manager, org, auth_state=ORGANIZATION_AUTH_MANAGER),
            _membership(target, org, ORGANIZATION_MEMBERSHIP_REMOVED),
        ],
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: True,
    )

    with pytest.raises(HTTPException) as conflict:
        OrganizationMemberService.update_member(
            db,
            manager,
            org.id,
            target.id,
            update_request,
        )

    assert conflict.value.status_code == 409


def test_invited_member_cannot_be_suspended_with_patch(monkeypatch):
    manager = _user()
    target = _user()
    org = _organization("Acme", created_by=manager.id)
    db = _Db(
        users=[manager, target],
        organizations=[org],
        memberships=[
            _membership(manager, org, auth_state=ORGANIZATION_AUTH_MANAGER),
            _membership(target, org, ORGANIZATION_MEMBERSHIP_INVITED),
        ],
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: True,
    )

    with pytest.raises(HTTPException) as conflict:
        OrganizationMemberService.update_member(
            db,
            manager,
            org.id,
            target.id,
            OrganizationMemberUpdateRequest(
                membership_state=ORGANIZATION_MEMBERSHIP_SUSPENDED
            ),
        )

    assert conflict.value.status_code == 409


def test_update_rejects_removed_member(monkeypatch):
    manager = _user()
    target = _user()
    org = _organization("Acme", created_by=manager.id)
    db = _Db(
        users=[manager, target],
        organizations=[org],
        memberships=[
            _membership(manager, org, auth_state=ORGANIZATION_AUTH_MANAGER),
            _membership(target, org, ORGANIZATION_MEMBERSHIP_REMOVED),
        ],
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: True,
    )

    with pytest.raises(HTTPException) as conflict:
        OrganizationMemberService.update_member(
            db,
            manager,
            org.id,
            target.id,
            OrganizationMemberUpdateRequest(
                organization_auth_state=ORGANIZATION_AUTH_MANAGER
            ),
        )

    assert conflict.value.status_code == 409


def test_remove_member_soft_removes_and_cleans_permissions(monkeypatch):
    manager = _user()
    target = _user()
    second_manager = _user()
    org = _organization("Acme", created_by=manager.id)
    target_membership = _membership(target, org)
    db = _Db(
        users=[manager, target, second_manager],
        organizations=[org],
        memberships=[
            _membership(manager, org, auth_state=ORGANIZATION_AUTH_MANAGER),
            _membership(second_manager, org, auth_state=ORGANIZATION_AUTH_MANAGER),
            target_membership,
        ],
        team_memberships=[_team_membership(org.id, target.id)],
        workflow_permissions=[_user_workflow_permission(org.id, target.id)],
        llm_permissions=[_user_llm_permission(org.id, target.id)],
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: True,
    )

    response = OrganizationMemberService.remove_member(db, manager, org.id, target.id)

    assert response.status == "removed"
    assert response.removed_team_memberships == 1
    assert response.revoked_user_permissions.workflow == 1
    assert response.revoked_user_permissions.llm_credential == 1
    assert target_membership.membership_state == ORGANIZATION_MEMBERSHIP_REMOVED
    assert db.team_memberships == []
    assert db.workflow_permissions == []
    assert db.llm_permissions == []
    assert _audit_actions(db) == [
        AuditAction.ORGANIZATION_MEMBER_REMOVE,
        AuditAction.PERMISSION_REVOKE,
    ]
    assert "email" not in str(db.audit_logs[0].audit_metadata).lower()


def test_invite_conflict_and_not_found_cases(monkeypatch):
    manager = _user()
    suspended_user = _user()
    deactivated_user = _user()
    deactivated_user.deactivated_at = _now()
    org = _organization("Acme", created_by=manager.id)
    db = _Db(
        users=[manager, suspended_user, deactivated_user],
        organizations=[org],
        memberships=[
            _membership(manager, org, auth_state=ORGANIZATION_AUTH_MANAGER),
            _membership(suspended_user, org, ORGANIZATION_MEMBERSHIP_SUSPENDED),
        ],
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: True,
    )

    def _invite(user_id):
        return OrganizationMemberService.invite_member(
            db, manager, org.id, OrganizationMemberInviteRequest(user_id=user_id)
        )

    with pytest.raises(HTTPException) as suspended:
        _invite(suspended_user.id)
    with pytest.raises(HTTPException) as self_invite:
        _invite(manager.id)
    with pytest.raises(HTTPException) as deactivated:
        _invite(deactivated_user.id)
    with pytest.raises(HTTPException) as missing:
        _invite(uuid4())

    assert suspended.value.status_code == 409
    assert self_invite.value.status_code == 400
    assert deactivated.value.status_code == 404
    assert missing.value.status_code == 404
    assert db.audit_logs == []


def test_invite_conflict_on_flush_returns_409(monkeypatch):
    # 동시 invite로 unique 제약이 깨지면 INSERT(flush) 시점에 IntegrityError가 나고,
    # 이를 409로 변환하면서 audit/commit은 일어나지 않아야 한다.
    manager = _user()
    target = _user()
    org = _organization("Acme", created_by=manager.id)
    db = _Db(
        users=[manager, target],
        organizations=[org],
        memberships=[_membership(manager, org, auth_state=ORGANIZATION_AUTH_MANAGER)],
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: True,
    )

    def _raise_integrity_error():
        raise IntegrityError("INSERT", {}, Exception("duplicate"))

    monkeypatch.setattr(db, "flush", _raise_integrity_error)

    with pytest.raises(HTTPException) as conflict:
        OrganizationMemberService.invite_member(
            db, manager, org.id, OrganizationMemberInviteRequest(user_id=target.id)
        )

    assert conflict.value.status_code == 409
    assert db.audit_logs == []
    assert db.commits == 0


def test_accept_is_idempotent_when_already_active():
    user = _user()
    org = _organization("Acme", created_by=user.id)
    db = _Db(
        users=[user],
        organizations=[org],
        memberships=[_membership(user, org, ORGANIZATION_MEMBERSHIP_ACTIVE)],
    )

    response = OrganizationMemberService.accept_invitation(db, user, org.id)

    assert response.membership_state == ORGANIZATION_MEMBERSHIP_ACTIVE
    assert db.audit_logs == []
    assert db.commits == 0


@pytest.mark.parametrize(
    "state",
    [ORGANIZATION_MEMBERSHIP_SUSPENDED, ORGANIZATION_MEMBERSHIP_REMOVED],
)
def test_accept_rejects_suspended_or_removed(state):
    user = _user()
    org = _organization("Acme", created_by=user.id)
    db = _Db(
        users=[user],
        organizations=[org],
        memberships=[_membership(user, org, state)],
    )

    with pytest.raises(HTTPException) as conflict:
        OrganizationMemberService.accept_invitation(db, user, org.id)

    assert conflict.value.status_code == 409


def test_accept_missing_invitation_returns_404():
    user = _user()
    org = _organization("Acme", created_by=user.id)
    db = _Db(users=[user], organizations=[org], memberships=[])

    with pytest.raises(HTTPException) as missing:
        OrganizationMemberService.accept_invitation(db, user, org.id)

    assert missing.value.status_code == 404


def test_remove_is_idempotent_for_already_removed(monkeypatch):
    manager = _user()
    target = _user()
    org = _organization("Acme", created_by=manager.id)
    db = _Db(
        users=[manager, target],
        organizations=[org],
        memberships=[
            _membership(manager, org, auth_state=ORGANIZATION_AUTH_MANAGER),
            _membership(target, org, ORGANIZATION_MEMBERSHIP_REMOVED),
        ],
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: True,
    )

    response = OrganizationMemberService.remove_member(db, manager, org.id, target.id)

    assert response.status == "removed"
    assert response.removed_team_memberships == 0
    assert response.revoked_user_permissions.workflow == 0
    assert db.audit_logs == []
    assert db.commits == 0


@pytest.mark.parametrize(
    ("scope_access", "expected_status"),
    [(True, 403), (False, 404)],
)
def test_manager_gate_hides_or_forbids_non_manager(monkeypatch, scope_access, expected_status):
    user = _user()
    org = _organization("Acme", created_by=user.id)
    db = _Db(users=[user], organizations=[org], memberships=[])
    events = []
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_manager_permission",
        lambda *args: False,
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.has_organization_scope_access",
        lambda *args: scope_access,
    )
    monkeypatch.setattr(
        "apps.gateway.services.organization_member_service.record_audit",
        lambda **event: events.append(event),
    )

    with pytest.raises(HTTPException) as denied:
        OrganizationMemberService.list_members(db, user, org.id)

    assert denied.value.status_code == expected_status
    if scope_access:
        assert getattr(denied.value, "audit_recorded", False) is True
        assert events == [
            {
                "action": AuditAction.PERMISSION_DENIED,
                "category": "action",
                "actor_id": user.id,
                "actor_type": "user",
                "target_type": "organization",
                "target_id": org.id,
                "status": "failure",
                "metadata": {
                    "policy_result": "deny",
                    "resource_type": "organization",
                    "resource_id": str(org.id),
                    "required_permission": ORGANIZATION_AUTH_MANAGER,
                    "permission_action": "manage_members",
                    "effective_auth_state": ORGANIZATION_AUTH_MEMBER,
                },
            }
        ]
    else:
        assert getattr(denied.value, "audit_recorded", False) is False
        assert events == []


class _Db:
    def __init__(
        self,
        users=None,
        organizations=None,
        memberships=None,
        team_memberships=None,
        workflow_permissions=None,
        llm_permissions=None,
    ):
        self.users = users or []
        self.organizations = organizations or []
        self.memberships = memberships or []
        self.team_memberships = team_memberships or []
        self.workflow_permissions = workflow_permissions or []
        self.llm_permissions = llm_permissions or []
        self.audit_logs = []
        self.commits = 0
        self.for_update_calls = 0
        self.for_update_order_by_args = []

    def query(self, *models):
        if models == (Organization, OrganizationMembership):
            rows = [
                (organization, membership)
                for organization in self.organizations
                for membership in self.memberships
                if organization.id == membership.organization_id
            ]
            return _Query(rows, on_for_update=self._record_for_update)
        model = models[0]
        if model is Organization:
            return _Query(self.organizations, on_for_update=self._record_for_update)
        if model is User:
            return _Query(self.users, on_for_update=self._record_for_update)
        if model is OrganizationMembership:
            return _Query(self.memberships, on_for_update=self._record_for_update)
        if model is TeamMembership:
            return _Query(
                self.team_memberships,
                self.team_memberships,
                on_for_update=self._record_for_update,
            )
        if model is UserWorkflowPermission:
            return _Query(
                self.workflow_permissions,
                self.workflow_permissions,
                on_for_update=self._record_for_update,
            )
        if model is UserLLMPermission:
            return _Query(
                self.llm_permissions,
                self.llm_permissions,
                on_for_update=self._record_for_update,
            )
        return _Query([], on_for_update=self._record_for_update)

    def _record_for_update(self, order_by_args=()):
        # 실제 DB lock 대신 서비스가 with_for_update()를 호출했는지만 기록한다.
        self.for_update_calls += 1
        self.for_update_order_by_args.append(tuple(order_by_args))

    def add(self, row):
        if isinstance(row, AuditLog):
            self.audit_logs.append(row)
        elif isinstance(row, OrganizationMembership):
            self.memberships.append(row)

    def flush(self):
        for membership in self.memberships:
            if membership.id is None:
                membership.id = uuid4()

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def refresh(self, row):
        return row


class _Query:
    def __init__(self, items, backing=None, on_for_update=None):
        self.items = list(items)
        self.backing = backing
        self.filters = []
        self.on_for_update = on_for_update
        self.order_by_args = []

    def join(self, *args, **kwargs):
        return self

    def options(self, *args, **kwargs):
        return self

    def filter(self, *expressions):
        self.filters.extend(expressions)
        return self

    def order_by(self, *args):
        self.order_by_args.extend(args)
        return self

    def with_for_update(self):
        if self.on_for_update is not None:
            self.on_for_update(self.order_by_args)
        return self

    def all(self):
        return [item for item in self.items if self._matches(item)]

    def first(self):
        return next(iter(self.all()), None)

    def count(self):
        return len(self.all())

    def delete(self, synchronize_session=False):
        matches = self.all()
        if self.backing is not None:
            self.backing[:] = [item for item in self.backing if item not in matches]
        return len(matches)

    def _matches(self, item):
        return all(_matches_expression(item, expression) for expression in self.filters)


def _matches_expression(item, expression):
    if not hasattr(expression, "left"):
        return True
    value = _field_value(item, str(expression.left))
    if expression.operator is eq:
        return value == expression.right.value
    if expression.operator is is_:
        if str(expression.right).lower() == "null":
            return value is None
        return value is (str(expression.right) == "true")
    if expression.operator is in_op:
        return value in expression.right.value
    return True


def _field_value(item, field):
    if isinstance(item, tuple):
        organization, membership = item
        if field.startswith("organization."):
            return _field_value(organization, field)
        return _field_value(membership, field)
    mapping = {
        "organization.id": "id",
        "organization.is_active": "is_active",
        "users.id": "id",
        "users.deactivated_at": "deactivated_at",
        "organization_memberships.user_id": "user_id",
        "organization_memberships.organization_id": "organization_id",
        "organization_memberships.membership_state": "membership_state",
        "organization_memberships.organization_auth_state": "organization_auth_state",
        "team_memberships.grantee_organization_id": "grantee_organization_id",
        "team_memberships.user_id": "user_id",
        "user_workflow_permissions.grantee_organization_id": "grantee_organization_id",
        "user_workflow_permissions.user_id": "user_id",
        "user_llm_permissions.grantee_organization_id": "grantee_organization_id",
        "user_llm_permissions.user_id": "user_id",
    }
    return getattr(item, mapping[field])


def _user():
    return User(
        id=uuid4(),
        email=f"{uuid4()}@example.com",
        name="User",
        social_provider="local",
    )


def _organization(name, created_by):
    return Organization(
        id=uuid4(),
        name=name,
        created_by=created_by,
        is_active=True,
    )


def _membership(
    user,
    organization,
    membership_state=ORGANIZATION_MEMBERSHIP_ACTIVE,
    auth_state=ORGANIZATION_AUTH_MEMBER,
    accepted_at=None,
    removed_at=None,
):
    membership = OrganizationMembership(
        id=uuid4(),
        organization_id=organization.id,
        user_id=user.id,
        membership_state=membership_state,
        organization_auth_state=auth_state,
        invited_by=organization.created_by,
        invited_at=_now(),
        accepted_at=accepted_at,
        removed_at=removed_at,
        created_at=_now(),
        updated_at=_now(),
    )
    membership.user = user
    return membership


def _team_membership(organization_id, user_id):
    return TeamMembership(
        id=uuid4(),
        grantee_organization_id=organization_id,
        user_id=user_id,
        team_id=uuid4(),
        assigned_by=uuid4(),
    )


def _user_workflow_permission(organization_id, user_id):
    return UserWorkflowPermission(
        id=uuid4(),
        grantee_organization_id=organization_id,
        user_id=user_id,
        workflow_id=uuid4(),
        assigned_by=uuid4(),
        auth_state="viewer",
    )


def _user_llm_permission(organization_id, user_id):
    return UserLLMPermission(
        id=uuid4(),
        grantee_organization_id=organization_id,
        user_id=user_id,
        llm_credential_id=uuid4(),
        assigned_by=uuid4(),
        auth_state="viewer",
    )


def _now():
    return datetime.now(timezone.utc)


def _audit_actions(db):
    return [log.action for log in db.audit_logs]
