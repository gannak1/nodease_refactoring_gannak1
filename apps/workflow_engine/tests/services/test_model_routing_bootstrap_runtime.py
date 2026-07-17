from types import SimpleNamespace

from apps.workflow_engine.services.model_router import (
    ModelPerformance,
    ModelRouter,
    NodeRunProfile,
)


def test_request_complexity_policy_routes_each_rendered_request_by_difficulty(monkeypatch):
    """같은 노드에서도 요청 프롬프트 난이도에 따라 다른 모델을 선택한다."""
    classifier_inputs: list[str] = []

    def predict(_artifact, feature_text):
        classifier_inputs.append(feature_text)
        if "충돌하는 근거를 비교" in feature_text:
            return SimpleNamespace(
                difficulty="advanced",
                confidence=0.92,
                probabilities={"economy": 0.02, "balanced": 0.06, "advanced": 0.92},
                difficulty_score=91.0,
            )
        return SimpleNamespace(
            difficulty="economy",
            confidence=0.94,
            probabilities={"economy": 0.94, "balanced": 0.04, "advanced": 0.02},
            difficulty_score=8.0,
        )

    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router.MDebertaDifficultyClassifier.predict",
        predict,
    )
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_request_complexity_v3",
            "default_model_id": "gpt-4o-mini",
            "fallback_model_id": "gpt-5-mini",
            "classifier_artifact": {"kind": "mdeberta_linear_difficulty_v1"},
            "global_profile_catalog": _global_profile_catalog(),
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-4o-mini",
        fallback_model_id="gpt-5-mini",
        parameters={"max_tokens": 512},
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="복수 조건을 JSON으로 판정합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decisions = [
        ModelRouter.resolve_policy(
            policy,
            inputs={"message": message},
            node_data=node_data,
            available_model_ids=["gpt-4o-mini", "gpt-5-mini", "gpt-5.4", "gpt-5.6"],
        )
        for message in (
            "휴가 신청 메뉴가 어디에 있나요?",
            "충돌하는 근거를 비교하고 예외 승인 조건까지 판단해 주세요.",
        )
    ]

    assert decisions[0].selected_model_id in {"gpt-4o-mini", "gpt-5-mini"}
    assert decisions[1].selected_model_id == "gpt-5.4"
    assert decisions[0].selected_model_id != decisions[1].selected_model_id
    assert [decision.reason_code for decision in decisions] == [
        "bootstrap_global_profile_economy",
        "bootstrap_global_profile_advanced",
    ]
    assert all(
        decision.decision_factors["routing_basis"] == "request_prompt_complexity_classifier"
        for decision in decisions
    )
    assert "휴가 신청 메뉴가 어디에 있나요?" in classifier_inputs[0]
    assert "충돌하는 근거를 비교" in classifier_inputs[1]


def test_request_complexity_policy_ranks_catalog_even_when_confidence_is_low(monkeypatch):
    """v3의 낮은 분류 신뢰도는 기본 모델 고정이 아니라 보수적 후보 순위화로 처리한다."""

    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router.MDebertaDifficultyClassifier.predict",
        lambda _artifact, _feature_text: SimpleNamespace(
            difficulty="advanced",
            confidence=0.40,
            probabilities={"economy": 0.25, "balanced": 0.35, "advanced": 0.40},
            difficulty_score=57.5,
        ),
    )
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_request_complexity_v3",
            "default_model_id": "gpt-5.6",
            "fallback_model_id": "gpt-5.4",
            "minimum_confidence": 0.45,
            "classifier_artifact": {"kind": "mdeberta_linear_difficulty_v1"},
            "global_profile_catalog": _global_profile_catalog(),
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-5.6",
        fallback_model_id="gpt-5.4",
        parameters={"max_tokens": 512},
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="복수 조건을 JSON으로 판정합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "조건이 일부 충돌하지만 근거를 종합해 판단해 주세요."},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-5-mini", "gpt-5.4", "gpt-5.6"],
    )

    assert decision.reason_code.startswith("bootstrap_global_profile_")
    assert decision.selected_model_id != "gpt-5.6"
    assert decision.decision_factors["confidence_status"] == "low"


def _global_profile_catalog() -> dict:
    """새 bootstrap policy가 저장하는 전체 후보 profile snapshot fixture."""
    def profile(*, economy: float, balanced: float, advanced: float, latency: int):
        return {
            "quality_by_difficulty": {
                "economy": economy,
                "balanced": balanced,
                "advanced": advanced,
            },
            "uncertainty_by_difficulty": {
                "economy": 0.03,
                "balanced": 0.04,
                "advanced": 0.05,
            },
            "expected_latency_ms_by_input_profile": {
                "short": latency,
                "medium": latency,
                "long": latency * 2,
                "unknown": latency,
            },
            "fallback_rate": 0.02,
            "prior_strength": 4.0,
            "source": "test_catalog",
            "profile_version": "test-v1",
            "capability_tier": "balanced",
        }

    return {
        "version": "global-model-profile-catalog-v1",
        "candidates": [
            {
                "model_id": "gpt-4o-mini",
                "display_name": "GPT-4o mini",
                "input_price_1k": 0.00015,
                "output_price_1k": 0.0006,
            },
            {
                "model_id": "gpt-5-mini",
                "display_name": "GPT-5 mini",
                "input_price_1k": 0.00025,
                "output_price_1k": 0.002,
            },
            {
                "model_id": "gpt-5.4",
                "display_name": "GPT-5.4",
                "input_price_1k": 0.0025,
                "output_price_1k": 0.015,
            },
            {
                "model_id": "gpt-5.6",
                "display_name": "GPT-5.6",
                "input_price_1k": 0.005,
                "output_price_1k": 0.03,
            },
        ],
        "profiles": {
            "gpt-4o-mini": profile(
                economy=0.95, balanced=0.70, advanced=0.45, latency=350
            ),
            "gpt-5-mini": profile(
                economy=0.97, balanced=0.91, advanced=0.75, latency=600
            ),
            "gpt-5.4": profile(
                economy=0.99, balanced=0.97, advanced=0.96, latency=1_100
            ),
            "gpt-5.6": profile(
                economy=0.995, balanced=0.98, advanced=0.98, latency=1_600
            ),
        },
    }


def test_bootstrap_difficulty_policy_uses_artifact_tier_before_default_model(monkeypatch):
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router.MDebertaDifficultyClassifier.predict",
        lambda *_args, **_kwargs: SimpleNamespace(
            difficulty="economy",
            confidence=0.91,
            probabilities={"economy": 0.91, "balanced": 0.06, "advanced": 0.03},
            difficulty_score=6.0,
        ),
    )
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1",
            "classifier_artifact": {"kind": "mdeberta_centroid_v1"},
            "difficulty_models": {
                "economy": "gpt-4o-mini",
                "balanced": "gpt-4.1-mini",
                "advanced": "gpt-4.1",
            },
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1",
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="JSON으로 분류합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "비밀번호 재설정 방법을 알려주세요."},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"],
    )

    assert decision.selected_model_id == "gpt-4o-mini"
    assert decision.matched_rule_id == "difficulty-economy"
    assert decision.reason_code == "bootstrap_difficulty_economy"
    assert decision.decision_factors["difficulty_score"] == 6.0


def test_bootstrap_policy_scores_all_available_models_after_difficulty_classification(
    monkeypatch,
):
    """난이도는 입력이고, 실제 선택은 세 개의 tier 고정값이 아닌 전체 후보 점수다."""
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router.MDebertaDifficultyClassifier.predict",
        lambda *_args, **_kwargs: SimpleNamespace(
            difficulty="balanced",
            confidence=0.92,
            probabilities={"economy": 0.05, "balanced": 0.90, "advanced": 0.05},
            difficulty_score=51.0,
        ),
    )
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-5.4",
            "fallback_model_id": "gpt-5.4",
            "classifier_artifact": {"kind": "mdeberta_centroid_v1"},
            # Historical compatibility field intentionally points elsewhere.
            # New policies must use global_profile_catalog before this fallback.
            "difficulty_models": {
                "economy": "gpt-4o-mini",
                "balanced": "gpt-4o-mini",
                "advanced": "gpt-5.4",
            },
            "global_profile_catalog": _global_profile_catalog(),
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-5.4",
        fallback_model_id="gpt-5.4",
        parameters={"max_tokens": 512},
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="JSON으로 고객 요청을 처리합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "여러 단계의 계정 설정 절차를 정리해 주세요."},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-5-mini", "gpt-5.4", "gpt-5.6"],
    )

    assert decision.selected_model_id == "gpt-5-mini"
    assert decision.selected_model_id != "gpt-4o-mini"
    assert decision.reason_code == "bootstrap_global_profile_balanced"
    assert decision.decision_factors["selection_mode"] == "global_profile_score"
    assert decision.decision_factors["compared_model_count"] == 4
    assert decision.decision_factors["effective_operational_samples"] == 0


def test_bootstrap_policy_uses_node_operational_performance_to_adjust_global_score(
    monkeypatch,
):
    """후속 배포 로그가 충분하면 같은 난이도 안에서 해당 노드 성적을 반영한다."""
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router.MDebertaDifficultyClassifier.predict",
        lambda *_args, **_kwargs: SimpleNamespace(
            difficulty="balanced",
            confidence=0.92,
            probabilities={"economy": 0.05, "balanced": 0.90, "advanced": 0.05},
        ),
    )
    catalog = _global_profile_catalog()
    # 전역 prior만 보면 quality floor보다 낮은 후보다. 동일 노드에서의 충분한
    # 성공 성적이 누적된 뒤에만 저비용 모델로 승격되는지 확인한다.
    catalog["profiles"]["gpt-5-mini"]["quality_by_difficulty"]["balanced"] = 0.75
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-5.4",
            "fallback_model_id": "gpt-5.4",
            "classifier_artifact": {"kind": "mdeberta_centroid_v1"},
            "difficulty_models": {"balanced": "gpt-5.4"},
            "global_profile_catalog": catalog,
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-5.4",
        fallback_model_id="gpt-5.4",
        parameters={"max_tokens": 512},
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="JSON으로 고객 요청을 처리합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )
    performance = ModelPerformance(
        model_id="gpt-5-mini",
        run_count=30,
        success_count=30,
        schema_pass_count=30,
        schema_eval_count=30,
        downstream_success_count=30,
        downstream_eval_count=30,
        total_cost=0.03,
        total_latency_ms=12_000,
    )
    node_profile = NodeRunProfile(
        operational_usable_runs=30,
        model_performance={"gpt-5-mini": performance},
        segment_performance={
            "medium": {
                "conditions": {"input_length_bucket": "medium"},
                "model_performance": {"gpt-5-mini": performance},
            }
        },
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "긴 설명 " * 150},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-5-mini", "gpt-5.4", "gpt-5.6"],
        node_profile=node_profile,
    )

    assert decision.selected_model_id == "gpt-5-mini"
    assert decision.decision_factors["effective_operational_samples"] == 30
    assert decision.decision_factors["profile_source"] == "test_catalog+node_operational"


def test_bootstrap_global_profile_routes_when_configured_default_is_no_longer_available(
    monkeypatch,
):
    """기본 모델 권한이 회수돼도 snapshot 안의 다른 사용 가능 후보로 계속 선택한다."""
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router.MDebertaDifficultyClassifier.predict",
        lambda *_args, **_kwargs: SimpleNamespace(
            difficulty="balanced",
            confidence=0.92,
            probabilities={"economy": 0.05, "balanced": 0.90, "advanced": 0.05},
        ),
    )
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "classifier_artifact": {"kind": "mdeberta_centroid_v1"},
            "difficulty_models": {"balanced": "gpt-4.1"},
            "global_profile_catalog": _global_profile_catalog(),
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        parameters={"max_tokens": 512},
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="JSON으로 고객 요청을 처리합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "여러 단계의 계정 설정 절차를 정리해 주세요."},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-5-mini", "gpt-5.4", "gpt-5.6"],
    )

    assert decision.selected_model_id == "gpt-5-mini"
    assert decision.fallback_model_id in {"gpt-5.4", "gpt-5.6", "gpt-4o-mini"}


def test_bootstrap_policy_uses_planner_rule_after_low_confidence_classifier(
    monkeypatch,
):
    """초기 Planner가 만든 노드 전용 신호는 첫 배포부터 모델을 분기한다."""
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router.MDebertaDifficultyClassifier.predict",
        lambda *_args, **_kwargs: SimpleNamespace(
            difficulty="economy",
            confidence=0.34,
            probabilities={"economy": 0.34, "balanced": 0.33, "advanced": 0.33},
        ),
    )
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "classifier_artifact": {"kind": "mdeberta_centroid_v1"},
            "difficulty_models": {
                "economy": "gpt-4o-mini",
                "balanced": "gpt-4.1-mini",
                "advanced": "gpt-5.4",
            },
            "difficulty_rules": [
                {
                    "id": "planner-advanced-conflict",
                    "difficulty": "advanced",
                    "keyword_any": ["규정 충돌", "예외 승인"],
                    "minimum_matches": 1,
                    "reason": "상충하는 규정은 고성능 추론이 필요합니다.",
                }
            ],
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="문서 근거를 바탕으로 답합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "두 규정 충돌이 있을 때 예외 승인 절차를 알려 주세요."},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-5.4"],
    )

    assert decision.selected_model_id == "gpt-5.4"
    assert decision.matched_rule_id == "planner-advanced-conflict"
    assert decision.reason_code == "bootstrap_planner_rule_advanced"
    assert decision.decision_factors["classification_status"] == "planner_rule"
    assert decision.decision_factors["matched_terms"] == ["규정 충돌", "예외 승인"]


def test_bootstrap_policy_prefers_a_validated_structural_rule_before_an_unvalidated_classifier(
    monkeypatch,
):
    """새 bootstrap은 holdout 검증을 통과한 요청 구조 규칙을 먼저 쓴다."""
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router.MDebertaDifficultyClassifier.predict",
        lambda *_args, **_kwargs: SimpleNamespace(
            difficulty="economy",
            confidence=0.88,
            probabilities={"economy": 0.88, "balanced": 0.08, "advanced": 0.04},
        ),
    )
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "classifier_artifact": {"kind": "multilingual_e5_prototype_v1"},
            "difficulty_models": {
                "economy": "gpt-4o-mini",
                "balanced": "gpt-4.1-mini",
                "advanced": "gpt-5.4",
            },
            "generalization_validation": {
                "rules": {"passed": True},
                "classifier": {"passed": False},
            },
            "difficulty_rules": [
                {
                    "id": "balanced-order",
                    "difficulty": "balanced",
                    "keyword_any": ["순서", "절차"],
                    "minimum_matches": 1,
                    "reason": "여러 단계를 정리하는 요청입니다.",
                }
            ],
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="문서 근거를 바탕으로 답합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "계정 설정과 교육 이수를 어떤 순서로 진행하나요?"},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-5.4"],
    )

    assert decision.selected_model_id == "gpt-4.1-mini"
    assert decision.reason_code == "bootstrap_planner_rule_balanced"
    assert decision.decision_factors["classification_status"] == "validated_planner_rule"


def test_bootstrap_policy_uses_only_the_individually_validated_planner_rules(
    monkeypatch,
):
    """분류 확신이 낮을 때도 holdout을 통과한 rule만 보조 경로로 적용한다."""
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router.MDebertaDifficultyClassifier.predict",
        lambda *_args, **_kwargs: SimpleNamespace(
            difficulty="balanced",
            confidence=0.12,
            probabilities={"economy": 0.42, "balanced": 0.12, "advanced": 0.46},
        ),
    )
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "classifier_artifact": {"kind": "mdeberta_centroid_v1"},
            "difficulty_models": {
                "economy": "gpt-4o-mini",
                "balanced": "gpt-4.1-mini",
                "advanced": "gpt-5.4",
            },
            "generalization_validation": {
                "rules": {
                    "status": "partial",
                    "passed": True,
                    "validated_rule_ids": ["planner-economy-lookup"],
                },
                "classifier": {"passed": True},
            },
            "difficulty_rules": [
                {
                    "id": "planner-economy-lookup",
                    "difficulty": "economy",
                    "keyword_any": ["어디", "어느", "시작"],
                    "minimum_matches": 1,
                    "reason": "단일 위치나 시작점 확인",
                },
                {
                    "id": "planner-balanced-broad",
                    "difficulty": "balanced",
                    "keyword_any": ["신청"],
                    "minimum_matches": 1,
                    "reason": "검증에서 오탐된 넓은 규칙",
                },
            ],
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="JSON으로 분류합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "휴가 신청은 어느 화면에서 시작하나요?"},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-5.4"],
    )

    assert decision.selected_model_id == "gpt-4o-mini"
    assert decision.matched_rule_id == "planner-economy-lookup"
    assert decision.decision_factors["classification_status"] == "validated_planner_rule"


def test_bootstrap_policy_uses_a_classifier_only_for_its_validated_difficulty(
    monkeypatch,
):
    """전체 holdout이 미달이어도 economy prediction 검증이 끝났으면 선택한다."""
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router.MDebertaDifficultyClassifier.predict",
        lambda *_args, **_kwargs: SimpleNamespace(
            difficulty="economy",
            confidence=0.74,
            probabilities={"economy": 0.74, "balanced": 0.19, "advanced": 0.07},
        ),
    )
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "classifier_artifact": {"kind": "mdeberta_centroid_v1"},
            "difficulty_models": {
                "economy": "gpt-4o-mini",
                "balanced": "gpt-4.1-mini",
                "advanced": "gpt-5.4",
            },
            "generalization_validation": {
                "rules": {"passed": False, "validated_rule_ids": []},
                "classifier": {
                    "passed": False,
                    "validated_difficulties": ["economy"],
                    "per_difficulty": {
                        "economy": {"minimum_confidence": 0.7},
                    },
                },
            },
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="JSON으로 분류합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "휴가 신청 메뉴는 어디에 있나요?"},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-5.4"],
    )

    assert decision.selected_model_id == "gpt-4o-mini"
    assert decision.reason_code == "bootstrap_difficulty_economy"
    assert decision.decision_factors["classification_validation_scope"] == "difficulty"


def test_bootstrap_policy_prefers_confident_classifier_over_broad_planner_rule(
    monkeypatch,
):
    """구체적인 예문 분류 결과가 일반 Planner phrase보다 우선해야 한다."""
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_router.MDebertaDifficultyClassifier.predict",
        lambda *_args, **_kwargs: SimpleNamespace(
            difficulty="economy",
            confidence=0.88,
            probabilities={"economy": 0.88, "balanced": 0.08, "advanced": 0.04},
        ),
    )
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "classifier_artifact": {"kind": "mdeberta_prototype_v2"},
            "difficulty_models": {
                "economy": "gpt-4o-mini",
                "balanced": "gpt-4.1-mini",
                "advanced": "gpt-5.4",
            },
            "difficulty_rules": [
                {
                    "id": "planner-broad-advanced",
                    "difficulty": "advanced",
                    "keyword_any": ["정책"],
                    "minimum_matches": 1,
                    "reason": "너무 넓은 Planner 신호",
                }
            ],
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="문서 근거를 바탕으로 답합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "휴가 정책 메뉴 위치를 알려 주세요."},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-5.4"],
    )

    assert decision.selected_model_id == "gpt-4o-mini"
    assert decision.reason_code == "bootstrap_difficulty_economy"
    assert decision.decision_factors["classification_status"] == "matched"


def test_bootstrap_classifier_feature_includes_rendered_prompt_but_not_rag_contents():
    """요청별 난이도에는 렌더링 prompt를 쓰되 RAG 원문은 넣지 않는다."""
    node_data = SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        knowledgeBases=[{"id": "kb-1"}],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="문서 근거를 바탕으로 답합니다.",
        user_prompt="질문: {{message}}",
        assistant_prompt="",
        referenced_variables=[
            SimpleNamespace(
                name="message",
                value_selector=["webhook", "message"],
            )
        ],
        task_type="generate",
    )
    baseline = ModelRouter.bootstrap_classifier_feature_text(
        {"webhook": {"message": "휴가 신청 메뉴 위치를 알려 주세요."}},
        node_data,
    )
    runtime = ModelRouter.bootstrap_classifier_feature_text(
        {"webhook": {"message": "휴가 신청 메뉴 위치를 알려 주세요."}},
        node_data,
        rendered_prompt_parts=("새로 렌더된 긴 프롬프트",),
        rag_metadata={
            "knowledge_enabled": True,
            "retrieved_context_chars": 12000,
            "source_count": 4,
            "raw_document": "절대 분류 feature에 들어가면 안 되는 RAG 원문",
        },
    )

    assert "질문: 휴가 신청 메뉴 위치를 알려 주세요." in baseline
    assert baseline != runtime
    assert "새로 렌더된 긴 프롬프트" in runtime
    assert "RAG_RUNTIME_METADATA" in runtime
    assert "절대 분류 feature에 들어가면 안 되는 RAG 원문" not in runtime


def test_bootstrap_policy_uses_planner_rule_when_classifier_artifact_is_missing():
    """규칙 기반 첫 실행은 mDeBERTa artifact 상태에 의존하지 않는다."""
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "classifier_artifact": None,
            "difficulty_models": {
                "economy": "gpt-4o-mini",
                "balanced": "gpt-4.1-mini",
                "advanced": "gpt-5.4",
            },
            "difficulty_rules": [
                {
                    "id": "planner-economy-lookup",
                    "difficulty": "economy",
                    "keyword_any": ["메뉴 위치"],
                    "minimum_matches": 1,
                    "reason": "단일 위치 확인은 경제형 모델로 처리합니다.",
                }
            ],
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="문서 근거를 바탕으로 답합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "휴가 신청 메뉴 위치를 알려 주세요."},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"],
    )

    assert decision.selected_model_id == "gpt-4o-mini"
    assert decision.reason_code == "bootstrap_planner_rule_economy"
    assert decision.decision_factors["classification_status"] == "planner_rule"


def test_bootstrap_policy_does_not_match_a_multi_word_rule_on_one_polite_suffix():
    """`비교해 주세요`의 `주세요`만으로 모든 문의가 balanced가 되면 안 된다."""
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "classifier_artifact": None,
            "difficulty_models": {
                "economy": "gpt-4o-mini",
                "balanced": "gpt-4.1-mini",
                "advanced": "gpt-5.4",
            },
            "difficulty_rules": [
                {
                    "id": "planner-balanced-comparison",
                    "difficulty": "balanced",
                    "keyword_any": ["비교해 주세요"],
                    "minimum_matches": 1,
                }
            ],
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="문서 근거를 바탕으로 답합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "휴가 신청 메뉴를 알려 주세요."},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-5.4"],
    )

    assert decision.selected_model_id == "gpt-4.1"
    assert decision.reason_code == "bootstrap_classifier_missing"


def test_bootstrap_policy_does_not_match_a_multi_word_rule_on_one_meaningful_word():
    """`권한 신청 방법`의 `신청` 하나로 balanced를 고르면 안 된다."""
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "classifier_artifact": None,
            "difficulty_models": {
                "economy": "gpt-4o-mini",
                "balanced": "gpt-4.1-mini",
                "advanced": "gpt-5.4",
            },
            "difficulty_rules": [
                {
                    "id": "planner-balanced-access-request",
                    "difficulty": "balanced",
                    "keyword_any": ["권한 신청 방법"],
                    "minimum_matches": 1,
                }
            ],
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="문서 근거를 바탕으로 답합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "휴가 신청 메뉴 위치를 알려 주세요."},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-5.4"],
    )

    assert decision.selected_model_id == "gpt-4.1"
    assert decision.reason_code == "bootstrap_classifier_missing"


def test_bootstrap_policy_matches_planner_phrase_parts_for_varied_korean_wording():
    """Planner가 만든 짧은 구문은 실제 문의에서 나뉘어도 난이도 신호가 된다.

    Planner는 정책 생성 때 ``개인정보 처리와 관련된 예외``처럼 자연스러운
    구문을 만들 수 있다. 실제 문의가 ``개인정보 원칙이 충돌``처럼 표현을
    바꾸더라도, 도메인 키워드를 코드에 따로 넣지 않고 정책 구문의 핵심 단어
    조합만으로 advanced 모델을 선택해야 한다.
    """
    policy = {
        "active_policy": {
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "default_model_id": "gpt-4.1",
            "fallback_model_id": "gpt-4.1-mini",
            "classifier_artifact": None,
            "difficulty_models": {
                "economy": "gpt-4o-mini",
                "balanced": "gpt-4.1-mini",
                "advanced": "gpt-5.4",
            },
            "difficulty_rules": [
                {
                    "id": "planner-advanced-policy-conflict",
                    "difficulty": "advanced",
                    "keyword_any": [
                        "개인정보 처리와 관련된 예외",
                        "정책이 충돌",
                    ],
                    "minimum_matches": 2,
                    "reason": "정책 충돌은 복합 판단이 필요합니다.",
                }
            ],
        }
    }
    node_data = SimpleNamespace(
        model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        knowledgeBases=[],
        knowledgeCollections=[],
        output_format={"type": "json"},
        system_prompt="문서 근거를 바탕으로 답합니다.",
        user_prompt="{{message}}",
        assistant_prompt="",
        task_type="generate",
    )

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "개인정보 원칙이 충돌할 때 안전한 승인 절차를 판단해 주세요."},
        node_data=node_data,
        available_model_ids=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-5.4"],
    )

    assert decision.selected_model_id == "gpt-5.4"
    assert decision.reason_code == "bootstrap_planner_rule_advanced"
    assert decision.decision_factors["classification_status"] == "planner_rule"
