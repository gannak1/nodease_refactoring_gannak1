import unittest
from datetime import date, datetime, timezone
from operator import eq, ge, le
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.api.v1.endpoints.users import list_my_audit_logs
from apps.gateway.main import app
from apps.shared.db.models.audit_log import (
    ActorType,
    AuditCategory,
    AuditLog,
    AuditStatus,
)
from apps.shared.db.session import get_db


class TestUsersAuditApi(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides = {}

    def test_list_my_audit_logs_filters_current_user_and_paginates(self):
        user_id = uuid4()
        other_user_id = uuid4()
        log = AuditLog(
            id=uuid4(),
            occurred_at=datetime.now(timezone.utc),
            actor_id=user_id,
            actor_type=ActorType.USER,
            category=AuditCategory.ACTION,
            action="app.create",
            status=AuditStatus.SUCCESS,
            audit_metadata={"request_id": "req-1"},
        )
        admin_log = AuditLog(
            id=uuid4(),
            occurred_at=datetime.now(timezone.utc),
            actor_id=user_id,
            actor_type=ActorType.ADMIN,
            category=AuditCategory.ACTION,
            action="admin.view",
            status=AuditStatus.SUCCESS,
        )
        other_user_log = AuditLog(
            id=uuid4(),
            occurred_at=datetime.now(timezone.utc),
            actor_id=other_user_id,
            actor_type=ActorType.USER,
            category=AuditCategory.ACTION,
            action="app.create",
            status=AuditStatus.SUCCESS,
        )

        query = _Query([log, admin_log, other_user_log])
        db = SimpleNamespace(query=lambda model: query)

        response = list_my_audit_logs(
            page=2,
            limit=10,
            db=db,
            current_user=SimpleNamespace(id=user_id),
        )

        self.assertEqual(response["total"], 1)
        self.assertEqual([item["id"] for item in response["items"]], [log.id])
        self.assertEqual(query.offset_value, 10)
        self.assertEqual(query.limit_value, 10)
        self.assertEqual(
            [(str(expr.left), expr.right.value) for expr in query.filter_expressions],
            [
                ("audit_logs.actor_id", user_id),
                ("audit_logs.actor_type", ActorType.USER),
            ],
        )
        self.assertEqual(
            [str(order.element) for order in query.order_by_values],
            ["audit_logs.occurred_at", "audit_logs.id"],
        )

    def test_list_my_audit_logs_filters_before_pagination(self):
        user_id = uuid4()
        logs = [
            AuditLog(
                id=uuid4(),
                occurred_at=datetime(2024, 1, day, tzinfo=timezone.utc),
                actor_id=user_id,
                actor_type=ActorType.USER,
                category=AuditCategory.ACTION,
                action="app.create",
                status=AuditStatus.SUCCESS,
            )
            for day in range(1, 12)
        ]
        match = AuditLog(
            id=uuid4(),
            occurred_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            actor_id=user_id,
            actor_type=ActorType.USER,
            category=AuditCategory.ACTION,
            action="app.delete",
            status=AuditStatus.FAILURE,
        )
        query = _Query(logs + [match], apply_paging=True)
        db = SimpleNamespace(query=lambda model: query)

        response = list_my_audit_logs(
            page=1,
            limit=10,
            status=AuditStatus.FAILURE,
            startDate=date(2024, 1, 15),
            endDate=date(2024, 1, 15),
            db=db,
            current_user=SimpleNamespace(id=user_id),
        )

        self.assertEqual(response["total"], 1)
        self.assertEqual([item["id"] for item in response["items"]], [match.id])
        self.assertEqual(query.offset_value, 0)
        self.assertEqual(query.limit_value, 10)

    def test_route_returns_current_user_audit_logs(self):
        user_id = uuid4()
        log_id = uuid4()
        occurred_at = datetime.now(timezone.utc)
        log = AuditLog(
            id=log_id,
            occurred_at=occurred_at,
            actor_id=user_id,
            actor_type=ActorType.USER,
            category=AuditCategory.ACTION,
            action="app.create",
            status=AuditStatus.SUCCESS,
            before={"api_key": "secret-before"},
            after={"api_key": "secret-after"},
            audit_metadata={
                "request_id": "req-1",
                "ip": "127.0.0.1",
                "user_agent": "test-agent",
            },
        )
        admin_log = AuditLog(
            id=uuid4(),
            occurred_at=occurred_at,
            actor_id=user_id,
            actor_type=ActorType.ADMIN,
            category=AuditCategory.ACTION,
            action="admin.view",
            status=AuditStatus.SUCCESS,
            audit_metadata={"request_id": "req-admin"},
        )
        query = _Query([log, admin_log])

        app.dependency_overrides[get_db] = lambda: SimpleNamespace(
            query=lambda model: query
        )
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=user_id
        )

        response = TestClient(app).get("/api/v1/users/me/audit-logs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "total": 1,
                "items": [
                    {
                        "id": str(log_id),
                        "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
                        "actor_id": str(user_id),
                        "actor_type": "user",
                        "category": "action",
                        "action": "app.create",
                        "target_type": None,
                        "target_id": None,
                        "status": "success",
                        "request_id": "req-1",
                    }
                ],
            },
        )


class _Query:
    def __init__(self, items, apply_paging=False):
        self.items = items
        self.apply_paging = apply_paging
        self.filter_expressions = []
        self.order_by_values = []
        self.offset_value = None
        self.limit_value = None

    def filter(self, *expressions):
        self.filter_expressions.extend(expressions)
        for expression in expressions:
            column = str(expression.left)
            value = expression.right.value
            operator = expression.operator
            if column == "audit_logs.actor_id" and operator is eq:
                self.items = [item for item in self.items if item.actor_id == value]
            if column == "audit_logs.actor_type" and operator is eq:
                self.items = [item for item in self.items if item.actor_type == value]
            if column == "audit_logs.status" and operator is eq:
                self.items = [item for item in self.items if item.status == value]
            if column == "audit_logs.occurred_at" and operator is ge:
                self.items = [item for item in self.items if item.occurred_at >= value]
            if column == "audit_logs.occurred_at" and operator is le:
                self.items = [item for item in self.items if item.occurred_at <= value]
        return self

    def count(self):
        return len(self.items)

    def order_by(self, *args):
        self.order_by_values.extend(args)
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        if self.apply_paging:
            start = self.offset_value or 0
            end = None if self.limit_value is None else start + self.limit_value
            return self.items[start:end]
        return self.items


if __name__ == "__main__":
    unittest.main()
