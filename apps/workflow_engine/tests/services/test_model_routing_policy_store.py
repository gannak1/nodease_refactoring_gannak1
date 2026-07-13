from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from apps.shared.db.models.workflow_run import NodeRunStatus
from apps.workflow_engine.services.llm_service import LLMService


class _Query:
    def __init__(self, *, first_value=None, all_value=None):
        self.first_value = first_value
        self.all_value = all_value or []
        self.filters = []

    def filter(self, expression):
        self.filters.append(expression)
        return self

    def populate_existing(self):
        return self

    def with_for_update(self):
        self.with_for_update_called = True
        return self

    def first(self):
        return self.first_value

    def all(self):
        return self.all_value


def test_successful_run_waits_until_auto_routing_node_log_is_terminal():
    """workflow 성공보다 node finish 로그가 늦으면 집계 task가 재시도해야 한다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
        ModelRoutingRunLogPendingError,
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
                    "type": "llmNode",
                    "data": {"auto_model_routing": True},
                }
            ]
        }
    )
    running_node = SimpleNamespace(
        node_id="llm-1",
        status=NodeRunStatus.RUNNING,
    )
    db = MagicMock()
    db.query.side_effect = [
        _Query(first_value=workflow_run),
        _Query(first_value=deployment),
        _Query(all_value=[running_node]),
    ]

    with pytest.raises(ModelRoutingRunLogPendingError):
        ModelRoutingPolicyStore.record_completed_deployed_run(
            db,
            workflow_run_id=workflow_run.id,
        )


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
    node_run = SimpleNamespace(node_id="llm-1", status=NodeRunStatus.SUCCESS)
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
        patch.object(
            ModelRoutingPolicyStore,
            "_lock_policy_for_update",
            return_value=policy,
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
    assert "workflow_node_runs.node_id" in str(node_query.filters[-1])


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


def test_duplicate_run_requeues_refresh_that_is_still_pending_publish():
    """broker publish 실패 뒤 같은 run이 재시도되면 pending refresh를 다시 반환한다."""
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
            "nodes": [{"id": "llm-1", "data": {"auto_model_routing": True}}]
        }
    )
    policy = SimpleNamespace(
        id=uuid4(),
        enabled=True,
        status="refreshing",
        refresh_requested_at=object(),
    )
    db = MagicMock()
    db.query.side_effect = [
        _Query(first_value=workflow_run),
        _Query(first_value=deployment),
        _Query(
            all_value=[
                SimpleNamespace(node_id="llm-1", status=NodeRunStatus.SUCCESS)
            ]
        ),
    ]

    with (
        patch.object(
            ModelRoutingPolicyStore,
            "ensure_policy_for_deployed_node",
            return_value=policy,
        ),
        patch.object(ModelRoutingPolicyStore, "_record_policy_event", return_value=False),
        patch.object(
            ModelRoutingPolicyStore,
            "_lock_policy_for_update",
            return_value=policy,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_store.ModelRoutingPolicyLifecycleService.apply_run_event",
            return_value=SimpleNamespace(should_enqueue_refresh=False),
        ),
    ):
        scheduled = ModelRoutingPolicyStore.record_completed_deployed_run(
            db,
            workflow_run_id=workflow_run.id,
        )

    assert scheduled == [policy.id]


def test_new_run_does_not_reenqueue_refresh_already_requested_by_another_run():
    """갱신 중인 policy에는 다른 신규 run이 broker 메시지를 중복 발행하지 않는다."""
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
            "nodes": [{"id": "llm-1", "data": {"auto_model_routing": True}}]
        }
    )
    policy = SimpleNamespace(
        id=uuid4(),
        enabled=True,
        status="refreshing",
        refresh_requested_at=object(),
    )
    db = MagicMock()
    db.query.side_effect = [
        _Query(first_value=workflow_run),
        _Query(first_value=deployment),
        _Query(
            all_value=[
                SimpleNamespace(node_id="llm-1", status=NodeRunStatus.SUCCESS)
            ]
        ),
    ]

    with (
        patch.object(
            ModelRoutingPolicyStore,
            "ensure_policy_for_deployed_node",
            return_value=policy,
        ),
        patch.object(ModelRoutingPolicyStore, "_record_policy_event", return_value=True),
        patch.object(
            ModelRoutingPolicyStore,
            "_lock_policy_for_update",
            return_value=policy,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_store.ModelRoutingPolicyLifecycleService.apply_run_event",
            return_value=SimpleNamespace(should_enqueue_refresh=False),
        ),
    ):
        scheduled = ModelRoutingPolicyStore.record_completed_deployed_run(
            db,
            workflow_run_id=workflow_run.id,
        )

    assert scheduled == []


def test_bootstrap_policy_skips_model_without_run_users_credential_use_permission():
    """첫 배포 정책은 실행 주체가 사용할 수 있는 configured model이 있을 때만 생성한다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    organization_id = uuid4()
    workflow_run = SimpleNamespace(
        workflow_id=uuid4(),
        deployment_id=uuid4(),
        user_id=uuid4(),
    )
    db = MagicMock()

    with (
        patch.object(ModelRoutingPolicyStore, "get_runtime_policy", return_value=None),
        patch.object(
            ModelRoutingPolicyStore,
            "_organization_id_for_run",
            return_value=organization_id,
        ),
        patch.object(
            LLMService,
            "get_runtime_available_model_ids_for_user",
            return_value=["gpt-4.1-mini"],
        ) as available_models,
    ):
        policy = ModelRoutingPolicyStore.ensure_policy_for_deployed_node(
            db,
            workflow_run=workflow_run,
            node_id="llm-1",
            node_data={"auto_model_routing": True, "model_id": "gpt-4.1"},
        )

    assert policy is None
    available_models.assert_called_once_with(
        db,
        user_id=workflow_run.user_id,
        organization_id=organization_id,
    )
    db.add.assert_not_called()


def test_bootstrap_policy_ignores_legacy_active_policy_and_preserves_node_models():
    """첫 persisted policy는 legacy snapshot이 아니라 배포 node의 현재 모델을 보존한다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    organization_id = uuid4()
    workflow_run = SimpleNamespace(
        workflow_id=uuid4(),
        deployment_id=uuid4(),
        user_id=uuid4(),
    )
    db = MagicMock()
    node_data = {
        "auto_model_routing": True,
        "model_id": "gpt-4.1",
        "fallback_model_id": "gpt-4.1-mini",
        "model_routing_policy": {
            "policy_version": "legacy-stale-v9",
            "active_policy": {
                "default_model_id": "gpt-4o-mini",
                "fallback_model_id": "gpt-4o",
                "rules": [
                    {
                        "id": "legacy-cheap-route",
                        "selected_model_id": "gpt-4o-mini",
                    }
                ],
            },
            "refresh": {"refresh_every_runs": 35},
        },
    }

    with (
        patch.object(ModelRoutingPolicyStore, "get_runtime_policy", return_value=None),
        patch.object(
            ModelRoutingPolicyStore,
            "_organization_id_for_run",
            return_value=organization_id,
        ),
        patch.object(
            LLMService,
            "get_runtime_available_model_ids_for_user",
            return_value=["gpt-4.1", "gpt-4.1-mini"],
        ) as available_models,
    ):
        policy = ModelRoutingPolicyStore.ensure_policy_for_deployed_node(
            db,
            workflow_run=workflow_run,
            node_id="llm-1",
            node_data=node_data,
        )

    assert policy.active_policy == {
        "default_model_id": "gpt-4.1",
        "fallback_model_id": "gpt-4.1-mini",
        "rules": [],
    }
    assert policy.policy_version == "bootstrap-preserve-config-v1"
    assert policy.refresh_every_runs == 35
    available_models.assert_called_once_with(
        db,
        user_id=workflow_run.user_id,
        organization_id=organization_id,
    )


def test_record_completed_run_locks_policies_in_node_id_order_before_counting():
    """동시 운영 run은 동일 policy 카운터를 결정적 순서로 잠근 뒤 반영한다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    workflow_run = SimpleNamespace(
        id=uuid4(),
        workflow_id=uuid4(),
        deployment_id=uuid4(),
        trigger_mode="scheduler",
        status="success",
    )
    deployment = SimpleNamespace(
        graph_snapshot={
            "nodes": [
                {"id": "llm-a", "data": {"auto_model_routing": True}},
                {"id": "llm-z", "data": {"auto_model_routing": True}},
            ]
        }
    )
    policy_by_node = {
        "llm-a": SimpleNamespace(id=uuid4()),
        "llm-z": SimpleNamespace(id=uuid4()),
    }
    db = MagicMock()
    db.query.side_effect = [
        _Query(first_value=workflow_run),
        _Query(first_value=deployment),
        _Query(
            all_value=[
                    SimpleNamespace(node_id="llm-z", status=NodeRunStatus.SUCCESS),
                    SimpleNamespace(node_id="llm-a", status=NodeRunStatus.SUCCESS),
            ]
        ),
    ]
    locked_policy_ids = []

    def lock_policy(_db, *, policy_id):
        locked_policy_ids.append(policy_id)
        return next(policy for policy in policy_by_node.values() if policy.id == policy_id)

    with (
        patch.object(
            ModelRoutingPolicyStore,
            "ensure_policy_for_deployed_node",
            side_effect=lambda _db, **kwargs: policy_by_node[kwargs["node_id"]],
        ),
        patch.object(ModelRoutingPolicyStore, "_record_policy_event", return_value=True),
        patch.object(
            ModelRoutingPolicyStore,
            "_lock_policy_for_update",
            side_effect=lock_policy,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_store.ModelRoutingPolicyLifecycleService.apply_run_event",
            return_value=SimpleNamespace(should_enqueue_refresh=False),
        ) as apply_run_event,
    ):
        ModelRoutingPolicyStore.record_completed_deployed_run(
            db,
            workflow_run_id=workflow_run.id,
        )

    expected_policy_ids = [policy_by_node["llm-a"].id, policy_by_node["llm-z"].id]
    assert locked_policy_ids == expected_policy_ids
    assert [call.args[0].id for call in apply_run_event.call_args_list] == expected_policy_ids
