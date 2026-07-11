import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from apps.gateway.services.cost_optimizer_output_quality_service import (
    CostOptimizerOutputQualityService,
)


class _JudgeClient:
    def __init__(self, response):
        self.response = response
        self.messages = None

    def invoke_sync(self, messages, **kwargs):
        self.messages = messages
        return self.response


def _judge_response():
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "variant_left": {
                                "instruction_fulfillment": 71,
                                "relevance_completeness": 74,
                                "clarity_consistency": 70,
                            },
                            "variant_right": {
                                "instruction_fulfillment": 86,
                                "relevance_completeness": 82,
                                "clarity_consistency": 84,
                            },
                            "confidence": 0.82,
                            "safe_summary": "한 출력이 더 간결하고 요청 범위를 충족합니다.",
                        }
                    )
                }
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
    }


def test_fr13_quality_judge_uses_blind_pairwise_variants_and_records_usage():
    db = MagicMock()
    workflow = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    current_user = SimpleNamespace(id=uuid4())
    candidate_row = SimpleNamespace(id=uuid4())
    judge_log = SimpleNamespace(id=uuid4(), total_cost=0.0004)
    client = _JudgeClient(_judge_response())

    with (
        patch(
            "apps.gateway.services.cost_optimizer_output_quality_service.LLMService.get_my_available_models",
            return_value=[
                SimpleNamespace(model_id_for_api_call="gpt-4.1-mini", type="chat")
            ],
        ),
        patch(
            "apps.gateway.services.cost_optimizer_output_quality_service.LLMService.calculate_cost",
            return_value=0.0004,
        ),
        patch(
            "apps.gateway.services.cost_optimizer_output_quality_service.LLMService.log_usage",
            return_value=judge_log,
        ) as log_usage,
    ):
        result = CostOptimizerOutputQualityService.evaluate(
            db=db,
            workflow=workflow,
            current_user=current_user,
            node_id="llm-triage",
            candidate_row=candidate_row,
            baseline={"input": {"message": "정산 파일을 다시 생성해 주세요."}, "output": {"text": "처리하겠습니다."}},
            candidate_result={"output": {"text": "정산 파일을 재생성하고 결과를 안내하겠습니다."}},
            judge_client=client,
            judge_model_id="gpt-4.1-mini",
            pair_order="baseline_left",
        )

    assert result["status"] == "completed"
    assert result["baseline"]["score"] == 72
    assert result["candidate"]["score"] == 84
    assert result["delta"] == 12
    assert result["confidence"] == "high"
    assert result["judge_cost"] == 0.0004
    assert result["judge_usage_log_id"] == str(judge_log.id)
    payload = json.loads(client.messages[1]["content"])
    assert set(payload) >= {"variant_left", "variant_right"}
    assert "baseline" not in payload
    assert "candidate" not in payload
    log_usage.assert_called_once()
    assert log_usage.call_args.kwargs["node_id"] == "llm-triage:quality-judge"


def test_fr13_quality_judge_is_partial_when_no_usable_judge_model_exists():
    db = MagicMock()

    with patch(
        "apps.gateway.services.cost_optimizer_output_quality_service.LLMService.get_my_available_models",
        return_value=[],
    ):
        result = CostOptimizerOutputQualityService.evaluate(
            db=db,
            workflow=SimpleNamespace(id=uuid4(), organization_id=uuid4()),
            current_user=SimpleNamespace(id=uuid4()),
            node_id="llm-triage",
            candidate_row=SimpleNamespace(id=uuid4()),
            baseline={"input": {"message": "문의"}, "output": {"text": "A"}},
            candidate_result={"output": {"text": "B"}},
        )

    assert result == {
        "status": "unavailable",
        "baseline": {"score": None},
        "candidate": {"score": None},
        "delta": None,
        "dimensions": {},
        "confidence": "unavailable",
        "safe_summary": "품질 평가에 사용할 수 있는 LLM credential/model이 없습니다.",
        "judge_cost": None,
        "judge_usage_log_id": None,
    }


def test_fr13_quality_judge_tries_next_model_when_first_model_is_not_usable_in_org():
    db = MagicMock()
    workflow = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    current_user = SimpleNamespace(id=uuid4())
    candidate_row = SimpleNamespace(id=uuid4())
    usable_client = _JudgeClient(_judge_response())

    with (
        patch(
            "apps.gateway.services.cost_optimizer_output_quality_service.LLMService.get_my_available_models",
            return_value=[
                SimpleNamespace(model_id_for_api_call="unavailable-model", type="chat"),
                SimpleNamespace(model_id_for_api_call="usable-model", type="chat"),
            ],
        ),
        patch(
            "apps.gateway.services.cost_optimizer_output_quality_service.LLMService.get_client_for_user",
            side_effect=[ValueError("credential denied"), usable_client],
        ) as get_client,
        patch(
            "apps.gateway.services.cost_optimizer_output_quality_service.LLMService.calculate_cost",
            return_value=0.0004,
        ),
        patch(
            "apps.gateway.services.cost_optimizer_output_quality_service.LLMService.log_usage",
            return_value=SimpleNamespace(id=uuid4(), total_cost=0.0004),
        ),
    ):
        result = CostOptimizerOutputQualityService.evaluate(
            db=db,
            workflow=workflow,
            current_user=current_user,
            node_id="llm-triage",
            candidate_row=candidate_row,
            baseline={"input": {"message": "문의"}, "output": {"text": "A"}},
            candidate_result={"input": {"message": "문의"}, "output": {"text": "B"}},
            pair_order="baseline_left",
        )

    assert result["status"] == "completed"
    assert result["judge"]["model_id"] == "usable-model"
    assert get_client.call_count == 2


def test_fr13_quality_judge_skips_legacy_completion_models_mislabeled_as_chat():
    db = MagicMock()
    user_id = uuid4()
    organization_id = uuid4()
    client = _JudgeClient(_judge_response())

    with (
        patch(
            "apps.gateway.services.cost_optimizer_output_quality_service.LLMService.get_my_available_models",
            return_value=[
                SimpleNamespace(model_id_for_api_call="babbage-002", type="chat"),
                SimpleNamespace(model_id_for_api_call="davinci-002", type="chat"),
                SimpleNamespace(model_id_for_api_call="gpt-5.4", type="chat"),
            ],
        ),
        patch(
            "apps.gateway.services.cost_optimizer_output_quality_service.LLMService.get_client_for_user",
            return_value=client,
        ) as get_client,
    ):
        model_id, selected_client = CostOptimizerOutputQualityService._select_judge_runtime(
            db=db,
            user_id=user_id,
            organization_id=organization_id,
            preferred_model_id=None,
        )

    assert model_id == "gpt-5.4"
    assert selected_client is client
    get_client.assert_called_once_with(db, user_id, "gpt-5.4", organization_id)


def test_fr13_quality_judge_adds_groundedness_only_for_rag_variants():
    client = _JudgeClient(_judge_response())

    with (
        patch(
            "apps.gateway.services.cost_optimizer_output_quality_service.LLMService.calculate_cost",
            return_value=0.0004,
        ),
        patch(
            "apps.gateway.services.cost_optimizer_output_quality_service.LLMService.log_usage",
            return_value=SimpleNamespace(id=uuid4(), total_cost=0.0004),
        ),
    ):
        CostOptimizerOutputQualityService.evaluate(
            db=MagicMock(),
            workflow=SimpleNamespace(id=uuid4(), organization_id=uuid4()),
            current_user=SimpleNamespace(id=uuid4()),
            node_id="llm-triage",
            candidate_row=SimpleNamespace(id=uuid4()),
            baseline={
                "input": {"message": "문의"},
                "output": {"text": "A"},
                "trace": {"rag_summary": {"retrieved_chunk_count": 3}},
            },
            candidate_result={"input": {"message": "문의"}, "output": {"text": "B"}},
            judge_client=client,
            judge_model_id="gpt-4.1-mini",
            pair_order="baseline_left",
        )

    payload = json.loads(client.messages[1]["content"])
    assert "groundedness" in payload["dimensions"]
    assert payload["variant_left"]["rag_summary"] == {"retrieved_chunk_count": 3}
