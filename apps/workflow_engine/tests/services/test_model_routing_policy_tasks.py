from unittest.mock import MagicMock, patch
from uuid import uuid4


def test_operational_run_task_dispatches_refresh_for_due_policy():
    """운영 run 집계 결과가 due policy를 반환하면 refresh task를 dispatch한다."""
    from apps.workflow_engine import tasks

    policy_id = uuid4()
    session = MagicMock()
    sent = []

    with (
        patch.object(tasks, "SessionLocal", return_value=session),
        patch.object(
            tasks.celery_app,
            "send_task",
            side_effect=lambda *args, **kwargs: sent.append((args, kwargs)),
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_store.ModelRoutingPolicyStore.record_completed_deployed_run",
            return_value=[policy_id],
        ),
    ):
        result = tasks.record_model_routing_operational_run.__wrapped__(str(uuid4()))

    assert result == {"status": "success", "scheduled_policy_ids": [str(policy_id)]}
    session.commit.assert_called_once()
    assert sent == [
        (
            ("workflow.model_routing.refresh_policy",),
            {
                "args": [str(policy_id), "score_change"],
                "kwargs": {},
                "argsrepr": "[workflow arguments redacted]",
                "kwargsrepr": "{workflow arguments redacted}",
            },
        )
    ]


def test_duplicate_auto_refresh_delivery_is_skipped_after_request_is_consumed():
    """publish 재시도로 같은 auto refresh가 다시 와도 judge를 다시 호출하지 않는다."""
    from apps.workflow_engine import tasks
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    session = MagicMock()
    policy_id = uuid4()

    with (
        patch.object(tasks, "SessionLocal", return_value=session),
        patch.object(
            ModelRoutingPolicyStore,
            "claim_pending_auto_refresh",
            return_value=None,
        ) as claim_pending,
        patch.object(PersistedModelRoutingPolicyRefreshService, "refresh") as refresh,
    ):
        result = tasks.refresh_model_routing_policy.__wrapped__(
            str(policy_id), "score_change"
        )

    assert result == {"status": "skipped", "update_id": None, "result": None}
    claim_pending.assert_called_once_with(session, policy_id=str(policy_id))
    refresh.assert_not_called()


def test_deployment_bootstrap_task_compiles_prior_guided_policy_without_validation_batch():
    """배포 직후 prior-guided 정책을 만들고 입력군 Replay는 예약하지 않는다."""
    from apps.workflow_engine import tasks
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    session = MagicMock()
    policy_id = uuid4()
    update_id = uuid4()
    update = MagicMock(id=update_id, status="applied")
    sent = []

    with (
        patch.object(tasks, "SessionLocal", return_value=session),
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "refresh",
            return_value=update,
        ) as refresh,
        patch.object(
            tasks.celery_app,
            "send_task",
            side_effect=lambda *args, **kwargs: sent.append((args, kwargs)),
        ),
    ):
        result = tasks.bootstrap_model_routing_policy.__wrapped__(str(policy_id))

    refresh.assert_called_once_with(
        session,
        policy_id=str(policy_id),
        trigger="deployment_bootstrap",
    )
    session.commit.assert_called_once()
    assert result == {
        "status": "applied",
        "policy_id": str(policy_id),
        "update_id": str(update_id),
    }
    assert sent == []


def test_generate_bootstrap_task_runs_planner_outside_gateway_request():
    """기준 생성은 Worker에서 완료하고, 별도 encoder 학습 task를 예약하지 않는다."""
    from apps.workflow_engine import tasks
    from apps.workflow_engine.services.llm_service import LLMService
    from apps.workflow_engine.services.model_router import ModelRouter
    from apps.workflow_engine.services.model_routing_bootstrap import (
        PersistedModelRoutingBootstrapStore,
    )

    bootstrap_id = uuid4()
    user_id = uuid4()
    organization_id = uuid4()
    bootstrap = MagicMock(
        id=bootstrap_id,
        status="generating",
        created_by=user_id,
        organization_id=organization_id,
        planner_model_id="gpt-4.1",
        default_model_id="gpt-4.1",
    )
    completed = MagicMock(id=bootstrap_id, status="ready")
    session = MagicMock()
    session.get.return_value = bootstrap
    selection = MagicMock(client=object(), model_id="gpt-4.1")

    with (
        patch.object(tasks, "SessionLocal", return_value=session),
        patch.object(
            LLMService,
            "get_runtime_available_model_ids_for_user",
            return_value=["gpt-4.1", "gpt-4.1-mini"],
        ),
        patch.object(
            LLMService,
            "get_runtime_client_for_user",
            return_value=selection,
        ),
        patch.object(LLMService, "calculate_cost", return_value=0.012),
        patch.object(
            ModelRouter,
            "collect_candidates",
            return_value=[
                MagicMock(model_id="gpt-4.1"),
                MagicMock(model_id="gpt-4.1-mini"),
            ],
        ),
        patch.object(ModelRouter, "is_workflow_chat_model", return_value=True),
        patch.object(
            PersistedModelRoutingBootstrapStore,
            "complete_pending",
            return_value=completed,
        ) as complete_pending,
        patch.object(
            PersistedModelRoutingBootstrapStore,
            "finalize_request_complexity_classifier",
        ) as finalize_profile,
        patch.object(tasks.celery_app, "send_task") as send_task,
    ):
        result = tasks.generate_model_routing_bootstrap.__wrapped__(str(bootstrap_id))

    complete_pending.assert_called_once()
    finalize_profile.assert_called_once_with(session, bootstrap_id=bootstrap_id)
    session.commit.assert_called_once()
    send_task.assert_not_called()
    assert result == {"status": "ready", "bootstrap_id": str(bootstrap_id)}
