from apps.workflow_engine.services.model_routing_semantic_catalog import (
    SemanticRouteCatalogBuilder,
)
from apps.workflow_engine.services.model_routing_semantic_router import (
    semantic_catalog_from_policy,
)


def test_catalog_builder_precomputes_vectors_and_drops_curated_utterance_text():
    calls: list[str] = []

    def embed(text: str) -> list[float]:
        calls.append(text)
        return [float(len(calls)), 1.0]

    source = {
        "route_catalog_version": "ticket-routing-v1",
        "encoder_model_id": "text-embedding-test",
        "input_paths": ["webhook-ticket.message"],
        "top_k": 3,
        "aggregation": "centroid",
        "min_margin": 0.08,
        "routes": [
            {
                "cohort_id": "routine_support",
                "label": "단순 사용·안내 문의",
                "threshold": 0.72,
                "utterances": ["다운로드 위치를 알려 주세요.", "설정 방법이 궁금합니다."],
            },
            {
                "cohort_id": "high_risk",
                "label": "보안·보상 위험 문의",
                "threshold": 0.78,
                "utterances": ["계정 탈취가 의심됩니다.", "보상 승인이 필요합니다."],
                "safety_override": True,
                "lexical_override_threshold": 1.5,
                "lexical_signals": [
                    {"term": "계정 탈취", "weight": 1.0},
                    {"term": "개인정보 유출", "weight": 1.5},
                ],
            },
        ],
    }

    snapshot = SemanticRouteCatalogBuilder.build(source, embed=embed)

    assert calls == [
        "다운로드 위치를 알려 주세요.",
        "설정 방법이 궁금합니다.",
        "계정 탈취가 의심됩니다.",
        "보상 승인이 필요합니다.",
    ]
    assert "다운로드 위치" not in str(snapshot)
    assert "계정 탈취가 의심됩니다." not in str(snapshot)
    assert snapshot["routes"][0]["representatives"][0]["utterance_hash"]
    assert snapshot["routes"][0]["representatives"][0]["embedding"] == [
        1.0,
        1.0,
    ]
    assert snapshot["routes"][0]["centroid_embedding"] == [1.5, 1.0]
    assert snapshot["input_paths"] == ["webhook-ticket.message"]
    catalog = semantic_catalog_from_policy(snapshot)
    assert catalog is not None
    assert catalog.input_paths == ("webhook-ticket.message",)
    assert catalog.routes[0].centroid_vector == (1.5, 1.0)
    high_risk = catalog.routes[1]
    assert high_risk.safety_override is True
    assert high_risk.lexical_override_threshold == 1.5
    assert [(signal.term, signal.weight) for signal in high_risk.lexical_signals] == [
        ("계정 탈취", 1.0),
        ("개인정보 유출", 1.5),
    ]


def test_catalog_builder_rejects_duplicate_cohort_ids_before_embedding():
    source = {
        "route_catalog_version": "ticket-routing-v1",
        "encoder_model_id": "text-embedding-test",
        "routes": [
            {
                "cohort_id": "duplicate",
                "label": "첫 번째",
                "threshold": 0.7,
                "utterances": ["첫 문장"],
            },
            {
                "cohort_id": "duplicate",
                "label": "두 번째",
                "threshold": 0.7,
                "utterances": ["둘 문장"],
            },
        ],
    }

    try:
        SemanticRouteCatalogBuilder.build(source, embed=lambda _text: [1.0, 2.0])
    except ValueError as exc:
        assert "cohort_id" in str(exc)
    else:
        raise AssertionError("duplicate cohort_id must fail")
