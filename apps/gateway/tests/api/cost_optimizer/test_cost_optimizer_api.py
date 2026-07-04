from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.api.v1.endpoints import workflow as workflow_endpoint
from apps.gateway.main import app
from apps.shared.db.models.workflow_run import NodeRunStatus
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


def _baseline_row(
    baseline_id=None,
    workflow_run_id=None,
    *,
    input_available=True,
    compare_available=True,
):
    baseline_id = baseline_id or uuid4()
    workflow_run_id = workflow_run_id or uuid4()
    return {
        "baseline_id": str(baseline_id),
        "baseline_source": "workflow_node_run",
        "source_workflow_node_run_id": str(baseline_id),
        "workflow_run_id": str(workflow_run_id),
        "workflow_id": "workflow-id",
        "node_id": "llm-triage",
        "run_started_at": "2026-07-04T00:00:00Z",
        "workflow_run_status": "success",
        "node_status": "success",
        "model": "gpt-4.1-mini",
        "cost": 0.0012,
        "total_tokens": 420,
        "latency_ms": 1800,
        "input_available": input_available,
        "output_available": True,
        "usage_available": True,
        "trace_available": True,
        "compare_available": compare_available,
        "unavailable_reason": None
        if compare_available
        else "input_payload_unavailable",
        "input_preview": "고객 문의를 분류해줘",
        "output_preview": "billing",
        "has_trace": True,
        "node_options": {
            "model_id": "gpt-4.1-mini",
            "system_prompt": "baseline system prompt",
            "parameters": {"max_tokens": 800, "temperature": 0.2},
        },
        "usage": {
            "model": "gpt-4.1-mini",
            "prompt_tokens": 300,
            "completion_tokens": 120,
            "total_tokens": 420,
            "cost": 0.0012,
            "latency_ms": 1800,
            "status": "success",
        },
        "trace": {
            "input_preview": "고객 문의를 분류해줘",
            "output_preview": "billing",
            "messages_preview": [],
            "rag_summary": None,
            "error_message": None,
        },
        "downstream_compatibility": {
            "state": "compatible",
            "label": "검증 가능",
            "message": "baseline downstream is compatible",
        },
    }


class TestCostOptimizerBaselinesApi:
    def setup_method(self):
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides = {}

    def test_fr2_latest_baseline_returns_most_recent_comparable_node_run(self):
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
        baseline = _baseline_row()

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)

        with (
            patch(
                "apps.gateway.api.v1.endpoints.workflow.ensure_workflow_permission",
                return_value=workflow,
            ) as ensure_builder,
            patch(
                "apps.gateway.api.v1.endpoints.workflow.get_cost_optimizer_latest_baseline",
                return_value=baseline,
                create=True,
            ) as get_latest,
        ):
            response = self.client.get(
                f"/api/v1/workflows/{workflow_id}/llm-nodes/llm-triage"
                "/cost-optimizer/baselines/latest"
            )

        assert response.status_code == 200
        ensure_builder.assert_called_once_with(db, SimpleNamespace(id=user_id), str(workflow_id), "write")
        get_latest.assert_called_once_with(db, workflow, "llm-triage")
        payload = response.json()
        assert payload["baseline"]["baseline_id"] == baseline["baseline_id"]
        assert payload["baseline"]["input_available"] is True
        assert payload["baseline"]["output_available"] is True
        assert payload["baseline"]["usage_available"] is True
        assert payload["baseline"]["compare_available"] is True

    def test_fr2_latest_baseline_returns_no_baseline_when_comparable_log_is_missing(self):
        workflow_id = uuid4()
        organization_id = uuid4()
        user_id = uuid4()
        db = MagicMock()
        workflow = _workflow_with_nodes(
            workflow_id,
            organization_id,
            [{"id": "llm-triage", "type": "llmNode", "position": {"x": 0, "y": 0}, "data": {}}],
        )

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)

        with (
            patch(
                "apps.gateway.api.v1.endpoints.workflow.ensure_workflow_permission",
                return_value=workflow,
            ),
            patch(
                "apps.gateway.api.v1.endpoints.workflow.get_cost_optimizer_latest_baseline",
                side_effect=HTTPException(
                    status_code=400,
                    detail="cost_optimizer.no_baseline",
                ),
                create=True,
            ),
        ):
            response = self.client.get(
                f"/api/v1/workflows/{workflow_id}/llm-nodes/llm-triage"
                "/cost-optimizer/baselines/latest"
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "cost_optimizer.no_baseline"

    def test_fr2_baseline_list_returns_pagination_and_non_comparable_rows_without_secrets(self):
        workflow_id = uuid4()
        organization_id = uuid4()
        user_id = uuid4()
        db = MagicMock()
        workflow = _workflow_with_nodes(
            workflow_id,
            organization_id,
            [{"id": "llm-triage", "type": "llmNode", "position": {"x": 0, "y": 0}, "data": {}}],
        )
        rows = [
            _baseline_row(),
            _baseline_row(input_available=False, compare_available=False),
        ]

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)

        with (
            patch(
                "apps.gateway.api.v1.endpoints.workflow.ensure_workflow_permission",
                return_value=workflow,
            ),
            patch(
                "apps.gateway.api.v1.endpoints.workflow.list_cost_optimizer_baselines",
                return_value={"total": 2, "limit": 20, "offset": 0, "items": rows},
                create=True,
            ) as list_baselines,
        ):
            response = self.client.get(
                f"/api/v1/workflows/{workflow_id}/llm-nodes/llm-triage"
                "/cost-optimizer/baselines"
            )

        assert response.status_code == 200
        list_baselines.assert_called_once()
        payload = response.json()
        assert payload["total"] == 2
        assert payload["items"][1]["input_available"] is False
        assert payload["items"][1]["compare_available"] is False
        assert payload["items"][1]["unavailable_reason"] == "input_payload_unavailable"
        serialized = response.text
        assert "api_key" not in serialized
        assert "encrypted_config" not in serialized
        assert "raw_payload" not in serialized

    def test_fr2_baseline_list_passes_search_filter_sort_and_pagination_options(self):
        workflow_id = uuid4()
        organization_id = uuid4()
        user_id = uuid4()
        db = MagicMock()
        workflow = _workflow_with_nodes(
            workflow_id,
            organization_id,
            [{"id": "llm-triage", "type": "llmNode", "position": {"x": 0, "y": 0}, "data": {}}],
        )

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)

        with (
            patch(
                "apps.gateway.api.v1.endpoints.workflow.ensure_workflow_permission",
                return_value=workflow,
            ),
            patch(
                "apps.gateway.api.v1.endpoints.workflow.list_cost_optimizer_baselines",
                return_value={"total": 0, "limit": 10, "offset": 20, "items": []},
                create=True,
            ) as list_baselines,
        ):
            response = self.client.get(
                f"/api/v1/workflows/{workflow_id}/llm-nodes/llm-triage"
                "/cost-optimizer/baselines"
                "?q=billing&model=gpt-4.1-mini"
                "&date_from=2026-07-01T00:00:00Z"
                "&date_to=2026-07-04T23:59:59Z"
                "&sort=cost_desc&compare_available=true&limit=10&offset=20"
            )

        assert response.status_code == 200
        list_baselines.assert_called_once_with(
            db,
            workflow,
            "llm-triage",
            q="billing",
            model="gpt-4.1-mini",
            date_from=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
            date_to=datetime(2026, 7, 4, 23, 59, 59, tzinfo=timezone.utc),
            sort="cost_desc",
            compare_available=True,
            limit=10,
            offset=20,
        )


class TestCostOptimizerBaselineHelpers:
    def test_fr2_latest_baseline_ignores_non_comparable_rows(self):
        workflow = SimpleNamespace(id=uuid4())
        comparable = _baseline_row(
            baseline_id=uuid4(),
            workflow_run_id=uuid4(),
            input_available=True,
            compare_available=True,
        )
        comparable["run_started_at"] = "2026-07-03T00:00:00+00:00"
        non_comparable_newer = _baseline_row(
            baseline_id=uuid4(),
            workflow_run_id=uuid4(),
            input_available=False,
            compare_available=False,
        )
        non_comparable_newer["run_started_at"] = "2026-07-04T00:00:00+00:00"

        with patch(
            "apps.gateway.api.v1.endpoints.workflow._cost_optimizer_baseline_rows",
            return_value=[comparable, non_comparable_newer],
        ):
            result = workflow_endpoint.get_cost_optimizer_latest_baseline(
                MagicMock(),
                workflow,
                "llm-triage",
            )

        assert result["baseline_id"] == comparable["baseline_id"]
        assert result["compare_available"] is True

    def test_fr2_latest_baseline_raises_when_only_non_comparable_rows_exist(self):
        workflow = SimpleNamespace(id=uuid4())
        non_comparable = _baseline_row(input_available=False, compare_available=False)

        with (
            patch(
                "apps.gateway.api.v1.endpoints.workflow._cost_optimizer_baseline_rows",
                return_value=[non_comparable],
            ),
        ):
            try:
                workflow_endpoint.get_cost_optimizer_latest_baseline(
                    MagicMock(),
                    workflow,
                    "llm-triage",
                )
            except HTTPException as exc:
                assert exc.status_code == 400
                assert exc.detail == "cost_optimizer.no_baseline"
            else:
                raise AssertionError("expected cost_optimizer.no_baseline")

    def test_fr2_baseline_list_filters_by_search_model_date_and_compare_available(self):
        workflow = SimpleNamespace(id=uuid4())
        matched = _baseline_row()
        matched.update(
            {
                "baseline_id": "matched",
                "run_started_at": "2026-07-03T00:00:00+00:00",
                "model": "gpt-4.1-mini",
                "input_preview": "billing escalation",
                "output_preview": "enterprise response",
                "compare_available": True,
            }
        )
        wrong_query = _baseline_row()
        wrong_query.update(
            {
                "baseline_id": "wrong-query",
                "run_started_at": "2026-07-03T00:00:00+00:00",
                "model": "gpt-4.1-mini",
                "input_preview": "refund request",
                "output_preview": "consumer response",
                "compare_available": True,
            }
        )
        wrong_model = _baseline_row()
        wrong_model.update(
            {
                "baseline_id": "wrong-model",
                "run_started_at": "2026-07-03T00:00:00+00:00",
                "model": "claude-3-haiku",
                "input_preview": "billing escalation",
                "output_preview": "enterprise response",
                "compare_available": True,
            }
        )
        wrong_compare_state = _baseline_row(input_available=False, compare_available=False)
        wrong_compare_state.update(
            {
                "baseline_id": "wrong-compare",
                "run_started_at": "2026-07-03T00:00:00+00:00",
                "model": "gpt-4.1-mini",
                "input_preview": "billing escalation",
                "output_preview": "enterprise response",
            }
        )
        outside_date = _baseline_row()
        outside_date.update(
            {
                "baseline_id": "outside-date",
                "run_started_at": "2026-06-30T00:00:00+00:00",
                "model": "gpt-4.1-mini",
                "input_preview": "billing escalation",
                "output_preview": "enterprise response",
                "compare_available": True,
            }
        )

        with patch(
            "apps.gateway.api.v1.endpoints.workflow._cost_optimizer_baseline_rows",
            return_value=[
                matched,
                wrong_query,
                wrong_model,
                wrong_compare_state,
                outside_date,
            ],
        ):
            result = workflow_endpoint.list_cost_optimizer_baselines(
                MagicMock(),
                workflow,
                "llm-triage",
                q="billing",
                model="gpt-4.1-mini",
                date_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
                date_to=datetime(2026, 7, 4, tzinfo=timezone.utc),
                compare_available=True,
            )

        assert result["total"] == 1
        assert [row["baseline_id"] for row in result["items"]] == ["matched"]

    def test_fr2_baseline_list_applies_sort_and_offset_limit(self):
        workflow = SimpleNamespace(id=uuid4())
        cheap = _baseline_row()
        cheap.update({"baseline_id": "cheap", "cost": 0.1, "total_tokens": 100})
        medium = _baseline_row()
        medium.update({"baseline_id": "medium", "cost": 0.5, "total_tokens": 300})
        expensive = _baseline_row()
        expensive.update({"baseline_id": "expensive", "cost": 0.9, "total_tokens": 900})

        with patch(
            "apps.gateway.api.v1.endpoints.workflow._cost_optimizer_baseline_rows",
            return_value=[cheap, expensive, medium],
        ):
            result = workflow_endpoint.list_cost_optimizer_baselines(
                MagicMock(),
                workflow,
                "llm-triage",
                sort="cost_desc",
                limit=1,
                offset=1,
            )

        assert result["total"] == 3
        assert result["limit"] == 1
        assert result["offset"] == 1
        assert [row["baseline_id"] for row in result["items"]] == ["medium"]

    def test_fr2_baseline_row_redacts_secret_values_from_previews_and_payload(self):
        workflow = SimpleNamespace(id=uuid4())
        run = SimpleNamespace(
            id=uuid4(),
            workflow_id=workflow.id,
            status=SimpleNamespace(value="success"),
            started_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
        )
        node_run = SimpleNamespace(
            id=uuid4(),
            workflow_run_id=run.id,
            node_id="llm-triage",
            node_type="llmNode",
            status=SimpleNamespace(value="success"),
            inputs={"message": "hello", "api_key": "sk-secret"},
            outputs={"answer": "done", "encrypted_config": "ciphertext"},
            process_data={
                "node_options": {
                    "model_id": "gpt-4.1-mini",
                    "api_key": "sk-process-secret",
                    "parameters": {"temperature": 0.2},
                }
            },
            error_message=None,
            trace_metadata={"trace_id": "trace-1"},
        )
        usage = SimpleNamespace(
            model=SimpleNamespace(model_id_for_api_call="gpt-4.1-mini"),
            model_id=uuid4(),
            prompt_tokens=10,
            completion_tokens=5,
            total_cost=0.0001,
            latency_ms=300,
            status="success",
        )

        row = workflow_endpoint._baseline_row_from_records(
            workflow=workflow,
            run=run,
            node_run=node_run,
            usage=usage,
        )

        serialized = str(row)
        assert "sk-secret" not in serialized
        assert "sk-process-secret" not in serialized
        assert "ciphertext" not in serialized
        assert row["input"]["api_key"] == "[REDACTED]"
        assert row["output"]["encrypted_config"] == "[REDACTED]"
        assert row["node_options"]["api_key"] == "[REDACTED]"
        assert row["node_options"]["model_id"] == "gpt-4.1-mini"

    def test_fr2_baseline_query_filters_failed_node_runs_at_db_boundary(self):
        db = MagicMock()
        query = db.query.return_value
        workflow = SimpleNamespace(id=uuid4())

        workflow_endpoint._cost_optimizer_baseline_rows(db, workflow, "llm-triage")

        filter_args = query.join.return_value.join.return_value.filter.call_args.args
        assert any(
            str(arg).endswith("workflow_node_runs.status = :status_1")
            for arg in filter_args
        )
        assert any(
            getattr(arg, "right", None).value == NodeRunStatus.SUCCESS
            for arg in filter_args
            if hasattr(getattr(arg, "right", None), "value")
        )

    def test_fr2_trace_payload_redacted_input_should_drive_preview_and_availability(self):
        workflow = SimpleNamespace(id=uuid4())
        run = SimpleNamespace(
            id=uuid4(),
            workflow_id=workflow.id,
            status=SimpleNamespace(value="success"),
            started_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
        )
        node_run = SimpleNamespace(
            id=uuid4(),
            workflow_run_id=run.id,
            node_id="llm-triage",
            node_type="llmNode",
            status=SimpleNamespace(value="success"),
            inputs=None,
            outputs={"fallback": "node output should not be preview source"},
            error_message=None,
            trace_metadata={"trace_id": "trace-1"},
            trace_payloads=[
                SimpleNamespace(
                    payload_kind="input",
                    retention_purged_at=None,
                    redacted_payload={"message": "trace safe input"},
                ),
                SimpleNamespace(
                    payload_kind="output",
                    retention_purged_at=None,
                    redacted_payload={"answer": "trace safe output"},
                ),
            ],
        )
        usage = SimpleNamespace(
            model=SimpleNamespace(model_id_for_api_call="gpt-4.1-mini"),
            model_id=uuid4(),
            prompt_tokens=10,
            completion_tokens=5,
            total_cost=0.0001,
            latency_ms=300,
            status="success",
        )

        row = workflow_endpoint._baseline_row_from_records(
            workflow=workflow,
            run=run,
            node_run=node_run,
            usage=usage,
        )

        assert row["input_available"] is True
        assert row["compare_available"] is True
        assert "trace safe input" in row["input_preview"]
        assert "trace safe output" in row["output_preview"]

    def test_fr2_purged_trace_input_marks_row_not_comparable(self):
        workflow = SimpleNamespace(id=uuid4())
        run = SimpleNamespace(
            id=uuid4(),
            workflow_id=workflow.id,
            status=SimpleNamespace(value="success"),
            started_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
        )
        node_run = SimpleNamespace(
            id=uuid4(),
            workflow_run_id=run.id,
            node_id="llm-triage",
            node_type="llmNode",
            status=SimpleNamespace(value="success"),
            inputs={"message": "node input should be blocked by trace retention"},
            outputs={"answer": "ok"},
            error_message=None,
            trace_metadata={"trace_id": "trace-1"},
            trace_payloads=[
                SimpleNamespace(
                    payload_kind="input",
                    retention_purged_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
                    redacted_payload={"message": "purged input"},
                ),
                SimpleNamespace(
                    payload_kind="output",
                    retention_purged_at=None,
                    redacted_payload={"answer": "safe output"},
                ),
            ],
        )
        usage = SimpleNamespace(
            model=SimpleNamespace(model_id_for_api_call="gpt-4.1-mini"),
            model_id=uuid4(),
            prompt_tokens=10,
            completion_tokens=5,
            total_cost=0.0001,
            latency_ms=300,
            status="success",
        )

        row = workflow_endpoint._baseline_row_from_records(
            workflow=workflow,
            run=run,
            node_run=node_run,
            usage=usage,
        )

        assert row["input_available"] is False
        assert row["compare_available"] is False
        assert row["unavailable_reason"] == "input_payload_unavailable"
