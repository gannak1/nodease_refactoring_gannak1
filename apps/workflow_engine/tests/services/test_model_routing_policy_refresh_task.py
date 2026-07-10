from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4


class _FirstQuery:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.value


class _CountQuery:
    def filter(self, *args, **kwargs):
        return self

    def count(self):
        return 0


def test_persisted_refresh_records_judge_usage_log_reference():
    """정책 갱신 judge 호출 비용은 usage log와 policy update에 연결되어야 한다."""
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    policy = SimpleNamespace(
        id=uuid4(),
        deployment_id=uuid4(),
        workflow_id=uuid4(),
        node_id="llm-1",
        organization_id=uuid4(),
        judge_user_id=uuid4(),
        active_policy={"default_model_id": "gpt-4.1", "rules": []},
        pending_policy=None,
        policy_version="router-policy-v1",
        refresh_every_runs=20,
        eligible_runs_since_last_refresh=20,
        refresh_requested_at=None,
        last_refreshed_at=None,
        last_refresh_result=None,
        status="refreshing",
    )
    deployment = SimpleNamespace(graph_snapshot={"nodes": []})
    usage_log = SimpleNamespace(id=uuid4(), total_cost=0.0012)
    db = MagicMock()
    db.query.side_effect = [_FirstQuery(policy), _FirstQuery(deployment), _CountQuery()]
    refresh_result = SimpleNamespace(
        status="applied",
        policy={
            "policy_version": "router-policy-v2",
            "active_policy": {"default_model_id": "gpt-4.1-mini", "rules": []},
        },
        reason="quality gate passed",
        judge_model_id="gpt-4.1-mini",
        judge_usage={
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
        metadata={"confidence": 0.95},
        judge_credential_id=uuid4(),
        judge_provider="openai",
    )

    with (
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_node_data",
            return_value={},
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRouter.collect_candidates",
            return_value=[SimpleNamespace(model_id="gpt-4.1-mini")],
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRouter.collect_profile",
            return_value=SimpleNamespace(
                operational_usable_runs=20,
                as_snapshot=lambda: {
                    "operational_usable_runs": 20,
                    "model_performance": {},
                },
            ),
        ),
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_excluded_run_count",
            return_value=0,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRoutingPolicyRefreshService.refresh_policy",
            return_value=refresh_result,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.LLMService.calculate_cost",
            return_value=0.0012,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.LLMService.log_usage",
            return_value=usage_log,
        ) as log_usage,
    ):
        update = PersistedModelRoutingPolicyRefreshService.refresh(
            db,
            policy_id=policy.id,
            trigger="manual_refresh",
        )

    assert update.error_code is None, update.output_summary
    assert update.judge_provider == "openai"
    assert update.judge_usage_log_id == usage_log.id
    log_usage.assert_called_once()
