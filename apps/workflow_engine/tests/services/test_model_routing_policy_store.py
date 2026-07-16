from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

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


def test_claim_pending_auto_refresh_skips_delivery_after_refresh_started():
    """같은 자동 refresh의 중복 Celery delivery는 기존 update를 보고 건너뛴다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    policy = SimpleNamespace(
        id=uuid4(),
        enabled=True,
        status="refreshing",
        refresh_requested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    update_query = _Query(first_value=SimpleNamespace(id=uuid4()))
    db = MagicMock()
    db.query.return_value = update_query

    with patch.object(
        ModelRoutingPolicyStore,
        "_lock_policy_for_update",
        return_value=policy,
    ):
        claimed = ModelRoutingPolicyStore.claim_pending_auto_refresh(
            db,
            policy_id=policy.id,
        )

    assert claimed is None
    assert len(update_query.filters) == 2


def test_claim_pending_auto_refresh_allows_first_delivery_without_update():
    """아직 update가 없으면 첫 worker만 refresh를 시작할 수 있다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    policy = SimpleNamespace(
        id=uuid4(),
        enabled=True,
        status="refreshing",
        refresh_requested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    db = MagicMock()
    db.query.return_value = _Query(first_value=None)

    with patch.object(
        ModelRoutingPolicyStore,
        "_lock_policy_for_update",
        return_value=policy,
    ):
        claimed = ModelRoutingPolicyStore.claim_pending_auto_refresh(
            db,
            policy_id=policy.id,
        )

    assert claimed is policy


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


def test_successful_run_does_not_wait_for_auto_routing_node_in_an_unselected_branch():
    """조건 분기로 실행되지 않은 LLM node는 완료 로그를 기다리면 안 된다."""
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
                    "id": "llm-selected",
                    "type": "llmNode",
                    "data": {"auto_model_routing": True},
                },
                {
                    "id": "llm-unselected-branch",
                    "type": "llmNode",
                    "data": {"auto_model_routing": True},
                },
            ]
        }
    )
    selected_node = SimpleNamespace(
        node_id="llm-selected",
        status=NodeRunStatus.SUCCESS,
    )
    db = MagicMock()
    db.query.side_effect = [
        _Query(first_value=workflow_run),
        _Query(first_value=deployment),
        _Query(all_value=[selected_node]),
    ]
    policy = SimpleNamespace(id=uuid4())

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
        assert (
            ModelRoutingPolicyStore.record_completed_deployed_run(
                db,
                workflow_run_id=workflow_run.id,
            )
            == []
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


def test_record_completed_run_excludes_rag_safe_no_result_from_policy_evidence():
    """모델을 호출하지 않은 RAG 안전 응답은 routing 품질 표본이 아니다."""
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
    safe_rag_node = SimpleNamespace(
        node_id="llm-1",
        status=NodeRunStatus.SUCCESS,
        outputs={
            "metadata": {
                "rag": {
                    "failure_policy": "safe_no_result",
                    "evidence_sufficient": False,
                }
            }
        },
        trace_metadata={
            "rag": {
                "failure_policy": "safe_no_result",
                "evidence_sufficient": False,
            }
        },
    )
    db = MagicMock()
    db.query.side_effect = [
        _Query(first_value=workflow_run),
        _Query(first_value=deployment),
        _Query(all_value=[safe_rag_node]),
    ]

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


def test_routing_evidence_includes_successful_rag_run_with_safe_failure_policy():
    """safe_no_result 설정이 있어도 근거가 충분하면 실제 모델 실행 표본이다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    successful_rag_node = SimpleNamespace(
        outputs={
            "metadata": {
                "rag": {
                    "failure_policy": "safe_no_result",
                    "evidence_sufficient": True,
                }
            }
        },
        trace_metadata={
            "rag": {
                "failure_policy": "safe_no_result",
                "evidence_sufficient": True,
            }
        },
    )

    assert ModelRoutingPolicyStore._is_routing_evidence_eligible_node_run(
        successful_rag_node
    ) is True


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
        "strategy": "prior_guided_adaptive",
        "strategy_id": "prior_guided_adaptive_v1",
        "decision_profiles": [],
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


def test_bootstrap_policy_matches_google_catalog_ids_with_or_without_models_prefix():
    """배포 graph와 Google credential catalog의 표기가 달라도 bootstrap을 만들 수 있다."""
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
            return_value=["models/gemini-2.5-flash", "models/gemini-2.5-pro"],
        ),
    ):
        policy = ModelRoutingPolicyStore.ensure_policy_for_deployed_node(
            db,
            workflow_run=workflow_run,
            node_id="llm-1",
            node_data={
                "auto_model_routing": True,
                "model_id": "gemini-2.5-flash",
                "fallback_model_id": "gemini-2.5-pro",
            },
        )

    assert policy is not None
    assert policy.active_policy == {
        "strategy": "prior_guided_adaptive",
        "strategy_id": "prior_guided_adaptive_v1",
        "decision_profiles": [],
        "default_model_id": "models/gemini-2.5-flash",
        "fallback_model_id": "models/gemini-2.5-pro",
        "rules": [],
    }


def test_bootstrap_policy_preserves_deployment_max_cohorts_setting():
    """배포 snapshot의 입력군 상한은 첫 persisted policy에도 그대로 저장한다."""
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
        "model_routing_policy": {"max_cohorts": 8},
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
            return_value=["gpt-4.1"],
        ),
    ):
        policy = ModelRoutingPolicyStore.ensure_policy_for_deployed_node(
            db,
            workflow_run=workflow_run,
            node_id="llm-1",
            node_data=node_data,
        )

    assert policy is not None
    assert policy.max_cohorts == 8


def test_deployment_bootstrap_creates_policy_before_first_operational_run():
    """배포가 끝나면 운영 실행을 기다리지 않고 저장 모델 기반 정책을 만든다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    organization_id = uuid4()
    workflow_id = uuid4()
    deployment_id = uuid4()
    execution_subject_user_id = uuid4()
    db = MagicMock()
    graph_snapshot = {
        "nodes": [
            {
                "id": "llm-1",
                "type": "llmNode",
                "data": {
                    "auto_model_routing": True,
                    "model_id": "gpt-4.1",
                    "fallback_model_id": "gpt-4.1-mini",
                },
            }
        ]
    }

    with (
        patch.object(ModelRoutingPolicyStore, "get_runtime_policy", return_value=None),
        patch.object(
            LLMService,
            "get_runtime_available_model_ids_for_user",
            return_value=["gpt-4.1", "gpt-4.1-mini"],
        ),
    ):
        policies = ModelRoutingPolicyStore.ensure_policies_for_deployment(
            db,
            workflow_id=workflow_id,
            deployment_id=deployment_id,
            organization_id=organization_id,
            execution_subject_user_id=execution_subject_user_id,
            graph_snapshot=graph_snapshot,
        )

    assert len(policies) == 1
    assert policies[0].workflow_id == workflow_id
    assert policies[0].deployment_id == deployment_id
    assert policies[0].execution_subject_user_id == execution_subject_user_id
    assert policies[0].active_policy == {
        "strategy": "prior_guided_adaptive",
        "strategy_id": "prior_guided_adaptive_v1",
        "decision_profiles": [],
        "default_model_id": "gpt-4.1",
        "fallback_model_id": "gpt-4.1-mini",
        "rules": [],
    }


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


def test_first_policy_materializes_draft_cohorts_with_stable_ids():
    """첫 배포 정책은 graph 초안을 같은 UUID의 실제 입력군으로 승격한다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    draft_id = uuid4()
    policy = SimpleNamespace(id=uuid4(), organization_id=uuid4(), max_cohorts=6)
    workflow_run = SimpleNamespace(user_id=uuid4())
    node_data = {
        "model_id": "gpt-5.6-luna",
        "model_routing_policy": {
            "cohort_drafts": [
                {
                    "id": str(draft_id),
                    "key": "common_account_security",
                    "label": "공통 계정·보안 온보딩",
                    "representative_query": "입사 첫날 SSO와 보안 교육 순서를 알려 주세요.",
                    "representative_examples": [
                        "입사 첫날 SSO와 보안 교육 순서를 알려 주세요.",
                        "신규 입사자의 MFA 등록 절차가 궁금합니다.",
                        "첫 출근 전에 계정 보안 설정을 완료하고 싶습니다.",
                    ],
                    "fixed": True,
                }
            ]
        },
        "model_routing_context": {
            "semantic_router": {"encoder_model_id": "text-embedding-3-large"}
        },
    }
    db = MagicMock()
    db.query.return_value = _Query(first_value=None)
    embedding_client = SimpleNamespace(embed_sync=MagicMock(return_value=[0.1, 0.2]))

    with patch.object(
        LLMService,
        "get_runtime_available_embedding_model_ids_for_user",
        return_value=["text-embedding-3-large"],
    ), patch.object(
        LLMService,
        "get_runtime_client_for_user",
        return_value=SimpleNamespace(client=embedding_client),
    ), patch(
        "apps.workflow_engine.services.model_routing_adaptive_store."
        "AdaptiveModelRoutingCohortStore.create_manual_cohort",
        return_value=SimpleNamespace(id=draft_id),
    ) as create_cohort:
        created = ModelRoutingPolicyStore._materialize_draft_cohorts(
            db,
            policy=policy,
            workflow_run=workflow_run,
            node_data=node_data,
        )

    assert created == 1
    assert create_cohort.call_args.kwargs["cohort_id"] == draft_id
    assert create_cohort.call_args.kwargs["cohort_key"] == "common_account_security"
    assert create_cohort.call_args.kwargs["fixed"] is True


def test_invalid_legacy_draft_does_not_block_later_valid_cohort_materialization():
    """예문이 부족한 예전 초안 하나가 뒤의 정상 입력군 승격까지 막지 않는다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    policy = SimpleNamespace(id=uuid4(), organization_id=uuid4(), max_cohorts=6)
    workflow_run = SimpleNamespace(user_id=uuid4())
    node_data = {
        "model_id": "gpt-5.6-luna",
        "model_routing_policy": {
            "cohort_drafts": [
                {
                    "id": str(uuid4()),
                    "key": "legacy_one_example",
                    "label": "예전 입력군",
                    "representative_query": "대표 문의가 하나뿐입니다.",
                    "fixed": False,
                },
                {
                    "id": str(uuid4()),
                    "key": "valid_examples",
                    "label": "정상 입력군",
                    "representative_query": "정상 대표 문의입니다.",
                    "representative_examples": [
                        "정상 대표 문의입니다.",
                        "같은 의미의 두 번째 표현입니다.",
                        "같은 의미를 다른 상황으로 표현했습니다.",
                    ],
                    "fixed": False,
                },
            ]
        },
    }
    db = MagicMock()
    db.query.return_value = _Query(first_value=None)

    with patch.object(
        LLMService,
        "get_runtime_available_embedding_model_ids_for_user",
        return_value=["text-embedding-3-large"],
    ), patch.object(
        LLMService,
        "get_runtime_client_for_user",
        return_value=SimpleNamespace(
            client=SimpleNamespace(embed_sync=MagicMock(return_value=[0.1, 0.2]))
        ),
    ), patch(
        "apps.workflow_engine.services.model_routing_adaptive_store."
        "AdaptiveModelRoutingCohortStore.create_manual_cohort",
        side_effect=[
            ValueError("model_routing.cohort_examples_insufficient"),
            SimpleNamespace(id=uuid4()),
        ],
    ) as create_cohort:
        created = ModelRoutingPolicyStore._materialize_draft_cohorts(
            db,
            policy=policy,
            workflow_run=workflow_run,
            node_data=node_data,
        )

    assert created == 1
    assert create_cohort.call_count == 2


def test_existing_policy_does_not_materialize_legacy_cohort_drafts():
    """사전 지식 기반 정책은 이전 입력군 초안이나 임베딩 경로를 호출하지 않는다."""
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    existing_policy = SimpleNamespace(id=uuid4())
    workflow_run = SimpleNamespace(
        workflow_id=uuid4(),
        deployment_id=uuid4(),
        user_id=uuid4(),
    )
    node_data = {
        "auto_model_routing": True,
        "model_id": "gpt-5.6-luna",
        "model_routing_policy": {
            "cohort_drafts": [
                {
                    "id": str(uuid4()),
                    "key": "platform_access",
                    "label": "플랫폼 접근 온보딩",
                    "representative_query": "개발 저장소와 배포 권한 신청 절차를 알려 주세요.",
                    "fixed": False,
                }
            ]
        },
    }
    db = MagicMock()

    with (
        patch.object(
            ModelRoutingPolicyStore,
            "get_runtime_policy",
            return_value=existing_policy,
        ),
        patch.object(
            ModelRoutingPolicyStore,
            "_materialize_draft_cohorts",
            return_value=1,
        ) as materialize,
    ):
        policy = ModelRoutingPolicyStore.ensure_policy_for_deployed_node(
            db,
            workflow_run=workflow_run,
            node_id="llm-answer",
            node_data=node_data,
        )

    assert policy is existing_policy
    materialize.assert_not_called()
