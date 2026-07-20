import json
from types import SimpleNamespace
from uuid import uuid4

from apps.workflow_engine.services.model_router import ModelRouter
from apps.workflow_engine.services.model_routing_incremental_learning import (
    learning_mode_for,
)
from apps.workflow_engine.services.model_routing_judge_first_policy import (
    build_judge_first_active_policy,
)
from apps.workflow_engine.services.model_routing_local_classifier import (
    MDebertaModelChoiceClassifier,
    MDebertaTaskRequirementClassifier,
)
from apps.workflow_engine.services.model_routing_runtime_judge import (
    ModelRoutingRuntimeJudge,
)


class _FeatureEmbedder:
    model_id = "test/judge-first-feature-encoder"

    def encode(self, texts, *, mode="plain"):
        del mode
        return [
            [1.0, 0.0] if "간단" in text else [0.0, 1.0]
            for text in texts
        ]


class _JudgeClient:
    def invoke_sync(self, *, messages, **kwargs):
        del kwargs
        body = json.loads(messages[1]["content"])
        is_simple = "간단" in body["request_feature"]
        selected = "gpt-4o-mini" if is_simple else "gpt-5.4"
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "selected_model_id": selected,
                                "confidence": 0.92,
                                "reason_short": "단순 안내 요청" if is_simple else "여러 조건 종합",
                                "reason_code": "request_capability_match",
                                "task_requirements": {
                                    "task_complexity": 1 if is_simple else 3,
                                    "decision_impact": 0 if is_simple else 2,
                                    "evidence_synthesis": 0 if is_simple else 2,
                                    "output_precision": 0,
                                },
                            }
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
        }


def _node_data():
    return SimpleNamespace(
        model_id="gpt-5-mini",
        fallback_model_id="gpt-4o-mini",
        system_prompt="고객 요청을 처리합니다.",
        user_prompt="{{ message }}",
        assistant_prompt="",
        output_format={"type": "text"},
        knowledgeBases=[],
        knowledgeCollections=[],
    )


def test_judge_labels_gradually_enable_confident_local_routing(monkeypatch):
    candidates = ["gpt-4o-mini", "gpt-5.4"]
    active_policy = build_judge_first_active_policy(
        policy_version="judge-first-e2e-v1",
        default_model_id="gpt-5.4",
        fallback_model_id="gpt-4o-mini",
        candidate_model_ids=candidates,
    )
    policy = {"active_policy": active_policy}

    initial = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "간단 사용 안내"},
        node_data=_node_data(),
        available_model_ids=candidates,
        routing_feature_text="간단 사용 안내",
    )
    assert initial.requires_runtime_judge is True
    assert initial.decision_source == "runtime_judge_pending"

    embedder = _FeatureEmbedder()
    artifact = None
    selected_models: set[str] = set()
    for index in range(50):
        feature = "간단 사용 안내" if index % 2 == 0 else "복잡 규정 종합 판단"
        judge_decision = ModelRoutingRuntimeJudge.decide(
            client=_JudgeClient(),
            candidate_model_ids=candidates,
            routing_feature_text=feature,
        )
        selected_models.add(judge_decision.selected_model_id)
        vector, encoder_model_id = MDebertaModelChoiceClassifier.vectorize(
            feature,
            artifact=artifact,
            embedder=embedder,
        )
        artifact = MDebertaTaskRequirementClassifier.update_from_vector(
            artifact,
            vector=vector,
            encoder_model_id=encoder_model_id,
            task_requirements=judge_decision.task_requirements or {},
        )

    mode = learning_mode_for(
        judged_request_count=50,
        distinct_selected_model_count=len(selected_models),
        success_rate=1.0,
        schema_pass_rate=1.0,
        downstream_success_rate=1.0,
        fallback_rate=0.0,
    )
    assert mode == "local_first"

    monkeypatch.setitem(
        MDebertaModelChoiceClassifier._embedder_cache,
        embedder.model_id,
        embedder,
    )
    active_policy["learning"] = {
        "mode": mode,
        "judged_request_count": 50,
        "selected_model_ids": sorted(selected_models),
        "local_confidence_threshold": 0.78,
        "local_requirement_artifact": artifact,
    }

    simple = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "간단 사용 안내"},
        node_data=_node_data(),
        available_model_ids=candidates,
        routing_feature_text="간단 사용 안내",
    )
    complex_request = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "복잡 규정 종합 판단"},
        node_data=_node_data(),
        available_model_ids=candidates,
        routing_feature_text="복잡 규정 종합 판단",
    )

    assert simple.selected_model_id == "gpt-4o-mini"
    assert complex_request.selected_model_id == "gpt-5.4"
    assert simple.decision_source == "local_router"
    assert complex_request.decision_source == "local_router"
    assert simple.requires_runtime_judge is False
    assert complex_request.requires_runtime_judge is False


def test_fifty_accepted_labels_enable_local_router_on_fifty_first_request(monkeypatch):
    """배포 1회 label 확정부터 51회차 local router 전환까지 같은 경로로 검증한다."""
    from apps.workflow_engine.services.model_routing_operational_performance import (
        ModelRoutingOperationalPerformanceService,
    )
    from apps.workflow_engine.services.model_routing_policy_store import (
        ModelRoutingPolicyStore,
    )

    candidates = ["gpt-4o-mini", "gpt-5-mini"]
    policy = SimpleNamespace(
        id=uuid4(),
        active_policy=build_judge_first_active_policy(
            policy_version="judge-first-e2e-v2",
            default_model_id="gpt-5-mini",
            fallback_model_id="gpt-4o-mini",
            candidate_model_ids=candidates,
        ),
    )
    initial_label = SimpleNamespace(
        status="pending",
        feature_vector=[1.0, 0.0],
        encoder_model_id="test/judge-first-feature-encoder",
        selected_model_id="gpt-4o-mini",
        candidate_model_ids=candidates,
        confidence=0.94,
        reason_code="simple_response",
        task_requirements={
            "task_complexity": 1,
            "decision_impact": 0,
            "evidence_synthesis": 0,
        },
        routing_feature_hash=None,
        outcome_reason=None,
    )

    # 첫 label은 실제 finalize 경로에서 accepted가 되고 count가 1이 된다.
    assert ModelRoutingPolicyStore._finalize_runtime_judge_label(
        policy=policy,
        label=initial_label,
        contract_passed=True,
        outcome_reason="contract_passed",
    )
    assert initial_label.status == "accepted"
    assert policy.active_policy["learning"]["judged_request_count"] == 1

    # 서로 다른 두 Judge 선택을 계약 통과 label로 50개 누적한다.
    for index in range(49):
        simple = index % 2 == 0
        label = SimpleNamespace(
            status="pending",
            feature_vector=[1.0, 0.0] if simple else [0.0, 1.0],
            encoder_model_id="test/judge-first-feature-encoder",
            selected_model_id="gpt-4o-mini" if simple else "gpt-5-mini",
            candidate_model_ids=candidates,
            confidence=0.94,
            reason_code="simple_response" if simple else "multi_constraint",
            task_requirements={
                "task_complexity": 1 if simple else 3,
                "decision_impact": 0 if simple else 2,
                "evidence_synthesis": 0 if simple else 2,
            },
            routing_feature_hash=None,
            outcome_reason=None,
        )
        assert ModelRoutingPolicyStore._finalize_runtime_judge_label(
            policy=policy,
            label=label,
            contract_passed=True,
            outcome_reason="contract_passed",
        )

    assert policy.active_policy["learning"]["judged_request_count"] == 50
    monkeypatch.setattr(
        ModelRoutingOperationalPerformanceService,
        "response_summary",
        lambda *_args, **_kwargs: {
            "models": [
                {
                    "run_count": 50,
                    "success_rate": 1.0,
                    "schema_pass_rate": 1.0,
                    "downstream_success_rate": 1.0,
                    "fallback_rate": 0.0,
                }
            ]
        },
    )
    ModelRoutingPolicyStore.reconcile_incremental_learning_mode(
        object(), policy=policy
    )
    assert policy.active_policy["learning"]["mode"] == "local_first"

    embedder = _FeatureEmbedder()
    monkeypatch.setitem(
        MDebertaModelChoiceClassifier._embedder_cache,
        embedder.model_id,
        embedder,
    )
    decision = ModelRouter.resolve_policy(
        {"active_policy": policy.active_policy},
        inputs={"message": "간단 사용 안내"},
        node_data=_node_data(),
        available_model_ids=candidates,
        routing_feature_text="간단 사용 안내",
    )
    assert decision.decision_source == "local_router"
    assert decision.selected_model_id == "gpt-4o-mini"
