from types import SimpleNamespace

import pytest

from apps.workflow_engine.services.model_router import (
    ModelRouter,
    ModelRoutingUnavailableError,
)
from apps.workflow_engine.services.model_routing_judge_first_policy import (
    build_judge_first_active_policy,
)
from apps.workflow_engine.workflow.nodes.llm.entities import LLMNodeData


def _node(**overrides):
    values = {
        "model_id": "gpt-4.1",
        "fallback_model_id": "gpt-4.1-mini",
        "system_prompt": "고객 문의를 처리합니다.",
        "user_prompt": "{{message}}",
        "assistant_prompt": "",
        "output_format": {"type": "json", "schema": {"type": "object"}},
        "knowledgeBases": [],
        "knowledgeCollections": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _policy(**active_overrides):
    active = build_judge_first_active_policy(
        policy_version="judge-first-v1",
        default_model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        candidate_model_ids=["gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"],
    )
    active.update(active_overrides)
    return {"active_policy": active}


def test_workflow_chat_model_allowlist_includes_gpt_56_aliases():
    for model_id in ("gpt-5.6", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        assert ModelRouter.is_workflow_chat_model(
            SimpleNamespace(model_id_for_api_call=model_id, type="chat")
        )


def test_judge_first_requires_runtime_judge_before_local_learning():
    decision = ModelRouter.resolve_policy(
        _policy(),
        inputs={"message": "환불 정책을 확인해 주세요."},
        node_data=_node(),
        available_model_ids=["gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"],
    )

    assert decision.selected_model_id == "gpt-4.1"
    assert decision.reason_code == "judge_bootstrap_required"
    assert decision.decision_source == "runtime_judge_pending"
    assert decision.requires_runtime_judge is True


def test_confident_local_prediction_skips_runtime_judge(monkeypatch):
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router."
        "MDebertaModelChoiceClassifier.predict",
        lambda *_args, **_kwargs: SimpleNamespace(
            selected_model_id="gpt-4o-mini",
            confidence=0.91,
        ),
    )
    policy = _policy(
        learning={
            "mode": "local_first",
            "local_confidence_threshold": 0.78,
            "local_router_artifact": {"version": 1},
        }
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "비밀번호 변경 위치를 알려 주세요."},
        node_data=_node(),
        available_model_ids=["gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"],
        routing_feature_text="CURRENT_REQUEST: 비밀번호 변경 위치",
    )

    assert decision.selected_model_id == "gpt-4o-mini"
    assert decision.reason_code == "local_router_confident"
    assert decision.decision_source == "local_router"
    assert decision.requires_runtime_judge is False


def test_uncertain_local_prediction_returns_to_runtime_judge(monkeypatch):
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router."
        "MDebertaModelChoiceClassifier.predict",
        lambda *_args, **_kwargs: SimpleNamespace(
            selected_model_id="gpt-4o-mini",
            confidence=0.55,
        ),
    )
    policy = _policy(
        learning={
            "mode": "local_first",
            "local_confidence_threshold": 0.78,
            "local_router_artifact": {"version": 1},
        }
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "모호한 복합 요청"},
        node_data=_node(),
        available_model_ids=["gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"],
    )

    assert decision.reason_code == "local_router_uncertain"
    assert decision.requires_runtime_judge is True


def test_legacy_policy_is_not_executable():
    with pytest.raises(ModelRoutingUnavailableError):
        ModelRouter.resolve_policy(
            {"active_policy": {"strategy_id": "prior_guided_adaptive_v1"}},
            inputs={"message": "문의"},
            node_data=_node(),
        )


def test_routing_feature_contains_all_node_prompts_and_runtime_signals():
    feature = ModelRouter.routing_feature_text(
        {"message": "세 문서를 비교해 승인 여부를 판단해 주세요."},
        _node(),
        rendered_prompt_parts=[
            "고정 시스템 프롬프트",
            "고정 사용자 프롬프트",
            "고정 어시스턴트 프롬프트",
        ],
        # 작업 설명은 프롬프트 원문보다 먼저 이해되는 고정 계약이다.
        rag_metadata={
            "used": True,
            "retrieved_chunk_count": 3,
            "retrieved_context_chars": 920,
            "source_count": 2,
            "evidence_sufficient": True,
            "knowledge_enabled": True,
        },
    )

    feature_with_description = ModelRouter.routing_feature_text(
        {"message": "세 문서를 비교해 승인 여부를 판단해 주세요."},
        _node(
            title="계약 검토",
            model_routing_task_description="여러 근거를 비교해 조건 충돌을 설명하고 구조화된 결론을 작성합니다.",
        ),
        rendered_prompt_parts=["시스템", "사용자", "어시스턴트"],
        rag_metadata={
            "used": True,
            "retrieved_chunk_count": 3,
            "retrieved_context_chars": 920,
            "source_count": 2,
            "evidence_sufficient": True,
            "knowledge_enabled": True,
        },
    )

    assert feature.startswith("CURRENT_REQUEST:")
    assert "세 문서를 비교" in feature
    assert "RAG_RUNTIME_SIGNALS:" in feature
    assert '"retrieved_chunk_count": 3' in feature
    assert '"evidence_sufficient": true' in feature
    assert "NODE_TASK_CONTRACT:" in feature
    assert "SYSTEM_PROMPT:\n고정 시스템 프롬프트" in feature
    assert "USER_PROMPT:\n고정 사용자 프롬프트" in feature
    assert "ASSISTANT_PROMPT:\n고정 어시스턴트 프롬프트" in feature
    assert "STRUCTURAL_CONSTRAINTS:" not in feature
    assert "schema_required" not in feature
    assert "knowledge_enabled" not in feature
    assert "NODE_TITLE: 계약 검토" in feature_with_description
    assert "TASK_DESCRIPTION:" in feature_with_description
    assert "여러 근거를 비교" in feature_with_description


def test_llm_node_data_preserves_bounded_model_routing_task_description():
    description = "여러 근거를 비교해 조건 충돌을 설명합니다."
    node_data = LLMNodeData.model_validate(
        {
            "title": "계약 검토",
            "model_id": "gpt-4.1-mini",
            "model_routing_task_description": description,
        }
    )

    dumped = node_data.model_dump()
    feature = ModelRouter.routing_feature_text(
        {"message": "휴가 규정과 운영 규정을 비교해 주세요."},
        node_data,
    )

    assert dumped["model_routing_task_description"] == description
    assert f"TASK_DESCRIPTION:\n{description}" in feature

    with pytest.raises(ValueError):
        LLMNodeData.model_validate(
            {
                "title": "계약 검토",
                "model_id": "gpt-4.1-mini",
                "model_routing_task_description": "가" * 4001,
            }
        )


def test_routing_feature_renders_variables_and_json_output_contract():
    node_data = _node(
        system_prompt="{{department}} 정책을 검토합니다.",
        user_prompt="질문: {{question}}",
        assistant_prompt="응답 형식: {{format}}",
        referenced_variables=[
            {"name": "department", "value_selector": ["start", "department"]},
            {"name": "question", "value_selector": ["start", "question"]},
            {"name": "format", "value_selector": ["start", "format"]},
        ],
        output_format={
            "type": "json",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
            },
        },
    )

    feature = ModelRouter.routing_feature_text(
        {
            "start": {
                "department": "개발팀",
                "question": "휴가 규정을 알려 주세요.",
                "format": "요약",
            }
        },
        node_data,
    )

    assert "SYSTEM_PROMPT:\n개발팀 정책을 검토합니다." in feature
    assert "USER_PROMPT:\n질문: 휴가 규정을 알려 주세요." in feature
    assert "ASSISTANT_PROMPT:\n응답 형식: 요약" in feature
    assert "json schema:" in feature
    assert '"answer"' in feature
    assert "{{" not in feature

    missing_value_feature = ModelRouter.routing_feature_text({}, node_data)
    assert "None" not in missing_value_feature
    assert "{{" not in missing_value_feature


def test_routing_feature_truncates_task_description_to_judge_budget():
    feature = ModelRouter.routing_feature_text(
        {"message": "요청"},
        _node(model_routing_task_description="가" * 4000),
    )

    description = feature.split("TASK_DESCRIPTION:\n", 1)[1].split(
        "\n\nPROMPT_CONSTRAINTS:", 1
    )[0]
    assert len(description) == 420
    assert description.endswith("…")


def test_routing_feature_preserves_current_request_when_node_prompts_are_long():
    long_prompt = "고정 작업 계약 " * 1_000
    request = "짧지만 여러 예외 조건을 함께 검토해 승인 여부를 결정해 주세요."

    feature = ModelRouter.routing_feature_text(
        {"message": request},
        _node(),
        rendered_prompt_parts=[long_prompt, long_prompt, long_prompt],
    )

    assert feature.startswith(f"CURRENT_REQUEST:\nmessage: {request}")
    assert "NODE_TASK_CONTRACT:" in feature
    assert len(feature) < 3_000
    assert feature.count("…") == 3
