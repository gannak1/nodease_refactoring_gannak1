import unittest
from datetime import datetime, timezone
from operator import eq
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.sql.operators import is_

from apps.gateway.api.v1.endpoints.organization import list_organizations
from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.main import app
from apps.shared.db.models.organization import Organization
from apps.shared.db.session import get_db


class TestOrganizationsApi(unittest.TestCase):
    def setUp(self):
        self.audit_patchers = [
            patch("apps.gateway.utils.audit.record_audit"),
            patch("apps.gateway.main.record_audit"),
        ]
        for audit_patcher in self.audit_patchers:
            audit_patcher.start()

    def tearDown(self):
        for audit_patcher in reversed(self.audit_patchers):
            audit_patcher.stop()
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

    def test_patch_organization_allows_owner_without_team_membership(self):
        organization_id = uuid4()
        user_id = uuid4()
        organization = _organization(
            id=organization_id,
            name="Acme",
            created_by=user_id,
            options={"theme": "legacy", "limits": {"runs": 10}},
        )
        db = _Session([organization])

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).patch(
            f"/api/v1/organizations/{organization_id}",
            headers={"X-Organization-Id": str(organization_id)},
            json={"name": "  Acme Korea  ", "options": {"theme": "modern"}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Acme Korea")
        self.assertEqual(organization.name, "Acme Korea")
        self.assertEqual(organization.options, {"theme": "modern"})
        self.assertEqual(db.query_value.join_values, [])
        _assert_patch_scope_filters(self, db.query_value, organization_id)
        self.assertTrue(db.commit_called)
        self.assertEqual(db.refresh_values, [organization])

    def test_patch_organization_requires_organization_header(self):
        organization_id = uuid4()
        user_id = uuid4()

        app.dependency_overrides[get_db] = lambda: _Session([])
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).patch(
            f"/api/v1/organizations/{organization_id}",
            json={"name": "Acme Korea"},
        )

        self.assertEqual(response.status_code, 400)

    def test_patch_organization_hides_header_path_mismatch(self):
        organization_id = uuid4()
        header_organization_id = uuid4()
        user_id = uuid4()

        app.dependency_overrides[get_db] = lambda: _Session([])
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).patch(
            f"/api/v1/organizations/{organization_id}",
            headers={"X-Organization-Id": str(header_organization_id)},
            json={"name": "Acme Korea"},
        )

        self.assertEqual(response.status_code, 404)

    def test_patch_organization_rejects_non_manager(self):
        organization_id = uuid4()
        user_id = uuid4()
        organization = _organization(id=organization_id, name="Acme")

        app.dependency_overrides[get_db] = lambda: _Session([organization])
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).patch(
            f"/api/v1/organizations/{organization_id}",
            headers={"X-Organization-Id": str(organization_id)},
            json={"name": "Acme Korea"},
        )

        self.assertEqual(response.status_code, 403)

    def test_patch_organization_rejects_missing_or_out_of_scope_organization(self):
        organization_id = uuid4()
        user_id = uuid4()

        app.dependency_overrides[get_db] = lambda: _Session([])
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).patch(
            f"/api/v1/organizations/{organization_id}",
            headers={"X-Organization-Id": str(organization_id)},
            json={"name": "Acme Korea"},
        )

        self.assertEqual(response.status_code, 403)

    def test_patch_organization_rejects_different_organization_from_query(self):
        organization_id = uuid4()
        user_id = uuid4()
        organization = _organization(
            id=uuid4(),
            name="Acme",
            created_by=user_id,
        )

        app.dependency_overrides[get_db] = lambda: _Session([organization])
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).patch(
            f"/api/v1/organizations/{organization_id}",
            headers={"X-Organization-Id": str(organization_id)},
            json={"name": "Acme Korea"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(organization.name, "Acme")

    def test_patch_organization_rejects_inactive_organization(self):
        organization_id = uuid4()
        user_id = uuid4()
        organization = _organization(
            id=organization_id,
            name="Acme",
            created_by=user_id,
            is_active=False,
        )

        app.dependency_overrides[get_db] = lambda: _Session([organization])
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).patch(
            f"/api/v1/organizations/{organization_id}",
            headers={"X-Organization-Id": str(organization_id)},
            json={"name": "Acme Korea"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(organization.name, "Acme")

    def test_patch_organization_rejects_empty_update(self):
        organization_id = uuid4()
        user_id = uuid4()
        organization = _organization(
            id=organization_id,
            name="Acme",
            created_by=user_id,
        )

        app.dependency_overrides[get_db] = lambda: _Session([organization])
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).patch(
            f"/api/v1/organizations/{organization_id}",
            headers={"X-Organization-Id": str(organization_id)},
            json={},
        )

        self.assertEqual(response.status_code, 400)

    def test_patch_organization_rejects_blank_name(self):
        organization_id = uuid4()
        user_id = uuid4()
        organization = _organization(
            id=organization_id,
            name="Acme",
            created_by=user_id,
        )

        app.dependency_overrides[get_db] = lambda: _Session([organization])
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).patch(
            f"/api/v1/organizations/{organization_id}",
            headers={"X-Organization-Id": str(organization_id)},
            json={"name": "   "},
        )

        self.assertEqual(response.status_code, 400)

    def test_patch_organization_rejects_name_longer_than_database_column(self):
        organization_id = uuid4()
        user_id = uuid4()
        organization = _organization(
            id=organization_id,
            name="Acme",
            created_by=user_id,
        )

        app.dependency_overrides[get_db] = lambda: _Session([organization])
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).patch(
            f"/api/v1/organizations/{organization_id}",
            headers={"X-Organization-Id": str(organization_id)},
            json={"name": "A" * 256},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(organization.name, "Acme")


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
        for item in self.items:
            if self._matches_filters(item):
                return item
        return None

    def _matches_filters(self, item):
        return all(
            self._matches_filter(item, expression)
            for expression in self.filter_expressions
        )

    def _matches_filter(self, item, expression):
        if not hasattr(expression, "left"):
            return True

        left = str(expression.left)
        if left == "organization.id" and expression.operator is eq:
            return item.id == expression.right.value
        if left == "organization.is_active" and expression.operator is is_:
            return item.is_active is (str(expression.right) == "true")
        if left.startswith("organization."):
            raise AssertionError(f"Unsupported organization filter: {expression}")
        return True


class _Session:
    def __init__(self, items):
        self.query_value = _Query(items)
        self.commit_called = False
        self.refresh_values = []

    def query(self, model):
        return self.query_value

    def commit(self):
        self.commit_called = True

    def refresh(self, value):
        self.refresh_values.append(value)


def _organization(
    id,
    name,
    created_by=None,
    managed_by=None,
    options=None,
    is_active=True,
    created_at=None,
    updated_at=None,
):
    now = datetime.now(timezone.utc)
    return Organization(
        id=id,
        name=name,
        options=options or {},
        created_by=created_by or uuid4(),
        managed_by=managed_by,
        is_active=is_active,
        created_at=created_at or now,
        updated_at=updated_at or now,
    )


def _assert_patch_scope_filters(test_case, query, organization_id):
    test_case.assertEqual(len(query.filter_expressions), 2)
    organization_filter, org_active_filter = query.filter_expressions

    test_case.assertEqual(str(organization_filter.left), "organization.id")
    test_case.assertIs(organization_filter.operator, eq)
    test_case.assertEqual(organization_filter.right.value, organization_id)

    test_case.assertEqual(str(org_active_filter.left), "organization.is_active")
    test_case.assertIs(org_active_filter.operator, is_)
    test_case.assertEqual(str(org_active_filter.right), "true")


if __name__ == "__main__":
    unittest.main()
