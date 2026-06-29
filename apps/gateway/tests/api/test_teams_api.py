import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from apps.gateway.main import app
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.team import Team, TeamMembership
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db


class TestTeamsApi(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides = {}

    def test_list_teams_returns_manager_visible_fields_and_records_query_contract(self):
        user_id = uuid4()
        organization_id = uuid4()
        created_at = datetime(2026, 6, 27, 1, 2, 3, tzinfo=timezone.utc)
        updated_at = datetime(2026, 6, 27, 4, 5, 6, tzinfo=timezone.utc)
        deactivated_at = datetime(2026, 6, 28, 1, 2, 3, tzinfo=timezone.utc)
        active_team_id = uuid4()
        inactive_team_id = uuid4()
        manager_id = uuid4()

        active_team = _team(
            id=active_team_id,
            organization_id=organization_id,
            name="Alpha",
            description="Core builders",
            options={"template": "builder"},
            flags=3,
            created_by=user_id,
            managed_by=manager_id,
            is_active=True,
            is_auto_add=True,
            created_at=created_at,
            updated_at=updated_at,
        )
        inactive_team = _team(
            id=inactive_team_id,
            organization_id=organization_id,
            name="Legacy",
            description=None,
            options={"template": "viewer"},
            flags=0,
            created_by=user_id,
            managed_by=None,
            is_active=False,
            is_auto_add=False,
            created_at=created_at,
            updated_at=updated_at,
            deactivated_at=deactivated_at,
        )
        session = _Session(
            organization=_organization(
                id=organization_id,
                name="Acme",
                created_by=user_id,
            ),
            teams=[active_team, inactive_team],
        )

        response = self._get_teams(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "id": str(active_team_id),
                    "organization_id": str(organization_id),
                    "name": "Alpha",
                    "description": "Core builders",
                    "options": {"template": "builder"},
                    "flags": 3,
                    "created_by": str(user_id),
                    "managed_by": str(manager_id),
                    "is_active": True,
                    "is_auto_add": True,
                    "created_at": "2026-06-27T01:02:03Z",
                    "updated_at": "2026-06-27T04:05:06Z",
                    "deactivated_at": None,
                },
                {
                    "id": str(inactive_team_id),
                    "organization_id": str(organization_id),
                    "name": "Legacy",
                    "description": None,
                    "options": {"template": "viewer"},
                    "flags": 0,
                    "created_by": str(user_id),
                    "managed_by": None,
                    "is_active": False,
                    "is_auto_add": False,
                    "created_at": "2026-06-27T01:02:03Z",
                    "updated_at": "2026-06-27T04:05:06Z",
                    "deactivated_at": "2026-06-28T01:02:03Z",
                },
            ],
        )
        self.assertNotIn(TeamMembership, session.query_calls)
        self.assertEqual(session.team_query.limit_value, 10)
        self.assertEqual(
            [str(value) for value in session.team_query.order_by_values],
            ["teams.name ASC", "teams.id ASC"],
        )

    def test_list_teams_applies_limit_query_parameter(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(
                id=organization_id,
                name="Acme",
                created_by=user_id,
            ),
            teams=[
                _team(id=uuid4(), organization_id=organization_id, name="A"),
                _team(id=uuid4(), organization_id=organization_id, name="B"),
            ],
        )

        response = self._get_teams(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            query="?limit=1",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(session.team_query.limit_value, 1)

    def test_list_teams_allows_managed_by_without_team_membership(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(
                id=organization_id,
                name="Acme",
                managed_by=user_id,
            ),
            teams=[],
        )

        response = self._get_teams(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        self.assertNotIn(TeamMembership, session.query_calls)

    def test_list_teams_requires_organization_header(self):
        user_id = uuid4()
        session = _Session()

        response = self._get_teams(
            session=session,
            user_id=user_id,
            organization_id=None,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            _error("organization.required", "X-Organization-Id header is required."),
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_list_teams_rejects_invalid_organization_header(self):
        user_id = uuid4()
        session = _Session()

        response = self._get_teams(
            session=session,
            user_id=user_id,
            raw_organization_id="not-a-uuid",
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

    def test_list_teams_rejects_invalid_limit(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session()

        response = self._get_teams(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            query="?limit=0",
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json(),
            _error(
                "validation.failed",
                "limit must be between 1 and 100.",
                {"field": "limit"},
            ),
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_list_teams_hides_missing_or_inactive_organization(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(organization=None)

        response = self._get_teams(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            _error("resource.not_found", "Organization not found."),
        )

    def test_list_teams_hides_organization_outside_user_scope(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, name="Acme"),
            membership=None,
        )

        response = self._get_teams(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            _error("resource.not_found", "Organization not found."),
        )
        self.assertIn(TeamMembership, session.query_calls)

    def test_list_teams_rejects_member_without_manager_permission(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, name="Acme"),
            membership=SimpleNamespace(id=uuid4()),
        )

        response = self._get_teams(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            _error(
                "permission.denied",
                "Organization manager permission is required.",
            ),
        )

    def test_list_teams_returns_auth_envelope_for_unauthenticated_request(self):
        session = _Session()
        app.dependency_overrides[get_db] = lambda: session

        with patch(
            "apps.gateway.api.v1.endpoints.team.AuthService.get_user_from_token",
            side_effect=HTTPException(status_code=401, detail="로그인이 필요합니다"),
        ):
            response = TestClient(app).get(
                "/api/v1/teams",
                headers={"X-Request-ID": "req-test"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            _error("auth.required", "로그인이 필요합니다"),
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_list_team_members_returns_members_for_manager(self):
        user_id = uuid4()
        organization_id = uuid4()
        team_id = uuid4()
        member_user_id = uuid4()
        membership_id = uuid4()
        assigned_at = datetime(2026, 6, 29, 2, 11, 34, tzinfo=timezone.utc)
        member = _user(
            id=member_user_id,
            email="member@example.com",
            name="Member One",
        )
        membership = _team_membership(
            id=membership_id,
            organization_id=organization_id,
            team_id=team_id,
            user_id=member_user_id,
            assigned_by=user_id,
            assigned_at=assigned_at,
            user=member,
        )
        session = _Session(
            organization=_organization(
                id=organization_id,
                name="Acme",
                created_by=user_id,
            ),
            team=_team(id=team_id, organization_id=organization_id, name="Alpha"),
            memberships=[membership],
        )

        response = self._get_team_members(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id=team_id,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "id": str(membership_id),
                    "user_id": str(member_user_id),
                    "email": "member@example.com",
                    "name": "Member One",
                    "assigned_at": "2026-06-29T02:11:34Z",
                }
            ],
        )
        self.assertIn(Team, session.query_calls)
        self.assertIn(TeamMembership, session.query_calls)
        self.assertEqual(
            [str(value) for value in session.membership_query.order_by_values],
            ["users.name ASC", "users.email ASC", "team_memberships.id ASC"],
        )

    def test_create_team_checks_manager_permission_without_request_schema(self):
        # docs/api/organization-rbac.md에서 POST /teams schema는 아직 TBD다.
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(
                id=organization_id,
                name="Acme",
                created_by=user_id,
            ),
            teams=[],
        )

        response = self._post_team(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            payload={"unexpected": {"contract": "tbd"}},
        )

        self.assertEqual(response.status_code, 501)
        self.assertEqual(
            response.json(),
            _error(
                "operation.not_implemented",
                "Team creation request and response contract is TBD.",
            ),
        )
        self.assertNotIn(TeamMembership, session.query_calls)
        self.assertNotIn(Team, session.query_calls)

    def test_create_team_rejects_member_without_manager_permission(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, name="Acme"),
            membership=SimpleNamespace(id=uuid4()),
        )

        response = self._post_team(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            payload={"name": "Builders"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            _error(
                "permission.denied",
                "Organization manager permission is required.",
            ),
        )
        self.assertIn(TeamMembership, session.query_calls)

    def test_create_team_hides_organization_outside_user_scope(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, name="Acme"),
            membership=None,
        )

        response = self._post_team(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            payload={"name": "Builders"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            _error("resource.not_found", "Organization not found."),
        )
        self.assertIn(TeamMembership, session.query_calls)

    def test_update_team_checks_manager_permission_without_request_schema(self):
        # docs/api/organization-rbac.md에서 PATCH /teams/{team_id} schema는 아직 TBD다.
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(
                id=organization_id,
                name="Acme",
                created_by=user_id,
            ),
            teams=[],
        )

        response = self._patch_team(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id=uuid4(),
            payload={"unexpected": {"contract": "tbd"}},
        )

        self.assertEqual(response.status_code, 501)
        self.assertEqual(
            response.json(),
            _error(
                "operation.not_implemented",
                "Team update request and response contract is TBD.",
            ),
        )
        self.assertNotIn(TeamMembership, session.query_calls)
        self.assertNotIn(Team, session.query_calls)

    def test_update_team_requires_organization_header(self):
        # PATCH 라우트도 조직 헤더가 없으면 권한/DB 조회 전에 거부해야 한다.
        user_id = uuid4()
        session = _Session()

        response = self._patch_team(
            session=session,
            user_id=user_id,
            organization_id=None,
            team_id=uuid4(),
            payload={"name": "Builders"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            _error("organization.required", "X-Organization-Id header is required."),
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_update_team_rejects_invalid_organization_header(self):
        # PATCH 라우트도 조직 헤더 UUID 형식을 먼저 검증해야 한다.
        user_id = uuid4()
        session = _Session()

        response = self._patch_team(
            session=session,
            user_id=user_id,
            raw_organization_id="not-a-uuid",
            team_id=uuid4(),
            payload={"name": "Builders"},
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

    def test_update_team_returns_auth_envelope_for_unauthenticated_request(self):
        # PATCH 라우트가 미인증 요청을 공통 auth envelope로 반환하는지 확인한다.
        session = _Session()
        app.dependency_overrides[get_db] = lambda: session

        with patch(
            "apps.gateway.api.v1.endpoints.team.AuthService.get_user_from_token",
            side_effect=HTTPException(status_code=401, detail="로그인이 필요합니다"),
        ):
            response = TestClient(app).patch(
                f"/api/v1/teams/{uuid4()}",
                headers={
                    "X-Organization-Id": str(uuid4()),
                    "X-Request-ID": "req-test",
                },
                json={"name": "Builders"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            _error("auth.required", "로그인이 필요합니다"),
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_update_team_rejects_invalid_team_id_route_parameter(self):
        # team_id 경로 파라미터가 UUID가 아니면 FastAPI route validation에서 막혀야 한다.
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session()

        response = self._patch_team(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id="not-a-uuid",
            payload={"name": "Builders"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation.failed")
        self.assertEqual(response.json()["error"]["request_id"], "req-test")
        self.assertEqual(
            response.json()["error"]["message"],
            "Request validation failed.",
        )
        self.assertEqual(
            response.json()["error"]["details"]["errors"][0]["loc"],
            ["path", "team_id"],
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_update_team_rejects_member_without_manager_permission(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, name="Acme"),
            membership=SimpleNamespace(id=uuid4()),
        )

        response = self._patch_team(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id=uuid4(),
            payload={"name": "Builders"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            _error(
                "permission.denied",
                "Organization manager permission is required.",
            ),
        )
        self.assertIn(TeamMembership, session.query_calls)

    def test_update_team_hides_organization_outside_user_scope(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, name="Acme"),
            membership=None,
        )

        response = self._patch_team(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id=uuid4(),
            payload={"name": "Builders"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            _error("resource.not_found", "Organization not found."),
        )
        self.assertIn(TeamMembership, session.query_calls)

    def test_add_team_member_checks_manager_permission_without_request_schema(self):
        # docs/api/organization-rbac.md에서 POST /teams/{team_id}/members schema는 아직 TBD다.
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(
                id=organization_id,
                name="Acme",
                created_by=user_id,
            ),
            teams=[],
        )

        response = self._post_team_member(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id=uuid4(),
            payload={"unexpected": {"contract": "tbd"}},
        )

        self.assertEqual(response.status_code, 501)
        self.assertEqual(
            response.json(),
            _error(
                "operation.not_implemented",
                "Team member addition request and response contract is TBD.",
            ),
        )
        self.assertNotIn(TeamMembership, session.query_calls)
        self.assertNotIn(Team, session.query_calls)

    def test_add_team_member_requires_organization_header(self):
        user_id = uuid4()
        session = _Session()

        response = self._post_team_member(
            session=session,
            user_id=user_id,
            organization_id=None,
            team_id=uuid4(),
            payload={"user_id": str(uuid4())},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            _error("organization.required", "X-Organization-Id header is required."),
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_add_team_member_rejects_invalid_organization_header(self):
        user_id = uuid4()
        session = _Session()

        response = self._post_team_member(
            session=session,
            user_id=user_id,
            raw_organization_id="not-a-uuid",
            team_id=uuid4(),
            payload={"user_id": str(uuid4())},
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

    def test_add_team_member_returns_auth_envelope_for_unauthenticated_request(self):
        session = _Session()
        app.dependency_overrides[get_db] = lambda: session

        with patch(
            "apps.gateway.api.v1.endpoints.team.AuthService.get_user_from_token",
            side_effect=HTTPException(status_code=401, detail="로그인이 필요합니다"),
        ):
            response = TestClient(app).post(
                f"/api/v1/teams/{uuid4()}/members",
                headers={
                    "X-Organization-Id": str(uuid4()),
                    "X-Request-ID": "req-test",
                },
                json={"user_id": str(uuid4())},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            _error("auth.required", "로그인이 필요합니다"),
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_add_team_member_rejects_invalid_team_id_route_parameter(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session()

        response = self._post_team_member(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id="not-a-uuid",
            payload={"user_id": str(uuid4())},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation.failed")
        self.assertEqual(response.json()["error"]["request_id"], "req-test")
        self.assertEqual(
            response.json()["error"]["message"],
            "Request validation failed.",
        )
        self.assertEqual(
            response.json()["error"]["details"]["errors"][0]["loc"],
            ["path", "team_id"],
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_add_team_member_rejects_member_without_manager_permission(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, name="Acme"),
            membership=SimpleNamespace(id=uuid4()),
        )

        response = self._post_team_member(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id=uuid4(),
            payload={"user_id": str(uuid4())},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            _error(
                "permission.denied",
                "Organization manager permission is required.",
            ),
        )
        self.assertIn(TeamMembership, session.query_calls)

    def test_add_team_member_hides_organization_outside_user_scope(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, name="Acme"),
            membership=None,
        )

        response = self._post_team_member(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id=uuid4(),
            payload={"user_id": str(uuid4())},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            _error("resource.not_found", "Organization not found."),
        )
        self.assertIn(TeamMembership, session.query_calls)

    def test_remove_team_member_checks_manager_permission_without_response_schema(self):
        # docs/api/organization-rbac.md에서 DELETE /teams/{team_id}/members/{user_id} response는 아직 TBD다.
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(
                id=organization_id,
                name="Acme",
                created_by=user_id,
            ),
            teams=[],
        )

        response = self._delete_team_member(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id=uuid4(),
            member_user_id=uuid4(),
        )

        self.assertEqual(response.status_code, 501)
        self.assertEqual(
            response.json(),
            _error(
                "operation.not_implemented",
                "Team member removal response contract is TBD.",
            ),
        )
        self.assertNotIn(TeamMembership, session.query_calls)
        self.assertNotIn(Team, session.query_calls)

    def test_remove_team_member_allows_managed_by_without_response_schema(self):
        # organization.managed_by도 manager 권한으로 인정되어야 하므로,
        # created_by가 아닌 관리자가 DELETE 권한 관문을 통과하는지 검증한다.
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(
                id=organization_id,
                name="Acme",
                created_by=uuid4(),
                managed_by=user_id,
            ),
            teams=[],
        )

        response = self._delete_team_member(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id=uuid4(),
            member_user_id=uuid4(),
        )

        self.assertEqual(response.status_code, 501)
        self.assertEqual(
            response.json(),
            _error(
                "operation.not_implemented",
                "Team member removal response contract is TBD.",
            ),
        )
        self.assertNotIn(TeamMembership, session.query_calls)
        self.assertNotIn(Team, session.query_calls)

    def test_remove_team_member_requires_organization_header(self):
        user_id = uuid4()
        session = _Session()

        response = self._delete_team_member(
            session=session,
            user_id=user_id,
            organization_id=None,
            team_id=uuid4(),
            member_user_id=uuid4(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            _error("organization.required", "X-Organization-Id header is required."),
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_remove_team_member_rejects_invalid_organization_header(self):
        user_id = uuid4()
        session = _Session()

        response = self._delete_team_member(
            session=session,
            user_id=user_id,
            raw_organization_id="not-a-uuid",
            team_id=uuid4(),
            member_user_id=uuid4(),
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

    def test_remove_team_member_returns_auth_envelope_for_unauthenticated_request(self):
        session = _Session()
        app.dependency_overrides[get_db] = lambda: session

        with patch(
            "apps.gateway.api.v1.endpoints.team.AuthService.get_user_from_token",
            side_effect=HTTPException(status_code=401, detail="로그인이 필요합니다"),
        ):
            response = TestClient(app).delete(
                f"/api/v1/teams/{uuid4()}/members/{uuid4()}",
                headers={
                    "X-Organization-Id": str(uuid4()),
                    "X-Request-ID": "req-test",
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            _error("auth.required", "로그인이 필요합니다"),
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_remove_team_member_rejects_invalid_team_id_route_parameter(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session()

        response = self._delete_team_member(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id="not-a-uuid",
            member_user_id=uuid4(),
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation.failed")
        self.assertEqual(response.json()["error"]["request_id"], "req-test")
        self.assertEqual(
            response.json()["error"]["message"],
            "Request validation failed.",
        )
        self.assertEqual(
            response.json()["error"]["details"]["errors"][0]["loc"],
            ["path", "team_id"],
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_remove_team_member_rejects_invalid_user_id_route_parameter(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session()

        response = self._delete_team_member(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id=uuid4(),
            member_user_id="not-a-uuid",
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation.failed")
        self.assertEqual(response.json()["error"]["request_id"], "req-test")
        self.assertEqual(
            response.json()["error"]["message"],
            "Request validation failed.",
        )
        self.assertEqual(
            response.json()["error"]["details"]["errors"][0]["loc"],
            ["path", "user_id"],
        )
        self.assertNotIn(Organization, session.query_calls)

    def test_remove_team_member_rejects_member_without_manager_permission(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, name="Acme"),
            membership=SimpleNamespace(id=uuid4()),
        )

        response = self._delete_team_member(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id=uuid4(),
            member_user_id=uuid4(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            _error(
                "permission.denied",
                "Organization manager permission is required.",
            ),
        )
        self.assertIn(TeamMembership, session.query_calls)

    def test_remove_team_member_hides_organization_outside_user_scope(self):
        user_id = uuid4()
        organization_id = uuid4()
        session = _Session(
            organization=_organization(id=organization_id, name="Acme"),
            membership=None,
        )

        response = self._delete_team_member(
            session=session,
            user_id=user_id,
            organization_id=organization_id,
            team_id=uuid4(),
            member_user_id=uuid4(),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            _error("resource.not_found", "Organization not found."),
        )
        self.assertIn(TeamMembership, session.query_calls)

    def _get_teams(
        self,
        session,
        user_id,
        organization_id=None,
        raw_organization_id=None,
        query="",
    ):
        app.dependency_overrides[get_db] = lambda: session
        headers = {"X-Request-ID": "req-test"}
        if raw_organization_id is not None:
            headers["X-Organization-Id"] = raw_organization_id
        elif organization_id is not None:
            headers["X-Organization-Id"] = str(organization_id)
        headers["Cookie"] = "auth_token=token"

        with patch(
            "apps.gateway.api.v1.endpoints.team.AuthService.get_user_from_token",
            return_value=SimpleNamespace(id=user_id),
        ):
            return TestClient(app).get(
                f"/api/v1/teams{query}",
                headers=headers,
            )

    def _get_team_members(
        self,
        session,
        user_id,
        team_id,
        organization_id=None,
        raw_organization_id=None,
    ):
        app.dependency_overrides[get_db] = lambda: session
        headers = {"X-Request-ID": "req-test"}
        if raw_organization_id is not None:
            headers["X-Organization-Id"] = raw_organization_id
        elif organization_id is not None:
            headers["X-Organization-Id"] = str(organization_id)
        headers["Cookie"] = "auth_token=token"

        with patch(
            "apps.gateway.api.v1.endpoints.team.AuthService.get_user_from_token",
            return_value=SimpleNamespace(id=user_id),
        ):
            return TestClient(app).get(
                f"/api/v1/teams/{team_id}/members",
                headers=headers,
            )

    def _post_team(
        self,
        session,
        user_id,
        organization_id=None,
        raw_organization_id=None,
        payload=None,
    ):
        app.dependency_overrides[get_db] = lambda: session
        headers = {"X-Request-ID": "req-test"}
        if raw_organization_id is not None:
            headers["X-Organization-Id"] = raw_organization_id
        elif organization_id is not None:
            headers["X-Organization-Id"] = str(organization_id)
        headers["Cookie"] = "auth_token=token"

        with patch(
            "apps.gateway.api.v1.endpoints.team.AuthService.get_user_from_token",
            return_value=SimpleNamespace(id=user_id),
        ):
            return TestClient(app).post(
                "/api/v1/teams",
                headers=headers,
                json=payload,
            )

    def _patch_team(
        self,
        session,
        user_id,
        team_id,
        organization_id=None,
        raw_organization_id=None,
        payload=None,
    ):
        app.dependency_overrides[get_db] = lambda: session
        headers = {"X-Request-ID": "req-test"}
        if raw_organization_id is not None:
            headers["X-Organization-Id"] = raw_organization_id
        elif organization_id is not None:
            headers["X-Organization-Id"] = str(organization_id)
        headers["Cookie"] = "auth_token=token"

        with patch(
            "apps.gateway.api.v1.endpoints.team.AuthService.get_user_from_token",
            return_value=SimpleNamespace(id=user_id),
        ):
            return TestClient(app).patch(
                f"/api/v1/teams/{team_id}",
                headers=headers,
                json=payload,
            )

    def _post_team_member(
        self,
        session,
        user_id,
        team_id,
        organization_id=None,
        raw_organization_id=None,
        payload=None,
    ):
        app.dependency_overrides[get_db] = lambda: session
        headers = {"X-Request-ID": "req-test"}
        if raw_organization_id is not None:
            headers["X-Organization-Id"] = raw_organization_id
        elif organization_id is not None:
            headers["X-Organization-Id"] = str(organization_id)
        headers["Cookie"] = "auth_token=token"

        with patch(
            "apps.gateway.api.v1.endpoints.team.AuthService.get_user_from_token",
            return_value=SimpleNamespace(id=user_id),
        ):
            return TestClient(app).post(
                f"/api/v1/teams/{team_id}/members",
                headers=headers,
                json=payload,
            )

    def _delete_team_member(
        self,
        session,
        user_id,
        team_id,
        member_user_id,
        organization_id=None,
        raw_organization_id=None,
    ):
        app.dependency_overrides[get_db] = lambda: session
        headers = {"X-Request-ID": "req-test"}
        if raw_organization_id is not None:
            headers["X-Organization-Id"] = raw_organization_id
        elif organization_id is not None:
            headers["X-Organization-Id"] = str(organization_id)
        headers["Cookie"] = "auth_token=token"

        with patch(
            "apps.gateway.api.v1.endpoints.team.AuthService.get_user_from_token",
            return_value=SimpleNamespace(id=user_id),
        ):
            return TestClient(app).delete(
                f"/api/v1/teams/{team_id}/members/{member_user_id}",
                headers=headers,
            )


class _Query:
    def __init__(self, first_result=None, items=None):
        self.first_result = first_result
        self.items = items or []
        self.join_values = []
        self.filter_expressions = []
        self.order_by_values = []
        self.options_values = []
        self.limit_value = None

    def join(self, *args):
        self.join_values.append(args)
        return self

    def filter(self, *expressions):
        self.filter_expressions.extend(expressions)
        return self

    def order_by(self, *args):
        self.order_by_values.extend(args)
        return self

    def options(self, *args):
        self.options_values.extend(args)
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def first(self):
        return self.first_result

    def all(self):
        if self.limit_value is None:
            return self.items
        return self.items[: self.limit_value]


class _Session:
    def __init__(
        self,
        organization=None,
        membership=None,
        teams=None,
        team=None,
        memberships=None,
    ):
        self.organization_query = _Query(first_result=organization)
        self.membership_query = _Query(
            first_result=membership,
            items=memberships or [],
        )
        self.team_query = _Query(first_result=team, items=teams or [])
        self.query_calls = []

    def query(self, model):
        self.query_calls.append(model)
        if model is Organization:
            return self.organization_query
        if model is TeamMembership:
            return self.membership_query
        if model is Team:
            return self.team_query
        raise AssertionError(f"Unexpected query model: {model}")


def _organization(
    id,
    name,
    created_by=None,
    managed_by=None,
    is_active=True,
):
    now = datetime.now(timezone.utc)
    return Organization(
        id=id,
        name=name,
        options={},
        flags=0,
        created_by=created_by or uuid4(),
        managed_by=managed_by,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _team(
    id,
    organization_id,
    name,
    description=None,
    options=None,
    flags=0,
    created_by=None,
    managed_by=None,
    is_active=True,
    is_auto_add=False,
    created_at=None,
    updated_at=None,
    deactivated_at=None,
):
    now = datetime.now(timezone.utc)
    return Team(
        id=id,
        organization_id=organization_id,
        name=name,
        description=description,
        options=options or {},
        flags=flags,
        created_by=created_by or uuid4(),
        managed_by=managed_by,
        is_active=is_active,
        is_auto_add=is_auto_add,
        created_at=created_at or now,
        updated_at=updated_at or now,
        deactivated_at=deactivated_at,
    )


def _team_membership(
    id,
    organization_id,
    team_id,
    user_id,
    assigned_by,
    assigned_at,
    user,
):
    membership = TeamMembership(
        id=id,
        grantee_organization_id=organization_id,
        team_id=team_id,
        user_id=user_id,
        assigned_by=assigned_by,
        assigned_at=assigned_at,
    )
    membership.user = user
    return membership


def _user(id, email, name):
    now = datetime.now(timezone.utc)
    return User(
        id=id,
        email=email,
        name=name,
        social_provider="local",
        created_at=now,
        updated_at=now,
    )


def _error(code, message, details=None):
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
