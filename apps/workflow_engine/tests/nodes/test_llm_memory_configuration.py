from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.workflow_engine.workflow.nodes.llm.entities import LLMNodeData


def _node_data(memory: dict | None) -> dict:
    return {
        "title": "Answer",
        "model_id": "fixed-model",
        "user_prompt": "{{ question }}",
        "memory": memory,
    }


def test_memory_configuration_round_trips_without_enabling_legacy_nodes() -> None:
    disabled = LLMNodeData.model_validate(_node_data(None))
    enabled = LLMNodeData.model_validate(
        _node_data(
            {
                "enabled": True,
                "channel": "conversation",
                "readSource": "conversation_turns",
                "writeMode": "none",
                "maxTurns": 5,
                "maxContextTokens": 1200,
                "strategy": "window",
                "failurePolicy": "fail_node",
            }
        )
    )

    assert disabled.memory is None
    assert enabled.model_dump(mode="json")["memory"] == {
        "enabled": True,
        "channel": "conversation",
        "readSource": "conversation_turns",
        "writeMode": "none",
        "selectedNodeIds": [],
        "maxTurns": 5,
        "maxContextTokens": 1200,
        "strategy": "window",
        "summaryModelPolicy": "inherit_node",
        "failurePolicy": "fail_node",
    }


@pytest.mark.parametrize(
    "memory",
    [
        {"enabled": True, "maxTurns": 0},
        {"enabled": True, "maxContextTokens": 8193},
        {"enabled": True, "strategy": "unknown"},
        {"enabled": True, "arbitraryFilter": "all"},
    ],
)
def test_invalid_or_unbounded_memory_configuration_is_not_silently_discarded(
    memory: dict,
) -> None:
    with pytest.raises(ValidationError):
        LLMNodeData.model_validate(_node_data(memory))
