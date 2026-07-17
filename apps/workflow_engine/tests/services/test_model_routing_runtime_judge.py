from types import SimpleNamespace

import pytest

from apps.workflow_engine.services.model_routing_runtime_judge import (
    ModelRoutingRuntimeJudge,
    RuntimeJudgeResponseError,
)
from apps.shared.services.llm_client.base import ProviderInvocationError


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


class _IncompleteThenCompactJudgeClient(_JudgeClient):
    def invoke_sync(self, *, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if len(self.calls) == 1:
            raise ProviderInvocationError(
                "OpenAI Responses 응답이 완료되지 않았습니다: status=incomplete",
                reason_code="responses_incomplete",
                provider_response_status="incomplete",
            )
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"difficulty_score":74,"confidence":0.81,'
                            '"reason_code":"high_risk_reasoning"}'
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 26, "completion_tokens": 12},
        }


def test_runtime_judge_accepts_only_current_execution_subject_candidates():
    client = _JudgeClient(
        '{"difficulty_score":82,"confidence":0.86,'
        '"reason_short":"근거 종합 필요","reason_code":"advanced_quality"}'
    )

    decision = ModelRoutingRuntimeJudge.decide(
        client=client,
        candidate_model_ids=["gpt-4o-mini", "gpt-5-mini"],
        routing_feature_text="고객 요청: 서로 충돌하는 세 개의 규정을 비교해 JSON으로 판단",
        rag_context={
            "used": True,
            "retrieved_context_token_estimate": 4200,
            "retrieved_context_chars": 14800,
            "source_count": 3,
        },
        candidate_profiles=[
            {
                "model_id": "gpt-4o-mini",
                "input_price_per_1k": 0.00015,
                "output_price_per_1k": 0.0006,
                "context_window": 128000,
                "capability_tier": "economy",
                "quality_by_difficulty": {"advanced": 0.62},
                "fallback_rate": 0.04,
            },
            {
                "model_id": "gpt-5-mini",
                "input_price_per_1k": 0.00025,
                "output_price_per_1k": 0.002,
                "context_window": 400000,
                "capability_tier": "balanced",
                "quality_by_difficulty": {"advanced": 0.86},
                "fallback_rate": 0.01,
            },
        ],
    )

    assert decision.selected_model_id is None
    assert decision.difficulty_score == 82
    assert decision.reason_short == "근거 종합 필요"
    assert decision.confidence == 0.86
    assert decision.reason_code == "advanced_quality"
    assert decision.usage == {"prompt_tokens": 42, "completion_tokens": 18}
    rendered_prompt = client.calls[0]["messages"][1]["content"]
    prompt_body = __import__("json").loads(rendered_prompt)
    assert '"gpt-4o-mini"' not in rendered_prompt
    assert '"gpt-5-mini"' not in rendered_prompt
    assert "default_model_id" not in rendered_prompt
    assert "fallback_model_id" not in rendered_prompt
    assert "node_contract" not in rendered_prompt
    assert "candidate_profiles" not in prompt_body
    assert prompt_body["rag_context"] == {
        "used": True,
        "retrieved_context_token_estimate": 4200,
        "retrieved_context_chars": 14800,
        "source_count": 3,
    }
    assert "[파일:" not in rendered_prompt
    assert client.calls[0]["kwargs"]["response_format"] == {"type": "json_object"}
    assert client.calls[0]["kwargs"]["max_tokens"] == 256


def test_runtime_judge_marks_non_rag_request_without_inventing_retrieval_metrics():
    client = _JudgeClient(
        '{"difficulty_score":18,"confidence":0.72,'
        '"reason_short":"단순 안내 요청","reason_code":"economy_fit"}'
    )

    ModelRoutingRuntimeJudge.decide(
        client=client,
        candidate_model_ids=["gpt-4o-mini"],
        routing_feature_text="짧은 JSON 분류 요청",
        rag_context={"used": False},
    )

    prompt_body = __import__("json").loads(client.calls[0]["messages"][1]["content"])
    assert prompt_body["rag_context"] == {"used": False}


def test_runtime_judge_retries_incomplete_response_with_compact_contract():
    client = _IncompleteThenCompactJudgeClient("")

    decision = ModelRoutingRuntimeJudge.decide(
        client=client,
        candidate_model_ids=["gpt-4o-mini"],
        routing_feature_text="승인 전 예외 조항과 근거 문서를 함께 검토해 주세요.",
        rag_context={"used": True, "retrieved_chunk_count": 4, "source_count": 2},
    )

    assert len(client.calls) == 2
    assert client.calls[0]["kwargs"]["max_tokens"] == 256
    assert client.calls[1]["kwargs"]["max_tokens"] == 256
    assert decision.difficulty_score == 74
    assert decision.reason_short == "고위험 판단 필요"
    compact_instruction = client.calls[1]["messages"][0]["content"]
    assert "reason_short" not in compact_instruction
    assert "reason_code" in compact_instruction


def test_runtime_judge_rejects_model_outside_available_candidates():
    client = _JudgeClient(
        '{"selected_model_id":"gpt-5.6","confidence":0.92,'
        '"reason_code":"invalid_candidate"}'
    )

    with pytest.raises(RuntimeJudgeResponseError, match="unavailable model"):
        ModelRoutingRuntimeJudge.decide(
            client=client,
            candidate_model_ids=["gpt-4o-mini", "gpt-5-mini"],
            routing_feature_text="간단한 안내 요청",
        )


def test_catalog_selector_uses_continuous_difficulty_score_before_cost():
    profiles = [
        {
            "model_id": "gpt-4o-mini",
            "input_price_per_1k": 0.00015,
            "output_price_per_1k": 0.0006,
            "quality_by_difficulty": {
                "economy": 0.94,
                "balanced": 0.84,
                "advanced": 0.68,
            },
            "fallback_rate": 0.01,
        },
        {
            "model_id": "gpt-5.4",
            "input_price_per_1k": 0.0025,
            "output_price_per_1k": 0.015,
            "quality_by_difficulty": {
                "economy": 0.98,
                "balanced": 0.95,
                "advanced": 0.90,
            },
            "fallback_rate": 0.01,
        },
    ]

    economy = ModelRoutingRuntimeJudge.select_catalog_candidate(
        profiles, difficulty_score=18
    )
    advanced = ModelRoutingRuntimeJudge.select_catalog_candidate(
        profiles, difficulty_score=82
    )
    assert economy.selected_model_id == "gpt-4o-mini"
    assert economy.eligible_model_count == 2
    assert advanced.selected_model_id == "gpt-5.4"
    assert advanced.eligible_model_count == 1


def test_low_judge_confidence_keeps_the_default_model():
    assert ModelRoutingRuntimeJudge.confidence_allows_catalog_selection(0.65) is True
    assert ModelRoutingRuntimeJudge.confidence_allows_catalog_selection(0.64) is False


def test_runtime_judge_rejects_long_or_non_korean_reason():
    client = _JudgeClient(
        '{"difficulty_score":42,"confidence":0.70,'
        '"reason_short":"this reason is too long","reason_code":"balanced_quality"}'
    )

    with pytest.raises(RuntimeJudgeResponseError, match="reason"):
        ModelRoutingRuntimeJudge.decide(
            client=client,
            candidate_model_ids=["gpt-4o-mini"],
            routing_feature_text="조건을 확인해 주세요",
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
        routing_feature_text=secret_like_request,
    )

    assert "SECRET-123" not in str(decision.safe_metadata())
    assert "customer@example.com" not in str(decision.safe_metadata())
