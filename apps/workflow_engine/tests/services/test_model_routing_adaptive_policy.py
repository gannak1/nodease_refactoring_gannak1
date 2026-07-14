"""FR-011-A48~A50: 적응형 입력군의 runtime policy 경계를 검증한다."""

from apps.workflow_engine.services.model_routing_adaptive_policy import (
    AdaptiveCandidate,
    AdaptiveCohortRoute,
    AdaptiveModelRoutingPolicyService,
)


def test_runtime_catalog_only_contains_active_or_required_validated_cohorts():
    """검증 전/휴면 입력군은 실행 정책에 섞이지 않는다."""
    catalog = AdaptiveModelRoutingPolicyService.build_runtime_catalog(
        encoder_model_id="text-embedding-3-small",
        input_paths=["message"],
        routes=[
            AdaptiveCohortRoute(
                cohort_id="active-billing",
                label="청구 문의",
                status="active",
                validated=True,
                centroid_embedding=(1.0, 0.0),
            ),
            AdaptiveCohortRoute(
                cohort_id="proposed-integration",
                label="연동 문의",
                status="proposed",
                validated=False,
                centroid_embedding=(0.0, 1.0),
            ),
            AdaptiveCohortRoute(
                cohort_id="dormant-routine",
                label="저빈도 안내",
                status="dormant",
                validated=True,
                centroid_embedding=(0.5, 0.5),
            ),
        ],
    )

    assert [route["cohort_id"] for route in catalog["routes"]] == ["active-billing"]


def test_runtime_catalog_keeps_policy_owned_safety_route_without_creating_a_discount_rule():
    catalog = AdaptiveModelRoutingPolicyService.build_runtime_catalog(
        encoder_model_id="text-embedding-3-small",
        input_paths=["message"],
        routes=[
            AdaptiveCohortRoute(
                cohort_id="routine",
                label="일반 안내",
                status="active",
                validated=True,
                centroid_embedding=(1.0, 0.0),
            )
        ],
        preserved_safety_routes=[
            {
                "cohort_id": "safety",
                "label": "고위험",
                "threshold": 0.7,
                "safety_override": True,
                "centroid_embedding": [0.0, 1.0],
                "representatives": [{"embedding": [0.0, 1.0]}],
            }
        ],
    )

    assert [route["cohort_id"] for route in catalog["routes"]] == [
        "routine",
        "safety",
    ]
    assert catalog["routes"][1]["safety_override"] is True


def test_candidate_plan_keeps_only_runtime_available_unvalidated_models():
    """새 후보 검증은 실행 주체가 실제 호출할 수 있는 chat model만 대상으로 한다."""
    candidates = AdaptiveModelRoutingPolicyService.plan_candidates(
        candidates=[
            AdaptiveCandidate("gpt-4.1", estimated_cost=0.02, validated=True),
            AdaptiveCandidate("gpt-4.1-mini", estimated_cost=0.004, validated=False),
            AdaptiveCandidate("gpt-4o-mini", estimated_cost=0.002, validated=False),
            AdaptiveCandidate("other-org-model", estimated_cost=0.0001, validated=False),
        ],
        available_model_ids={"gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"},
        maximum_candidates=2,
    )

    assert [candidate.model_id for candidate in candidates] == [
        "gpt-4o-mini",
        "gpt-4.1-mini",
    ]


def test_candidate_plan_never_revalidates_an_already_validated_model():
    """검증 예산은 이미 통과한 모델에 반복해서 쓰지 않는다."""
    candidates = AdaptiveModelRoutingPolicyService.plan_candidates(
        candidates=[
            AdaptiveCandidate("gpt-4.1", estimated_cost=0.02, validated=True),
            AdaptiveCandidate("gpt-4.1-mini", estimated_cost=0.004, validated=True),
        ],
        available_model_ids={"gpt-4.1", "gpt-4.1-mini"},
        maximum_candidates=2,
    )

    assert candidates == []


def test_candidate_plan_uses_two_cost_tiers_instead_of_two_near_identical_cheapest_models():
    """후보 두 자리는 초저가 하나와 더 높은 비용대 하나로 품질 탐색 범위를 넓힌다."""
    candidates = AdaptiveModelRoutingPolicyService.plan_candidates(
        candidates=[
            AdaptiveCandidate("cheap", estimated_cost=0.00045, validated=False),
            AdaptiveCandidate("cheap-neighbor", estimated_cost=0.00075, validated=False),
            AdaptiveCandidate("balanced", estimated_cost=0.00145, validated=False),
            AdaptiveCandidate("mid", estimated_cost=0.00200, validated=False),
        ],
        available_model_ids={"cheap", "cheap-neighbor", "balanced", "mid"},
        maximum_candidates=2,
    )

    assert [candidate.model_id for candidate in candidates] == ["cheap", "balanced"]
