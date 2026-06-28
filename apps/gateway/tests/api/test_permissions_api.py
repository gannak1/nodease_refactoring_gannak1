import unittest
from datetime import datetime, timezone
from operator import eq
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.operators import is_

from apps.gateway.main import app
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.team import (
    Team,
    TeamMembership,
    TeamWorkflowPermission,
    UserWorkflowPermission,
)
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.session import get_db


class TestPermissionsApi(unittest.TestCase):
    def setUp(self):
        """audit side effect를 막고 호출 인자만 검증하도록 patch한다."""
        self.main_audit_patcher = patch("apps.gateway.main.record_audit")
        self.permission_audit_patcher = patch(
            "apps.gateway.api.v1.endpoints.permissions.record_audit"
        )
        self.main_audit_patcher.start()
        self.permission_audit = self.permission_audit_patcher.start()

    def tearDown(self):
        """테스트에서 추가한 patch와 FastAPI dependency override를 정리한다."""
        self.permission_audit_patcher.stop()
        self.main_audit_patcher.stop()
        app.dependency_overrides.pop(get_db, None)

    def test_put_team_workflow_permission_creates_row_for_organization_manager(self):
        # organization owner/manager는 team membership 없이도 workflow 권한을 부여할 수 있다.
        user_id = uuid4()
        organization_id = uuid4()
        workflow_id = uuid4()
        team_id = uuid4()
        upsert_result = _team_workflow_permission(
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            auth_state="builder",
            assigned_by=user_id,
        )
        session = _Session(
            organization=_organization(id=organization_id, created_by=user_id),
            workflow=_workflow(id=workflow_id, organization_id=organization_id),
            team=_team(id=team_id, organization_id=organization_id),
            upsert_result=upsert_result,
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            payload={"auth_state": "builder"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["grantee_organization_id"], str(organization_id))
        self.assertEqual(response.json()["workflow_id"], str(workflow_id))
        self.assertEqual(response.json()["team_id"], str(team_id))
        self.assertEqual(response.json()["auth_state"], "builder")
        self.assertEqual(response.json()["assigned_by"], str(user_id))
        self.assertEqual(len(session.added), 0)
        self.assertTrue(session.scalars_called)
        _assert_organization_scope_filters(self, session.organization_query, organization_id)
        _assert_workflow_scope_filters(
            self,
            session.workflow_query,
            workflow_id,
            organization_id,
        )
        _assert_team_scope_filters(self, session.team_query, team_id, organization_id)
        self.assertIn(
            "ON CONFLICT (grantee_organization_id, workflow_id, team_id)",
            str(session.upsert_statement.compile(dialect=postgresql.dialect())),
        )
        self.assertTrue(session.committed)
        self.assertIsNotNone(session.lock_statement)
        self.assertIn(
            "pg_advisory_xact_lock",
            str(session.lock_statement.compile(dialect=postgresql.dialect())),
        )
        self.assertNotIn(TeamMembership, session.query_calls)
        self.permission_audit.assert_called_once()
        audit = self.permission_audit.call_args.kwargs
        self.assertEqual(audit["action"], "team_workflow_permission.created")
        self.assertEqual(audit["category"], "data_change")
        self.assertEqual(audit["actor_id"], str(user_id))
        self.assertEqual(audit["actor_type"], "user")
        self.assertEqual(audit["target_type"], "team_workflow_permission")
        self.assertEqual(audit["target_id"], upsert_result.id)
        self.assertIsNone(audit["before"])
        self.assertEqual(audit["after"]["id"], upsert_result.id)
        self.assertEqual(audit["after"]["grantee_organization_id"], organization_id)
        self.assertEqual(audit["after"]["workflow_id"], workflow_id)
        self.assertEqual(audit["after"]["team_id"], team_id)
        self.assertEqual(audit["after"]["auth_state"], "builder")
        self.assertEqual(audit["metadata"]["request_id"], "req-test")
        self.assertEqual(audit["metadata"]["actor"]["id"], str(user_id))

    def test_put_team_workflow_permission_updates_row_for_workflow_manager(self):
        # organization manager가 아니어도 대상 workflow의 manager 권한이 있으면 기존 row를 수정할 수 있다.
        user_id = uuid4()
        organization_id = uuid4()
        workflow_id = uuid4()
        team_id = uuid4()
        previous_assigned_by = uuid4()
        existing_permission = _team_workflow_permission(
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            auth_state="viewer",
            assigned_by=previous_assigned_by,
        )
        upsert_result = _team_workflow_permission(
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            auth_state="manager",
            assigned_by=user_id,
        )
        upsert_result.id = existing_permission.id
        session = _Session(
            organization=_organization(id=organization_id, created_by=uuid4()),
            membership=_membership(user_id=user_id, organization_id=organization_id),
            workflow=_workflow(id=workflow_id, organization_id=organization_id),
            team=_team(id=team_id, organization_id=organization_id),
            manager_permissions=[
                _team_workflow_permission(
                    organization_id=organization_id,
                    workflow_id=workflow_id,
                    team_id=uuid4(),
                    auth_state="manager",
                    assigned_by=uuid4(),
                    member_user_id=user_id,
                )
            ],
            existing_permission=existing_permission,
            upsert_result=upsert_result,
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            payload={"auth_state": "MANAGER"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["auth_state"], "manager")
        self.assertEqual(len(session.added), 0)
        self.assertEqual(session.workflow_permission_query_count, 2)
        self.assertTrue(session.scalars_called)
        _assert_active_membership_filters(
            self,
            session.membership_query,
            user_id,
            organization_id,
        )
        _assert_workflow_manage_filters(
            self,
            session.workflow_manager_query,
            user_id,
            workflow_id,
            organization_id,
        )
        self.assertTrue(session.committed)
        self.assertIsNotNone(session.lock_statement)
        self.permission_audit.assert_called_once()
        audit = self.permission_audit.call_args.kwargs
        self.assertEqual(audit["action"], "team_workflow_permission.updated")
        self.assertEqual(audit["category"], "data_change")
        self.assertEqual(audit["actor_id"], str(user_id))
        self.assertEqual(audit["actor_type"], "user")
        self.assertEqual(audit["target_type"], "team_workflow_permission")
        self.assertEqual(audit["target_id"], existing_permission.id)
        self.assertEqual(audit["before"]["auth_state"], "viewer")
        self.assertEqual(audit["after"]["auth_state"], "manager")
        self.assertEqual(audit["before"]["assigned_by"], previous_assigned_by)
        self.assertEqual(audit["after"]["assigned_by"], user_id)
        self.assertEqual(
            audit["before"]["assigned_at"],
            existing_permission.assigned_at,
        )
        self.assertEqual(audit["after"]["assigned_at"], upsert_result.assigned_at)
        self.assertNotIn("workflow_id", audit["before"])
        self.assertEqual(audit["metadata"]["request_id"], "req-test")
        self.assertEqual(audit["metadata"]["actor"]["id"], str(user_id))

    def test_put_team_workflow_permission_rejects_member_without_manage(self):
        # active member라도 workflow manager가 아니면 권한 변경은 거부해야 한다.
        user_id = uuid4()
        organization_id = uuid4()
        workflow_id = uuid4()
        team_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, created_by=uuid4()),
            membership=_membership(user_id=user_id, organization_id=organization_id),
            workflow=_workflow(id=workflow_id, organization_id=organization_id),
            team=_team(id=team_id, organization_id=organization_id),
            manager_permissions=[
                _team_workflow_permission(
                    organization_id=organization_id,
                    workflow_id=workflow_id,
                    team_id=uuid4(),
                    auth_state="builder",
                    assigned_by=uuid4(),
                    member_user_id=user_id,
                )
            ],
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            payload={"auth_state": "viewer"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            _error(
                "permission.denied",
                "Workflow manage or organization manager permission is required.",
            ),
        )
        self.assertFalse(session.committed)
        self.assertFalse(session.scalars_called)
        self.assertEqual(len(session.added), 0)
        _assert_workflow_manage_filters(
            self,
            session.workflow_manager_query,
            user_id,
            workflow_id,
            organization_id,
        )

    def test_put_team_workflow_permission_ignores_manager_permission_from_other_scope(self):
        # 다른 workflow/organization의 manager 권한은 현재 workflow 권한 변경에 쓰이면 안 된다.
        user_id = uuid4()
        organization_id = uuid4()
        workflow_id = uuid4()
        team_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, created_by=uuid4()),
            membership=_membership(user_id=user_id, organization_id=organization_id),
            workflow=_workflow(id=workflow_id, organization_id=organization_id),
            team=_team(id=team_id, organization_id=organization_id),
            manager_permissions=[
                _team_workflow_permission(
                    organization_id=uuid4(),
                    workflow_id=uuid4(),
                    team_id=team_id,
                    auth_state="manager",
                    assigned_by=uuid4(),
                    member_user_id=user_id,
                )
            ],
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            payload={"auth_state": "viewer"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            _error(
                "permission.denied",
                "Workflow manage or organization manager permission is required.",
            ),
        )
        self.assertFalse(session.committed)
        self.assertFalse(session.scalars_called)
        _assert_workflow_manage_filters(
            self,
            session.workflow_manager_query,
            user_id,
            workflow_id,
            organization_id,
        )

    def test_put_team_workflow_permission_allows_user_direct_manager(self):
        # user direct manager 권한도 effective manager로 합산되어 권한 변경을 허용한다.
        user_id = uuid4()
        organization_id = uuid4()
        workflow_id = uuid4()
        team_id = uuid4()
        upsert_result = _team_workflow_permission(
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            auth_state="viewer",
            assigned_by=user_id,
        )
        session = _Session(
            organization=_organization(id=organization_id, created_by=uuid4()),
            membership=_membership(user_id=user_id, organization_id=organization_id),
            workflow=_workflow(id=workflow_id, organization_id=organization_id),
            team=_team(id=team_id, organization_id=organization_id),
            manager_permissions=[],
            user_direct_permissions=[
                _user_workflow_permission(
                    organization_id=organization_id,
                    workflow_id=workflow_id,
                    user_id=user_id,
                    auth_state="manager",
                    assigned_by=uuid4(),
                )
            ],
            upsert_result=upsert_result,
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            payload={"auth_state": "viewer"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(session.scalars_called)
        self.assertTrue(session.committed)
        _assert_user_workflow_manage_filters(
            self,
            session.user_workflow_query,
            user_id,
            workflow_id,
            organization_id,
        )

    def test_put_team_workflow_permission_hides_other_org_membership(self):
        # 다른 organization membership은 active member scope로 인정하지 않는다.
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, created_by=uuid4()),
            membership=_membership(user_id=user_id, organization_id=uuid4()),
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=uuid4(),
            team_id=uuid4(),
            payload={"auth_state": "viewer"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            _error("resource.not_found", "Organization not found."),
        )
        self.assertNotIn(Workflow, session.query_calls)
        self.assertFalse(session.scalars_called)

    def test_put_team_workflow_permission_hides_inactive_membership_team(self):
        # inactive team membership은 organization scope 진입 권한으로 인정하지 않는다.
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, created_by=uuid4()),
            membership=_membership(
                user_id=user_id,
                organization_id=organization_id,
                team_is_active=False,
            ),
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=uuid4(),
            team_id=uuid4(),
            payload={"auth_state": "viewer"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            _error("resource.not_found", "Organization not found."),
        )
        self.assertNotIn(Workflow, session.query_calls)
        self.assertFalse(session.scalars_called)

    def test_put_team_workflow_permission_hides_organization_outside_user_scope(self):
        # scope 밖 organization은 존재 여부를 노출하지 않도록 404로 숨긴다.
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, created_by=uuid4()),
            membership=None,
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=uuid4(),
            team_id=uuid4(),
            payload={"auth_state": "viewer"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            _error("resource.not_found", "Organization not found."),
        )
        _assert_active_membership_filters(
            self,
            session.membership_query,
            user_id,
            organization_id,
        )
        self.assertNotIn(Workflow, session.query_calls)
        self.assertFalse(session.committed)
        self.assertFalse(session.scalars_called)

    def test_put_team_workflow_permission_requires_organization_header(self):
        # X-Organization-Id가 없으면 organization 조회 전에 400으로 거부한다.
        user_id = uuid4()
        session = _Session()

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=None,
            workflow_id=uuid4(),
            team_id=uuid4(),
            payload={"auth_state": "viewer"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            _error("organization.required", "X-Organization-Id header is required."),
        )
        self.assertNotIn(Organization, session.query_calls)
        self.assertFalse(session.scalars_called)

    def test_put_team_workflow_permission_rejects_malformed_organization_header(self):
        # X-Organization-Id가 UUID가 아니면 scope 조회 전에 validation error로 거부한다.
        user_id = uuid4()
        session = _Session()

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=None,
            raw_organization_id="not-a-uuid",
            workflow_id=uuid4(),
            team_id=uuid4(),
            payload={"auth_state": "viewer"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json(),
            _error(
                "validation.failed",
                "X-Organization-Id must be a valid UUID.",
                {"field": "X-Organization-Id"},
            ),
        )
        self.assertNotIn(Organization, session.query_calls)
        self.assertFalse(session.scalars_called)

    def test_put_team_workflow_permission_allows_managed_by_manager(self):
        # organization.managed_by도 organization manager로 인정되어 membership 없이 허용된다.
        user_id = uuid4()
        organization_id = uuid4()
        workflow_id = uuid4()
        team_id = uuid4()
        upsert_result = _team_workflow_permission(
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            auth_state="operator",
            assigned_by=user_id,
        )
        session = _Session(
            organization=_organization(
                id=organization_id,
                created_by=uuid4(),
                managed_by=user_id,
            ),
            workflow=_workflow(id=workflow_id, organization_id=organization_id),
            team=_team(id=team_id, organization_id=organization_id),
            upsert_result=upsert_result,
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            payload={"auth_state": "operator"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["auth_state"], "operator")
        self.assertNotIn(TeamMembership, session.query_calls)
        self.assertTrue(session.scalars_called)
        self.assertTrue(session.committed)

    def test_put_team_workflow_permission_noops_same_auth_state(self):
        # 같은 auth_state PUT은 assigned metadata만 바꾸는 update/audit을 만들지 않는다.
        user_id = uuid4()
        organization_id = uuid4()
        workflow_id = uuid4()
        team_id = uuid4()
        previous_assigned_by = uuid4()
        existing_permission = _team_workflow_permission(
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            auth_state="builder",
            assigned_by=previous_assigned_by,
        )
        session = _Session(
            organization=_organization(id=organization_id, created_by=user_id),
            workflow=_workflow(id=workflow_id, organization_id=organization_id),
            team=_team(id=team_id, organization_id=organization_id),
            existing_permission=existing_permission,
            upsert_result=None,
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            payload={"auth_state": "builder"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["auth_state"], "builder")
        self.assertEqual(response.json()["assigned_by"], str(previous_assigned_by))
        self.assertTrue(session.committed)
        self.permission_audit.assert_not_called()

    def test_put_team_workflow_permission_hides_missing_workflow(self):
        # workflow가 active organization scope 안에 없으면 team 조회나 upsert 없이 404로 숨긴다.
        user_id = uuid4()
        organization_id = uuid4()
        workflow_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, created_by=user_id),
            workflow=None,
            team=_team(id=uuid4(), organization_id=organization_id),
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=uuid4(),
            payload={"auth_state": "viewer"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            _error("resource.not_found", "Workflow not found."),
        )
        _assert_workflow_scope_filters(
            self,
            session.workflow_query,
            workflow_id,
            organization_id,
        )
        self.assertNotIn(Team, session.query_calls)
        self.assertFalse(session.scalars_called)

    def test_put_team_workflow_permission_requires_authentication(self):
        # auth_token cookie가 없고 AuthService가 401을 내면 auth.required envelope으로 반환한다.
        session = _Session()

        response = self._put_permission(
            session=session,
            user_id=uuid4(),
            organization_id=uuid4(),
            workflow_id=uuid4(),
            team_id=uuid4(),
            payload={"auth_state": "viewer"},
            include_auth_cookie=False,
            auth_side_effect=HTTPException(
                status_code=401,
                detail="로그인이 필요합니다",
            ),
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            _error("auth.required", "로그인이 필요합니다"),
        )
        self.assertNotIn(Organization, session.query_calls)
        self.assertFalse(session.scalars_called)

    def test_put_team_workflow_permission_rejects_invalid_token(self):
        # auth_token cookie가 있지만 AuthService가 401을 내면 auth.invalid envelope으로 반환한다.
        session = _Session()

        response = self._put_permission(
            session=session,
            user_id=uuid4(),
            organization_id=uuid4(),
            workflow_id=uuid4(),
            team_id=uuid4(),
            payload={"auth_state": "viewer"},
            auth_side_effect=HTTPException(
                status_code=401,
                detail="Invalid token",
            ),
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            _error("auth.invalid", "Invalid token"),
        )
        self.assertNotIn(Organization, session.query_calls)
        self.assertFalse(session.scalars_called)

    def test_put_team_workflow_permission_rejects_invalid_auth_state(self):
        # workflow matrix에 없는 auth_state는 DB 조회 전에 request validation에서 막는다.
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session()

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=uuid4(),
            team_id=uuid4(),
            payload={"auth_state": "admin"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation.failed")
        self.assertEqual(response.json()["error"]["request_id"], "req-test")
        self.assertEqual(
            response.json()["error"]["details"]["errors"][0]["loc"],
            ["body", "auth_state"],
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_put_team_workflow_permission_hides_missing_team(self):
        # team이 없으면 권한 row를 만들지 않고 404로 응답한다.
        user_id = uuid4()
        organization_id = uuid4()
        workflow_id = uuid4()
        team_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, created_by=user_id),
            workflow=_workflow(id=workflow_id, organization_id=organization_id),
            team=None,
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            payload={"auth_state": "viewer"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), _error("resource.not_found", "Team not found."))
        _assert_team_scope_filters(self, session.team_query, team_id, organization_id)
        self.assertFalse(session.committed)
        self.assertFalse(session.scalars_called)

    def test_put_team_workflow_permission_hides_inactive_team(self):
        # inactive team은 fake query의 Team.is_active 필터 적용으로 실제 404가 되어야 한다.
        user_id = uuid4()
        organization_id = uuid4()
        workflow_id = uuid4()
        team_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, created_by=user_id),
            workflow=_workflow(id=workflow_id, organization_id=organization_id),
            team=_team(id=team_id, organization_id=organization_id, is_active=False),
        )

        response = self._put_permission(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            team_id=team_id,
            payload={"auth_state": "viewer"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), _error("resource.not_found", "Team not found."))
        _assert_team_scope_filters(self, session.team_query, team_id, organization_id)
        self.assertFalse(session.committed)
        self.assertFalse(session.scalars_called)

    def _put_permission(
        self,
        session,
        user_id,
        workflow_id,
        team_id,
        payload,
        organization_id=None,
        raw_organization_id=None,
        include_auth_cookie=True,
        auth_side_effect=None,
    ):
        """fake DB session과 fake 인증 결과로 권한 PUT endpoint를 호출한다."""
        # 각 테스트는 실제 DB 대신 fake session을 주입하고 인증 결과만 고정한다.
        app.dependency_overrides[get_db] = lambda: session
        headers = {
            "X-Request-ID": "req-test",
        }
        if include_auth_cookie:
            headers["Cookie"] = "auth_token=token"
        if raw_organization_id is not None:
            headers["X-Organization-Id"] = raw_organization_id
        elif organization_id is not None:
            headers["X-Organization-Id"] = str(organization_id)

        patch_kwargs = (
            {"side_effect": auth_side_effect}
            if auth_side_effect is not None
            else {"return_value": SimpleNamespace(id=user_id)}
        )
        with patch(
            "apps.gateway.api.v1.endpoints.permissions.AuthService.get_user_from_token",
            **patch_kwargs,
        ):
            return TestClient(app).put(
                f"/api/v1/permissions/workflows/{workflow_id}/teams/{team_id}",
                headers=headers,
                json=payload,
            )


class _Query:
    # SQLAlchemy Query chain 중 이 테스트에서 사용하는 최소 동작만 흉내 낸다.
    def __init__(self, first_result=None, items=None, apply_filters=False):
        """first/all 결과와 필터 적용 여부를 받아 fake query를 구성한다."""
        self.first_result = first_result
        self.items = items or []
        self.apply_filters = apply_filters
        self.join_values = []
        self.filter_expressions = []

    def join(self, *args):
        """endpoint가 생성한 join 조건을 나중에 검증할 수 있게 저장한다."""
        self.join_values.append(args)
        return self

    def filter(self, *expressions):
        """filter 조건을 저장하고 필요하면 fake 결과에 적용한다."""
        self.filter_expressions.extend(expressions)
        return self

    def first(self):
        """첫 fake row를 반환하고 필요하면 SQLAlchemy 조건을 흉내 낸다."""
        if self.apply_filters and self.first_result is not None:
            for expression in self.filter_expressions:
                if not _matches_expression(self.first_result, expression):
                    return None
        return self.first_result

    def all(self):
        """fake row 목록을 반환하고 필요하면 조건과 맞는 row만 남긴다."""
        if self.apply_filters:
            return [
                item
                for item in self.items
                if all(_matches_expression(item, expr) for expr in self.filter_expressions)
            ]
        return self.items


class _ScalarResult:
    def __init__(self, value):
        """Session.scalars(...).one() 호출 형태를 흉내 내기 위한 wrapper."""
        self.value = value

    def one(self):
        """upsert returning 결과로 사용할 fake permission 객체를 반환한다."""
        return self.value

    def one_or_none(self):
        """no-op upsert처럼 returning row가 없을 수 있는 경로를 흉내 낸다."""
        return self.value


class _Session:
    # endpoint의 query 순서에 맞춰 각 모델별 fake query 결과를 반환한다.
    def __init__(
        self,
        organization=None,
        membership=None,
        workflow=None,
        team=None,
        manager_permissions=None,
        user_direct_permissions=None,
        existing_permission=None,
        upsert_result=None,
    ):
        """권한 endpoint가 사용하는 Session API의 최소 동작을 구성한다."""
        self.organization_query = _Query(
            first_result=organization,
            apply_filters=True,
        )
        self.membership_query = _Query(first_result=membership, apply_filters=True)
        self.workflow_query = _Query(first_result=workflow, apply_filters=True)
        self.team_query = _Query(first_result=team, apply_filters=True)
        self.manager_permissions = manager_permissions
        self.user_direct_permissions = user_direct_permissions or []
        self.existing_permission = existing_permission
        self.workflow_manager_query = None
        self.user_workflow_query = None
        self.workflow_permission_query_count = 0
        self.upsert_result = upsert_result
        self.upsert_statement = None
        self.lock_statement = None
        self.query_calls = []
        self.added = []
        self.scalars_called = False
        self.committed = False
        self.refreshed = False

    def query(self, model):
        """요청 ORM model에 맞는 fake query를 반환하고 순서를 기록한다."""
        self.query_calls.append(model)
        if model is Organization:
            return self.organization_query
        if model is TeamMembership:
            return self.membership_query
        if model is Workflow:
            return self.workflow_query
        if model is Team:
            return self.team_query
        if model is TeamWorkflowPermission:
            self.workflow_permission_query_count += 1
            # 첫 번째 TeamWorkflowPermission query는 요청자의 manage 권한 판정용이다.
            if (
                self.manager_permissions is not None
                and self.workflow_permission_query_count == 1
            ):
                self.workflow_manager_query = _Query(
                    items=self.manager_permissions,
                    apply_filters=True,
                )
                return self.workflow_manager_query
            return _Query(first_result=self.existing_permission, apply_filters=True)
        if model is UserWorkflowPermission:
            self.user_workflow_query = _Query(
                items=self.user_direct_permissions,
                apply_filters=True,
            )
            return self.user_workflow_query
        raise AssertionError(f"Unexpected query model: {model}")

    def add(self, value):
        """ORM insert 경로 사용 여부를 감지하도록 add 호출 값을 기록한다."""
        self.added.append(value)

    def scalars(self, statement):
        """Core upsert statement를 기록하고 returning 결과 wrapper를 반환한다."""
        self.scalars_called = True
        self.upsert_statement = statement
        return _ScalarResult(self.upsert_result)

    def execute(self, statement):
        """advisory lock statement를 기록한다."""
        self.lock_statement = statement
        return None

    def commit(self):
        """endpoint가 transaction commit까지 도달했는지 표시한다."""
        self.committed = True

    def refresh(self, value):
        """id가 비어 있으면 fake id를 넣고 refresh 호출을 기록한다."""
        if value.id is None:
            value.id = uuid4()
        self.refreshed = True


def _organization(id, created_by, managed_by=None, is_active=True):
    """organization scope 검증용 Organization fixture를 만든다."""
    now = datetime.now(timezone.utc)
    return Organization(
        id=id,
        name="Acme",
        options={},
        flags=0,
        created_by=created_by,
        managed_by=managed_by,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _workflow(id, organization_id):
    """workflow scope 검증에 필요한 필드만 채운 Workflow fixture를 만든다."""
    now = datetime.now(timezone.utc)
    return Workflow(
        id=id,
        organization_id=organization_id,
        app_id=uuid4(),
        graph={},
        features={},
        env_variables={},
        runtime_variables={},
        created_by=uuid4(),
        created_at=now,
        updated_at=now,
    )


def _team(id, organization_id, is_active=True):
    """team scope와 active team 검증에 필요한 Team fixture를 만든다."""
    now = datetime.now(timezone.utc)
    return Team(
        id=id,
        organization_id=organization_id,
        name="Builders",
        description=None,
        options={},
        flags=0,
        created_by=uuid4(),
        managed_by=None,
        is_active=is_active,
        is_auto_add=False,
        created_at=now,
        updated_at=now,
    )


def _membership(user_id, organization_id, team_is_active=True):
    """active membership scope 검증용 fixture를 만든다."""
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        grantee_organization_id=organization_id,
        team_organization_id=organization_id,
        team_is_active=team_is_active,
    )


def _team_workflow_permission(
    organization_id,
    workflow_id,
    team_id,
    auth_state,
    assigned_by,
    member_user_id=None,
    membership_organization_id=None,
    team_organization_id=None,
    team_is_active=True,
):
    """권한 판정과 upsert returning용 permission fixture를 만든다."""
    permission = TeamWorkflowPermission(
        id=uuid4(),
        grantee_organization_id=organization_id,
        workflow_id=workflow_id,
        team_id=team_id,
        auth_state=auth_state,
        assigned_by=assigned_by,
        assigned_at=datetime.now(timezone.utc),
        options={},
        flags=0,
    )
    if member_user_id is not None:
        permission.member_user_id = member_user_id
        permission.membership_grantee_organization_id = (
            membership_organization_id or organization_id
        )
        permission.team_organization_id = team_organization_id or organization_id
        permission.team_is_active = team_is_active
    return permission


def _user_workflow_permission(
    organization_id,
    workflow_id,
    user_id,
    auth_state,
    assigned_by,
):
    """user direct workflow permission fixture를 만든다."""
    return UserWorkflowPermission(
        id=uuid4(),
        grantee_organization_id=organization_id,
        workflow_id=workflow_id,
        user_id=user_id,
        auth_state=auth_state,
        assigned_by=assigned_by,
        assigned_at=datetime.now(timezone.utc),
        options={},
        flags=0,
    )


def _matches_expression(obj, expression):
    """fake query가 주요 SQLAlchemy filter 표현식을 적용하게 평가한다."""
    left_value = _column_value(obj, str(expression.left))

    if expression.operator is eq:
        if not hasattr(expression.right, "value"):
            return left_value == _column_value(obj, str(expression.right))
        return left_value == expression.right.value
    if expression.operator is is_:
        return left_value is (str(expression.right) == "true")
    raise AssertionError(f"Unexpected filter operator: {expression.operator}")


def _column_value(obj, column):
    missing = object()
    value_by_column = {
        "organization.id": getattr(obj, "id", missing),
        "organization.is_active": getattr(obj, "is_active", missing),
        "workflows.id": getattr(obj, "id", missing),
        "workflows.organization_id": getattr(obj, "organization_id", missing),
        "teams.id": getattr(obj, "id", missing),
        "teams.organization_id": getattr(
            obj,
            "team_organization_id",
            getattr(obj, "organization_id", missing),
        ),
        "teams.is_active": getattr(
            obj,
            "team_is_active",
            getattr(obj, "is_active", missing),
        ),
        "team_memberships.user_id": getattr(
            obj,
            "member_user_id",
            getattr(obj, "user_id", missing),
        ),
        "team_memberships.grantee_organization_id": getattr(
            obj,
            "membership_grantee_organization_id",
            getattr(obj, "grantee_organization_id", missing),
        ),
        "team_workflow_permissions.workflow_id": getattr(
            obj,
            "workflow_id",
            missing,
        ),
        "team_workflow_permissions.grantee_organization_id": getattr(
            obj,
            "grantee_organization_id",
            missing,
        ),
        "team_workflow_permissions.team_id": getattr(obj, "team_id", missing),
        "user_workflow_permissions.user_id": getattr(obj, "user_id", missing),
        "user_workflow_permissions.workflow_id": getattr(
            obj,
            "workflow_id",
            missing,
        ),
        "user_workflow_permissions.grantee_organization_id": getattr(
            obj,
            "grantee_organization_id",
            missing,
        ),
    }
    if column not in value_by_column:
        raise AssertionError(f"Unexpected filter column: {column}")
    if value_by_column[column] is missing:
        raise AssertionError(f"Missing fixture attribute for filter column: {column}")
    return value_by_column[column]


def _assert_organization_scope_filters(testcase, query, organization_id):
    """organization 조회가 id와 active 조건으로 scope를 제한하는지 검증한다."""
    id_filter = _find_filter(query, "organization.id", eq)
    testcase.assertEqual(id_filter.right.value, organization_id)

    active_filter = _find_filter(query, "organization.is_active", is_)
    testcase.assertEqual(str(active_filter.right), "true")


def _assert_active_membership_filters(testcase, query, user_id, organization_id):
    """active membership 조회가 필요한 scope 조건을 포함하는지 검증한다."""
    _assert_join_predicate(
        testcase,
        query,
        "teams.id",
        "team_memberships.team_id",
    )

    user_filter = _find_filter(query, "team_memberships.user_id", eq)
    testcase.assertEqual(user_filter.right.value, user_id)

    org_filter = _find_filter(
        query,
        "team_memberships.grantee_organization_id",
        eq,
        right_value=organization_id,
    )
    testcase.assertEqual(org_filter.right.value, organization_id)

    team_org_filter = _find_filter(
        query,
        "team_memberships.grantee_organization_id",
        eq,
        right_text="teams.organization_id",
    )
    testcase.assertEqual(str(team_org_filter.right), "teams.organization_id")

    active_filter = _find_filter(query, "teams.is_active", is_)
    testcase.assertEqual(str(active_filter.right), "true")


def _assert_workflow_scope_filters(testcase, query, workflow_id, organization_id):
    """workflow 조회가 요청 workflow와 organization scope로 제한되는지 검증한다."""
    workflow_filter = _find_filter(query, "workflows.id", eq)
    testcase.assertEqual(workflow_filter.right.value, workflow_id)

    org_filter = _find_filter(query, "workflows.organization_id", eq)
    testcase.assertEqual(org_filter.right.value, organization_id)


def _assert_team_scope_filters(testcase, query, team_id, organization_id):
    """team 조회가 요청 team, organization, active 조건을 포함하는지 검증한다."""
    team_filter = _find_filter(query, "teams.id", eq)
    testcase.assertEqual(team_filter.right.value, team_id)

    org_filter = _find_filter(query, "teams.organization_id", eq)
    testcase.assertEqual(org_filter.right.value, organization_id)

    active_filter = _find_filter(query, "teams.is_active", is_)
    testcase.assertEqual(str(active_filter.right), "true")


def _assert_workflow_manage_filters(
    testcase,
    query,
    user_id,
    workflow_id,
    organization_id,
):
    """workflow manager 조회가 membership/team/permission scope를 묶는지 검증한다."""
    _assert_join_predicate(
        testcase,
        query,
        "team_memberships.team_id",
        "team_workflow_permissions.team_id",
    )
    _assert_join_predicate(
        testcase,
        query,
        "teams.id",
        "team_workflow_permissions.team_id",
    )

    user_filter = _find_filter(query, "team_memberships.user_id", eq)
    testcase.assertEqual(user_filter.right.value, user_id)

    workflow_filter = _find_filter(
        query,
        "team_workflow_permissions.workflow_id",
        eq,
    )
    testcase.assertEqual(workflow_filter.right.value, workflow_id)

    org_filter = _find_filter(
        query,
        "team_workflow_permissions.grantee_organization_id",
        eq,
    )
    testcase.assertEqual(org_filter.right.value, organization_id)

    membership_org_filter = _find_filter(
        query,
        "team_memberships.grantee_organization_id",
        eq,
        right_text="team_workflow_permissions.grantee_organization_id",
    )
    testcase.assertEqual(
        str(membership_org_filter.right),
        "team_workflow_permissions.grantee_organization_id",
    )

    team_org_filter = _find_filter(
        query,
        "teams.organization_id",
        eq,
        right_text="team_workflow_permissions.grantee_organization_id",
    )
    testcase.assertEqual(
        str(team_org_filter.right),
        "team_workflow_permissions.grantee_organization_id",
    )

    active_filter = _find_filter(query, "teams.is_active", is_)
    testcase.assertEqual(str(active_filter.right), "true")


def _assert_user_workflow_manage_filters(
    testcase,
    query,
    user_id,
    workflow_id,
    organization_id,
):
    """user-direct manager 조회가 필요한 scope 조건을 포함하는지 검증한다."""
    user_filter = _find_filter(query, "user_workflow_permissions.user_id", eq)
    testcase.assertEqual(user_filter.right.value, user_id)

    workflow_filter = _find_filter(
        query,
        "user_workflow_permissions.workflow_id",
        eq,
    )
    testcase.assertEqual(workflow_filter.right.value, workflow_id)

    org_filter = _find_filter(
        query,
        "user_workflow_permissions.grantee_organization_id",
        eq,
    )
    testcase.assertEqual(org_filter.right.value, organization_id)


def _find_filter(query, left, operator, right_value=None, right_text=None):
    """저장된 SQLAlchemy filter 표현식 중 기대한 column/operator 조건을 찾는다."""
    for expression in query.filter_expressions:
        if str(expression.left) != left or expression.operator is not operator:
            continue
        if right_value is not None and getattr(expression.right, "value", None) != right_value:
            continue
        if right_text is not None and str(expression.right) != right_text:
            continue
        return expression
    raise AssertionError(f"Missing filter: {left}")


def _assert_join_predicate(testcase, query, left, right):
    """저장된 join 조건 중 기대한 column equality predicate를 검증한다."""
    for join_value in query.join_values:
        if len(join_value) < 2:
            continue
        expression = join_value[1]
        if (
            str(expression.left) == left
            and expression.operator is eq
            and str(expression.right) == right
        ):
            return
    testcase.fail(f"Missing join predicate: {left} == {right}")


def _error(code, message, details=None):
    """테스트에서 기대하는 권한 API error envelope을 만든다."""
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": "req-test",
            "details": details or {},
        }
    }


if __name__ == "__main__":
    unittest.main()
