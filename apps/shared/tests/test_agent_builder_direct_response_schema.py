from uuid import uuid4

from apps.shared.schemas.agent_builder import (
    AgentBuilderDirectMessageResponse,
    AgentBuilderMessageResponse,
    AgentBuilderPendingResolution,
    AgentBuilderStructuredRequest,
)


def test_direct_response_moves_kb_candidates_out_of_clarification_options() -> None:
    response = AgentBuilderMessageResponse(
        request_id=uuid4(),
        status="clarification_required",
        structured_request=AgentBuilderStructuredRequest(
            request_type="new_workflow",
            draft_mode="new_workflow",
            intent_summary="Knowledge workflow",
            knowledge_requirements=[
                {
                    "requirement_id": "knowledge-1",
                    "purpose": "internal documents",
                }
            ],
        ),
        clarification_options=[
            {
                "candidate_id": "kb-1",
                "resolution_id": "resolution-1",
                "safe_label": "Internal docs",
            },
            {
                "type": "target_node",
                "node_id": "node-1",
                "label": "Existing node",
            },
        ],
    )

    direct = AgentBuilderDirectMessageResponse.from_internal(response)

    assert [item["candidate_id"] for item in direct.knowledge_resolution["candidates"]] == [
        "kb-1"
    ]
    assert direct.clarification_options == [
        {
            "type": "target_node",
            "node_id": "node-1",
            "label": "Existing node",
        }
    ]


def test_direct_response_keeps_resolution_id_when_no_kb_candidates_exist() -> None:
    response = AgentBuilderMessageResponse(
        request_id=uuid4(),
        status="clarification_required",
        structured_request=AgentBuilderStructuredRequest(
            request_type="new_workflow",
            draft_mode="new_workflow",
            intent_summary="Knowledge workflow without eligible candidates",
            knowledge_requirements=[
                {
                    "requirement_id": "knowledge-1",
                    "purpose": "internal documents",
                    "target_step_ref": "step-llm",
                }
            ],
            pending_resolution=[
                AgentBuilderPendingResolution(
                    resolution_id="resolution-empty",
                    slot_type="knowledge_base",
                    slot_key="knowledge-1",
                    target_step_ref="step-llm",
                )
            ],
        ),
        clarification_options=[],
    )

    direct = AgentBuilderDirectMessageResponse.from_internal(response)

    assert direct.knowledge_resolution == {
        "resolution_id": "resolution-empty",
        "timing": "after_graph",
        "required": True,
        "candidates": [],
        "selected": [],
    }
