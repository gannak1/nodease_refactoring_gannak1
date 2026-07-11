from datetime import datetime, timezone
from operator import eq, ge, lt
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy.sql import operators as sqlalchemy_operators

from apps.shared.audit.actions import AuditAction
from apps.shared.db.models.audit_log import (
    ActorType,
    AuditCategory,
    AuditLog,
    AuditStatus,
)
from apps.shared.db.models.team import TeamAuditPermission


ADMIN_AUDIT_SERVICE = "apps.gateway.services.admin_audit_log_service"


def _service():
    from apps.gateway.services.admin_audit_log_service import (
        AdminAuditLogFilters,
        AdminAuditLogService,
    )

    return AdminAuditLogService, AdminAuditLogFilters


def _guard():
    from apps.gateway.services.admin_audit_log_service import AdminPermissionGuard

    return AdminPermissionGuard


def test_list_audit_logs_scopes_filters_and_sorts_descending(monkeypatch):
    AdminAuditLogService, AdminAuditLogFilters = _service()
    organization_id = uuid4()
    other_organization_id = uuid4()
    actor_id = uuid4()
    auditor_id = uuid4()
    newer_match = _audit_log(
        organization_id=organization_id,
        actor_id=actor_id,
        action="workflow.deploy",
        target_type="workflow",
        target_id="wf-1",
        status=AuditStatus.SUCCESS,
        occurred_at=datetime(2026, 7, 2, 9, tzinfo=timezone.utc),
    )
    older_match = _audit_log(
        organization_id=organization_id,
        actor_id=actor_id,
        action="workflow.deploy",
        target_type="workflow",
        target_id="wf-1",
        status=AuditStatus.SUCCESS,
        occurred_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
    )
    end_boundary = _audit_log(
        organization_id=organization_id,
        actor_id=actor_id,
        action="workflow.deploy",
        target_type="workflow",
        target_id="wf-1",
        status=AuditStatus.SUCCESS,
        occurred_at=datetime(2026, 7, 3, 0, tzinfo=timezone.utc),
    )
    wrong_action = _audit_log(
        organization_id=organization_id,
        actor_id=actor_id,
        action="workflow.create",
        target_type="workflow",
        target_id="wf-1",
        status=AuditStatus.SUCCESS,
        occurred_at=datetime(2026, 7, 2, 10, tzinfo=timezone.utc),
    )
    wrong_organization = _audit_log(
        organization_id=other_organization_id,
        actor_id=actor_id,
        action="workflow.deploy",
        target_type="workflow",
        target_id="wf-1",
        status=AuditStatus.SUCCESS,
        occurred_at=datetime(2026, 7, 2, 11, tzinfo=timezone.utc),
    )
    # FR-011 목록 조회는 조직 scope와 모든 검색 필터를 AND로 적용해야 한다.
    # endAt 경계 row와 다른 조직 row를 함께 넣어 누락/과다 노출을 잡는다.
    db = _AuditLogSession(
        [newer_match, older_match, end_boundary, wrong_action, wrong_organization]
    )
    # 이 테스트는 검색 쿼리 계약에 집중한다. audit reader 권한 검사는 별도 guard
    # 테스트에서 다루므로 여기서는 통과시킨다.
    monkeypatch.setattr(
        "apps.gateway.services.admin_audit_log_service.AdminPermissionGuard.require_audit_reader",
        lambda *args: None,
    )

    result = AdminAuditLogService.list_audit_logs(
        db,
        current_user=SimpleNamespace(id=auditor_id),
        organization_id=organization_id,
        filters=AdminAuditLogFilters(
            actor_id=actor_id,
            action="workflow.deploy",
            target_type="workflow",
            target_id="wf-1",
            status=AuditStatus.SUCCESS,
            start_at=datetime(2026, 7, 1, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 7, 3, 0, tzinfo=timezone.utc),
        ),
        page=1,
        limit=20,
    )

    assert result.total == 2
    assert [item.id for item in result.items] == [newer_match.id, older_match.id]
    assert db.query_for(AuditLog).offset_value == 0
    assert db.query_for(AuditLog).limit_value == 20


def test_resolve_period_treats_naive_datetime_as_kst_and_rejects_invalid_range():
    AdminAuditLogService, _ = _service()

    # 화면에서 timezone 없는 값을 보낼 수 있으므로 KST 기준으로 닫는다.
    period = AdminAuditLogService.resolve_period(
        start_at=datetime(2026, 7, 1, 9, 30),
        end_at=datetime(2026, 7, 2, 18, 0),
    )

    assert period.start_at == datetime(
        2026, 7, 1, 9, 30, tzinfo=ZoneInfo("Asia/Seoul")
    )
    assert period.end_at == datetime(
        2026, 7, 2, 18, 0, tzinfo=ZoneInfo("Asia/Seoul")
    )

    with pytest.raises(HTTPException) as exc:
        AdminAuditLogService.resolve_period(
            start_at=datetime(2026, 7, 2, 18, 0),
            end_at=datetime(2026, 7, 2, 18, 0),
        )

    assert exc.value.status_code == 400


def test_get_audit_log_detail_sanitizes_metadata_and_hides_cross_org(monkeypatch):
    AdminAuditLogService, _ = _service()
    organization_id = uuid4()
    other_organization_id = uuid4()
    auditor_id = uuid4()
    visible_log = _audit_log(
        organization_id=organization_id,
        actor_id=uuid4(),
        action=AuditAction.ORGANIZATION_MEMBER_REMOVE,
        target_type="organization_membership",
        target_id="membership-1",
        status=AuditStatus.SUCCESS,
        occurred_at=datetime(2026, 7, 2, 9, tzinfo=timezone.utc),
        audit_metadata={
            "organization_id": str(organization_id),
            "request_id": "req-1",
            "reason": "organization.member.remove",
            "summary": {"removed_team_memberships": 1},
            "raw_payload": {"prompt": "secret prompt"},
            "encrypted_config": "ciphertext",
            "nested": {"token": "secret-token"},
        },
    )
    # scope 밖 audit_log_id는 존재 여부를 숨겨야 하므로 404 계약을 함께 검증한다.
    cross_org_log = _audit_log(
        organization_id=other_organization_id,
        actor_id=uuid4(),
        action="workflow.deploy",
        target_type="workflow",
        target_id="wf-2",
        status=AuditStatus.SUCCESS,
        occurred_at=datetime(2026, 7, 2, 10, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "apps.gateway.services.admin_audit_log_service.AdminPermissionGuard.require_audit_reader",
        lambda *args: None,
    )

    detail = AdminAuditLogService.get_audit_log_detail(
        _AuditLogSession([visible_log, cross_org_log]),
        current_user=SimpleNamespace(id=auditor_id),
        organization_id=organization_id,
        audit_log_id=visible_log.id,
    )

    assert detail.id == visible_log.id
    assert detail.audit_metadata == {
        "organization_id": str(organization_id),
        "request_id": "req-1",
        "reason": "organization.member.remove",
        "summary": {"removed_team_memberships": 1},
    }

    with pytest.raises(HTTPException) as exc:
        AdminAuditLogService.get_audit_log_detail(
            _AuditLogSession([visible_log, cross_org_log]),
            current_user=SimpleNamespace(id=auditor_id),
            organization_id=organization_id,
            audit_log_id=cross_org_log.id,
        )

    assert exc.value.status_code == 404


def test_sanitize_audit_metadata_removes_secret_keys_recursively():
    AdminAuditLogService, _ = _service()

    # allowlist summary는 유지하되 raw payload와 secret 계열 key는 중첩되어도 제거한다.
    sanitized = AdminAuditLogService.sanitize_audit_metadata(
        {
            "organization_id": "org-1",
            "request_id": "req-1",
            "reason": "permission.denied",
            "payload": {"question": "raw user prompt"},
            "api_key": "sk-secret",
            "nested": {
                "summary": "kept",
                "authorization": "Bearer token",
                "child": {"password": "secret"},
            },
        }
    )

    assert sanitized == {
        "organization_id": "org-1",
        "request_id": "req-1",
        "reason": "permission.denied",
        "nested": {"summary": "kept", "child": {}},
    }


def test_detail_metadata_rejects_nested_or_malformed_typed_values(monkeypatch):
    AdminAuditLogService, _ = _service()
    organization_id = uuid4()
    log = _audit_log(
        organization_id=organization_id,
        actor_id=uuid4(),
        action="policy.block",
        target_type="organization_membership",
        target_id=str(uuid4()),
        status=AuditStatus.FAILURE,
        occurred_at=datetime(2026, 7, 2, 9, tzinfo=timezone.utc),
        audit_metadata={
            "organization_id": str(organization_id),
            "request_id": {"value": "must-not-leak"},
            "reason": ["must-not-leak"],
            "target_user_id": {"raw": str(uuid4())},
            "resource_type": "unknown",
            "resource_id": "not-a-uuid",
            "policy_reason": "raw_exception",
            "affected_resource_source_count": True,
            "summary": [{"token": "secret", "safe": "kept"}],
        },
    )
    monkeypatch.setattr(
        "apps.gateway.services.admin_audit_log_service.AdminPermissionGuard.require_audit_reader",
        lambda *args: None,
    )

    detail = AdminAuditLogService.get_audit_log_detail(
        _AuditLogSession([log]),
        current_user=SimpleNamespace(id=uuid4()),
        organization_id=organization_id,
        audit_log_id=log.id,
    )

    assert detail.request_id is None
    assert detail.audit_metadata == {
        "organization_id": str(organization_id),
        "summary": [{"safe": "kept"}],
    }


@pytest.mark.parametrize(
    ("action", "target_type", "expected_operation_fields"),
    [
        (
            "schedule_dispatch.outcome_reviewed",
            "schedule_dispatch_claim",
            {
                "operation_correlation_id": "github-run:123",
                "outcome_resolution_code": "confirmed_completed",
            },
        ),
        ("schedule_dispatch.outcome_reviewed", "workflow", {}),
        ("workflow.execute", "schedule_dispatch_claim", {}),
    ],
)
def test_outcome_review_operation_metadata_requires_exact_action_and_target(
    monkeypatch, action, target_type, expected_operation_fields
):
    AdminAuditLogService, _ = _service()
    organization_id = uuid4()
    log = _audit_log(
        organization_id=organization_id,
        actor_id=uuid4(),
        action=action,
        target_type=target_type,
        target_id=str(uuid4()),
        status=AuditStatus.SUCCESS,
        occurred_at=datetime(2026, 7, 2, 9, tzinfo=timezone.utc),
        audit_metadata={
            "organization_id": str(organization_id),
            "operation_correlation_id": "github-run:123",
            "outcome_resolution_code": "confirmed_completed",
        },
    )
    monkeypatch.setattr(
        "apps.gateway.services.admin_audit_log_service.AdminPermissionGuard.require_audit_reader",
        lambda *args: None,
    )

    detail = AdminAuditLogService.get_audit_log_detail(
        _AuditLogSession([log]),
        current_user=SimpleNamespace(id=uuid4()),
        organization_id=organization_id,
        audit_log_id=log.id,
    )

    assert detail.audit_metadata == {
        "organization_id": str(organization_id),
        **expected_operation_fields,
    }


def test_change_summary_requires_exact_action_target_and_complete_update_provenance(
    monkeypatch,
):
    AdminAuditLogService, _ = _service()
    organization_id = uuid4()
    user_id = uuid4()
    before = {
        "organization_id": str(organization_id),
        "user_id": str(user_id),
        "membership_state": "active",
        "organization_auth_state": "member",
        "raw_payload": {"secret": "must not leak"},
    }
    after = {
        "organization_id": str(organization_id),
        "user_id": str(user_id),
        "membership_state": "suspended",
        "organization_auth_state": "member",
        "password": "must not leak",
    }
    log = _audit_log(
        organization_id=organization_id,
        actor_id=uuid4(),
        action="organization.member.update",
        target_type="organization_membership",
        target_id="membership-1",
        status=AuditStatus.SUCCESS,
        occurred_at=datetime(2026, 7, 2, 9, tzinfo=timezone.utc),
        before=before,
        after=after,
    )
    monkeypatch.setattr(
        "apps.gateway.services.admin_audit_log_service.AdminPermissionGuard.require_audit_reader",
        lambda *args: None,
    )

    detail = AdminAuditLogService.get_audit_log_detail(
        _AuditLogSession([log]),
        current_user=SimpleNamespace(id=uuid4()),
        organization_id=organization_id,
        audit_log_id=log.id,
    )

    assert detail.change_summary.model_dump() == {
        "before": {
            "organization_id": str(organization_id),
            "user_id": str(user_id),
            "membership_state": "active",
            "organization_auth_state": "member",
        },
        "after": {
            "organization_id": str(organization_id),
            "user_id": str(user_id),
            "membership_state": "suspended",
            "organization_auth_state": "member",
        },
    }

    log.action = "organization.member.remove"
    assert (
        AdminAuditLogService.get_audit_log_detail(
            _AuditLogSession([log]),
            current_user=SimpleNamespace(id=uuid4()),
            organization_id=organization_id,
            audit_log_id=log.id,
        ).change_summary
        is None
    )


@pytest.mark.parametrize(
    ("action", "target_type", "before_present", "after_present"),
    [
        ("team_membership.created", "team_membership", False, True),
        ("team_membership.deleted", "team_membership", True, False),
        (
            "user_app_creation_permission.created",
            "user_app_creation_permission",
            False,
            True,
        ),
        (
            "user_app_creation_permission.deleted",
            "user_app_creation_permission",
            True,
            False,
        ),
    ],
)
def test_create_and_delete_summary_use_only_required_complete_snapshot(
    monkeypatch,
    action,
    target_type,
    before_present,
    after_present,
):
    AdminAuditLogService, _ = _service()
    organization_id = uuid4()
    user_id = uuid4()
    if target_type == "team_membership":
        snapshot = {
            "grantee_organization_id": str(organization_id),
            "team_id": str(uuid4()),
            "user_id": str(user_id),
        }
    else:
        snapshot = {
            "grantee_organization_id": str(organization_id),
            "user_id": str(user_id),
        }
    log = _audit_log(
        organization_id=organization_id,
        actor_id=uuid4(),
        action=action,
        target_type=target_type,
        target_id=str(uuid4()),
        status=AuditStatus.SUCCESS,
        occurred_at=datetime(2026, 7, 2, 9, tzinfo=timezone.utc),
        before=snapshot if before_present else None,
        after=snapshot if after_present else None,
    )
    monkeypatch.setattr(
        "apps.gateway.services.admin_audit_log_service.AdminPermissionGuard.require_audit_reader",
        lambda *args: None,
    )

    summary = AdminAuditLogService.get_audit_log_detail(
        _AuditLogSession([log]),
        current_user=SimpleNamespace(id=uuid4()),
        organization_id=organization_id,
        audit_log_id=log.id,
    ).change_summary

    assert summary is not None
    assert (summary.before is not None) is before_present
    assert (summary.after is not None) is after_present


@pytest.mark.parametrize(
    "mutation",
    [
        lambda before, after, other: before.pop("grantee_organization_id"),
        lambda before, after, other: after.pop("auth_state"),
        lambda before, after, other: before.update(
            grantee_organization_id=str(other)
        ),
        lambda before, after, other: after.update(user_id={"secret": "nested"}),
        lambda before, after, other: after.update(auth_state="raw_auditor"),
    ],
)
def test_resource_update_summary_fails_closed_on_partial_or_invalid_snapshot(
    monkeypatch,
    mutation,
):
    AdminAuditLogService, _ = _service()
    organization_id = uuid4()
    other_organization_id = uuid4()
    snapshot = {
        "grantee_organization_id": str(organization_id),
        "user_id": str(uuid4()),
        "knowledge_base_id": str(uuid4()),
        "auth_state": "viewer",
    }
    before = dict(snapshot)
    after = dict(snapshot, auth_state="operator")
    mutation(before, after, other_organization_id)
    log = _audit_log(
        organization_id=organization_id,
        actor_id=uuid4(),
        action="user_knowledge_permission.updated",
        target_type="user_knowledge_permission",
        target_id=str(uuid4()),
        status=AuditStatus.SUCCESS,
        occurred_at=datetime(2026, 7, 2, 9, tzinfo=timezone.utc),
        before=before,
        after=after,
    )
    monkeypatch.setattr(
        "apps.gateway.services.admin_audit_log_service.AdminPermissionGuard.require_audit_reader",
        lambda *args: None,
    )

    detail = AdminAuditLogService.get_audit_log_detail(
        _AuditLogSession([log]),
        current_user=SimpleNamespace(id=uuid4()),
        organization_id=organization_id,
        audit_log_id=log.id,
    )

    assert detail.change_summary is None


def test_policy_block_has_safe_metadata_but_never_change_summary(monkeypatch):
    AdminAuditLogService, _ = _service()
    organization_id = uuid4()
    metadata = {
        "organization_id": str(organization_id),
        "request_id": "request-1",
        "target_user_id": str(uuid4()),
        "requested_action": "membership.suspend",
        "policy_reason": "access_management.self_control_forbidden",
        "resource_type": "workflow",
        "resource_id": str(uuid4()),
        "team_id": str(uuid4()),
        "affected_resource_source_count": 3,
        "actor": {"email": "hidden@example.invalid"},
        "raw_payload": {"secret": "hidden"},
    }
    log = _audit_log(
        organization_id=organization_id,
        actor_id=uuid4(),
        action="policy.block",
        target_type="organization_membership",
        target_id=str(uuid4()),
        status=AuditStatus.FAILURE,
        occurred_at=datetime(2026, 7, 2, 9, tzinfo=timezone.utc),
        audit_metadata=metadata,
        before={"organization_id": str(organization_id)},
        after={"organization_id": str(organization_id)},
    )
    monkeypatch.setattr(
        "apps.gateway.services.admin_audit_log_service.AdminPermissionGuard.require_audit_reader",
        lambda *args: None,
    )

    detail = AdminAuditLogService.get_audit_log_detail(
        _AuditLogSession([log]),
        current_user=SimpleNamespace(id=uuid4()),
        organization_id=organization_id,
        audit_log_id=log.id,
    )

    assert detail.change_summary is None
    assert detail.audit_metadata == {
        key: value
        for key, value in metadata.items()
        if key not in {"actor", "raw_payload"}
    }


def test_require_audit_reader_ignores_inactive_team_grants(monkeypatch):
    AdminPermissionGuard = _guard()
    organization_id = uuid4()
    user_id = uuid4()
    db = _AuditPermissionSession(
        [
            _audit_permission_row(
                user_id=user_id,
                organization_id=organization_id,
                auth_state="auditor",
                team_is_active=False,
            )
        ]
    )
    monkeypatch.setattr(
        f"{ADMIN_AUDIT_SERVICE}.has_organization_manager_permission",
        lambda *args: False,
    )

    with pytest.raises(HTTPException) as exc:
        AdminPermissionGuard.require_audit_reader(
            db, SimpleNamespace(id=user_id), organization_id
        )

    assert exc.value.status_code == 403


def test_require_audit_reader_accepts_any_auditor_team_grant(monkeypatch):
    AdminPermissionGuard = _guard()
    organization_id = uuid4()
    user_id = uuid4()
    db = _AuditPermissionSession(
        [
            _audit_permission_row(
                user_id=user_id,
                organization_id=organization_id,
                auth_state="none",
            ),
            _audit_permission_row(
                user_id=user_id,
                organization_id=organization_id,
                auth_state="auditor",
            ),
        ]
    )
    monkeypatch.setattr(
        f"{ADMIN_AUDIT_SERVICE}.has_organization_manager_permission",
        lambda *args: False,
    )

    AdminPermissionGuard.require_audit_reader(
        db, SimpleNamespace(id=user_id), organization_id
    )


def test_require_audit_reader_records_permission_denied_audit(monkeypatch):
    AdminPermissionGuard = _guard()
    organization_id = uuid4()
    user_id = uuid4()
    audit_calls = []
    monkeypatch.setattr(
        f"{ADMIN_AUDIT_SERVICE}.has_organization_manager_permission",
        lambda *args: False,
    )
    monkeypatch.setattr(
        f"{ADMIN_AUDIT_SERVICE}.record_resource_permission_denied",
        lambda **kwargs: audit_calls.append(kwargs),
        raising=False,
    )

    with pytest.raises(HTTPException) as exc:
        AdminPermissionGuard.require_audit_reader(
            _AuditPermissionSession([]),
            SimpleNamespace(id=user_id),
            organization_id,
        )

    assert exc.value.status_code == 403
    assert getattr(exc.value, "audit_recorded", False) is True
    assert audit_calls
    assert audit_calls[0]["user_id"] == user_id
    assert audit_calls[0]["resource_type"] == "audit"
    assert audit_calls[0]["resource_id"] == organization_id
    assert audit_calls[0]["action"] == "read"
    assert audit_calls[0]["effective_auth_state"] == "none"
    assert audit_calls[0]["organization_id"] == organization_id


class _AuditLogSession:
    # SQLAlchemy Session의 query(AuditLog)만 흉내 내는 최소 테스트 더블이다.
    def __init__(self, logs):
        self._queries = {AuditLog: _AuditLogQuery(logs)}

    def query(self, model):
        return self._queries[model]

    def query_for(self, model):
        return self._queries[model]


class _AuditLogQuery:
    # production 구현이 SQLAlchemy expression을 쓰면 _matches_condition이 해석하고,
    # 단순 predicate를 쓰는 구현도 받을 수 있게 callable도 허용한다.
    def __init__(self, logs):
        self.logs = list(logs)
        self.offset_value = None
        self.limit_value = None

    def filter(self, *conditions):
        self.logs = [
            log
            for log in self.logs
            if all(_matches_condition(log, condition) for condition in conditions)
        ]
        return self

    def order_by(self, *args):
        self.logs.sort(key=lambda log: (log.occurred_at, log.id), reverse=True)
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def count(self):
        return len(self.logs)

    def all(self):
        start = self.offset_value or 0
        end = None if self.limit_value is None else start + self.limit_value
        return self.logs[start:end]

    def first(self):
        return next(iter(self.logs), None)


def _matches_condition(log, condition):
    # FR-011 green 구현에서 필요한 audit_logs 컬럼 조건만 명시적으로 지원한다.
    if callable(condition):
        return condition(log)
    column = str(condition.left)
    value = condition.right.value
    operator = condition.operator
    if column == "audit_logs.id" and operator is eq:
        return log.id == value
    if column == "audit_logs.actor_id" and operator is eq:
        return log.actor_id == value
    if column == "audit_logs.action" and operator is eq:
        return log.action == value
    if column == "audit_logs.target_type" and operator is eq:
        return log.target_type == value
    if column == "audit_logs.target_id" and operator is eq:
        return log.target_id == value
    if column == "audit_logs.status" and operator is eq:
        return log.status == value
    if column == "audit_logs.occurred_at" and operator is ge:
        return log.occurred_at >= value
    if column == "audit_logs.occurred_at" and operator is lt:
        return log.occurred_at < value
    if "audit_logs.audit_metadata" in column and operator is eq:
        return (log.audit_metadata or {}).get("organization_id") == value
    raise AssertionError(f"Unsupported audit filter condition: {condition}")


class _AuditPermissionSession:
    # AdminPermissionGuard가 쓰는 team audit permission query만 흉내 낸다.
    def __init__(self, rows):
        self.rows = list(rows)

    def query(self, model):
        if model in (TeamAuditPermission, TeamAuditPermission.auth_state):
            return _AuditPermissionQuery(self.rows, model)
        raise AssertionError(f"Unexpected model query: {model}")


class _AuditPermissionQuery:
    def __init__(self, rows, model):
        self.rows = list(rows)
        self.model = model

    def join(self, *args):
        if len(args) > 1:
            self.filter(args[1])
        return self

    def filter(self, *conditions):
        self.rows = [
            row
            for row in self.rows
            if all(
                _matches_audit_permission_condition(row, condition)
                for condition in conditions
            )
        ]
        return self

    def all(self):
        if self.model is TeamAuditPermission.auth_state:
            return [_AuthStateRow(row.auth_state) for row in self.rows]
        return self.rows

    def first(self):
        rows = self.all()
        return next(iter(rows), None)


class _AuthStateRow:
    def __init__(self, auth_state):
        self.auth_state = auth_state

    def __iter__(self):
        yield self.auth_state

    def __getitem__(self, index):
        if index == 0:
            return self.auth_state
        raise IndexError(index)


def _matches_audit_permission_condition(row, condition):
    clauses = getattr(condition, "clauses", None)
    if clauses is not None:
        return all(
            _matches_audit_permission_condition(row, clause) for clause in clauses
        )
    left = str(condition.left)
    right = condition.right
    right_column = str(right)
    value = getattr(right, "value", None)
    operator = condition.operator
    if operator is eq:
        if (
            left == "team_memberships.team_id"
            and right_column == "team_audit_permissions.team_id"
        ):
            return row.team_id == row.permission_team_id
        if (
            left == "team_memberships.grantee_organization_id"
            and right_column == "team_audit_permissions.grantee_organization_id"
        ):
            return row.grantee_organization_id == row.permission_grantee_organization_id
        if (
            left == "teams.id"
            and right_column == "team_audit_permissions.team_id"
        ):
            return row.team_id == row.permission_team_id
        if (
            left == "teams.organization_id"
            and right_column == "team_memberships.grantee_organization_id"
        ):
            return row.team_organization_id == row.grantee_organization_id
        if left == "team_memberships.user_id":
            return row.user_id == value
        if left == "team_memberships.grantee_organization_id":
            return row.grantee_organization_id == value
        if left == "team_audit_permissions.grantee_organization_id":
            return row.permission_grantee_organization_id == value
        if left == "team_audit_permissions.target_organization_id":
            return row.target_organization_id == value
        if left == "teams.organization_id":
            return row.team_organization_id == value
    if operator is sqlalchemy_operators.is_ and left == "teams.is_active":
        expected = value if value is not None else str(right).lower() == "true"
        return row.team_is_active is expected
    raise AssertionError(f"Unsupported audit permission filter condition: {condition}")


def _audit_permission_row(
    *,
    user_id,
    organization_id,
    auth_state,
    target_organization_id=None,
    team_id=None,
    team_is_active=True,
):
    team_id = team_id or uuid4()
    return SimpleNamespace(
        user_id=user_id,
        grantee_organization_id=organization_id,
        permission_grantee_organization_id=organization_id,
        target_organization_id=target_organization_id or organization_id,
        team_id=team_id,
        permission_team_id=team_id,
        team_organization_id=organization_id,
        team_is_active=team_is_active,
        auth_state=auth_state,
    )


def _audit_log(
    *,
    organization_id,
    actor_id,
    action,
    target_type,
    target_id,
    status,
    occurred_at,
    audit_metadata=None,
    before=None,
    after=None,
):
    # audit_logs에는 organization_id 컬럼이 없으므로 조직 scope는 metadata 기준으로 검증한다.
    metadata = audit_metadata or {
        "organization_id": str(organization_id),
        "request_id": f"req-{uuid4()}",
    }
    return AuditLog(
        id=uuid4(),
        occurred_at=occurred_at,
        actor_id=actor_id,
        actor_type=ActorType.USER,
        category=AuditCategory.ACTION,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
        status=status,
        audit_metadata=metadata,
    )
