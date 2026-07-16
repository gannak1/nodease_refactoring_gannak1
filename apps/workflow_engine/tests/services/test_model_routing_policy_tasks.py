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
                "args": [str(policy_id), "auto_n_runs"],
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
            str(policy_id), "auto_n_runs"
        )

    assert result == {"status": "skipped", "update_id": None, "result": None}
    claim_pending.assert_called_once_with(session, policy_id=str(policy_id))
    refresh.assert_not_called()


def test_deployment_bootstrap_task_dispatches_paid_validation_batch():
    """배포 직후 입력군 준비가 끝나면 기준·후보 검증 batch를 예약한다."""
    from apps.workflow_engine import tasks
    from apps.workflow_engine.services.model_routing_adaptive_validation_service import (
        AdaptiveModelRoutingValidationService,
    )

    session = MagicMock()
    policy_id = uuid4()
    batch_id = uuid4()
    batch = MagicMock(id=batch_id, status="pending")
    sent = []

    with (
        patch.object(tasks, "SessionLocal", return_value=session),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "prepare_deployment_bootstrap",
            return_value=batch,
        ) as prepare,
        patch.object(
            tasks.celery_app,
            "send_task",
            side_effect=lambda *args, **kwargs: sent.append((args, kwargs)),
        ),
    ):
        result = tasks.bootstrap_model_routing_policy.__wrapped__(str(policy_id))

    prepare.assert_called_once_with(session, policy_id=str(policy_id))
    session.commit.assert_called_once()
    assert result["validation_batch_id"] == str(batch_id)
    assert sent[0][0] == ("workflow.model_routing.validate_batch",)


def test_completed_bootstrap_batch_dispatches_the_next_candidate_wave():
    """첫 후보가 탈락해도 운영 로그를 기다리지 않고 다음 후보 검증을 이어간다."""
    from apps.workflow_engine import tasks
    from apps.workflow_engine.services.model_routing_adaptive_validation_service import (
        AdaptiveModelRoutingValidationService,
    )

    session = MagicMock()
    policy_id = uuid4()
    completed_batch = MagicMock(
        id=uuid4(),
        policy_id=policy_id,
        trigger="deployment_bootstrap",
        status="completed",
        completed_items=10,
    )
    follow_up_batch = MagicMock(id=uuid4(), status="pending")
    sent = []

    with (
        patch.object(tasks, "SessionLocal", return_value=session),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "execute_batch",
            return_value=completed_batch,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "plan_deployment_bootstrap_follow_up",
            return_value=follow_up_batch,
        ) as plan_follow_up,
        patch.object(
            tasks.celery_app,
            "send_task",
            side_effect=lambda *args, **kwargs: sent.append((args, kwargs)),
        ),
    ):
        result = tasks.validate_model_routing_batch.__wrapped__(str(completed_batch.id))

    plan_follow_up.assert_called_once_with(session, batch=completed_batch)
    assert result["follow_up_batch_id"] == str(follow_up_batch.id)
    assert sent[-1][0] == ("workflow.model_routing.validate_batch",)
    assert sent[-1][1]["args"] == [str(follow_up_batch.id)]


def test_non_bootstrap_batch_does_not_dispatch_a_candidate_follow_up():
    """운영 정책 갱신 batch는 bootstrap 후보 연쇄 탐색을 시작하지 않는다."""
    from apps.workflow_engine import tasks
    from apps.workflow_engine.services.model_routing_adaptive_validation_service import (
        AdaptiveModelRoutingValidationService,
    )

    session = MagicMock()
    completed_batch = MagicMock(
        id=uuid4(),
        policy_id=uuid4(),
        trigger="auto_n_runs",
        status="completed",
        completed_items=5,
    )

    with (
        patch.object(tasks, "SessionLocal", return_value=session),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "execute_batch",
            return_value=completed_batch,
        ),
        patch.object(
            AdaptiveModelRoutingValidationService,
            "plan_deployment_bootstrap_follow_up",
        ) as plan_follow_up,
    ):
        result = tasks.validate_model_routing_batch.__wrapped__(str(completed_batch.id))

    plan_follow_up.assert_not_called()
    assert result["follow_up_batch_id"] is None
