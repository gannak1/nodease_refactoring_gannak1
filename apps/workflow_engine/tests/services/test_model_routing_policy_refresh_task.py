from datetime import datetime, timezone
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


def _policy(*, enabled: bool = True):
    return SimpleNamespace(
        id=uuid4(),
        deployment_id=uuid4(),
        workflow_id=uuid4(),
        node_id="llm-1",
        organization_id=uuid4(),
        judge_user_id=uuid4(),
        execution_subject_user_id=uuid4(),
        active_policy={"default_model_id": "gpt-4.1", "rules": []},
        pending_policy=None,
        policy_version="router-policy-v1",
        refresh_every_runs=20,
        eligible_runs_since_last_refresh=20,
        refresh_requested_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        last_refreshed_at=None,
        last_refresh_result=None,
        status="refreshing",
        enabled=enabled,
    )


def test_refresh_compiles_prior_guided_policy_without_semantic_router():
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    policy = _policy()
    deployment = SimpleNamespace(
        graph_snapshot={
            "nodes": [
                {
                    "id": "llm-1",
                    "data": {
                        "auto_model_routing": True,
                        "model_id": "gpt-4.1",
                        "output_format": {"type": "json", "schema": {"type": "object"}},
                    },
                }
            ]
        }
    )
    db = MagicMock()
    db.query.side_effect = [_FirstQuery(policy), _FirstQuery(deployment)]
    profile = SimpleNamespace(
        operational_usable_runs=20,
        as_snapshot=lambda: {"operational_usable_runs": 20},
    )
    compiled = SimpleNamespace(
        active_policy={
            "strategy": "prior_guided_adaptive",
            "strategy_id": "prior_guided_adaptive_v1",
            "default_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "rules": [{"when": {"input_length_bucket": "short"}}],
            "decision_profiles": [],
        },
        summary={"profile_count": 3},
    )

    with (
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.LLMService.get_runtime_available_model_ids_for_user",
            return_value=["gpt-4.1", "gpt-4.1-mini"],
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRoutingOperationalPerformanceService.profile_for_policy",
            return_value=profile,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRoutingOperationalPerformanceService.checkpoint_snapshot",
            return_value={"total_runs": 20, "models": {}},
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.compile_prior_guided_policy_from_db",
            return_value=compiled,
        ) as compile_policy,
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRoutingPolicyChangeGuard.evaluate",
            return_value=SimpleNamespace(
                status="applied",
                reason_code="material_efficiency_improvement",
                max_cost_improvement=0.2,
                max_latency_improvement=0.1,
            ),
        ),
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_remaining_event_count",
            return_value=2,
        ),
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_excluded_run_count",
            return_value=1,
        ),
    ):
        update = PersistedModelRoutingPolicyRefreshService.refresh(
            db,
            policy_id=policy.id,
            trigger="auto_runs",
        )

    assert update.status == "applied"
    assert policy.active_policy["strategy_id"] == "prior_guided_adaptive_v1"
    assert "semantic_router" not in policy.active_policy
    assert policy.eligible_runs_since_last_refresh == 2
    assert update.judge_model is None
    compile_policy.assert_called_once()


def test_refresh_keeps_current_policy_when_auto_routing_is_off():
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    policy = _policy(enabled=False)
    deployment = SimpleNamespace(
        graph_snapshot={
            "nodes": [
                {
                    "id": "llm-1",
                    "data": {"auto_model_routing": False, "model_id": "gpt-4.1"},
                }
            ]
        }
    )
    db = MagicMock()
    db.query.side_effect = [_FirstQuery(policy), _FirstQuery(deployment)]

    with patch.object(
        PersistedModelRoutingPolicyRefreshService,
        "_remaining_event_count",
        return_value=0,
    ):
        update = PersistedModelRoutingPolicyRefreshService.refresh(
            db,
            policy_id=policy.id,
            trigger="manual_refresh",
        )

    assert update.status == "kept_current"
    assert policy.active_policy["default_model_id"] == "gpt-4.1"
    assert policy.refresh_requested_at is None


def test_refresh_keeps_bootstrap_classifier_policy_without_replacing_strategy():
    """재평가가 bootstrap 난이도 분류기를 legacy compiler로 덮어쓰면 안 된다."""
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    policy = _policy()
    policy.active_policy = {
        "strategy_id": "bootstrap_mdeberta_difficulty_v1",
        "default_model_id": "gpt-4.1-mini",
        "difficulty_models": {"economy": "gpt-4o-mini"},
    }
    deployment = SimpleNamespace(
        graph_snapshot={
            "nodes": [
                {
                    "id": "llm-1",
                    "data": {"auto_model_routing": True, "model_id": "gpt-4.1-mini"},
                }
            ]
        }
    )
    profile = SimpleNamespace(
        operational_usable_runs=20,
        as_snapshot=lambda: {"operational_usable_runs": 20},
    )
    db = MagicMock()
    db.query.side_effect = [_FirstQuery(policy), _FirstQuery(deployment)]

    with (
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRoutingOperationalPerformanceService.profile_for_policy",
            return_value=profile,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRoutingOperationalPerformanceService.checkpoint_snapshot",
            return_value={"total_runs": 20},
        ),
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_remaining_event_count",
            return_value=1,
        ),
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_excluded_run_count",
            return_value=0,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.compile_prior_guided_policy_from_db"
        ) as compile_policy,
    ):
        update = PersistedModelRoutingPolicyRefreshService.refresh(
            db,
            policy_id=policy.id,
            trigger="auto_runs",
        )

    assert update.status == "kept_current"
    assert policy.active_policy["strategy_id"] == "bootstrap_mdeberta_difficulty_v1"
    assert update.output_summary["replay_required"] is True
    compile_policy.assert_not_called()


def test_refresh_fails_closed_without_execution_subject():
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    policy = _policy()
    policy.execution_subject_user_id = None
    policy.judge_user_id = None
    deployment = SimpleNamespace(
        graph_snapshot={
            "nodes": [
                {
                    "id": "llm-1",
                    "data": {"auto_model_routing": True, "model_id": "gpt-4.1"},
                }
            ]
        }
    )
    db = MagicMock()
    db.query.side_effect = [_FirstQuery(policy), _FirstQuery(deployment)]

    update = PersistedModelRoutingPolicyRefreshService.refresh(
        db,
        policy_id=policy.id,
        trigger="manual_refresh",
    )

    assert update.status == "failed"
    assert update.error_code == "ValueError"
    assert policy.active_policy["default_model_id"] == "gpt-4.1"


def test_safe_node_summary_does_not_include_prompt_or_input_content():
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    summary = PersistedModelRoutingPolicyRefreshService._safe_node_summary(
        {
            "system_prompt": "secret prompt",
            "user_prompt": "{{customer_message}}",
            "output_format": {"type": "json", "schema": {"type": "object"}},
            "knowledgeBases": [{"id": "kb-1"}],
            "fallback_model_id": "gpt-4.1",
        }
    )

    assert summary == {
        "output_format": "json",
        "schema_required": True,
        "knowledge_enabled": True,
        "has_fallback_model": True,
    }
