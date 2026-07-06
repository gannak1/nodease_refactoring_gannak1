"""workflow 예산 관리 API(FR-051) route 등록 테스트.

TDD red phase: route가 아직 없으므로 404로 실패해야 한다.
route가 등록되어 있으면 미인증 요청은 404가 아니라 인증 실패 401로 끝난다
(test_admin_usage_api.py와 같은 패턴).
"""

import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.gateway.main import app


class TestWorkflowBudgetRoutesRegistered(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides = {}

    def test_budget_list_route_is_registered(self):
        response = self.client.get("/api/v1/admin/workflow-budgets")

        self.assertEqual(response.status_code, 401)

    def test_budget_detail_route_is_registered(self):
        response = self.client.get(f"/api/v1/admin/workflow-budgets/{uuid4()}")

        self.assertEqual(response.status_code, 401)

    def test_budget_upsert_route_is_registered(self):
        response = self.client.put(
            f"/api/v1/admin/workflow-budgets/{uuid4()}",
            json={"monthly_budget_usd": 100.0, "is_enabled": True},
        )

        self.assertEqual(response.status_code, 401)
