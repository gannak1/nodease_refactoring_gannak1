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


def test_runtime_catalog_uses_multiple_safe_representatives_for_varied_queries():
    """FR-011: 같은 입력군의 다양한 운영 표현을 중심점 하나로 축약하지 않는다."""
    catalog = AdaptiveModelRoutingPolicyService.build_runtime_catalog(
        encoder_model_id="text-embedding-3-large",
        input_paths=["question"],
        routes=[
            AdaptiveCohortRoute(
                cohort_id="platform-access",
                label="플랫폼 접근",
                status="active",
                validated=True,
                centroid_embedding=(0.7, 0.3),
                representative_embeddings=((1.0, 0.0), (0.4, 0.6)),
            )
        ],
    )

    route = catalog["routes"][0]
    assert catalog["aggregation"] == "top_k_mean"
    assert catalog["top_k"] == 2
    assert [item["embedding"] for item in route["representatives"]] == [
        [1.0, 0.0],
        [0.4, 0.6],
    ]
    assert all(set(item) == {"utterance_hash", "embedding"} for item in route["representatives"])


def test_runtime_catalog_derives_unique_lexical_signals_from_representative_examples():
    """A61: 도메인 상수 없이 입력군 예문에서만 보조 매칭 신호를 만든다."""
    catalog = AdaptiveModelRoutingPolicyService.build_runtime_catalog(
        encoder_model_id="text-embedding-3-large",
        input_paths=["question"],
        routes=[
            AdaptiveCohortRoute(
                cohort_id="platform_access",
                label="플랫폼 접근",
                status="active",
                validated=True,
                centroid_embedding=(1.0, 0.0),
                representative_texts=(
                    "신입 개발자가 VPN 접근을 신청하는 절차를 알려 주세요.",
                    "Git 저장소와 VPN 권한은 어디에서 신청하나요?",
                    "개발 환경 VPN 연결을 먼저 준비하고 싶습니다.",
                ),
            ),
            AdaptiveCohortRoute(
                cohort_id="sales_enablement",
                label="영업 온보딩",
                status="active",
                validated=True,
                centroid_embedding=(0.0, 1.0),
                representative_texts=(
                    "영업팀 신입이 CRM 권한을 신청하려면 무엇이 필요한가요?",
                    "CRM을 사용하기 전 영업 교육을 받고 싶습니다.",
                    "신규 영업 담당자의 CRM 접근 절차를 알려 주세요.",
                ),
            ),
        ],
    )

    signals = {
        route["cohort_id"]: {signal["term"] for signal in route["lexical_signals"]}
        for route in catalog["routes"]
    }

    assert "vpn" in signals["platform_access"]
    assert "crm" in signals["sales_enablement"]
    assert "신입" not in signals["platform_access"]
    assert "신입" not in signals["sales_enablement"]


def test_runtime_catalog_reserves_lexical_terms_used_by_inactive_cohorts():
    """A62: 아직 할인 rule이 없는 입력군의 공통어도 다른 route 신호가 되면 안 된다."""
    catalog = AdaptiveModelRoutingPolicyService.build_runtime_catalog(
        encoder_model_id="text-embedding-3-large",
        input_paths=["question"],
        routes=[
            AdaptiveCohortRoute(
                cohort_id="sales_enablement",
                label="영업 온보딩",
                status="active",
                validated=True,
                centroid_embedding=(0.0, 1.0),
                representative_texts=(
                    "영업팀 신입이 CRM 권한을 신청하려면 무엇이 필요한가요?",
                    "CRM을 사용하기 전 영업 권한과 교육을 받고 싶습니다.",
                    "신규 영업 담당자의 CRM 접근 절차를 알려 주세요.",
                ),
            ),
        ],
        lexical_representative_texts={
            "sales_enablement": (
                "영업팀 신입이 CRM 권한을 신청하려면 무엇이 필요한가요?",
                "CRM을 사용하기 전 영업 권한과 교육을 받고 싶습니다.",
                "신규 영업 담당자의 CRM 접근 절차를 알려 주세요.",
            ),
            "platform_access": (
                "플랫폼개발팀 신입이 Git, VPN과 운영 조회 권한을 신청합니다.",
                "개발 저장소와 VPN 권한은 어떤 순서로 신청하나요?",
                "운영 로그를 조회하는 접근 권한을 준비하고 싶습니다.",
            ),
        },
    )

    signals = {
        signal["term"] for signal in catalog["routes"][0]["lexical_signals"]
    }

    assert "crm" in signals
    assert "권한" not in signals


def test_runtime_catalog_normalizes_korean_particles_before_reserving_terms():
    """A62: `권한과`/`권한을`처럼 조사가 달라도 같은 공통 신호로 본다."""
    catalog = AdaptiveModelRoutingPolicyService.build_runtime_catalog(
        encoder_model_id="text-embedding-3-large",
        input_paths=["question"],
        routes=[
            AdaptiveCohortRoute(
                cohort_id="sales_enablement",
                label="영업 온보딩",
                status="active",
                validated=True,
                centroid_embedding=(0.0, 1.0),
                representative_texts=(
                    "영업팀 신입이 CRM 권한과 교육을 준비합니다.",
                    "CRM 사용 전에 영업 권한과 고객 교육을 확인합니다.",
                    "신규 영업 담당자의 CRM 접근 절차를 알려 주세요.",
                ),
            ),
        ],
        lexical_representative_texts={
            "sales_enablement": (
                "영업팀 신입이 CRM 권한과 교육을 준비합니다.",
                "CRM 사용 전에 영업 권한과 고객 교육을 확인합니다.",
                "신규 영업 담당자의 CRM 접근 절차를 알려 주세요.",
            ),
            "platform_access": (
                "플랫폼개발팀은 Git 저장소 권한을 신청합니다.",
                "VPN 접근 권한은 어떤 순서로 준비하나요?",
                "운영 로그 조회 권한을 받기 전에 교육을 완료합니다.",
            ),
        },
    )

    signals = {
        signal["term"] for signal in catalog["routes"][0]["lexical_signals"]
    }

    assert "권한과" not in signals
    assert "권한" not in signals
    assert "crm" in signals


def test_each_cohort_calibrates_its_own_similarity_threshold_from_positive_and_negative_examples():
    billing = AdaptiveModelRoutingPolicyService.calibrate_similarity_threshold(
        positive_embeddings=((1.0, 0.0), (0.99, 0.1), (0.98, -0.1)),
        negative_embeddings=((0.0, 1.0), (0.1, 0.99), (-0.1, 0.98)),
        default_threshold=0.60,
    )
    support = AdaptiveModelRoutingPolicyService.calibrate_similarity_threshold(
        positive_embeddings=((0.8, 0.6), (0.75, 0.66), (0.7, 0.71)),
        negative_embeddings=((-1.0, 0.0), (-0.9, 0.1), (-0.8, -0.2)),
        default_threshold=0.60,
    )

    assert billing.status == "calibrated"
    assert support.status == "calibrated"
    assert billing.threshold != support.threshold
    assert billing.positive_sample_count == 3
    assert billing.negative_sample_count == 3


def test_similarity_calibration_keeps_the_safe_default_when_examples_are_insufficient():
    calibration = AdaptiveModelRoutingPolicyService.calibrate_similarity_threshold(
        positive_embeddings=((1.0, 0.0), (0.99, 0.1)),
        negative_embeddings=((0.0, 1.0),),
        default_threshold=0.60,
    )

    assert calibration.status == "insufficient_positive_examples"
    assert calibration.threshold == 0.60


def test_similarity_calibration_uses_negative_boundary_when_cohorts_overlap():
    """FR-011-A57: 겹치는 분포는 양성·음성 경계의 중간값으로 오분류를 줄인다."""
    calibration = AdaptiveModelRoutingPolicyService.calibrate_similarity_threshold(
        positive_embeddings=(
            (0.5299595337147563, -0.25575086094310634, 0.568396767730397, 0.5750300028566642),
            (0.5226020397175609, -0.497868395450461, 0.6045551357254926, 0.33693806072119475),
            (0.2812127773133253, 0.24231258868268876, -0.7183945588426774, 0.5883138967140373),
            (0.1439630399833549, -0.13351557424894286, -0.4842649211089811, 0.8526052549304621),
        ),
        negative_embeddings=(
            (0.4961237221413488, 0.6501293216131776, -0.5025171806241409, -0.2804810166213886),
            (-0.3628956265300091, -0.57853973839885, -0.250270544029137, -0.6862675791046392),
            (0.4059360601500631, -0.37357165172100953, -0.5877195495788423, -0.5918157374919356),
            (0.6024945557930004, -0.7535609203977122, -0.09478706039634792, -0.2452787448405734),
        ),
        default_threshold=0.60,
    )

    assert calibration.status == "conservative_overlap"
    assert calibration.negative_ceiling == 0.433597
    assert calibration.positive_floor == 0.437325
    assert calibration.threshold == 0.435461
    assert calibration.negative_ceiling < calibration.threshold
    assert calibration.threshold < calibration.positive_floor
    assert calibration.threshold < 0.60


def test_centroid_calibration_uses_the_same_aggregation_as_runtime():
    """정책 calibration과 runtime matcher가 서로 다른 점수 공식을 쓰지 않는다."""
    calibration = AdaptiveModelRoutingPolicyService.calibrate_similarity_threshold(
        positive_embeddings=(
            (1.0, 0.0),
            (0.8, 0.2),
            (0.7, 0.3),
        ),
        negative_embeddings=(
            (0.0, 1.0),
            (0.1, 0.9),
            (0.2, 0.8),
        ),
        default_threshold=0.60,
        aggregation="centroid",
    )

    assert calibration.status == "calibrated"
    assert calibration.threshold > 0.60


def test_runtime_catalog_preserves_the_configured_aggregation():
    catalog = AdaptiveModelRoutingPolicyService.build_runtime_catalog(
        encoder_model_id="text-embedding-3-large",
        input_paths=["request.query"],
        aggregation="centroid",
        top_k=3,
        min_margin=0.08,
        routes=[
            AdaptiveCohortRoute(
                cohort_id="routine",
                label="일반 안내",
                status="active",
                validated=True,
                centroid_embedding=(1.0, 0.0),
                representative_embeddings=((1.0, 0.0), (0.8, 0.2)),
            )
        ],
    )

    assert catalog["aggregation"] == "centroid"
    assert catalog["top_k"] == 3
    assert catalog["min_margin"] == 0.08


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


def test_runtime_catalog_derives_dense_safety_guard_from_calibration():
    """안전 경계는 새 표현의 작은 embedding drift까지 보수적으로 보호한다."""
    catalog = AdaptiveModelRoutingPolicyService.build_runtime_catalog(
        encoder_model_id="text-embedding-3-small",
        input_paths=["message"],
        min_margin=0.05,
        routes=[
            AdaptiveCohortRoute(
                cohort_id="security_incident",
                label="보안 사고",
                status="active",
                validated=True,
                safety_override=True,
                threshold=0.415,
                calibration={
                    "positive_floor": 0.415,
                    "negative_ceiling": 0.486,
                },
                centroid_embedding=(0.0, 1.0),
            )
        ],
    )

    assert catalog["routes"][0]["dense_override_threshold"] == 0.456


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
