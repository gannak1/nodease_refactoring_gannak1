from types import SimpleNamespace

import pytest

from apps.workflow_engine.services.model_routing_runtime_judge import (
    ModelRoutingRuntimeJudge,
    RuntimeJudgeResponseError,
)


class _JudgeClient:
    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    def invoke_sync(self, *, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return {
            "choices": [{"message": {"content": self.content}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 18},
        }


def test_runtime_judge_accepts_only_current_execution_subject_candidates():
    client = _JudgeClient(
        '{"selected_model_id":"gpt-5-mini","confidence":0.86,'
        '"reason_code":"multi_step_contract"}'
    )

    decision = ModelRoutingRuntimeJudge.decide(
        client=client,
        candidate_model_ids=["gpt-4o-mini", "gpt-5-mini"],
        default_model_id="gpt-4o-mini",
        fallback_model_id="gpt-5-mini",
        routing_feature_text="고객 요청: 서로 충돌하는 세 개의 규정을 비교해 JSON으로 판단",
        node_contract={"output_format": "json", "knowledge_enabled": True},
    )

    assert decision.selected_model_id == "gpt-5-mini"
    assert decision.confidence == 0.86
    assert decision.reason_code == "multi_step_contract"
    assert decision.usage == {"prompt_tokens": 42, "completion_tokens": 18}
    rendered_prompt = client.calls[0]["messages"][1]["content"]
    assert '"gpt-4o-mini"' in rendered_prompt
    assert '"gpt-5-mini"' in rendered_prompt
    assert "사용 가능한 후보 외의 모델을 선택하지 마세요" in rendered_prompt
    assert "response_format" not in client.calls[0]["kwargs"]


def test_runtime_judge_rejects_model_outside_available_candidates():
    client = _JudgeClient(
        '{"selected_model_id":"gpt-5.6","confidence":0.92,'
        '"reason_code":"invalid_candidate"}'
    )

    with pytest.raises(RuntimeJudgeResponseError, match="unavailable model"):
        ModelRoutingRuntimeJudge.decide(
            client=client,
            candidate_model_ids=["gpt-4o-mini", "gpt-5-mini"],
            default_model_id="gpt-4o-mini",
            fallback_model_id=None,
            routing_feature_text="간단한 안내 요청",
            node_contract={},
        )


def test_runtime_judge_does_not_persist_raw_feature_text_in_decision():
    secret_like_request = "customer@example.com 의 계약 번호 SECRET-123을 확인해 주세요"
    client = _JudgeClient(
        '{"selected_model_id":"gpt-4o-mini","confidence":0.71,'
        '"reason_code":"short_answer"}'
    )

    decision = ModelRoutingRuntimeJudge.decide(
        client=client,
        candidate_model_ids=["gpt-4o-mini"],
        default_model_id="gpt-4o-mini",
        fallback_model_id=None,
        routing_feature_text=secret_like_request,
        node_contract={},
    )

    assert "SECRET-123" not in str(decision.safe_metadata())
    assert "customer@example.com" not in str(decision.safe_metadata())
