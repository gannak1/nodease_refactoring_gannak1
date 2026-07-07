"""Red/green tests for budget alert recipient resolution (BGA-REQ-020~022).

`resolve_alert_recipients(db, workflow, organization)`는 관리자 판정을 권한 경계
(`has_organization_manager_permission`)로, 제작자 접근을 `has_organization_scope_access`로
재사용한다. 후보군에는 membership row 없이 `organization.created_by/managed_by`로
manager로 인정되는 owner 경로가 포함되어야 한다.

권한 함수는 monkeypatch로 대체해, 이 유닛은 (1) 후보군 산출(멤버십 + owner 필드)과
(2) 경계 함수로의 위임을 검증한다. 실제 권한 판정은 permissions 테스트가 담당한다.

대응 문서: docs/features/budget-alerts/test_cases.md
  - Unit Tests > 수신자 산출 `resolve_alert_recipients`
  - Acceptance Criteria AC-4
  - Boundary Cases > 수신자 경계
"""

import uuid
from types import SimpleNamespace

import pytest

from apps.shared.services import budget_alerts


def _org(created_by=None, managed_by=None, member_ids=()):
    return SimpleNamespace(
        id=uuid.uuid4(),
        created_by=created_by,
        managed_by=managed_by,
        memberships=[SimpleNamespace(user_id=uid) for uid in member_ids],
    )


def _wf(created_by, org):
    return SimpleNamespace(created_by=created_by, organization_id=org.id)


@pytest.fixture
def patch_perms(monkeypatch):
    def _apply(managers=(), scope=()):
        managers = set(managers)
        scope = set(scope)
        monkeypatch.setattr(
            budget_alerts,
            "has_organization_manager_permission",
            lambda db, uid, org_id: uid in managers,
        )
        monkeypatch.setattr(
            budget_alerts,
            "has_organization_scope_access",
            lambda db, uid, org_id: uid in scope,
        )

    return _apply


def test_creator_and_all_managers(patch_perms):
    u0, u1, u2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    org = _org(member_ids=[u0, u1, u2])
    wf = _wf(u0, org)
    patch_perms(managers={u1, u2}, scope={u0, u1, u2})
    assert budget_alerts.resolve_alert_recipients(object(), wf, org) == {u0, u1, u2}


def test_creator_is_manager_deduped(patch_perms):
    u0, u1 = uuid.uuid4(), uuid.uuid4()
    org = _org(member_ids=[u0, u1])
    wf = _wf(u0, org)
    patch_perms(managers={u0, u1}, scope={u0, u1})
    result = budget_alerts.resolve_alert_recipients(object(), wf, org)
    assert result == {u0, u1}
    assert len(result) == 2


def test_only_creator_when_no_managers(patch_perms):
    # 관리자 0명: 제작자만. 다른 member는 (관리자도 제작자도 아니므로) 제외.
    u0, u1 = uuid.uuid4(), uuid.uuid4()
    org = _org(member_ids=[u0, u1])
    wf = _wf(u0, org)
    patch_perms(managers=set(), scope={u0, u1})
    assert budget_alerts.resolve_alert_recipients(object(), wf, org) == {u0}


def test_departed_creator_excluded(patch_perms):
    # 제작자가 조직 접근 없음(scope False) → 제외, 관리자만.
    u0, u1 = uuid.uuid4(), uuid.uuid4()
    org = _org(member_ids=[u1])
    wf = _wf(u0, org)
    patch_perms(managers={u1}, scope={u1})
    assert budget_alerts.resolve_alert_recipients(object(), wf, org) == {u1}


def test_owner_via_managed_by_without_membership_is_recipient(patch_perms):
    # 리뷰 케이스: membership row 없는 managed_by owner도 관리자 수신자에 포함.
    owner = uuid.uuid4()
    creator = uuid.uuid4()
    org = _org(managed_by=owner, member_ids=[creator])  # owner는 membership 없음
    wf = _wf(creator, org)
    patch_perms(managers={owner}, scope={creator, owner})
    result = budget_alerts.resolve_alert_recipients(object(), wf, org)
    assert owner in result
    assert result == {owner, creator}


def test_owner_via_created_by_without_membership_is_recipient(patch_perms):
    owner = uuid.uuid4()
    creator = uuid.uuid4()
    org = _org(created_by=owner, member_ids=[creator])
    wf = _wf(creator, org)
    patch_perms(managers={owner}, scope={creator, owner})
    result = budget_alerts.resolve_alert_recipients(object(), wf, org)
    assert owner in result


def test_non_manager_owner_excluded(patch_perms):
    # owner 후보라도 권한 경계가 manager로 인정하지 않으면(멤버십이 member로 우선) 제외.
    owner = uuid.uuid4()
    creator = uuid.uuid4()
    org = _org(managed_by=owner, member_ids=[owner, creator])
    wf = _wf(creator, org)
    patch_perms(managers=set(), scope={creator, owner})
    result = budget_alerts.resolve_alert_recipients(object(), wf, org)
    assert owner not in result
    assert result == {creator}


def test_large_manager_fanout(patch_perms):
    creator = uuid.uuid4()
    managers = {uuid.uuid4() for _ in range(50)}
    org = _org(member_ids=[creator, *managers])
    wf = _wf(creator, org)
    patch_perms(managers=managers, scope={creator, *managers})
    result = budget_alerts.resolve_alert_recipients(object(), wf, org)
    assert result == {creator, *managers}
    assert len(result) == 51
