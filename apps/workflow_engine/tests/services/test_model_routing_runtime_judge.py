
import pytest

from apps.workflow_engine.services.model_routing_runtime_judge import (
    ModelRoutingRuntimeJudge,
    RuntimeJudgeResponseError,
)
from apps.shared.services.llm_client.base import ProviderInvocationError
from apps.workflow_engine.workflow.nodes.llm.llm_node import LLMNode


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
                            '{"selected_model_id":"gpt-4o-mini",'
                            '"confidence":0.81,'
                            '"reason_code":"high_risk_reasoning"}'
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 26, "completion_tokens": 12},
        }


def test_runtime_judge_accepts_only_current_execution_subject_candidates():
    client = _JudgeClient(
        '{"selected_model_id":"gpt-5-mini",'
        '"confidence":0.86,'
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

    assert decision.selected_model_id == "gpt-5-mini"
    assert decision.reason_short == "근거 종합 필요"
    assert decision.confidence == 0.86
    assert decision.reason_code == "advanced_quality"
    assert decision.usage == {"prompt_tokens": 42, "completion_tokens": 18}
    rendered_prompt = client.calls[0]["messages"][1]["content"]
    prompt_body = __import__("json").loads(rendered_prompt)
    assert prompt_body["candidate_models"] == [
        {
            "id": "gpt-4o-mini",
            "input_price_per_1k": 0.00015,
            "output_price_per_1k": 0.0006,
            "capability_tier": "economy",
            "quality_for_complex_reasoning": 0.62,
            "fallback_rate": 0.04,
        },
        {
            "id": "gpt-5-mini",
            "input_price_per_1k": 0.00025,
            "output_price_per_1k": 0.002,
            "capability_tier": "balanced",
            "quality_for_complex_reasoning": 0.86,
            "fallback_rate": 0.01,
        },
    ]
    assert "default_model_id" not in rendered_prompt
    assert "fallback_model_id" not in rendered_prompt
    assert "node_contract" not in rendered_prompt
    assert "candidate_profiles" not in prompt_body
    assert prompt_body["candidate_models"][0]["capability_tier"] == "economy"
    assert "작업 복잡도" in client.calls[0]["messages"][0]["content"]
    assert "CURRENT_REQUEST는 이번 실행에서 달라지는 난이도 판단의 주된 근거" in client.calls[0]["messages"][0]["content"]
    assert "economy·balanced·advanced 중 하나를 기계적으로 먼저 고르지 마세요" in client.calls[0]["messages"][0]["content"]
    assert "결정 영향도" in client.calls[0]["messages"][0]["content"]
    assert "근거 종합 범위" in client.calls[0]["messages"][0]["content"]
    assert "특정 업무 분야의 단어만으로 고성능 모델을 고르면 안 됩니다" in client.calls[0]["messages"][0]["content"]
    assert "권한·개인정보·금전·보상" not in client.calls[0]["messages"][0]["content"]
    assert "가장 낮은 모델을 선택하세요" not in client.calls[0]["messages"][0]["content"]
    assert "cost" not in prompt_body["candidate_models"][0]
    assert "quality" not in prompt_body["candidate_models"][0]
    assert prompt_body["rag_context"] == {
        "used": True,
        "retrieved_context_token_estimate": 4200,
        "retrieved_context_chars": 14800,
        "source_count": 3,
    }
    assert "[파일:" not in rendered_prompt
    assert client.calls[0]["kwargs"]["response_format"] == {"type": "json_object"}
    assert client.calls[0]["kwargs"]["max_tokens"] == 512


def test_runtime_judge_marks_non_rag_request_without_inventing_retrieval_metrics():
    client = _JudgeClient(
        '{"selected_model_id":"gpt-4o-mini",'
        '"confidence":0.72,'
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


def test_runtime_judge_collapses_sol_alias_and_receives_source_backed_specializations():
    client = _JudgeClient(
        '{"selected_model_id":"gpt-5.6-sol","confidence":0.88,'
        '"reason_short":"전문 업무 종합","reason_code":"professional_synthesis"}'
    )

    decision = ModelRoutingRuntimeJudge.decide(
        client=client,
        candidate_model_ids=["gpt-5.6", "gpt-5.6-sol", "o3"],
        routing_feature_text="여러 부서 자료를 통합해 경영진 보고서를 작성합니다.",
        candidate_profiles=[
            {
                "model_id": "gpt-5.6-sol",
                "canonical_model_id": "gpt-5.6-sol",
                "evidence_type": "provider_documentation",
                "model_role": "frontier_generalist",
                "specialization_tags": [
                    "complex_professional_work",
                    "complex_reasoning",
                    "coding",
                ],
            },
            {
                "model_id": "o3",
                "canonical_model_id": "o3",
                "evidence_type": "provider_documentation",
                "model_role": "reasoning_specialist",
                "specialization_tags": [
                    "multi_step_reasoning",
                    "math_reasoning",
                    "scientific_reasoning",
                ],
            },
        ],
    )

    assert decision.selected_model_id == "gpt-5.6-sol"
    prompt_body = __import__("json").loads(client.calls[0]["messages"][1]["content"])
    assert [row["id"] for row in prompt_body["candidate_models"]] == [
        "gpt-5.6-sol",
        "o3",
    ]
    assert prompt_body["candidate_models"][0]["specialization_tags"] == [
        "complex_professional_work",
        "complex_reasoning",
        "coding",
    ]
    assert prompt_body["candidate_models"][0]["evidence_type"] == "provider_documentation"
    assert prompt_body["candidate_models"][0]["model_role"] == "frontier_generalist"
    assert prompt_body["candidate_models"][1]["specialization_tags"] == [
        "multi_step_reasoning",
        "math_reasoning",
        "scientific_reasoning",
    ]
    assert prompt_body["candidate_models"][1]["model_role"] == "reasoning_specialist"
    instruction = client.calls[0]["messages"][0]["content"]
    assert "공급자 공식 특화 태그는 약한 사전 정보" in instruction
    assert "일반 전문 업무 능력과 전문 추론 능력을 같은 것으로 취급하지 마세요" in instruction
    assert "reasoning_specialist인 후보는 형식 논증이나 다단계 추론 자체가 핵심일 때" in instruction


def test_llm_node_builds_distinct_source_backed_profiles_for_sol_and_o3():
    profiles = LLMNode._routing_candidate_profiles(
        object(),
        ["gpt-5.6-sol", "o3"],
    )

    assert profiles[0]["canonical_model_id"] == "gpt-5.6-sol"
    assert profiles[0]["catalog_evidence_type"] == "provider_documentation"
    assert "complex_professional_work" in profiles[0]["specialization_tags"]
    assert "math_reasoning" in profiles[1]["specialization_tags"]
    assert profiles[0]["specialization_tags"] != profiles[1]["specialization_tags"]


def test_runtime_judge_receives_operational_contract_evidence_as_stronger_than_catalog_prior():
    client = _JudgeClient(
        '{"selected_model_id":"gpt-5-mini","confidence":0.84,'
        '"reason_short":"실제성적우선반영","reason_code":"contract_reliability"}'
    )

    ModelRoutingRuntimeJudge.decide(
        client=client,
        candidate_model_ids=["gpt-4o-mini", "gpt-5-mini"],
        routing_feature_text="여러 계정 상태와 계약 조건을 함께 확인해야 합니다.",
        candidate_profiles=[
            {
                "model_id": "gpt-4o-mini",
                "quality_by_difficulty": {"balanced": 0.90},
                "operational_run_count": 8,
                "operational_schema_pass_rate": 0.75,
                "operational_downstream_success_rate": 0.75,
                "operational_fallback_rate": 0.25,
            },
            {
                "model_id": "gpt-5-mini",
                "quality_by_difficulty": {"balanced": 0.83},
                "operational_run_count": 8,
                "operational_schema_pass_rate": 1.0,
                "operational_downstream_success_rate": 1.0,
                "operational_fallback_rate": 0.0,
            },
        ],
    )

    instruction = client.calls[0]["messages"][0]["content"]
    prompt_body = __import__("json").loads(client.calls[0]["messages"][1]["content"])
    assert "실제 배포 실행에서 나온 workflow 계약 성적" in instruction
    assert prompt_body["candidate_models"][0]["operational_run_count"] == 8
    assert prompt_body["candidate_models"][0]["operational_schema_pass_rate"] == 0.75
    assert prompt_body["candidate_models"][0]["operational_fallback_rate"] == 0.25


def test_runtime_judge_diagnostic_mode_requests_and_keeps_candidate_comparison():
    client = _JudgeClient(
        '{"selected_model_id":"gpt-5.4","confidence":0.91,'
        '"reason_short":"복수 근거 종합","reason_code":"evidence_synthesis",'
        '"decision_detail":{"task_assessment":"충돌하는 정책 근거를 비교해야 합니다.",'
        '"difficulty_analysis":{"overall_level":"high","task_complexity":3,'
        '"decision_impact":2,"evidence_synthesis":3,'
        '"reason":"복수 규정의 충돌과 예외를 함께 해석해야 합니다."},'
        '"selection_explanation":"gpt-5.4가 필요한 근거 종합 능력을 가장 안정적으로 제공합니다.",'
        '"candidate_comparison":['
        '{"model_id":"gpt-4o-mini","decision":"not_selected",'
        '"reason":"복수 근거 충돌 판단에 보수적입니다."},'
        '{"model_id":"gpt-5.4","decision":"selected",'
        '"reason":"근거 충돌과 예외 조건을 함께 판단합니다."}]}}'
    )

    decision = ModelRoutingRuntimeJudge.decide(
        client=client,
        candidate_model_ids=["gpt-4o-mini", "gpt-5.4"],
        routing_feature_text="두 정책 문서가 충돌할 때 고객 보상 여부를 판단해 주세요.",
        diagnostic_mode=True,
    )

    assert decision.decision_detail == {
        "task_assessment": "충돌하는 정책 근거를 비교해야 합니다.",
        "difficulty_analysis": {
            "overall_level": "high",
            "task_complexity": 3,
            "decision_impact": 2,
            "evidence_synthesis": 3,
            "reason": "복수 규정의 충돌과 예외를 함께 해석해야 합니다.",
        },
        "selection_explanation": "gpt-5.4가 필요한 근거 종합 능력을 가장 안정적으로 제공합니다.",
        "candidate_comparison": [
            {
                "model_id": "gpt-4o-mini",
                "decision": "not_selected",
                "reason": "복수 근거 충돌 판단에 보수적입니다.",
            },
            {
                "model_id": "gpt-5.4",
                "decision": "selected",
                "reason": "근거 충돌과 예외 조건을 함께 판단합니다.",
            },
        ],
    }
    instruction = client.calls[0]["messages"][0]["content"]
    assert "decision_detail" in instruction
    assert "candidate_comparison" in instruction
    assert "difficulty_analysis" in instruction
    assert "selection_explanation" in instruction
    assert client.calls[0]["kwargs"]["max_tokens"] == 2000


def test_runtime_judge_retries_incomplete_response_with_compact_contract():
    client = _IncompleteThenCompactJudgeClient("")

    decision = ModelRoutingRuntimeJudge.decide(
        client=client,
        candidate_model_ids=["gpt-4o-mini"],
        routing_feature_text="승인 전 예외 조항과 근거 문서를 함께 검토해 주세요.",
        rag_context={"used": True, "retrieved_chunk_count": 4, "source_count": 2},
    )

    assert len(client.calls) == 2
    assert client.calls[0]["kwargs"]["max_tokens"] == 512
    assert client.calls[1]["kwargs"]["max_tokens"] == 512
    assert decision.reason_short == "고위험 판단 필요"
    compact_instruction = client.calls[1]["messages"][0]["content"]
    assert "reason_short" not in compact_instruction
    assert "reason_code" in compact_instruction
    compact_body = __import__("json").loads(client.calls[1]["messages"][1]["content"])
    assert compact_body["candidate_models"] == [{"id": "gpt-4o-mini"}]


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


def test_runtime_judge_rejects_response_without_a_selected_candidate():
    client = _JudgeClient(
        '{"confidence":0.81,'
        '"reason_short":"여러 조건 종합","reason_code":"multi_constraint"}'
    )

    with pytest.raises(RuntimeJudgeResponseError, match="selected model"):
        ModelRoutingRuntimeJudge.decide(
            client=client,
            candidate_model_ids=["gpt-4o-mini", "gpt-5-mini"],
            routing_feature_text="두 계약 조건을 함께 검토해 주세요.",
        )


def test_runtime_judge_rejects_long_or_non_korean_reason():
    client = _JudgeClient(
        '{"selected_model_id":"gpt-4o-mini","confidence":0.70,'
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
        '"reason_short":"단순 계약 확인","reason_code":"short_answer"}'
    )

    decision = ModelRoutingRuntimeJudge.decide(
        client=client,
        candidate_model_ids=["gpt-4o-mini"],
        routing_feature_text=secret_like_request,
    )

    assert "SECRET-123" not in str(decision.safe_metadata())
    assert "customer@example.com" not in str(decision.safe_metadata())
