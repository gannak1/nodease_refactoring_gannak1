import json
from types import SimpleNamespace
from uuid import uuid4

from apps.workflow_engine.services.model_router import ModelCandidate, ModelRouter
from apps.workflow_engine.services.model_routing_policy_lifecycle import (
    ModelRoutingPolicyLifecycleService,
)
from apps.workflow_engine.services.model_routing_policy_refresh import (
    ModelRoutingPolicyRefreshRequest,
    ModelRoutingPolicyRefreshService,
)


class _JudgeClient:
    def __init__(self):
        self.calls = 0

    def invoke_sync(self, messages, **kwargs):
        self.calls += 1
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "status": "applied",
                                "confidence": 0.95,
                                "default_model_id": "gpt-4.1-mini",
                                "fallback_model_id": "gpt-4.1",
                                "rules": [
                                    {
                                        "id": "short-json-low-cost",
                                        "priority": 10,
                                        "when": {
                                            "output_format": "json",
                                            "input_length_bucket": "short",
                                        },
                                        "selected_model_id": "gpt-4o-mini",
                                        "fallback_model_id": "gpt-4.1-mini",
                                        "reason_code": "short_structured_input_uses_low_cost_model",
                                    },
                                ],
                            }
                        )
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "total_tokens": 200,
            },
        }


def _candidates():
    return [
        ModelCandidate("gpt-4o-mini", "GPT-4o mini", 0.00015, 0.0006),
        ModelCandidate("gpt-4.1-mini", "GPT-4.1 mini", 0.001, 0.004),
        ModelCandidate("gpt-4.1", "GPT-4.1", 0.01, 0.03),
    ]


def _node_data():
    return SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1",
        system_prompt="JSON으로 답합니다.",
        user_prompt="고객 문의를 분류합니다.",
        assistant_prompt="",
        knowledgeBases=[],
        output_format={
            "type": "json",
            "schema": {"type": "object", "required": ["reply"]},
        },
        model_routing_context={"customer_facing": True, "node_task": "triage"},
    )


def test_policy_refresh_e2e_runs_every_20_runs_and_runtime_uses_saved_rules():
    """61회 실행 동안 judge는 20회 경계에서만 호출되고 runtime은 저장 rule을 평가한다."""
    candidates = _candidates()
    policy = ModelRoutingPolicyRefreshService.default_rule_policy(
        policy_id=str(uuid4()),
        policy_version="bootstrap-v1",
        default_model_id="gpt-4.1",
        fallback_model_id=None,
        refresh_every_runs=20,
    )
    lifecycle_state = SimpleNamespace(
        enabled=True,
        status=policy["status"],
        eligible_runs_since_last_refresh=0,
        refresh_every_runs=20,
        refresh_requested_at=None,
        active_policy=policy["active_policy"],
        pending_policy=None,
        policy_version=policy["policy_version"],
        last_refresh_result=None,
    )
    judge = _JudgeClient()
    refresh_points = []
    decisions = []
    recent_runs = [
        {
            "model_id": candidate.model_id,
            "run_count": 10,
            "success_rate": 1.0,
            "schema_pass_rate": 1.0,
            "downstream_success_rate": 1.0,
            "fallback_rate": 0.0,
            "avg_cost": candidate.price_score,
        }
        for candidate in candidates
    ]
    segment_profiles = [
        {
            "conditions": {
                "output_format": "json",
                "input_length_bucket": "short",
            },
            "model_performance": {
                "gpt-4o-mini": {
                    "run_count": 10,
                    "success_rate": 1.0,
                    "schema_pass_rate": 1.0,
                    "downstream_success_rate": 1.0,
                    "fallback_rate": 0.0,
                    "avg_cost": 0.001,
                    "avg_latency_ms": 300,
                }
            },
        }
    ]

    for index in range(1, 62):
        message = (
            "SLA 보상 검토가 필요합니다."
            if index % 7 == 0
            else "상태를 JSON으로 분류해 주세요."
        )
        decision = ModelRouter.resolve_policy(
            policy,
            inputs={"message": message},
            node_data=_node_data(),
            available_model_ids=[candidate.model_id for candidate in candidates],
        )
        decisions.append((index, message, decision.selected_model_id))

        outcome = ModelRoutingPolicyLifecycleService.apply_run_event(
            lifecycle_state,
            event_was_created=True,
        )
        if not outcome.should_enqueue_refresh:
            continue

        refresh_points.append(index)
        result = ModelRoutingPolicyRefreshService.refresh_policy(
            None,
            ModelRoutingPolicyRefreshRequest(
                workflow_id="workflow-1",
                node_id="llm-1",
                user_id=uuid4(),
                organization_id=uuid4(),
                current_policy=policy,
                candidate_models=candidates,
                recent_runs=recent_runs,
                segment_profiles=segment_profiles,
                node_summary={"output_format": "json", "schema_required": True},
                trigger=f"auto_{index}_runs",
                judge_model_id="gpt-4.1-mini",
            ),
            judge_client=judge,
        )
        assert result.status == "applied"
        policy = result.policy
        ModelRoutingPolicyLifecycleService.apply_refresh_result(
            lifecycle_state,
            status=result.status,
            proposed_policy=policy["active_policy"],
            policy_version=policy["policy_version"],
        )
        lifecycle_state.eligible_runs_since_last_refresh = 0
        lifecycle_state.refresh_requested_at = None

    assert refresh_points == [20, 40, 60]
    assert judge.calls == 3
    assert all(selected == "gpt-4.1" for index, _, selected in decisions if index <= 20)
    assert all(
        selected == "gpt-4o-mini"
        for index, _, selected in decisions
        if index > 20
    )
    assert lifecycle_state.policy_version == "bootstrap-v4"
