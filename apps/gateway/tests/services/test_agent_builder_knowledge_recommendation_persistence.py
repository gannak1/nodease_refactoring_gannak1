import uuid

from apps.gateway.services.agent_builder_service import AgentBuilderService
from apps.shared.schemas.agent_builder import (
    AgentBuilderDirectMessageResponse,
    AgentBuilderMessageResponse,
)


RECOMMENDATION_ONLY_KEYS = {
    "confidence",
    "parent_relevance",
    "reason_category",
    "recommendation_state",
    "retrieval_state",
    "safe_reason_code",
    "score",
    "semantic_state",
    "threshold_result",
}


def _recommendation_keys(value):
    found = set()
    if isinstance(value, dict):
        found.update(RECOMMENDATION_ONLY_KEYS.intersection(value))
        for child in value.values():
            found.update(_recommendation_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_recommendation_keys(child))
    return found


def test_durable_safe_kb_bindings_omit_recommendation_scores_and_search_state():
    service = object.__new__(AgentBuilderService)

    projected = service._safe_kb_bindings(  # noqa: SLF001
        [
            {
                "safe_handle": "rec-safe",
                "name": "Knowledge Base",
                "confidence": "high",
                "score": 0.91,
                "reason_category": "content_match",
                "threshold_result": "high_confidence",
                "recommendation_state": "degraded",
                "semantic_state": "available",
            }
        ]
    )

    assert projected == [
        {
            "safe_handle": "rec-safe",
            "name": "Knowledge Base",
        }
    ]


def test_ui_response_keeps_score_and_state_but_stored_payload_redacts_them():
    service = object.__new__(AgentBuilderService)
    kb_id = uuid.uuid4()
    response = AgentBuilderMessageResponse(
        request_id=uuid.uuid4(),
        status="clarification_required",
        clarification_options=[
            {
                "type": "knowledge_base",
                "candidate_id": "rec-safe",
                "label": "Knowledge Base",
                "score": 0.91,
                "confidence": "high",
                "reason_category": "content_match",
                "threshold_result": "high_confidence",
                "recommendation_state": "degraded",
            },
            {
                "type": "workflow_node",
                "label": "Node",
                "score": 0.75,
            },
        ],
        knowledge_selection={
            "collections": [
                {
                    "collection_handle": "col-safe",
                    "safe_label": "Collection",
                    "score": 0.88,
                    "children": [
                        {
                            "kb_handle": "rec-safe",
                            "selection_key": "kbsel-safe",
                            "safe_label": "Knowledge Base",
                            "score": 0.91,
                        }
                    ],
                }
            ],
            "ungrouped_kbs": [],
        },
    )
    response._issued_knowledge_handle_bindings = {
        "knowledge_bases": {
            "rec-safe": str(kb_id),
            "score": "0.91",
        },
        "collections": {},
        "recommendation_state": {"rec-safe": "degraded"},
    }

    ui_response = AgentBuilderDirectMessageResponse.from_internal(response)
    ui_candidate = ui_response.knowledge_resolution.candidates[0]
    assert ui_candidate.score == 0.91
    assert ui_candidate.recommendation_state == "degraded"

    payload = service._stored_response_payload(  # noqa: SLF001
        response,
        direct_edit=True,
    )

    assert payload["clarification_options"] == [
        {
            "type": "workflow_node",
            "label": "Node",
            "score": 0.75,
        }
    ]
    assert _recommendation_keys(payload["knowledge_resolution"]) == set()
    assert _recommendation_keys(payload["knowledge_selection"]) == set()
    issued = payload["_issued_knowledge_handle_bindings"]
    assert _recommendation_keys(issued) == set()
    assert issued["knowledge_bases"] == {"rec-safe": str(kb_id)}
    assert payload["knowledge_resolution"]["candidates"][0]["candidate_id"] == (
        "rec-safe"
    )
    stored_child = payload["knowledge_selection"]["collections"][0]["children"][0]
    assert stored_child["kb_handle"] == "rec-safe"


def test_stored_payload_redacts_every_recommendation_only_internal_signal():
    service = object.__new__(AgentBuilderService)
    payload = {
        "knowledge_resolution": {
            "candidate_id": "rec-safe",
            "parent_relevance": 0.91,
        },
        "knowledge_selection": {
            "collections": [],
            "retrieval_state": "complete",
        },
        "_issued_knowledge_handle_bindings": {
            "knowledge_bases": {"rec-safe": str(uuid.uuid4())},
            "safe_reason_code": "content_match",
        },
    }

    service._redact_persisted_knowledge_recommendation(payload)  # noqa: SLF001

    assert _recommendation_keys(payload["knowledge_resolution"]) == set()
    assert _recommendation_keys(payload["knowledge_selection"]) == set()
    assert _recommendation_keys(payload["_issued_knowledge_handle_bindings"]) == set()
    assert payload["knowledge_resolution"] == {"candidate_id": "rec-safe"}
    assert payload["knowledge_selection"] == {"collections": []}
    assert set(payload["_issued_knowledge_handle_bindings"]) == {
        "knowledge_bases"
    }
