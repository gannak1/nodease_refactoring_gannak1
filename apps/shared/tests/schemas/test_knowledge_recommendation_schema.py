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
