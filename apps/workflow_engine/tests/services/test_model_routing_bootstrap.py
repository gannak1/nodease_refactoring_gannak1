from types import SimpleNamespace
from uuid import uuid4

from apps.workflow_engine.services.model_routing_bootstrap import (
    BootstrapHistoryRun,
    BootstrapSample,
    ModelRoutingBootstrapPlanner,
    PersistedModelRoutingBootstrapStore,
    task_fingerprint,
)
from apps.workflow_engine.services.model_router import ModelRouter


def _node(**overrides):
    values = {
        "system_prompt": "고객 문의를 JSON으로 분류합니다.",
        "user_prompt": "{{message}}",
        "assistant_prompt": "",
        "referenced_variables": [
            {"name": "message", "value_selector": ["webhook", "message"]}
        ],
        "output_format": {
            "type": "json",
            "schema": {"type": "object", "required": ["severity"]},
        },
        "knowledgeBases": [],
        "knowledgeCollections": [],
        "topK": 3,
        "scoreThreshold": 0.5,
        "retrievedContextMaxChars": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _run(index: int) -> BootstrapHistoryRun:
    return BootstrapHistoryRun(
        node_run_id=f"run-{index}",
        safe_input_summary={"message": f"마스킹된 운영 문의 {index}"},
        feature_text=f"운영 문의 {index}",
        input_length=30 + index,
        knowledge_enabled=False,
        output_format="json",
        executed_at=f"2026-07-{index:02d}T00:00:00+00:00",
    )


class _Planner:
    def label_history(self, *, history_runs, **_kwargs):
        tiers = ("economy", "balanced", "advanced")
        return {
            run.node_run_id: (tiers[index % len(tiers)], "테스트용 운영 로그 라벨")
            for index, run in enumerate(history_runs)
        }

    def create_samples(self, *, coverage_targets, count_per_target, **_kwargs):
        return [
            {
                "complexity_score": target,
                "payload": {"message": f"complexity {target} synthetic {index}"},
                "feature_text": f"complexity {target} synthetic {index}",
                "reason": "테스트용 합성 입력",
            }
            for target in coverage_targets
            for index in range(count_per_target)
        ]

    def create_difficulty_rules(self, **_kwargs):
        return [
            {
                "id": "planner-economy",
                "difficulty": "economy",
                "keyword_any": ["위치", "메뉴"],
                "minimum_matches": 1,
                "reason": "단일 사실 확인",
            }
        ]


class _TaskComplexityPlanner(_Planner):
    def create_task_complexity_profile(self, *, task_summary):
        assert task_summary["output_format"]["type"] == "json"
        return {
            "score": 78,
            # Planner가 잘못된 tier를 반환해도 score 기반으로 정규화돼야 한다.
            "tier": "economy",
            "reasoning_depth": 4,
            "instruction_complexity": 4,
            "schema_precision": 5,
            "context_synthesis": 2,
            "grounding_requirement": 3,
            "output_generation_demand": 2,
            "ambiguity": 3,
            "reason": "복수 조건과 엄격한 JSON 계약을 함께 만족해야 합니다.",
        }


def test_bootstrap_uses_planner_task_complexity_profile_not_example_similarity():
    result = ModelRoutingBootstrapPlanner.plan(
        node_data=_node(),
        task_description="고객 문의를 JSON으로 분류합니다.",
        history_runs=[],
        initial_budget_usd=1.0,
        planner=_TaskComplexityPlanner(),
    )

    assert result.task_complexity_profile["kind"] == "planner_task_complexity_v1"
    assert result.task_complexity_profile["score"] == 78
    assert result.task_complexity_profile["tier"] == "advanced"
    assert result.task_complexity_profile["reasoning_depth"] == 4


def test_bootstrap_feature_keeps_dict_node_contract_and_renders_request():
    """초안 API가 넘기는 dict node_data도 runtime과 같은 난이도 feature를 만든다."""
    feature = ModelRouter.bootstrap_classifier_feature_text(
        {"webhook": {"message": "예외 세 건을 비교해 JSON으로 승인 여부를 판정해 주세요."}},
        _node().__dict__,
    )

    assert "RENDERED_PROMPT:" in feature
    assert "예외 세 건을 비교해 JSON으로 승인 여부를 판정해 주세요." in feature
    assert feature.index("CURRENT_REQUEST:") < feature.index("TASK_CONTRACT:")
    assert '"output_format": "json"' in feature
    assert '"schema_required": true' in feature
    assert '"knowledge_enabled": false' in feature


def test_bootstrap_feature_uses_current_values_in_every_prompt_part():
    """난이도는 user prompt뿐 아니라 @변수가 쓰인 모든 prompt를 기준으로 계산한다."""
    feature = ModelRouter.bootstrap_classifier_feature_text(
        {"webhook": {"message": "조건 세 개가 충돌할 때 예외 승인 여부를 판단해 주세요."}},
        _node(
            system_prompt="운영 정책: {{message}}",
            user_prompt="고객 요청: {{message}}",
            assistant_prompt="응답 전에 검토할 내용: {{message}}",
        ).__dict__,
    )

    # 현재 요청, 세 prompt, 공통 요청 입력에 같은 값이 남는다. 횟수보다 모든
    # prompt 영역에 실제 값이 전달되는 계약이 중요하다.
    assert feature.count("조건 세 개가 충돌할 때 예외 승인 여부를 판단해 주세요.") >= 4
    assert "[UNTRUSTED_INPUT:message]" not in feature


def test_bootstrap_plan_maps_generated_payload_to_llm_input_shape():
    """합성 외부 payload도 LLM 노드가 실제 변수 selector로 읽는 구조로 바꾼다."""
    plan = ModelRoutingBootstrapPlanner.plan(
        node_data=_node().__dict__,
        task_description="요청 난이도에 따라 JSON 답변을 생성합니다.",
        history_runs=[],
        initial_budget_usd=0.5,
        planner=_Planner(),
    )

    low_complexity_feature = next(
        sample.feature_text
        for sample in plan.samples
        if sample.complexity_score == 15
    )

    assert "CURRENT_REQUEST:\nwebhook: message: complexity 15.0 synthetic 0" in low_complexity_feature
    assert "RENDERED_PROMPT:\ncomplexity 15.0 synthetic 0\n고객 문의를 JSON으로 분류합니다." in low_complexity_feature


def test_bootstrap_plan_maps_history_payload_to_llm_input_shape():
    """과거 node run의 안전 요약도 같은 selector 구조로 학습한다."""
    plan = ModelRoutingBootstrapPlanner.plan(
        node_data=_node().__dict__,
        task_description="요청 난이도에 따라 JSON 답변을 생성합니다.",
        history_runs=[_run(1)],
        initial_budget_usd=0.5,
        planner=_Planner(),
    )

    history_feature = next(
        sample.feature_text
        for sample in plan.samples
        if sample.source == "history"
    )

    assert "CURRENT_REQUEST:\nwebhook: message: 마스킹된 운영 문의 1" in history_feature
    assert "RENDERED_PROMPT:\n마스킹된 운영 문의 1\n고객 문의를 JSON으로 분류합니다." in history_feature


class _RuleRepairPlanner(_Planner):
    def __init__(self):
        self.repair_calls = 0

    def create_samples(self, **_kwargs):
        return [
            {
                "difficulty": "economy",
                "payload": {"message": "휴가 신청 메뉴는 어디에 있나요?"},
                "feature_text": "단일 메뉴 위치 확인",
                "reason": "단일 사실 조회",
            },
            {
                "difficulty": "balanced",
                "payload": {"message": "계정 생성과 권한 신청 순서를 알려 주세요."},
                "feature_text": "여러 단계를 순서대로 설명",
                "reason": "다단계 절차",
            },
            {
                "difficulty": "advanced",
                "payload": {"message": "보안 예외 승인과 개인정보 위험을 함께 판단해 주세요."},
                "feature_text": "위험과 예외를 함께 판단",
                "reason": "다중 제약 판단",
            },
        ]

    def create_difficulty_rules(self, **_kwargs):
        # 역할명만 보는 잘못된 초안 규칙이다. 세 예문 모두 분류하지 못해야 한다.
        return [
            {
                "id": "bad-economy",
                "difficulty": "economy",
                "keyword_any": ["담당자"],
                "minimum_matches": 1,
            }
        ]

    def repair_difficulty_rules(self, **_kwargs):
        self.repair_calls += 1
        return [
            {
                "id": "economy-lookup",
                "difficulty": "economy",
                "keyword_any": ["메뉴", "어디"],
                "minimum_matches": 1,
            },
            {
                "id": "balanced-procedure",
                "difficulty": "balanced",
                "keyword_any": ["순서", "단계"],
                "minimum_matches": 1,
            },
            {
                "id": "advanced-risk",
                "difficulty": "advanced",
                "keyword_any": ["보안 예외", "개인정보 위험"],
                "minimum_matches": 1,
            },
        ]


def test_bootstrap_without_history_creates_labeled_samples_for_request_classifier():
    result = ModelRoutingBootstrapPlanner.plan(
        node_data=_node(),
        task_description="고객 문의를 위험도별로 JSON 분류합니다.",
        history_runs=[],
        initial_budget_usd=1.0,
        planner=_Planner(),
    )

    assert result.source == "synthetic"
    assert result.history_sample_count == 0
    assert {sample.difficulty for sample in result.samples} == {
        "economy",
        "balanced",
        "advanced",
    }
    assert all(sample.source == "synthetic" for sample in result.samples)
    assert {sample.source for sample in result.samples} == {"synthetic"}
    assert len(result.samples) == 12
    assert {sample.complexity_score for sample in result.samples} == {
        15.0,
        30.0,
        45.0,
        60.0,
        75.0,
        90.0,
    }
    assert result.validation_samples == []
    assert result.difficulty_rules == []
    assert result.rule_generalization["status"] == "not_used"


def test_bootstrap_does_not_create_holdout_examples_for_runtime_topic_classification():
    """예문은 runtime 난이도 분류기를 학습하거나 검증하는 데 쓰지 않는다."""

    class _SplitPlanner(_Planner):
        def create_samples(
            self,
            *,
            coverage_targets,
            count_per_target,
            sample_role="training",
            **_kwargs,
        ):
            return [
                {
                    "complexity_score": target,
                    "payload": {
                        "message": (
                            f"complexity {target} {'학습' if sample_role == 'training' else '검증'} "
                            f"표현 {index}"
                        )
                    },
                    "reason": f"{sample_role} 표본",
                }
                for target in coverage_targets
                for index in range(count_per_target)
            ]

    result = ModelRoutingBootstrapPlanner.plan(
        node_data=_node(),
        task_description="고객 문의를 난이도별로 JSON 분류합니다.",
        history_runs=[],
        initial_budget_usd=1.0,
        planner=_SplitPlanner(),
    )

    assert result.samples
    assert {sample.sample_role for sample in result.samples} == {"training"}
    assert result.validation_samples == []
    assert result.difficulty_rules == []


def test_bootstrap_does_not_turn_examples_into_keyword_routing_rules():
    """입력 주제 키워드는 새 bootstrap policy의 runtime 조건이 될 수 없다."""

    class _HeldOutRepairPlanner(_Planner):
        def create_samples(self, *, sample_role="training", **_kwargs):
            if sample_role == "training":
                return [
                    {
                        "difficulty": "economy",
                        "payload": {"message": "메뉴 위치만 알려 주세요."},
                        "reason": "학습 경제형",
                    },
                    {
                        "difficulty": "balanced",
                        "payload": {"message": "절차 순서를 정리해 주세요."},
                        "reason": "학습 균형형",
                    },
                    {
                        "difficulty": "advanced",
                        "payload": {"message": "규정 충돌을 판단해 주세요."},
                        "reason": "학습 고성능형",
                    },
                ]
            return [
                {
                    "difficulty": "economy",
                    "payload": {"message": "어느 화면에서 확인하나요?"},
                    "reason": "검증 경제형",
                },
                {
                    "difficulty": "balanced",
                    "payload": {"message": "두 작업을 어떤 차례로 진행하나요?"},
                    "reason": "검증 균형형",
                },
                {
                    "difficulty": "advanced",
                    "payload": {"message": "서로 상충하는 조건의 대안을 정해 주세요."},
                    "reason": "검증 고성능형",
                },
            ]

        def create_difficulty_rules(self, **_kwargs):
            return [
                {
                    "id": "literal-training-only",
                    "difficulty": "economy",
                    "keyword_any": ["메뉴 위치"],
                    "minimum_matches": 1,
                }
            ]

        def repair_difficulty_rules(self, **_kwargs):
            return [
                {
                    "id": "economy-lookup-shape",
                    "difficulty": "economy",
                    "keyword_any": ["어느", "확인"],
                    "minimum_matches": 1,
                },
                {
                    "id": "balanced-process-shape",
                    "difficulty": "balanced",
                    "keyword_any": ["차례", "두 작업"],
                    "minimum_matches": 1,
                },
                {
                    "id": "advanced-conflict-shape",
                    "difficulty": "advanced",
                    "keyword_any": ["상충", "대안"],
                    "minimum_matches": 1,
                },
            ]

    result = ModelRoutingBootstrapPlanner.plan(
        node_data=_node(),
        task_description="고객 문의를 난이도별로 JSON 분류합니다.",
        history_runs=[],
        initial_budget_usd=1.0,
        planner=_HeldOutRepairPlanner(),
    )

    assert result.difficulty_rules == []
    assert result.rule_generalization == {"status": "not_used", "passed": False}


def test_bootstrap_never_requests_keyword_rule_repair_for_synthetic_examples():
    planner = _RuleRepairPlanner()

    result = ModelRoutingBootstrapPlanner.plan(
        node_data=_node(),
        task_description="고객 문의를 난이도별로 분류합니다.",
        history_runs=[],
        initial_budget_usd=1.0,
        planner=planner,
    )

    assert planner.repair_calls == 0
    assert result.difficulty_rules == []


def test_rule_generalization_keeps_individually_safe_rules_when_another_rule_is_broad():
    """한 rule의 오탐이 다른 난이도의 검증 완료 rule까지 막으면 안 된다."""
    validation_samples = [
        BootstrapSample(
            source="synthetic",
            difficulty="economy",
            safe_input_summary={"message": "휴가 신청 메뉴는 어디에 있나요?"},
            feature_text="휴가 신청 메뉴 위치를 묻는 단일 조회",
            source_node_run_id=None,
            reason=None,
            input_length=20,
            knowledge_enabled=False,
            output_format="json",
            sample_role="validation",
        ),
        BootstrapSample(
            source="synthetic",
            difficulty="economy",
            safe_input_summary={"message": "계정 요청은 어느 화면에서 시작하나요?"},
            feature_text="계정 요청 시작 화면을 묻는 단일 조회",
            source_node_run_id=None,
            reason=None,
            input_length=23,
            knowledge_enabled=False,
            output_format="json",
            sample_role="validation",
        ),
        BootstrapSample(
            source="synthetic",
            difficulty="balanced",
            safe_input_summary={"message": "두 작업 신청의 처리 순서를 정리해 주세요."},
            feature_text="두 작업의 순서를 설명하는 절차 요청",
            source_node_run_id=None,
            reason=None,
            input_length=22,
            knowledge_enabled=False,
            output_format="json",
            sample_role="validation",
        ),
        BootstrapSample(
            source="synthetic",
            difficulty="advanced",
            safe_input_summary={"message": "서로 충돌하는 규정의 예외를 판단해 주세요."},
            feature_text="충돌과 예외를 함께 판단하는 고난도 요청",
            source_node_run_id=None,
            reason=None,
            input_length=26,
            knowledge_enabled=False,
            output_format="json",
            sample_role="validation",
        ),
        BootstrapSample(
            source="synthetic",
            difficulty="advanced",
            safe_input_summary={"message": "긴급 보안 사고의 위험과 우선순위를 결정해 주세요."},
            feature_text="긴급 위험과 우선순위를 함께 판단하는 고난도 요청",
            source_node_run_id=None,
            reason=None,
            input_length=29,
            knowledge_enabled=False,
            output_format="json",
            sample_role="validation",
        ),
    ]
    rules = [
        {
            "id": "economy-lookup",
            "difficulty": "economy",
            "keyword_any": ["어디", "어느", "시작"],
            "keyword_all": [],
            "minimum_matches": 1,
            "priority": 100,
        },
        {
            "id": "balanced-broad",
            "difficulty": "balanced",
            "keyword_any": ["신청"],
            "keyword_all": [],
            "minimum_matches": 1,
            "priority": 200,
        },
        {
            "id": "advanced-risk",
            "difficulty": "advanced",
            "keyword_any": ["충돌", "예외", "긴급", "위험"],
            "keyword_all": [],
            "minimum_matches": 1,
            "priority": 300,
        },
    ]

    result = ModelRoutingBootstrapPlanner._rule_generalization(
        rules,
        node_data=_node(),
        validation_samples=validation_samples,
    )

    assert result["status"] == "partial"
    assert result["validated_rule_ids"] == ["economy-lookup", "advanced-risk"]
    assert result["per_rule"]["balanced-broad"]["passed"] is False
    assert result["per_rule"]["balanced-broad"]["false_positive_count"] == 1


def test_rule_sanitization_removes_only_holdout_false_positive_cues():
    """검증에서 다른 난이도에 걸린 cue만 빼고 나머지 rule 범위는 보존한다."""
    samples = [
        BootstrapSample(
            source="synthetic",
            difficulty="economy",
            safe_input_summary={"message": "휴가 메뉴는 어디에 있나요?"},
            feature_text="메뉴 위치 단일 조회",
            source_node_run_id=None,
            reason=None,
            input_length=16,
            knowledge_enabled=False,
            output_format="json",
            sample_role="validation",
        ),
        BootstrapSample(
            source="synthetic",
            difficulty="advanced",
            safe_input_summary={"message": "규정 충돌을 확인하고 예외를 판단해 주세요."},
            feature_text="충돌과 예외를 판단하는 고난도 요청",
            source_node_run_id=None,
            reason=None,
            input_length=24,
            knowledge_enabled=False,
            output_format="json",
            sample_role="validation",
        ),
    ]
    rules = [
        {
            "id": "economy-lookup",
            "difficulty": "economy",
            "keyword_any": ["어디", "확인"],
            "keyword_all": [],
            "minimum_matches": 1,
            "priority": 100,
        }
    ]

    sanitized = ModelRoutingBootstrapPlanner._sanitize_difficulty_rules_with_holdout(
        rules,
        node_data=_node(),
        validation_samples=samples,
    )

    assert sanitized[0]["keyword_any"] == ["어디"]


def test_classifier_generalization_allows_only_reliable_predicted_difficulties(
    monkeypatch,
):
    """전체 accuracy가 부족해도 신뢰도 높은 난이도 prediction은 버리지 않는다."""
    samples = [
        BootstrapSample(
            source="synthetic",
            difficulty=tier,
            safe_input_summary={"message": text},
            feature_text=text,
            source_node_run_id=None,
            reason=None,
            input_length=len(text),
            knowledge_enabled=False,
            output_format="json",
            sample_role="validation",
        )
        for tier, text in (
            ("economy", "economy-one"),
            ("economy", "economy-two"),
            ("balanced", "balanced-one"),
            ("balanced", "balanced-two"),
            ("advanced", "advanced-one"),
            ("advanced", "advanced-two"),
        )
    ]
    predictions = {
        "economy-one": ("economy", 0.71),
        "economy-two": ("economy", 0.72),
        "balanced-one": ("economy", 0.63),
        "balanced-two": ("economy", 0.62),
        "advanced-one": ("advanced", 0.81),
        "advanced-two": ("advanced", 0.82),
    }
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_routing_bootstrap.MDebertaDifficultyClassifier.predict",
        lambda _artifact, text, **_kwargs: SimpleNamespace(
            difficulty=predictions[text][0],
            confidence=predictions[text][1],
            probabilities={},
        ),
    )

    result = PersistedModelRoutingBootstrapStore._classifier_generalization_for_samples(
        {"kind": "multilingual_e5_prototype_v1"},
        validation_samples=samples,
    )

    assert result["passed"] is False
    assert result["validated_difficulties"] == ["advanced"]
    assert result["per_difficulty"]["economy"]["passed"] is False
    assert result["per_difficulty"]["advanced"]["passed"] is True


def test_bootstrap_with_partial_history_fills_missing_difficulty_training_ranges():
    result = ModelRoutingBootstrapPlanner.plan(
        node_data=_node(),
        task_description="고객 문의를 위험도별로 JSON 분류합니다.",
        history_runs=[_run(index) for index in range(1, 5)],
        initial_budget_usd=1.0,
        planner=_Planner(),
    )

    assert result.source == "hybrid"
    assert result.history_sample_count == 4
    assert any(sample.source == "history" for sample in result.samples)
    assert any(sample.source == "synthetic" for sample in result.samples)
    assert {sample.difficulty for sample in result.samples} == {
        "economy",
        "balanced",
        "advanced",
    }


def test_bootstrap_can_defer_classifier_artifact_without_loading_mdeberta(monkeypatch):
    """초기 정책 API는 무거운 분류기 다운로드를 기다리지 않고 규칙을 먼저 저장한다."""
    plan = ModelRoutingBootstrapPlanner.plan(
        node_data=_node(),
        task_description="고객 문의를 위험도별로 JSON 분류합니다.",
        history_runs=[],
        initial_budget_usd=1.0,
        planner=_Planner(),
    )
    monkeypatch.setattr(
        "apps.workflow_engine.services.model_routing_bootstrap.MDebertaDifficultyClassifier.fit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("deferred bootstrap must not load the classifier")
        ),
    )

    artifact, status = PersistedModelRoutingBootstrapStore._classifier_artifact_for_plan(
        plan,
        defer_classifier=True,
    )

    assert artifact == {}
    assert status == "pending"


def test_pending_bootstrap_returns_generating_before_any_planner_call(monkeypatch):
    """HTTP API는 LLM 호출을 기다리지 않고 Worker용 artifact만 먼저 저장한다."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    monkeypatch.setattr(
        PersistedModelRoutingBootstrapStore,
        "_find_exact_bootstrap",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        PersistedModelRoutingBootstrapStore,
        "_collect_history_runs",
        lambda *_args, **_kwargs: ([], {"test_run": 0}),
    )

    bootstrap, should_enqueue = PersistedModelRoutingBootstrapStore.create_pending(
        session,
        workflow_id=uuid4(),
        organization_id=uuid4(),
        node_id="llm-1",
        node_data=_node().__dict__,
        task_description="문의 난이도에 따라 모델을 선택합니다.",
        default_model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        initial_budget_usd=1.0,
        created_by=uuid4(),
        planner_model_id="gpt-4.1",
        available_candidates=[SimpleNamespace(model_id="gpt-4.1"), SimpleNamespace(model_id="gpt-4.1-mini")],
    )

    assert bootstrap.status == "generating"
    assert bootstrap.generation_summary["generation_status"] == "queued"
    assert should_enqueue is True
    session.add.assert_called_once_with(bootstrap)


def test_pending_bootstrap_does_not_enqueue_duplicate_generation(monkeypatch):
    """같은 지문의 생성 중 버튼 재클릭은 추가 Planner 비용을 만들면 안 된다."""
    from unittest.mock import MagicMock

    existing = SimpleNamespace(status="generating")
    session = MagicMock()
    monkeypatch.setattr(
        PersistedModelRoutingBootstrapStore,
        "_find_exact_bootstrap",
        lambda *_args, **_kwargs: existing,
    )

    bootstrap, should_enqueue = PersistedModelRoutingBootstrapStore.create_pending(
        session,
        workflow_id=uuid4(),
        organization_id=uuid4(),
        node_id="llm-1",
        node_data=_node().__dict__,
        task_description="문의 난이도에 따라 모델을 선택합니다.",
        default_model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        initial_budget_usd=1.0,
        created_by=uuid4(),
        planner_model_id="gpt-4.1",
        available_candidates=[SimpleNamespace(model_id="gpt-4.1"), SimpleNamespace(model_id="gpt-4.1-mini")],
    )

    assert bootstrap is existing
    assert should_enqueue is False


def test_regression_artifact_is_copied_to_existing_deployment_policy_as_v4():
    """비동기 회귀기가 준비되면 이미 배포된 policy도 새 artifact를 사용해야 한다."""
    policy = SimpleNamespace(
        active_policy={
            "strategy_id": "bootstrap_mdeberta_difficulty_v1",
            "classifier_artifact": {},
        }
    )
    artifact = {
        "kind": "mdeberta_centroid_v1",
        "tier_centroids": {"economy": [0.1, 0.2]},
    }

    PersistedModelRoutingBootstrapStore._apply_classifier_artifact_to_policy(
        policy,
        artifact=artifact,
    )

    assert policy.active_policy["classifier_artifact"] == artifact
    assert (
        policy.active_policy["strategy_id"]
        == "bootstrap_request_complexity_regression_v4"
    )
    assert policy.active_policy["rules"] == []


def test_deferred_task_syncs_ready_regressor_to_deployment_policy():
    """대기 작업도 준비된 회귀 artifact를 배포 정책에 반영한다."""
    bootstrap_id = uuid4()
    profile = {
        "kind": "planner_task_complexity_v1",
        "score": 74,
        "tier": "advanced",
    }
    bootstrap = SimpleNamespace(
        id=bootstrap_id,
        generation_summary={"task_complexity_profile": profile},
        classifier_artifact={"kind": "mdeberta_linear_difficulty_v1"},
    )
    policy = SimpleNamespace(active_policy={"classifier_artifact": {}})

    class _Query:
        def filter(self, *_args, **_kwargs):
            return self

        def all(self):
            return [policy]

    class _Session:
        def get(self, _model, _id):
            return bootstrap

        def query(self, _model):
            return _Query()

    result = PersistedModelRoutingBootstrapStore.build_deferred_classifier(
        _Session(),
        bootstrap_id=bootstrap_id,
    )

    assert result is bootstrap
    assert bootstrap.classifier_artifact == {"kind": "mdeberta_linear_difficulty_v1"}
    assert policy.active_policy["task_complexity_profile"] == profile
    assert (
        policy.active_policy["strategy_id"]
        == "bootstrap_request_complexity_regression_v4"
    )
    assert policy.active_policy["classifier_artifact"] == {"kind": "mdeberta_linear_difficulty_v1"}


def test_active_policy_starts_judge_bootstrap_and_keeps_task_profile_as_context():
    """새 배포 정책은 Judge-first를 사용하고 과거 난이도 profile은 설명용으로만 둔다."""
    bootstrap = SimpleNamespace(
        id=uuid4(),
        task_fingerprint="fingerprint",
        default_model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
        classifier_artifact={"kind": "multilingual_e5_prototype_v1"},
        generation_summary={
            "difficulty_models": {
                "economy": "gpt-4o-mini",
                "balanced": "gpt-4.1-mini",
                "advanced": "gpt-5.4",
            },
            "task_complexity_profile": {
                "kind": "planner_task_complexity_v1",
                "score": 58,
                "tier": "balanced",
                "reasoning_depth": 3,
            },
        },
    )

    policy = PersistedModelRoutingBootstrapStore.active_policy_for_bootstrap(bootstrap)

    assert policy["strategy_id"] == "judge_bootstrap_incremental_v1"
    assert policy["judge_model_id"] == "gpt-4.1"
    assert policy["task_complexity_profile"]["tier"] == "balanced"
    assert policy["minimum_confidence"] == 0.45
    assert policy["classifier_artifact"] == {"kind": "multilingual_e5_prototype_v1"}
    assert policy["rules"] == []
    assert policy["learning"]["mode"] == "judge_first"


def test_legacy_classifier_completion_does_not_overwrite_judge_bootstrap_policy():
    """과거 deferred worker가 끝나도 새 Judge-first 정책 전략을 되돌리지 않는다."""
    policy = SimpleNamespace(
        active_policy={
            "strategy_id": "judge_bootstrap_incremental_v1",
            "learning": {"mode": "judge_first"},
        }
    )

    PersistedModelRoutingBootstrapStore._apply_classifier_artifact_to_policy(
        policy,
        artifact={"kind": "mdeberta_linear_difficulty_v1"},
    )

    assert policy.active_policy == {
        "strategy_id": "judge_bootstrap_incremental_v1",
        "learning": {"mode": "judge_first"},
    }


def test_bootstrap_rule_normalization_rejects_full_sentence_terms():
    rules = ModelRoutingBootstrapPlanner._normalize_difficulty_rules(
        [
            {
                "id": "too-literal",
                "difficulty": "advanced",
                "keyword_any": [
                    "개인정보 처리방침과 사내 데이터 접근 정책이 충돌할 때 어떤 원칙을 적용해야 하나요"
                ],
            },
            {
                "id": "reusable-signal",
                "difficulty": "advanced",
                "keyword_any": ["정책 충돌", "예외 승인"],
            },
        ]
    )

    assert rules == [
        {
            "id": "reusable-signal",
            "difficulty": "advanced",
            "keyword_any": ["정책 충돌", "예외 승인"],
            "keyword_all": [],
            "minimum_matches": 1,
            "priority": 300,
            "reason": None,
        }
    ]


def test_bootstrap_rule_normalization_removes_terms_shared_by_multiple_tiers():
    """같은 신호가 서로 다른 난이도를 뜻하면 runtime에서 임의로 선택하면 안 된다."""
    rules = ModelRoutingBootstrapPlanner._normalize_difficulty_rules(
        [
            {
                "id": "economy-lookup",
                "difficulty": "economy",
                "keyword_any": ["메뉴 위치", "정책"],
            },
            {
                "id": "advanced-conflict",
                "difficulty": "advanced",
                "keyword_any": ["정책", "규정 충돌"],
            },
        ]
    )

    assert rules == [
        {
            "id": "economy-lookup",
            "difficulty": "economy",
            "keyword_any": ["메뉴 위치"],
            "keyword_all": [],
            "minimum_matches": 1,
            "priority": 100,
            "reason": None,
        },
        {
            "id": "advanced-conflict",
            "difficulty": "advanced",
            "keyword_any": ["규정 충돌"],
            "keyword_all": [],
            "minimum_matches": 1,
            "priority": 300,
            "reason": None,
        },
    ]


def test_bootstrap_with_history_fills_missing_continuous_complexity_ranges():
    result = ModelRoutingBootstrapPlanner.plan(
        node_data=_node(),
        task_description="고객 문의를 위험도별로 JSON 분류합니다.",
        history_runs=[_run(index) for index in range(1, 13)],
        initial_budget_usd=1.0,
        planner=_Planner(),
    )

    assert result.source == "hybrid"
    assert result.history_sample_count == 12
    assert len(result.samples) + len(result.validation_samples) == 18
    assert result.synthetic_sample_count == 6
    assert {sample.source for sample in result.samples} == {"history", "synthetic"}
    assert {
        sample.complexity_score
        for sample in result.samples
        if sample.source == "synthetic"
    } == {30.0, 45.0, 75.0}


def test_task_fingerprint_tracks_node_contract_not_manual_models_or_planner_description():
    base = _node(model_routing_task_description="고객 문의의 위험도를 JSON으로 분류합니다.")
    base_fingerprint = task_fingerprint(
        base,
        downstream_contract={"required_outputs": ["severity"]},
    )

    assert base_fingerprint == task_fingerprint(
        _node(
            model_id="gpt-4.1-mini",
            fallback_model_id="gpt-4.1",
            model_routing_task_description="고객 문의의 위험도를 JSON으로 분류합니다.",
        ),
        downstream_contract={"required_outputs": ["severity"]},
    )
    assert base_fingerprint != task_fingerprint(
        _node(
            system_prompt="다른 작업입니다.",
            model_routing_task_description="고객 문의의 위험도를 JSON으로 분류합니다.",
        ),
        downstream_contract={"required_outputs": ["severity"]},
    )
    assert base_fingerprint != task_fingerprint(
        _node(
            knowledgeBases=[{"id": "kb-1"}],
            model_routing_task_description="고객 문의의 위험도를 JSON으로 분류합니다.",
        ),
        downstream_contract={"required_outputs": ["severity"]},
    )
    assert base_fingerprint != task_fingerprint(
        base,
        downstream_contract={"required_outputs": ["severity", "answer"]},
    )
    assert base_fingerprint == task_fingerprint(
        _node(model_routing_task_description="문서 근거를 찾아 고객 답변을 작성합니다."),
        downstream_contract={"required_outputs": ["severity"]},
    )
