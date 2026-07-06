"""workflow 예산 관리 API(FR-051) route 등록 테스트.

TDD red phase: route가 아직 없으므로 404로 실패해야 한다.
route가 등록되어 있으면 미인증 요청은 404가 아니라 인증 실패 401로 끝난다
(test_admin_usage_api.py와 같은 패턴).
"""

from datetime import datetime, timezone
from decimal import Decimal
import unittest
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from apps.gateway.api.v1.endpoints import admin as admin_endpoint
from apps.gateway.main import app
from apps.shared.db.models.workflow_budget import WorkflowBudget

KST = ZoneInfo("Asia/Seoul")


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


def test_budget_usage_serialization_passes_timezone_aware_kst_now(monkeypatch):
    captured = {}
    workflow_id = uuid4()
    now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    budget = WorkflowBudget(
        id=uuid4(),
        organization_id=uuid4(),
        workflow_id=workflow_id,
        monthly_budget_usd=Decimal("100.00"),
        is_enabled=True,
        created_at=now,
        updated_at=now,
    )

    def fake_get_current_month_cost(db, *, workflow_id, now):
        captured["workflow_id"] = workflow_id
        captured["now"] = now
        return Decimal("1.00")

    monkeypatch.setattr(
        admin_endpoint.WorkflowBudgetService,
        "get_current_month_cost",
        staticmethod(fake_get_current_month_cost),
    )

    response = admin_endpoint._serialize_workflow_budget(
        db=object(),
        budget=budget,
        workflow_name="예산 워크플로우",
        include_usage=True,
    )

    assert response.current_month_cost == 1.0
    assert captured["workflow_id"] == workflow_id
    assert captured["now"].tzinfo is not None
    assert captured["now"].utcoffset() == KST.utcoffset(captured["now"])
