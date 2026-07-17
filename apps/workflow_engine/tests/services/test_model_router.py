from types import SimpleNamespace

import pytest

from apps.workflow_engine.services.model_router import (
    ModelRouter,
    ModelRoutingUnavailableError,
)
from apps.workflow_engine.services.model_routing_judge_first_policy import (
    build_judge_first_active_policy,
)


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


def test_routing_feature_contains_request_prompt_and_structural_contract():
    feature = ModelRouter.routing_feature_text(
        {"message": "세 문서를 비교해 승인 여부를 판단해 주세요."},
        _node(),
    )

    assert "CURRENT_REQUEST:" in feature
    assert "세 문서를 비교" in feature
    assert "RENDERED_PROMPT:" in feature
    assert "STRUCTURAL_CONSTRAINTS:" in feature
    assert '"schema_required": true' in feature
