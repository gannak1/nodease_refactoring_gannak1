import pytest
from pydantic import ValidationError

from apps.shared.schemas.knowledge import (
    KnowledgeRAGRecommendation,
    KnowledgeRAGRecommendationProvenance,
    KnowledgeRAGRecommendationSummary,
    KnowledgeRAGRecommendedOptions,
    KnowledgeSelection,
)


def test_legacy_knowledge_selection_deserializes_without_scores():
    selection = KnowledgeSelection.model_validate(
        {
            "collections": [
                {
                    "collection_handle": "collection-safe-1",
                    "safe_label": "Policy collection",
                    "children": [
                        {
                            "kb_handle": "kb-safe-1",
                            "selection_key": "kb-selection-1",
                            "safe_label": "Policy KB",
                        }
                    ],
                }
            ],
            "ungrouped_kbs": [
                {
                    "kb_handle": "kb-safe-2",
                    "selection_key": "kb-selection-2",
                }
            ],
        }
    )

    assert selection.collections[0].score is None
    assert selection.collections[0].children[0].score is None
    assert selection.ungrouped_kbs[0].score is None
    assert selection.collections[0].children[0].reason_category is None
    assert selection.collections[0].children[0].recommendation_state is None


def test_hierarchy_kb_recommendation_fields_are_optional_and_allowlisted():
    payload = {
        "kb_handle": "kb-safe-1",
        "selection_key": "kb-selection-1",
        "reason_category": "content_match",
        "recommendation_state": "complete",
    }

    selection = KnowledgeSelection.model_validate(
        {
            "ungrouped_kbs": [
                payload,
                {
                    **payload,
                    "kb_handle": "kb-safe-2",
                    "selection_key": "kb-selection-2",
                    "reason_category": "metadata_match",
                    "recommendation_state": "degraded",
                },
                {
                    **payload,
                    "kb_handle": "kb-safe-3",
                    "selection_key": "kb-selection-3",
                    "reason_category": "operational_fallback",
                    "recommendation_state": "degraded",
                },
            ]
        }
    )

    assert [item.reason_category for item in selection.ungrouped_kbs] == [
        "content_match",
        "metadata_match",
        "operational_fallback",
    ]
    with pytest.raises(ValidationError):
        KnowledgeSelection.model_validate(
            {"ungrouped_kbs": [{**payload, "reason_category": "raw_provider_reason"}]}
        )
    with pytest.raises(ValidationError):
        KnowledgeSelection.model_validate(
            {"ungrouped_kbs": [{**payload, "recommendation_state": "partial"}]}
        )


def test_recommendation_schema_defaults_to_parent_first_complete_state():
    provenance = KnowledgeRAGRecommendationProvenance(
        safe_reason_code="content_match"
    )
    payload = {
        "recommendation_id": "kb-safe-1",
        "recommendation_mode": "auto_collection",
        "candidate_id": "kb-safe-1",
        "confidence": "high",
        "safe_reason_code": "content_match",
        "recommended_options": KnowledgeRAGRecommendedOptions(),
        "provenance": provenance,
    }
    recommendation = KnowledgeRAGRecommendation.model_validate(payload)
    degraded = KnowledgeRAGRecommendation.model_validate(
        {**payload, "recommendation_state": "degraded"}
    )

    assert provenance.recommendation_strategy == "parent_first_v1"
    assert recommendation.recommendation_state == "complete"
    assert degraded.recommendation_state == "degraded"
    assert KnowledgeRAGRecommendationSummary().recommendation_strategy == (
        "parent_first_v1"
    )
    with pytest.raises(ValidationError):
        KnowledgeRAGRecommendation.model_validate(
            {**payload, "recommendation_state": "invalid"}
        )
