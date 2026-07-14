from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return [active_cohort]

    class _Db:
        def query(self, *_args):
            return _Query()

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
