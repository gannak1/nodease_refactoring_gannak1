from types import SimpleNamespace
from uuid import uuid4

from apps.workflow_engine.services.model_routing_bootstrap import (
    BootstrapHistoryRun,
    BootstrapSample,
    ModelRoutingBootstrapPlanner,
    PersistedModelRoutingBootstrapStore,
    task_fingerprint,
)


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

    def create_samples(self, *, missing_tiers, count_per_tier, **_kwargs):
        return [
            {
                "difficulty": tier,
                "payload": {"message": f"{tier} synthetic {index}"},
                "feature_text": f"{tier} synthetic {index}",
                "reason": "테스트용 합성 입력",
            }
            for tier in missing_tiers
            for index in range(count_per_tier)
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


def test_bootstrap_without_history_uses_diverse_synthetic_samples_for_generalization():
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
    assert {sample.source for sample in result.samples} == {"synthetic"}
    # 한 난이도당 여러 표현을 학습해야 새 문장에 대한 의미 비교가 가능하다.
    assert len(result.samples) == 30
    assert result.difficulty_rules == [
        {
            "id": "planner-economy",
            "difficulty": "economy",
            "keyword_any": ["위치", "메뉴"],
            "keyword_all": [],
            "minimum_matches": 1,
            "priority": 100,
            "reason": "단일 사실 확인",
        }
    ]


def test_bootstrap_separates_training_examples_from_unseen_generalization_examples():
    """정책은 학습에 쓰지 않은 표현으로 먼저 일반화 여부를 확인해야 한다."""

    class _SplitPlanner(_Planner):
        def create_samples(
            self,
            *,
            missing_tiers,
            count_per_tier,
            sample_role="training",
            **_kwargs,
        ):
            return [
                {
                    "difficulty": tier,
                    "payload": {
                        "message": (
                            f"{tier} {'학습' if sample_role == 'training' else '검증'} "
                            f"표현 {index}"
                        )
                    },
                    "reason": f"{sample_role} 표본",
                }
                for tier in missing_tiers
                for index in range(count_per_tier)
            ]

    result = ModelRoutingBootstrapPlanner.plan(
        node_data=_node(),
        task_description="고객 문의를 난이도별로 JSON 분류합니다.",
        history_runs=[],
        initial_budget_usd=1.0,
        planner=_SplitPlanner(),
    )

    assert result.samples
    assert result.validation_samples
    assert {sample.sample_role for sample in result.samples} == {"training"}
    assert {sample.sample_role for sample in result.validation_samples} == {"validation"}
    assert all(
        "검증 표현" in str(sample.safe_input_summary)
        for sample in result.validation_samples
    )


def test_bootstrap_repair_validates_rules_against_held_out_examples_not_training_examples():
    """학습 예문만 맞는 규칙은 새 표현에서 실패하므로 활성 정책에 쓰면 안 된다."""

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

    assert result.rule_generalization["passed"] is True
    assert result.rule_generalization["total_count"] == 3
    assert [rule["id"] for rule in result.difficulty_rules] == [
        "economy-lookup-shape",
        "balanced-process-shape",
        "advanced-conflict-shape",
    ]


def test_bootstrap_repairs_rules_that_cannot_classify_its_own_synthetic_samples():
    planner = _RuleRepairPlanner()

    result = ModelRoutingBootstrapPlanner.plan(
        node_data=_node(),
        task_description="고객 문의를 난이도별로 분류합니다.",
        history_runs=[],
        initial_budget_usd=1.0,
        planner=planner,
    )

    assert planner.repair_calls == 1
    assert [rule["id"] for rule in result.difficulty_rules] == [
        "economy-lookup",
        "balanced-procedure",
        "advanced-risk",
    ]


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


def test_bootstrap_with_partial_history_keeps_history_and_fills_missing_tiers():
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


def test_deferred_classifier_artifact_is_copied_to_existing_deployment_policy():
    """비동기 classifier가 준비되면 이미 배포된 policy도 새 artifact를 사용해야 한다."""
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
    assert policy.active_policy["strategy_id"] == "bootstrap_mdeberta_difficulty_v1"


def test_deferred_classifier_syncs_existing_policy_when_bootstrap_is_already_ready(
    monkeypatch,
):
    """재시도 task도 과거 policy의 빈 artifact를 복구할 수 있어야 한다."""
    bootstrap_id = uuid4()
    artifact = {
        "kind": "mdeberta_centroid_v1",
        "tier_centroids": {"economy": [0.1, 0.2]},
    }
    bootstrap = SimpleNamespace(
        id=bootstrap_id,
        generation_summary={"classifier_status": "ready"},
        classifier_artifact=artifact,
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
    assert policy.active_policy["classifier_artifact"] == artifact


def test_active_policy_carries_generalization_validation_and_calibrated_threshold():
    """배포 runtime은 bootstrap의 holdout 검증 결과를 그대로 읽어야 한다."""
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
            "difficulty_rules": [{"id": "balanced-order"}],
            "generalization_validation": {
                "rules": {"passed": True, "accuracy": 1.0},
                "classifier": {
                    "passed": True,
                    "minimum_confidence": 0.39,
                },
            },
        },
    )

    policy = PersistedModelRoutingBootstrapStore.active_policy_for_bootstrap(bootstrap)

    assert policy["minimum_confidence"] == 0.39
    assert policy["generalization_validation"]["rules"]["passed"] is True
    assert policy["generalization_validation"]["classifier"]["passed"] is True


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


def test_bootstrap_with_sufficient_history_does_not_generate_synthetic_samples():
    result = ModelRoutingBootstrapPlanner.plan(
        node_data=_node(),
        task_description="고객 문의를 위험도별로 JSON 분류합니다.",
        history_runs=[_run(index) for index in range(1, 13)],
        initial_budget_usd=1.0,
        planner=_Planner(),
    )

    assert result.source == "history"
    assert result.history_sample_count == 12
    assert len(result.samples) + len(result.validation_samples) == 12
    assert {sample.source for sample in result.samples} == {"history"}


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
