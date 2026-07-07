import json
import pathlib
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
PARENT_OF_ROOT = ROOT.parent
for p in [ROOT, PARENT_OF_ROOT]:
    if str(p) not in sys.path:
        sys.path.append(str(p))

from apps.workflow_engine.services.model_router import ModelCandidate  # noqa: E402
from apps.workflow_engine.services.model_routing_policy_refresh import (  # noqa: E402
    ModelRoutingPolicyRefreshRequest,
    ModelRoutingPolicyRefreshService,
)


class _JudgeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke_sync(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return {
            "choices": [{"message": {"content": json.dumps(self.payload)}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }


def _candidate(model_id: str, price: float) -> ModelCandidate:
    return ModelCandidate(
        model_id=model_id,
        display_name=model_id,
        input_price_1k=price / 2,
        output_price_1k=price / 2,
    )


def _request(current_policy=None):
    return ModelRoutingPolicyRefreshRequest(
        workflow_id="workflow-1",
        node_id="llm-1",
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        current_policy=current_policy,
        candidate_models=[
            _candidate("gpt-4o-mini", 0.001),
            _candidate("gpt-4.1-mini", 0.01),
            _candidate("gpt-4.1", 0.1),
        ],
        recent_runs=[
            {
                "model": "gpt-4.1",
                "status": "success",
                "input_length_bucket": "short",
                "output_format": "json",
                "cost": 0.02,
            }
        ],
    )


def test_policy_refresh_accepts_judge_generated_rule_set():
    """judge가 만든 rule set은 후보 모델 검증 후 active policy로 정규화된다."""
    judge = _JudgeClient(
        {
            "status": "applied",
            "default_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "rules": [
                {
                    "id": "simple",
                    "priority": 10,
                    "when": {
                        "output_format": "json",
                        "input_length_bucket": "short",
                    },
                    "selected_model_id": "gpt-4o-mini",
                    "fallback_model_id": "gpt-4.1-mini",
                    "reason_code": "short_json_cost",
                },
                {
                    "id": "high",
                    "priority": 20,
                    "when": {"keyword_any": ["SLA", "보상", "장애"]},
                    "selected_model_id": "gpt-4.1",
                    "fallback_model_id": None,
                    "reason_code": "domain_keyword_quality",
                },
            ],
        }
    )

    result = ModelRoutingPolicyRefreshService.refresh_policy(
        None,
        _request(),
        judge_client=judge,
    )

    assert result.status == "applied"
    assert result.policy["active_policy"]["default_model_id"] == "gpt-4.1-mini"
    assert [rule["id"] for rule in result.policy["active_policy"]["rules"]] == [
        "simple",
        "high",
    ]
    assert result.judge_usage["total_tokens"] == 150
    assert result.metadata["prompt_version"] == "model-routing-policy-judge-v1"
    assert judge.calls[0]["kwargs"]["temperature"] == 0.0


def test_policy_refresh_keeps_existing_policy_when_judge_returns_unusable_model():
    """judge가 후보 밖 모델만 반환하면 pending_review로 남기고 기존 정책을 유지한다."""
    current_policy = ModelRoutingPolicyRefreshService.default_rule_policy(
        policy_id="policy-1",
        policy_version="router-policy-v1",
        candidate_models=[
            _candidate("gpt-4o-mini", 0.001),
            _candidate("gpt-4.1-mini", 0.01),
            _candidate("gpt-4.1", 0.1),
        ],
    )
    judge = _JudgeClient(
        {
            "status": "applied",
            "default_model_id": "unknown",
            "rules": [
                {
                    "id": "bad",
                    "selected_model_id": "unknown",
                }
            ],
        }
    )

    result = ModelRoutingPolicyRefreshService.refresh_policy(
        None,
        _request(current_policy),
        judge_client=judge,
    )

    assert result.status == "pending_review"
    assert result.policy["policy_id"] == "policy-1"
    assert result.policy["refresh"]["last_refresh_result"] == "pending_review"


def test_policy_refresh_preserves_user_configured_refresh_every_runs():
    """사용자가 LLM 노드에서 정한 judge policy refresh 빈도는 갱신 후에도 유지된다."""
    current_policy = ModelRoutingPolicyRefreshService.default_rule_policy(
        policy_id="policy-1",
        policy_version="router-policy-v1",
        candidate_models=[
            _candidate("gpt-4o-mini", 0.001),
            _candidate("gpt-4.1-mini", 0.01),
            _candidate("gpt-4.1", 0.1),
        ],
        refresh_every_runs=45,
    )
    judge = _JudgeClient(
        {
            "status": "applied",
            "default_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "rules": [
                {
                    "id": "low",
                    "priority": 10,
                    "when": {"output_format": "json", "input_length_bucket": "short"},
                    "selected_model_id": "gpt-4o-mini",
                    "fallback_model_id": "gpt-4.1-mini",
                    "reason_code": "short_json_cost",
                },
            ],
        }
    )

    result = ModelRoutingPolicyRefreshService.refresh_policy(
        None,
        _request(current_policy),
        judge_client=judge,
    )

    assert result.status == "applied"
    assert result.policy["refresh"]["refresh_every_runs"] == 45


def test_policy_refresh_rejects_unknown_condition_keys():
    """judge가 허용되지 않은 when key를 반환하면 rule을 저장하지 않는다."""
    current_policy = ModelRoutingPolicyRefreshService.default_rule_policy(
        policy_id="policy-1",
        policy_version="router-policy-v1",
        candidate_models=[
            _candidate("gpt-4o-mini", 0.001),
            _candidate("gpt-4.1-mini", 0.01),
            _candidate("gpt-4.1", 0.1),
        ],
    )
    judge = _JudgeClient(
        {
            "status": "applied",
            "default_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "rules": [
                {
                    "id": "bad-unknown-key",
                    "priority": 10,
                    "when": {
                        "customer_facing": True,
                        "customer_support_ticket_triage": True,
                    },
                    "selected_model_id": "gpt-4.1",
                    "fallback_model_id": None,
                    "reason_code": "bad_unknown_condition",
                }
            ],
        }
    )

    result = ModelRoutingPolicyRefreshService.refresh_policy(
        None,
        _request(current_policy),
        judge_client=judge,
    )

    assert result.status == "pending_review"
    assert result.policy["policy_id"] == "policy-1"
    assert result.policy["refresh"]["last_refresh_result"] == "pending_review"
