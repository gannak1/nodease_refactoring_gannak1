from apps.workflow_engine.services.model_routing_judge_first_policy import (
    JUDGE_FIRST_STRATEGY_ID,
    build_judge_first_active_policy,
    normalize_judge_first_active_policy,
)


def test_builder_creates_only_judge_first_policy_contract():
    policy = build_judge_first_active_policy(
        policy_version="judge-first-v1",
        default_model_id="gpt-4.1-mini",
        fallback_model_id="gpt-4.1",
        candidate_model_ids=["gpt-4.1-mini", "gpt-4.1", "gpt-4.1-mini"],
    )

    assert policy == {
        "strategy_id": JUDGE_FIRST_STRATEGY_ID,
        "policy_version": "judge-first-v1",
        "default_model_id": "gpt-4.1-mini",
        "fallback_model_id": "gpt-4.1",
        "candidate_model_ids": ["gpt-4.1-mini", "gpt-4.1"],
        "learning": {
            "mode": "judge_first",
            "judged_request_count": 0,
            "selected_model_ids": [],
            "local_confidence_threshold": 0.78,
        },
    }


def test_legacy_policy_is_normalized_without_reusing_legacy_rules():
    legacy = {
        "strategy_id": "prior_guided_adaptive_v1",
        "policy_version": "legacy-v8",
        "default_model_id": "gpt-4.1-mini",
        "fallback_model_id": "gpt-4.1",
        "rules": [
            {
                "id": "legacy-high-risk",
                "selected_model_id": "gpt-5",
                "when": {"keyword_any": ["보상"]},
            }
        ],
        "decision_profiles": [{"id": "legacy-profile"}],
    }

    normalized = normalize_judge_first_active_policy(
        legacy,
        policy_version="judge-first-v1",
        default_model_id="gpt-4.1-mini",
        fallback_model_id="gpt-4.1",
        candidate_model_ids=["gpt-4.1-mini", "gpt-4.1", "gpt-5"],
    )

    assert normalized["strategy_id"] == JUDGE_FIRST_STRATEGY_ID
    assert normalized["learning"]["mode"] == "judge_first"
    assert "rules" not in normalized
    assert "decision_profiles" not in normalized


def test_existing_judge_first_learning_artifact_is_preserved():
    existing = build_judge_first_active_policy(
        policy_version="judge-first-v1",
        default_model_id="gpt-4.1-mini",
        fallback_model_id="gpt-4.1",
        candidate_model_ids=["gpt-4.1-mini", "gpt-4.1"],
    )
    existing["learning"] = {
        "mode": "local_first",
        "judged_request_count": 31,
        "selected_model_ids": ["gpt-4.1-mini", "gpt-4.1"],
        "local_confidence_threshold": 0.81,
        "local_router_artifact": {"kind": "incremental-model-choice-v1"},
    }

    normalized = normalize_judge_first_active_policy(
        existing,
        policy_version="judge-first-v2",
        default_model_id="gpt-4.1-mini",
        fallback_model_id="gpt-4.1",
        candidate_model_ids=["gpt-4.1-mini", "gpt-4.1"],
    )

    assert normalized["policy_version"] == "judge-first-v2"
    assert normalized["learning"] == existing["learning"]
