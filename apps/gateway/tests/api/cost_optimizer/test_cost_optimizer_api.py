from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.main import app
from apps.shared.db.session import get_db


def _workflow_with_nodes(workflow_id, organization_id, nodes):
    return SimpleNamespace(
        id=workflow_id,
        organization_id=organization_id,
        graph={
            "nodes": nodes,
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    )


class TestCostOptimizerAvailabilityApi:
    def setup_method(self):
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides = {}

    def test_fr1_llm_node_availability_returns_available_for_builder(self):
        workflow_id = uuid4()
        organization_id = uuid4()
        user_id = uuid4()
        db = MagicMock()
        workflow = _workflow_with_nodes(
            workflow_id,
            organization_id,
            [
                {
                    "id": "llm-triage",
                    "type": "llmNode",
                    "position": {"x": 100, "y": 120},
                    "data": {"label": "티켓 처리 판단", "model_id": "gpt-4.1-mini"},
                }
            ],
        )

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)

        with patch(
            "apps.gateway.api.v1.endpoints.workflow.ensure_workflow_permission",
            return_value=workflow,
        ) as ensure_builder:
            response = self.client.get(
                f"/api/v1/workflows/{workflow_id}/llm-nodes/llm-triage"
                "/cost-optimizer/availability"
            )

        assert response.status_code == 200
        ensure_builder.assert_called_once_with(db, SimpleNamespace(id=user_id), str(workflow_id), "write")
        assert response.json() == {
            "available": True,
            "reason": None,
            "workflow_id": str(workflow_id),
            "node_id": "llm-triage",
            "node_type": "llmNode",
            "permission": {
                "can_compare": True,
                "can_apply": True,
                "required_auth_state": "builder",
            },
        }

    def test_fr1_non_llm_node_is_rejected(self):
        workflow_id = uuid4()
        organization_id = uuid4()
        user_id = uuid4()
        db = MagicMock()
        workflow = _workflow_with_nodes(
            workflow_id,
            organization_id,
            [
                {
                    "id": "start",
                    "type": "startNode",
                    "position": {"x": 0, "y": 0},
                    "data": {"label": "입력"},
                }
            ],
        )

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)

        with patch(
            "apps.gateway.api.v1.endpoints.workflow.ensure_workflow_permission",
            return_value=workflow,
        ):
            response = self.client.get(
                f"/api/v1/workflows/{workflow_id}/llm-nodes/start"
                "/cost-optimizer/availability"
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "cost_optimizer.not_llm_node"

    def test_fr1_missing_node_returns_resource_not_found(self):
        workflow_id = uuid4()
        organization_id = uuid4()
        user_id = uuid4()
        db = MagicMock()
        workflow = _workflow_with_nodes(
            workflow_id,
            organization_id,
            [
                {
                    "id": "llm-triage",
                    "type": "llmNode",
                    "position": {"x": 100, "y": 120},
                    "data": {"label": "티켓 처리 판단"},
                }
            ],
        )

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)

        with patch(
            "apps.gateway.api.v1.endpoints.workflow.ensure_workflow_permission",
            return_value=workflow,
        ):
            response = self.client.get(
                f"/api/v1/workflows/{workflow_id}/llm-nodes/missing-node"
                "/cost-optimizer/availability"
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "resource.not_found"

    def test_fr1_availability_requires_builder_permission(self):
        workflow_id = uuid4()
        user_id = uuid4()
        db = MagicMock()
        denied = HTTPException(status_code=403, detail="Forbidden")
        setattr(denied, "audit_recorded", True)

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)

        with patch(
            "apps.gateway.api.v1.endpoints.workflow.ensure_workflow_permission",
            side_effect=denied,
        ) as ensure_builder:
            response = self.client.get(
                f"/api/v1/workflows/{workflow_id}/llm-nodes/llm-triage"
                "/cost-optimizer/availability"
            )

        assert response.status_code == 403
        ensure_builder.assert_called_once()
        assert ensure_builder.call_args.args[3] == "write"
