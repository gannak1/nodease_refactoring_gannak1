from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4


class _Query:
    def __init__(self, *, first_value=None, all_value=None):
        self.first_value = first_value
        self.all_value = all_value or []
        self.filters = []

    def filter(self, expression):
        self.filters.append(expression)
        return self

    def first(self):
        return self.first_value

    def all(self):
        return self.all_value


def test_record_completed_run_counts_only_successful_llm_node_runs():
    """실패/실행 중인 LLM node run은 정책 갱신 표본에 포함하지 않는다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    workflow_run = SimpleNamespace(
        id=uuid4(),
        workflow_id=uuid4(),
        deployment_id=uuid4(),
        trigger_mode="webhook",
        status="success",
    )
    deployment = SimpleNamespace(
        graph_snapshot={
            "nodes": [
                {
                    "id": "llm-1",
                    "data": {"auto_model_routing": True},
                }
            ]
        }
    )
    node_run = SimpleNamespace(node_id="llm-1")
    workflow_query = _Query(first_value=workflow_run)
    deployment_query = _Query(first_value=deployment)
    node_query = _Query(all_value=[node_run])
    db = MagicMock()
    db.query.side_effect = [workflow_query, deployment_query, node_query]
    policy = SimpleNamespace(id=uuid4())

    with (
        patch.object(
            ModelRoutingPolicyStore,
            "ensure_policy_for_deployed_node",
            return_value=policy,
        ),
        patch.object(
            ModelRoutingPolicyStore,
            "_record_policy_event",
            return_value=True,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_store.ModelRoutingPolicyLifecycleService.apply_run_event",
            return_value=SimpleNamespace(should_enqueue_refresh=False),
        ),
    ):
        assert (
            ModelRoutingPolicyStore.record_completed_deployed_run(
                db,
                workflow_run_id=workflow_run.id,
            )
            == []
        )

    assert len(node_query.filters) == 3
    assert "workflow_node_runs.status" in str(node_query.filters[-1])


def test_record_completed_run_ignores_deployment_snapshot_without_auto_routing():
    """draft 토글이 아니라 배포 snapshot의 자동 라우팅 ON 여부만 집계 기준이다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    workflow_run = SimpleNamespace(
        id=uuid4(),
        workflow_id=uuid4(),
        deployment_id=uuid4(),
        trigger_mode="api",
        status="success",
    )
    deployment = SimpleNamespace(
        graph_snapshot={
            "nodes": [
                {
                    "id": "llm-1",
                    "data": {"auto_model_routing": False},
                }
            ]
        }
    )
    workflow_query = _Query(first_value=workflow_run)
    deployment_query = _Query(first_value=deployment)
    node_query = _Query(all_value=[SimpleNamespace(node_id="llm-1")])
    db = MagicMock()
    db.query.side_effect = [workflow_query, deployment_query, node_query]

    with patch.object(
        ModelRoutingPolicyStore,
        "ensure_policy_for_deployed_node",
    ) as ensure_policy:
        assert (
            ModelRoutingPolicyStore.record_completed_deployed_run(
                db,
                workflow_run_id=workflow_run.id,
            )
            == []
        )

    ensure_policy.assert_not_called()
