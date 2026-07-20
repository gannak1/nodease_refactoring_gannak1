from types import SimpleNamespace

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


def test_json_output_contract_is_not_in_local_learning_feature():
    node = SimpleNamespace(
        title="고객 문의 처리",
        system_prompt="문의에 답합니다.",
        user_prompt="{{ message }}",
        assistant_prompt="",
        output_format={
            "type": "json",
            "schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
        },
    )

    feature = ModelRouter.learning_feature_text({"message": "VPN 연결 방법"}, node)

    assert "CURRENT_REQUEST_JSON:" in feature
    assert "NODE_TASK_CONTEXT:" in feature
    assert "OUTPUT_CONTRACT:" not in feature
    assert '"type": "json"' not in feature


def test_local_mode_rejects_a_collapsed_judge_label_distribution():
    assert learning_mode_for(
        judged_request_count=50,
        distinct_selected_model_count=3,
        largest_selected_model_share=0.84,
        success_rate=1.0,
        schema_pass_rate=1.0,
        downstream_success_rate=1.0,
        fallback_rate=0.0,
    ) == "judge_first"
