from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from apps.shared.db.models.model_routing_cohort import (
    LLMNodeModelRoutingCohort,
    LLMNodeModelRoutingCohortExample,
    LLMNodeModelRoutingObservation,
)
from apps.workflow_engine.services.model_routing_adaptive_cohorts import (
    AdaptiveCohortService,
    CohortObservation,
    CohortState,
)
from apps.workflow_engine.services.model_routing_adaptive_store import (
    AdaptiveModelRoutingCohortStore,
)


def _observation(index: int, window: int, vector: tuple[float, ...]) -> CohortObservation:
    return CohortObservation(
        input_hash=f"input-{index}",
        embedding=vector,
        review_window=window,
        observed_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )


def test_discovery_requires_distinct_inputs_in_two_review_windows():
    """FR-011-A45: 한 번의 우연한 유입만으로 입력군을 만들지 않는다."""
    observations = [
        *[_observation(index, 1, (1.0, 0.0)) for index in range(1, 4)],
        *[_observation(index, 2, (0.99, 0.01)) for index in range(4, 6)],
    ]

    candidates = AdaptiveCohortService.discover(
        observations,
        minimum_distinct_inputs=5,
        minimum_review_windows=2,
        similarity_threshold=0.90,
    )

    assert len(candidates) == 1
    assert candidates[0].distinct_input_count == 5
    assert candidates[0].review_windows == (1, 2)


def test_discovery_rejects_five_inputs_that_only_appeared_once():
    """FR-011-A45: 한 점검 구간의 일시적 급증은 proposed로 올리지 않는다."""
    observations = [
        _observation(index, 1, (1.0, 0.0)) for index in range(1, 6)
    ]

    candidates = AdaptiveCohortService.discover(
        observations,
        minimum_distinct_inputs=5,
        minimum_review_windows=2,
        similarity_threshold=0.90,
    )

    assert candidates == []


def test_discovery_keeps_two_recurring_input_groups_separate_at_runtime_threshold():
    """FR-011-A45: 현재 runtime 임계값에서 두 반복 의도가 하나로 합쳐지지 않는다."""
    invoice_vectors = ((1.0, 0.0), (0.98, 0.2), (0.96, 0.28))
    slack_vectors = ((0.0, 1.0), (0.2, 0.98), (0.28, 0.96))
    observations = [
        *[
            _observation(index + 1, index % 2, vector)
            for index, vector in enumerate([*invoice_vectors, *invoice_vectors])
        ],
        *[
            _observation(index + 101, index % 2, vector)
            for index, vector in enumerate([*slack_vectors, *slack_vectors])
        ],
    ]

    candidates = AdaptiveCohortService.discover(
        observations,
        minimum_distinct_inputs=5,
        minimum_review_windows=2,
        similarity_threshold=0.50,
    )

    assert len(candidates) == 2
    assert sorted(candidate.distinct_input_count for candidate in candidates) == [6, 6]
    assert all(candidate.review_windows == (0, 1) for candidate in candidates)


def test_runtime_catalog_preserves_safety_routes_from_the_current_policy():
    """FR-011-A48: active cohort catalog은 현재 policy의 안전 route를 함께 보존한다."""

    active_cohort = SimpleNamespace(
        id=uuid4(),
        cohort_key="billing",
        label="청구 문의",
        status="active",
        safety_protected=False,
        centroid_embedding=[1.0, 0.0],
        encoder_model_id="text-embedding-3-large",
    )
    policy = SimpleNamespace(
        active_policy={
            "semantic_router": {
                "routes": [
                    {
                        "cohort_id": "high-risk",
                        "label": "고위험",
                        "threshold": 0.7,
                        "safety_override": True,
                        "centroid_embedding": [0.0, 1.0],
                        "representatives": [{"embedding": [0.0, 1.0]}],
                    }
                ]
            }
        }
    )

    class _Query:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def limit(self, value):
            self.rows = self.rows[:value]
            return self

        def all(self):
            return self.rows

    class _Db:
        def query(self, model):
            if model is LLMNodeModelRoutingCohort:
                return _Query([active_cohort])
            if model in {
                LLMNodeModelRoutingCohortExample,
                LLMNodeModelRoutingObservation,
            }:
                return _Query([])
            raise AssertionError(f"unexpected query model: {model}")

    catalog = AdaptiveModelRoutingCohortStore.build_runtime_catalog(
        _Db(),
        policy_id="policy-1",
        policy=policy,
        node_data={"model_routing_context": {"input_paths": ["message"]}},
    )

    assert [route["cohort_id"] for route in catalog["routes"]] == [
        "billing",
        "high-risk",
    ]


def test_runtime_catalog_projects_curated_and_recent_observation_vectors():
    """FR-011: runtime route는 대표 문의와 최근 운영 표현 벡터를 함께 사용한다."""
    cohort_id = uuid4()
    active_cohort = SimpleNamespace(
        id=cohort_id,
        cohort_key="platform_access",
        label="플랫폼 접근",
        source="auto",
        status="active",
        safety_protected=False,
        centroid_embedding=[0.7, 0.3],
        encoder_model_id="text-embedding-3-large",
    )
    example = SimpleNamespace(cohort_id=cohort_id, embedding=[1.0, 0.0], ordinal=1)
    observations = [
        SimpleNamespace(matched_cohort_id=cohort_id, embedding=[0.4, 0.6]),
        SimpleNamespace(matched_cohort_id=cohort_id, embedding=[0.6, 0.4]),
    ]

    class _Query:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def limit(self, value):
            self.rows = self.rows[:value]
            return self

        def all(self):
            return self.rows

    class _Db:
        def query(self, model):
            if model is LLMNodeModelRoutingCohort:
                return _Query([active_cohort])
            if model is LLMNodeModelRoutingCohortExample:
                return _Query([example])
            if model is LLMNodeModelRoutingObservation:
                return _Query(observations)
            raise AssertionError(f"unexpected query model: {model}")

    catalog = AdaptiveModelRoutingCohortStore.build_runtime_catalog(
        _Db(),
        policy_id=uuid4(),
        policy=SimpleNamespace(active_policy={}),
        node_data={"model_routing_context": {"input_paths": ["question"]}},
    )

    assert catalog["aggregation"] == "top_k_mean"
    assert catalog["top_k"] == 2
    assert [item["embedding"] for item in catalog["routes"][0]["representatives"]] == [
        [1.0, 0.0],
        [0.4, 0.6],
        [0.6, 0.4],
    ]


def test_runtime_catalog_only_expands_manual_cohort_with_high_confidence_observations():
    """FR-011: 직접 정의 입력군은 대표 문의와 가까운 관찰만 확장한다."""
    cohort_id = uuid4()
    manual_cohort = SimpleNamespace(
        id=cohort_id,
        cohort_key="sales_enablement",
        label="영업 온보딩",
        source="manual",
        status="active",
        safety_protected=False,
        centroid_embedding=[1.0, 0.0],
        encoder_model_id="text-embedding-3-large",
    )
    example = SimpleNamespace(cohort_id=cohort_id, embedding=[1.0, 0.0], ordinal=1)
    misclassified_observation = SimpleNamespace(
        matched_cohort_id=cohort_id,
        embedding=[0.0, 1.0],
    )
    trusted_observation = SimpleNamespace(
        matched_cohort_id=cohort_id,
        embedding=[0.8, 0.2],
    )

    class _Query:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def limit(self, value):
            self.rows = self.rows[:value]
            return self

        def all(self):
            return self.rows

    class _Db:
        def query(self, model):
            if model is LLMNodeModelRoutingCohort:
                return _Query([manual_cohort])
            if model is LLMNodeModelRoutingCohortExample:
                return _Query([example])
            if model is LLMNodeModelRoutingObservation:
                return _Query([misclassified_observation, trusted_observation])
            raise AssertionError(f"unexpected query model: {model}")

    catalog = AdaptiveModelRoutingCohortStore.build_runtime_catalog(
        _Db(),
        policy_id=uuid4(),
        policy=SimpleNamespace(active_policy={}),
        node_data={"model_routing_context": {"input_paths": ["question"]}},
    )

    assert [item["embedding"] for item in catalog["routes"][0]["representatives"]] == [
        [1.0, 0.0],
        [0.8, 0.2],
    ]
    assert catalog["routes"][0]["threshold"] == 0.60


def test_manual_and_auto_cohorts_reject_low_confidence_boundary_observations():
    """FR-011: 50% 초반의 다른 업무 문의를 기존 입력군에 억지로 넣지 않는다."""
    manual = SimpleNamespace(
        id=uuid4(),
        source="manual",
        status="active",
        centroid_embedding=[1.0, 0.0],
    )
    auto = SimpleNamespace(
        id=uuid4(),
        source="auto",
        status="active",
        centroid_embedding=[1.0, 0.0],
    )
    low_confidence_vector = [0.52, 0.8541662602]
    auto_confident_vector = [0.56, 0.8284926071]

    assert AdaptiveModelRoutingCohortStore._match(low_confidence_vector, [manual]) is None
    assert AdaptiveModelRoutingCohortStore._match(low_confidence_vector, [auto]) is None
    assert AdaptiveModelRoutingCohortStore._match(auto_confident_vector, [manual]) is None
    assert AdaptiveModelRoutingCohortStore._match(auto_confident_vector, [auto]) is auto


def test_observation_match_rejects_ambiguous_auto_cohorts():
    """FR-011: 1·2위 입력군의 차이가 작으면 학습 데이터로 편입하지 않는다."""
    first = SimpleNamespace(
        id=uuid4(),
        cohort_key="first",
        source="auto",
        status="active",
        centroid_embedding=[0.58, 0.8146164742],
    )
    second = SimpleNamespace(
        id=uuid4(),
        cohort_key="second",
        source="auto",
        status="active",
        centroid_embedding=[0.57, 0.8216446910],
    )

    # 첫 번째와 두 번째의 유사도가 각각 0.58, 0.57이므로 runtime의
    # min_margin(0.05) 기준에서는 어느 입력군에도 확정 매칭하면 안 된다.
    assert AdaptiveModelRoutingCohortStore._match([1.0, 0.0], [first, second]) is None

    # runtime은 2위가 자신의 threshold를 넘지 못해도, 1위와 충분히 구분되지
    # 않으면 ambiguous로 처리한다. 관찰 저장도 같은 기준을 따라야 한다.
    manual_winner = SimpleNamespace(
        id=uuid4(),
        cohort_key="manual-winner",
        source="manual",
        status="active",
        centroid_embedding=[0.61, 0.7924014134],
    )
    manual_runner_up = SimpleNamespace(
        id=uuid4(),
        cohort_key="manual-runner-up",
        source="manual",
        status="active",
        centroid_embedding=[0.59, 0.8074032449],
    )
    assert (
        AdaptiveModelRoutingCohortStore._match(
            [1.0, 0.0],
            [manual_winner, manual_runner_up],
        )
        is None
    )


def test_observation_match_uses_top_two_example_average_per_cohort():
    """FR-011: 관찰 저장도 대표 예문 여러 개의 상위 두 점수를 사용한다."""
    access = SimpleNamespace(
        id=uuid4(),
        cohort_key="account_access",
        source="manual",
        status="active",
        centroid_embedding=[0.6, 0.4],
    )
    billing = SimpleNamespace(
        id=uuid4(),
        cohort_key="billing",
        source="manual",
        status="active",
        centroid_embedding=[0.7, 0.3],
    )

    matched = AdaptiveModelRoutingCohortStore._match(
        [1.0, 0.0],
        [access, billing],
        example_embeddings_by_cohort={
            str(access.id): [[1.0, 0.0], [0.8, 0.6], [0.0, 1.0]],
            str(billing.id): [[0.82, 0.5723635209], [0.61, 0.7924014134]],
        },
    )

    assert matched is access


def test_runtime_catalog_uses_auto_cohort_match_threshold():
    """FR-011: 자동 발견 입력군의 runtime 경계도 관찰 저장 경계와 같다."""
    active_cohort = SimpleNamespace(
        id=uuid4(),
        cohort_key="finance_operations",
        label="재무 결산",
        source="auto",
        status="active",
        safety_protected=False,
        centroid_embedding=[1.0, 0.0],
        encoder_model_id="text-embedding-3-large",
    )

    class _Query:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def limit(self, value):
            self.rows = self.rows[:value]
            return self

        def all(self):
            return self.rows

    class _Db:
        def query(self, model):
            if model is LLMNodeModelRoutingCohort:
                return _Query([active_cohort])
            if model in {
                LLMNodeModelRoutingCohortExample,
                LLMNodeModelRoutingObservation,
            }:
                return _Query([])
            raise AssertionError(f"unexpected query model: {model}")

    catalog = AdaptiveModelRoutingCohortStore.build_runtime_catalog(
        _Db(),
        policy_id=uuid4(),
        policy=SimpleNamespace(active_policy={}),
        node_data={"model_routing_context": {"input_paths": ["question"]}},
    )

    assert catalog["routes"][0]["threshold"] == 0.55


def test_non_required_declining_cohort_becomes_dormant_after_three_reviews():
    """FR-011-A46: 사라지는 일반 입력군은 runtime policy에서 제외한다."""
    state = CohortState(
        status="active",
        required=False,
        safety_protected=False,
        low_share_streak=2,
        last_seen_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    next_state = AdaptiveCohortService.advance_lifecycle(
        state,
        current_share=0.03,
        now=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )

    assert next_state.status == "dormant"
    assert next_state.dormant_since == datetime(2026, 7, 14, tzinfo=timezone.utc)


def test_required_or_safety_cohort_is_not_auto_dormanted():
    """FR-011-A46: 필수와 안전 입력군은 저빈도여도 자동 제거하지 않는다."""
    for required, safety_protected in ((True, False), (False, True)):
        state = CohortState(
            status="active",
            required=required,
            safety_protected=safety_protected,
            low_share_streak=5,
            last_seen_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )

        next_state = AdaptiveCohortService.advance_lifecycle(
            state,
            current_share=0.0,
            now=datetime(2026, 7, 14, tzinfo=timezone.utc),
        )

        assert next_state.status == "active"


def test_dormant_cohort_reactivates_before_retention_expiry():
    """FR-011-A47: 재등장 트렌드는 새 row가 아니라 기존 입력군을 복원한다."""
    dormant_since = datetime(2026, 7, 1, tzinfo=timezone.utc)
    state = CohortState(
        status="dormant",
        required=False,
        safety_protected=False,
        low_share_streak=3,
        last_seen_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        dormant_since=dormant_since,
    )

    next_state = AdaptiveCohortService.advance_lifecycle(
        state,
        current_share=0.12,
        now=dormant_since + timedelta(days=20),
    )

    assert next_state.status == "active"
    assert next_state.dormant_since is None


def test_dormant_cohort_is_retired_after_ninety_days_without_reappearance():
    """FR-011-A47: 휴면 상세 데이터는 90일 후 정리 대상이 된다."""
    dormant_since = datetime(2026, 4, 1, tzinfo=timezone.utc)
    state = CohortState(
        status="dormant",
        required=False,
        safety_protected=False,
        low_share_streak=3,
        last_seen_at=dormant_since,
        dormant_since=dormant_since,
    )

    next_state = AdaptiveCohortService.advance_lifecycle(
        state,
        current_share=0.0,
        now=dormant_since + timedelta(days=90),
    )

    assert next_state.status == "retired"


def test_dormant_cohort_does_not_consume_the_active_cohort_limit():
    """FR-011-A49: 사라진 trend가 새 입력군 발견을 영구적으로 막지 않는다."""
    cohorts = [
        SimpleNamespace(status="active"),
        SimpleNamespace(status="proposed"),
        SimpleNamespace(status="dormant"),
        SimpleNamespace(status="retired"),
    ]

    remaining = AdaptiveModelRoutingCohortStore.available_cohort_slots(
        cohorts,
        max_cohorts=3,
        proposed_or_validating_cap=None,
    )

    assert remaining == 1


def test_manual_cohort_edit_reembeds_and_invalidates_previous_evidence():
    """FR-011-A50: 대표 문의 변경은 기존 route 품질 증거를 그대로 재사용하지 않는다."""
    cohort = LLMNodeModelRoutingCohort(
        id=uuid4(),
        policy_id=uuid4(),
        cohort_key="billing_support",
        label="결제 문의",
        label_en="billing_support",
        source="manual",
        status="active",
        required=False,
        safety_protected=False,
        encoder_model_id="text-embedding-3-large",
        centroid_embedding=[0.5, 0.5],
        observation_count=12,
        review_window_count=2,
    )
    example = SimpleNamespace(
        cohort_id=cohort.id,
        ordinal=1,
        synthetic_text="기존 결제 문의",
        embedding=[0.5, 0.5],
    )
    evidence = SimpleNamespace(status="validated", expires_at=None)

    class _Query:
        def __init__(self, *, rows=None, one=None):
            self._rows = rows or []
            self._one = one

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return self._rows

        def one_or_none(self):
            return self._one

        def update(self, _values, synchronize_session=False):
            self.synchronize_session = synchronize_session
            return 0

    class _Db:
        def __init__(self):
            self.added = []
            self._queries = iter(
                [
                    _Query(rows=[cohort]),
                    _Query(rows=[example]),
                    _Query(rows=[evidence]),
                    _Query(),
                ]
            )

        def query(self, *_args):
            return next(self._queries)

        def add(self, value):
            self.added.append(value)

        def flush(self):
            pass

    db = _Db()
    updated = AdaptiveModelRoutingCohortStore.update_manual_cohort(
        db,
        cohort=cohort,
        policy=SimpleNamespace(id=cohort.policy_id),
        node_data={"model_id": "gpt-4.1"},
        label="청구서 발행 문의",
        cohort_key="invoice_issue",
        representative_query="결제는 완료됐지만 청구서가 발행되지 않았습니다.",
        fixed=True,
        encoder_model_id="text-embedding-3-large",
        embed=lambda _text: [1.0, 0.0],
    )

    assert updated.cohort_key == "invoice_issue"
    assert updated.status == "proposed"
    assert updated.required is True
    assert updated.observation_count == 0
    assert updated.centroid_embedding == [1.0, 0.0]
    assert example.synthetic_text == "결제는 완료됐지만 청구서가 발행되지 않았습니다."
    assert evidence.status == "expired"


def test_manual_cohort_creation_persists_multiple_representative_examples():
    """FR-011: 대표 문의와 마법사 예문을 각각 검색 가능한 벡터로 저장한다."""
    class _Query:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return []

    class _Db:
        def __init__(self):
            self.added = []

        def query(self, _model):
            return _Query()

        def add(self, value):
            self.added.append(value)

        def flush(self):
            pass

    vectors = {
        "퇴사자의 VPN 권한을 회수하고 싶습니다.": [1.0, 0.0],
        "신규 입사자가 SSO로 로그인하지 못합니다.": [0.8, 0.2],
        "휴대전화 교체 후 MFA를 다시 등록하고 싶습니다.": [0.6, 0.4],
    }
    db = _Db()

    cohort = AdaptiveModelRoutingCohortStore.create_manual_cohort(
        db,
        policy=SimpleNamespace(id=uuid4(), max_cohorts=6),
        node_data={"model_id": "gpt-4.1"},
        label="계정·접근 권한",
        cohort_key="account_access",
        representative_query="퇴사자의 VPN 권한을 회수하고 싶습니다.",
        representative_examples=list(vectors),
        fixed=False,
        encoder_model_id="text-embedding-3-large",
        embed=lambda text: vectors[text],
    )

    examples = [
        value
        for value in db.added
        if isinstance(value, LLMNodeModelRoutingCohortExample)
    ]
    assert [item.synthetic_text for item in examples] == list(vectors)
    assert [item.ordinal for item in examples] == [1, 2, 3]
    assert all(
        abs(actual - expected) < 1e-9
        for actual, expected in zip(cohort.centroid_embedding, [0.8, 0.2])
    )


def test_manual_cohort_edit_unmatches_observations_from_the_previous_definition():
    """FR-011: 수정 전 대표 문의의 관찰값은 새 입력군 검증에 재사용하지 않는다."""
    cohort = LLMNodeModelRoutingCohort(
        id=uuid4(),
        policy_id=uuid4(),
        cohort_key="billing_support",
        label="결제 문의",
        label_en="billing_support",
        source="manual",
        status="active",
        required=False,
        safety_protected=False,
        encoder_model_id="text-embedding-3-large",
        centroid_embedding=[0.5, 0.5],
    )

    class _Query:
        def __init__(self, *, rows=None, one=None):
            self._rows = rows or []
            self._one = one

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return self._rows

        def one_or_none(self):
            return self._one

        def update(self, values, synchronize_session=False):
            self.updated_values = values
            self.synchronize_session = synchronize_session
            return 5

    observation_query = _Query()

    class _Db:
        def __init__(self):
            self._queries = iter(
                [
                    _Query(rows=[cohort]),
                    _Query(rows=[SimpleNamespace(ordinal=1)]),
                    _Query(rows=[]),
                    observation_query,
                ]
            )

        def query(self, *_args):
            return next(self._queries)

        def add(self, _value):
            pass

        def flush(self):
            pass

    db = _Db()
    AdaptiveModelRoutingCohortStore.update_manual_cohort(
        db,
        cohort=cohort,
        policy=SimpleNamespace(id=cohort.policy_id),
        node_data={"model_id": "gpt-4.1"},
        label="청구서 발행 문의",
        cohort_key="invoice_issue",
        representative_query="결제는 완료됐지만 청구서가 발행되지 않았습니다.",
        fixed=False,
        encoder_model_id="text-embedding-3-large",
        embed=lambda _text: [1.0, 0.0],
    )

    assert observation_query.updated_values == {
        "matched_cohort_id": None,
        "match_status": "unmatched",
    }
    assert observation_query.synchronize_session is False
