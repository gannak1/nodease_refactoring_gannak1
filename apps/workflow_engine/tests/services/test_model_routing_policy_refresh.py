import json
import pathlib
import sys
import uuid

import pytest

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


def _request(
    current_policy=None,
    *,
    include_candidate_quality=True,
    recent_runs=None,
    segment_profiles=None,
):
    default_recent_runs = [
        {
            "model_id": "gpt-4.1",
            "run_count": 20,
            "success_rate": 1.0,
            "schema_pass_rate": 1.0,
            "downstream_success_rate": 1.0,
            "fallback_rate": 0.0,
            "avg_cost": 0.02,
        },
    ]
    if include_candidate_quality:
        default_recent_runs.append(
            {
                "model_id": "gpt-4o-mini",
                "run_count": 10,
                "success_rate": 1.0,
                "schema_pass_rate": 1.0,
                "downstream_success_rate": 1.0,
                "fallback_rate": 0.0,
                "avg_cost": 0.001,
            }
        )
        default_recent_runs.append(
            {
                "model_id": "gpt-4.1-mini",
                "run_count": 10,
                "success_rate": 1.0,
                "schema_pass_rate": 1.0,
                "downstream_success_rate": 1.0,
                "fallback_rate": 0.0,
                "avg_cost": 0.01,
            }
        )
    default_segment_profiles = [
        {
            "conditions": {"output_format": "json", "input_length_bucket": "short"},
            "model_performance": {
                "gpt-4o-mini": {
                    "run_count": 10,
                    "success_rate": 1.0,
                    "schema_pass_rate": 1.0,
                    "downstream_success_rate": 1.0,
                    "fallback_rate": 0.0,
                    "avg_cost": 0.001,
                }
            },
        },
        {
            "conditions": {"output_format": "json"},
            "model_performance": {
                "gpt-4o-mini": {
                    "run_count": 10,
                    "success_rate": 1.0,
                    "schema_pass_rate": 1.0,
                    "downstream_success_rate": 1.0,
                    "fallback_rate": 0.0,
                    "avg_cost": 0.001,
                }
            },
        },
    ]
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
        judge_model_id="gpt-4.1-mini",
        recent_runs=recent_runs if recent_runs is not None else default_recent_runs,
        segment_profiles=(
            segment_profiles if segment_profiles is not None else default_segment_profiles
        ),
    )


def _preserved_policy(*, refresh_every_runs=20):
    return ModelRoutingPolicyRefreshService.default_rule_policy(
        policy_id="policy-1",
        policy_version="bootstrap-preserve-config-v1",
        default_model_id="gpt-4.1-mini",
        fallback_model_id="gpt-4.1",
        refresh_every_runs=refresh_every_runs,
    )


def test_policy_refresh_request_requires_explicit_judge_model():
    """정책 갱신은 특정 provider의 judge 기본값에 의존하지 않는다."""
    with pytest.raises(TypeError, match="judge_model_id"):
        ModelRoutingPolicyRefreshRequest(
            workflow_id="workflow-1",
            node_id="llm-1",
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            current_policy=None,
            candidate_models=[],
        )


def test_bootstrap_policy_preserves_the_configured_models_without_rules():
    """운영 품질 근거가 없는 bootstrap은 가격으로 모델 등급을 만들지 않는다."""
    policy = ModelRoutingPolicyRefreshService.default_rule_policy(
        policy_id="policy-1",
        policy_version="bootstrap-preserve-config-v1",
        default_model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
    )

    assert policy["active_policy"] == {
        "default_model_id": "gpt-4.1",
        "fallback_model_id": "gpt-4.1-mini",
        "rules": [],
    }


def test_policy_refresh_sends_segmented_evidence_and_rejects_keyword_rules_without_evidence():
    request = _request()
    request = ModelRoutingPolicyRefreshRequest(
        **{
            **request.__dict__,
            "segment_profiles": [
                {
                    "conditions": {"output_format": "json", "input_length_bucket": "short"},
                    "model_performance": {
                        "gpt-4o-mini": {
                            "run_count": 10,
                            "success_rate": 1.0,
                            "schema_pass_rate": 1.0,
                            "downstream_success_rate": 1.0,
                            "fallback_rate": 0.0,
                            "avg_cost": 0.001,
                        }
                    },
                }
            ],
        }
    )

    messages = ModelRoutingPolicyRefreshService._build_messages(  # noqa: SLF001
        request,
        ModelRoutingPolicyRefreshService._sanitize_candidates(request.candidate_models),  # noqa: SLF001
    )
    payload = json.loads(messages[1]["content"])
    assert payload["segment_profiles"][0]["conditions"]["output_format"] == "json"

    rules = ModelRoutingPolicyRefreshService._sanitize_rules(  # noqa: SLF001
        [
            {
                "id": "unsupported-keyword-rule",
                "when": {"keyword_any": ["SLA"]},
                "selected_model_id": "gpt-4o-mini",
            }
        ],
        {"gpt-4o-mini"},
    )
    assert rules == []


def test_policy_refresh_accepts_judge_generated_rule_set():
    """judge가 만든 rule set은 후보 모델 검증 후 active policy로 정규화된다."""
    judge = _JudgeClient(
        {
            "status": "applied",
            "confidence": 0.95,
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
        "simple"
    ]
    assert result.judge_usage["total_tokens"] == 150
    assert result.metadata["prompt_version"] == "model-routing-policy-judge-v1"
    assert judge.calls[0]["kwargs"]["temperature"] == 0.0


def test_policy_refresh_keeps_existing_policy_when_judge_returns_unusable_model():
    """judge가 후보 밖 모델만 반환하면 pending_review로 남기고 기존 정책을 유지한다."""
    current_policy = _preserved_policy()
    judge = _JudgeClient(
        {
            "status": "applied",
            "confidence": 0.95,
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
    current_policy = _preserved_policy(refresh_every_runs=45)
    judge = _JudgeClient(
        {
            "status": "applied",
            "confidence": 0.95,
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
    current_policy = _preserved_policy()
    judge = _JudgeClient(
        {
            "status": "applied",
            "confidence": 0.95,
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


def test_policy_refresh_keeps_current_when_new_model_has_no_quality_evidence():
    """운영 표본이 없는 저비용 모델은 judge가 제안해도 active policy가 되면 안 된다."""
    current_policy = {
        "status": "active",
        "policy_id": "policy-1",
        "policy_version": "router-policy-v1",
        "active_policy": {
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "rules": [],
        },
    }
    judge = _JudgeClient(
        {
            "status": "applied",
            "confidence": 0.95,
            "default_model_id": "gpt-4o-mini",
            "fallback_model_id": "gpt-4.1",
            "rules": [
                {
                    "id": "unverified-cheap-model",
                    "priority": 10,
                    "when": {"output_format": "json"},
                    "selected_model_id": "gpt-4o-mini",
                    "fallback_model_id": "gpt-4.1",
                    "reason_code": "lower_cost",
                }
            ],
        }
    )

    result = ModelRoutingPolicyRefreshService.refresh_policy(
        None,
        _request(current_policy, include_candidate_quality=False),
        judge_client=judge,
    )

    assert result.status == "pending_review"
    assert (
        result.policy["active_policy"]["default_model_id"]
        == current_policy["active_policy"]["default_model_id"]
    )
    assert result.policy["policy_version"] == current_policy["policy_version"]


def test_policy_refresh_rejects_unverified_model_promoted_from_bootstrap_rule():
    """bootstrap rule에 있던 모델도 새 default로 승격되면 별도 운영 품질 근거가 필요하다."""
    current_policy = _preserved_policy()
    judge = _JudgeClient(
        {
            "status": "applied",
            "confidence": 0.95,
            "default_model_id": "gpt-4o-mini",
            "fallback_model_id": "gpt-4.1-mini",
            "rules": [
                {
                    "id": "short-json-no-knowledge",
                    "priority": 10,
                    "when": {"output_format": "json"},
                    "selected_model_id": "gpt-4o-mini",
                    "fallback_model_id": "gpt-4.1-mini",
                    "reason_code": "promote_existing_bootstrap_candidate",
                }
            ],
        }
    )

    result = ModelRoutingPolicyRefreshService.refresh_policy(
        None,
        _request(current_policy, include_candidate_quality=False),
        judge_client=judge,
    )

    assert result.status == "pending_review"
    assert result.policy["active_policy"] == current_policy["active_policy"]


def test_policy_refresh_keeps_current_when_changed_model_has_no_efficiency_evidence():
    """품질이 같아도 실제 평균 비용과 지연 시간이 나쁘면 정책을 바꾸지 않는다."""
    current_policy = {
        "status": "active",
        "policy_id": "policy-1",
        "policy_version": "router-policy-v1",
        "active_policy": {
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "rules": [],
        },
    }
    judge = _JudgeClient(
        {
            "status": "applied",
            "confidence": 0.95,
            "default_model_id": "gpt-4o-mini",
            "fallback_model_id": "gpt-4.1",
            "rules": [
                {
                    "id": "slower-and-costlier",
                    "priority": 10,
                    "when": {"output_format": "json"},
                    "selected_model_id": "gpt-4o-mini",
                    "fallback_model_id": "gpt-4.1",
                    "reason_code": "incorrect_efficiency_claim",
                }
            ],
        }
    )
    recent_runs = [
        {
            "model_id": "gpt-4.1",
            "run_count": 10,
            "success_rate": 1.0,
            "schema_pass_rate": 1.0,
            "downstream_success_rate": 1.0,
            "fallback_rate": 0.0,
            "avg_cost": 0.004,
            "avg_latency_ms": 900,
        },
        {
            "model_id": "gpt-4o-mini",
            "run_count": 10,
            "success_rate": 1.0,
            "schema_pass_rate": 1.0,
            "downstream_success_rate": 1.0,
            "fallback_rate": 0.0,
            "avg_cost": 0.006,
            "avg_latency_ms": 1200,
        },
    ]

    result = ModelRoutingPolicyRefreshService.refresh_policy(
        None,
        _request(current_policy, recent_runs=recent_runs),
        judge_client=judge,
    )

    assert result.status == "kept_current"
    assert result.policy["active_policy"] == current_policy["active_policy"]
