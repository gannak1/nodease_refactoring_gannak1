import unittest
from datetime import datetime, timezone
from operator import eq
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.sql.operators import is_

from apps.gateway.api.v1.endpoints.organization import list_organizations
from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.main import app
from apps.shared.db.models.organization import Organization
from apps.shared.db.session import get_db


class TestOrganizationsApi(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides = {}

    def test_list_organizations_uses_memberships_and_deduplicates(self):
        # 현재 사용자의 active team membership 기준으로 조직을 조회하고 중복 조직을 제거하는지 검증한다.
        user_id = uuid4()
        organization = _organization(id=uuid4(), name="Acme")
        other_organization = _organization(id=uuid4(), name="Beta")
        query = _Query([organization, organization, other_organization])
        db = SimpleNamespace(query=lambda model: query)

        response = list_organizations(
            db=db,
            current_user=SimpleNamespace(id=user_id),
        )

        self.assertEqual(response, [organization, other_organization])
        self.assertTrue(query.distinct_called)
        self.assertEqual(len(query.join_values), 2)

        user_filter, team_org_filter, team_active_filter, org_active_filter = (
            query.filter_expressions
        )
        self.assertEqual(str(user_filter.left), "team_memberships.user_id")
        self.assertIs(user_filter.operator, eq)
        self.assertEqual(user_filter.right.value, user_id)

        self.assertEqual(
            str(team_org_filter.left), "team_memberships.grantee_organization_id"
        )
        self.assertIs(team_org_filter.operator, eq)
        self.assertEqual(str(team_org_filter.right), "teams.organization_id")

        self.assertEqual(str(team_active_filter.left), "teams.is_active")
        self.assertIs(team_active_filter.operator, is_)
        self.assertEqual(str(team_active_filter.right), "true")

        self.assertEqual(str(org_active_filter.left), "organization.is_active")
        self.assertIs(org_active_filter.operator, is_)
        self.assertEqual(str(org_active_filter.right), "true")

    def test_route_returns_current_user_organizations(self):
        # GET /api/v1/organizations 라우터가 현재 사용자의 조직 목록을 응답 스키마로 직렬화하는지 검증한다.
        organization_id = uuid4()
        user_id = uuid4()
        created_at = datetime(2026, 6, 27, 1, 2, 3, tzinfo=timezone.utc)
        updated_at = datetime(2026, 6, 27, 4, 5, 6, tzinfo=timezone.utc)
        organization = _organization(
            id=organization_id,
            name="Acme",
            created_at=created_at,
            updated_at=updated_at,
        )

        app.dependency_overrides[get_db] = lambda: SimpleNamespace(
            query=lambda model: _Query([organization])
        )
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).get("/api/v1/organizations")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "id": str(organization_id),
                    "name": "Acme",
                    "is_active": True,
                    "created_at": "2026-06-27T01:02:03Z",
                    "updated_at": "2026-06-27T04:05:06Z",
                }
            ],
        )

    def test_route_returns_member_organization_detail(self):
        # GET /api/v1/organizations/{organization_id}가 현재 사용자의 active team membership scope 안에 있는 조직만 반환하는지 검증한다.
        organization_id = uuid4()
        user_id = uuid4()
        created_at = datetime(2026, 6, 27, 1, 2, 3, tzinfo=timezone.utc)
        updated_at = datetime(2026, 6, 27, 4, 5, 6, tzinfo=timezone.utc)
        organization = _organization(
            id=organization_id,
            name="Acme",
            created_at=created_at,
            updated_at=updated_at,
        )
        query = _Query([organization])

        app.dependency_overrides[get_db] = lambda: SimpleNamespace(
            query=lambda model: query
        )
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).get(f"/api/v1/organizations/{organization_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "id": str(organization_id),
                "name": "Acme",
                "is_active": True,
                "created_at": "2026-06-27T01:02:03Z",
                "updated_at": "2026-06-27T04:05:06Z",
            },
        )

        # 문서 기준 모델에 맞춰 organization, team_memberships, teams 조인과 active scope 조건을 사용해야 한다.
        self.assertEqual(len(query.join_values), 2)
        (
            organization_filter,
            user_filter,
            membership_org_filter,
            team_org_filter,
            team_active_filter,
            org_active_filter,
        ) = query.filter_expressions

        self.assertEqual(str(organization_filter.left), "organization.id")
        self.assertIs(organization_filter.operator, eq)
        self.assertEqual(organization_filter.right.value, organization_id)

        self.assertEqual(str(user_filter.left), "team_memberships.user_id")
        self.assertIs(user_filter.operator, eq)
        self.assertEqual(user_filter.right.value, user_id)

        self.assertEqual(
            str(membership_org_filter.left),
            "team_memberships.grantee_organization_id",
        )
        self.assertIs(membership_org_filter.operator, eq)
        self.assertEqual(str(membership_org_filter.right), "organization.id")

        self.assertEqual(
            str(team_org_filter.left),
            "team_memberships.grantee_organization_id",
        )
        self.assertIs(team_org_filter.operator, eq)
        self.assertEqual(str(team_org_filter.right), "teams.organization_id")

        self.assertEqual(str(team_active_filter.left), "teams.is_active")
        self.assertIs(team_active_filter.operator, is_)
        self.assertEqual(str(team_active_filter.right), "true")

        self.assertEqual(str(org_active_filter.left), "organization.is_active")
        self.assertIs(org_active_filter.operator, is_)
        self.assertEqual(str(org_active_filter.right), "true")

    def test_route_hides_organization_outside_user_memberships(self):
        # 조직이 없거나 현재 사용자의 membership scope 밖이면 존재 여부를 노출하지 않고 404로 숨긴다.
        organization_id = uuid4()
        user_id = uuid4()

        app.dependency_overrides[get_db] = lambda: SimpleNamespace(
            query=lambda model: _Query([])
        )
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).get(f"/api/v1/organizations/{organization_id}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Organization not found"})


class _Query:
    def __init__(self, items):
        self.items = items
        self.join_values = []
        self.filter_expressions = []
        self.order_by_values = []
        self.distinct_called = False

    def join(self, *args):
        self.join_values.append(args)
        return self

    def filter(self, *expressions):
        self.filter_expressions.extend(expressions)
        return self

    def distinct(self):
        self.distinct_called = True
        seen_ids = set()
        unique_items = []
        for item in self.items:
            if item.id in seen_ids:
                continue
            seen_ids.add(item.id)
            unique_items.append(item)
        self.items = unique_items
        return self

    def order_by(self, *args):
        self.order_by_values.extend(args)
        return self

    def all(self):
        return self.items

    def first(self):
        return self.items[0] if self.items else None


def _organization(
    id,
    name,
    created_at=None,
    updated_at=None,
):
    now = datetime.now(timezone.utc)
    return Organization(
        id=id,
        name=name,
        created_by=uuid4(),
        is_active=True,
        created_at=created_at or now,
        updated_at=updated_at or now,
    )


if __name__ == "__main__":
    unittest.main()
