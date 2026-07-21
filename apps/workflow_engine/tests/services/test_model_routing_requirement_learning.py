import json
import math
from types import SimpleNamespace

import pytest

from apps.workflow_engine.services.model_routing_local_classifier import (
    DEFAULT_MULTILINGUAL_E5_MODEL_ID,
    MultilingualE5Embedder,
    MultilingualE5ModelChoiceClassifier,
)
from apps.workflow_engine.services.model_routing_incremental_learning import (
    IncrementalTaskRequirementClassifier,
    learning_mode_for,
)
from apps.workflow_engine.services.model_router import ModelRouter


def test_requirement_classifier_learns_request_capability_not_selected_model_id():
    artifact = None
    for _ in range(20):
        artifact = IncrementalTaskRequirementClassifier.update(
            artifact,
            vector=[1.0, 0.0],
            task_requirements={
                "task_complexity": 0,
                "decision_impact": 0,
                "evidence_synthesis": 0,
            },
        )
        artifact = IncrementalTaskRequirementClassifier.update(
            artifact,
            vector=[0.0, 1.0],
            task_requirements={
                "task_complexity": 3,
                "decision_impact": 3,
                "evidence_synthesis": 2,
            },
        )

    simple = IncrementalTaskRequirementClassifier.predict(
        artifact,
        vector=[1.0, 0.0],
    )
    advanced = IncrementalTaskRequirementClassifier.predict(
        artifact,
        vector=[0.0, 1.0],
    )

    assert simple.requirements["task_complexity"] < advanced.requirements["task_complexity"]
    assert simple.requirements["decision_impact"] < advanced.requirements["decision_impact"]
    assert "selected_model_id" not in str(artifact)


def test_local_learning_feature_uses_runtime_variables_without_fixed_prompt_contract():
    node = SimpleNamespace(
        title="고객 문의 처리",
        system_prompt="모든 실행에 반복되는 고정 시스템 프롬프트",
        user_prompt="고정 문구 뒤에 {{ message }}를 붙입니다.",
        assistant_prompt="모든 실행에 반복되는 고정 어시스턴트 프롬프트",
        referenced_variables=[
            SimpleNamespace(name="message", value_selector=["webhook", "message"]),
        ],
        output_format={
            "type": "json",
            "schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
        },
    )

    feature = ModelRouter.learning_feature_text(
        {
            "webhook": {"message": "VPN 연결 방법"},
            "unrelated": {"fixed": "학습 대상이 아닌 upstream 값"},
        },
        node,
        rag_metadata={"used": True, "retrieved_chunk_count": 2},
    )

    payload = json.loads(feature)
    assert payload["primary_request"] == {"message": "VPN 연결 방법"}
    assert payload["dynamic_context"] == {}
    assert payload["structured_features"]["rag"] == {
        "retrieved_chunk_count": 2,
        "used": True,
    }
    assert "고정 시스템 프롬프트" not in feature
    assert "고정 문구 뒤에" not in feature
    assert "고정 어시스턴트 프롬프트" not in feature
    assert "학습 대상이 아닌 upstream 값" not in feature
    assert "NODE_TASK_CONTEXT:" not in feature
    assert "OUTPUT_CONTRACT:" not in feature
    assert '"type": "json"' not in feature


def test_local_learning_feature_separates_primary_context_and_structured_values():
    node = SimpleNamespace(
        referenced_variables=[
            SimpleNamespace(name="request", value_selector=["webhook", "request"]),
            SimpleNamespace(name="context", value_selector=["webhook", "context"]),
            SimpleNamespace(name="constraints", value_selector=["webhook", "constraints"]),
            SimpleNamespace(name="customerTier", value_selector=["webhook", "customerTier"]),
            SimpleNamespace(name="outputMode", value_selector=["webhook", "outputMode"]),
        ],
    )

    payload = json.loads(
        ModelRouter.learning_feature_text(
            {
                "webhook": {
                    "request": "결제 장애의 영향 범위를 판단해 주세요.",
                    "context": "복구 작업은 아직 시작되지 않았습니다.",
                    "constraints": ["확정되지 않은 보상을 약속하지 않습니다."],
                    "customerTier": "enterprise",
                    "outputMode": "analysis",
                }
            },
            node,
        )
    )

    assert payload["primary_request"] == {
        "request": "결제 장애의 영향 범위를 판단해 주세요."
    }
    assert payload["dynamic_context"] == {
        "constraints": ["확정되지 않은 보상을 약속하지 않습니다."],
        "context": "복구 작업은 아직 시작되지 않았습니다.",
    }
    assert payload["structured_features"] == {
        "customerTier": "enterprise",
        "outputMode": "analysis",
    }


class _GroupedEmbedder:
    model_id = "grouped-test-embedder"

    def __init__(self):
        self.texts: list[str] = []

    def encode(self, texts, *, mode="plain"):
        self.texts = list(texts)
        vectors = {
            "primary_request": [1.0, 0.0],
            "dynamic_context": [0.0, 1.0],
            "structured_features": [1.0, 1.0],
        }
        return [
            vectors[json.loads(text.removeprefix("query: "))["group"]]
            for text in texts
        ]


def test_grouped_learning_vector_prioritizes_primary_request_without_dropping_context():
    embedder = _GroupedEmbedder()
    feature = json.dumps(
        {
            "primary_request": {"request": "핵심 요청"},
            "dynamic_context": {"context": "추가 문맥"},
            "structured_features": {"customerTier": "enterprise"},
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    vector, model_id = MultilingualE5ModelChoiceClassifier.vectorize(
        feature,
        artifact=None,
        embedder=embedder,
    )

    x_value = 0.75 + 0.10 / math.sqrt(2)
    y_value = 0.15 + 0.10 / math.sqrt(2)
    norm = math.sqrt(x_value**2 + y_value**2)
    assert vector == pytest.approx([x_value / norm, y_value / norm])
    assert model_id == "grouped-test-embedder"
    assert len(embedder.texts) == 3
    assert all(text.startswith("query: ") for text in embedder.texts)


def test_local_router_uses_multilingual_e5_base_by_default(monkeypatch):
    monkeypatch.delenv("MODEL_ROUTING_EMBEDDING_MODEL_ID", raising=False)

    embedder = MultilingualE5Embedder()

    assert DEFAULT_MULTILINGUAL_E5_MODEL_ID == "intfloat/multilingual-e5-base"
    assert embedder.model_id == DEFAULT_MULTILINGUAL_E5_MODEL_ID


def test_local_learning_feature_is_unchanged_when_only_fixed_prompts_change():
    inputs = {"start": {"question": "휴가 규정을 알려 주세요."}}
    variables = [
        SimpleNamespace(name="question", value_selector=["start", "question"]),
    ]
    first = SimpleNamespace(
        title="첫 제목",
        system_prompt="첫 시스템 프롬프트",
        user_prompt="질문: {{ question }}",
        assistant_prompt="첫 어시스턴트 프롬프트",
        referenced_variables=variables,
    )
    second = SimpleNamespace(
        title="완전히 다른 제목",
        system_prompt="완전히 다른 시스템 프롬프트",
        user_prompt="다른 고정 문구: {{ question }}",
        assistant_prompt="완전히 다른 어시스턴트 프롬프트",
        referenced_variables=variables,
    )

    assert ModelRouter.learning_feature_text(
        inputs,
        first,
    ) == ModelRouter.learning_feature_text(inputs, second)


def test_local_learning_feature_falls_back_to_runtime_inputs_without_variable_metadata():
    node = SimpleNamespace(
        title="레거시 LLM 노드",
        system_prompt="고정 시스템 프롬프트",
        user_prompt="고정 사용자 프롬프트",
        assistant_prompt="",
        referenced_variables=[],
    )

    feature = ModelRouter.learning_feature_text(
        {"message": "비밀번호 재설정 방법을 알려 주세요."},
        node,
    )

    assert '"message": "비밀번호 재설정 방법을 알려 주세요."' in feature
    assert "고정 시스템 프롬프트" not in feature
    assert "고정 사용자 프롬프트" not in feature


def test_local_mode_rejects_a_collapsed_judge_label_distribution():
    assert learning_mode_for(
        judged_request_count=50,
        recent_judge_match_rate=0.95,
        recent_axis_mean_errors={
            "task_complexity": 0.1,
            "decision_impact": 0.1,
            "evidence_synthesis": 0.1,
        },
        recent_judge_label_diversity=3,
        recent_local_prediction_diversity=1,
        recent_contract_pass_rate=1.0,
        success_rate=1.0,
        schema_pass_rate=1.0,
        downstream_success_rate=1.0,
        fallback_rate=0.0,
    ) == "judge_first"


def test_local_mode_requires_recent_pre_learning_accuracy_and_contract_quality():
    healthy = {
        "judged_request_count": 50,
        "recent_judge_match_rate": 0.8,
        "recent_axis_mean_errors": {
            "task_complexity": 0.3,
            "decision_impact": 0.2,
            "evidence_synthesis": 0.4,
        },
        "recent_judge_label_diversity": 3,
        "recent_local_prediction_diversity": 3,
        "recent_contract_pass_rate": 0.95,
        "recent_evaluation_sample_count": 20,
        "success_rate": 0.98,
        "schema_pass_rate": 0.99,
        "downstream_success_rate": 0.99,
        "fallback_rate": 0.01,
    }

    assert learning_mode_for(**healthy) == "local_first"
    assert learning_mode_for(**{**healthy, "recent_judge_match_rate": 0.75}) == "judge_first"
    assert learning_mode_for(
        **{
            **healthy,
            "recent_axis_mean_errors": {
                "task_complexity": 0.6,
                "decision_impact": 0.2,
                "evidence_synthesis": 0.4,
            },
        }
    ) == "judge_first"
    assert learning_mode_for(**{**healthy, "recent_contract_pass_rate": 0.9}) == "judge_first"
