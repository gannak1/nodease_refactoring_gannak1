import pytest

from apps.workflow_engine.workflow.nodes.loop.loop_node import LoopNode, LoopNodeData


def _loop_node(
    *, subgraph: dict, error_strategy: str = "end", loop_key: str = "items"
) -> LoopNode:
    return LoopNode(
        id="loop-1",
        data=LoopNodeData(
            title="Loop",
            loop_key=loop_key,
            error_strategy=error_strategy,
            subGraph=subgraph,
        ),
    )


def test_loop_without_explicit_key_uses_first_mapped_array() -> None:
    node = _loop_node(subgraph={"nodes": [], "edges": []}, loop_key="")

    assert node._get_iteration_array(
        {}, {"scalar": "ignored", "items": ["a", "b"]}
    ) == ["a", "b"]


def test_loop_body_uses_validated_implicit_entry(monkeypatch) -> None:
    node = _loop_node(
        subgraph={
            "nodes": [
                {
                    "id": "first",
                    "type": "templateNode",
                    "position": {"x": 0, "y": 0},
                    "data": {},
                },
                {
                    "id": "second",
                    "type": "llmNode",
                    "position": {"x": 0, "y": 0},
                    "data": {},
                },
            ],
            "edges": [{"id": "first-second", "source": "first", "target": "second"}],
        }
    )
    captured_entries: list[str] = []

    def execute_body(context, *, iteration_index, entry_node_id):
        captured_entries.append(entry_node_id)
        return {"iteration": iteration_index}

    monkeypatch.setattr(node, "_execute_subgraph_scoped", execute_body)

    result = node._run({"items": ["a", "b"]})

    assert captured_entries == ["first", "first"]
    assert result["results"] == [{"iteration": 0}, {"iteration": 1}]


def test_loop_structure_error_is_not_swallowed_by_continue_strategy() -> None:
    node = _loop_node(
        subgraph={
            "nodes": [
                {
                    "id": "first",
                    "type": "templateNode",
                    "position": {"x": 0, "y": 0},
                    "data": {},
                },
                {
                    "id": "second",
                    "type": "llmNode",
                    "position": {"x": 0, "y": 0},
                    "data": {},
                },
            ],
            "edges": [],
        },
        error_strategy="continue",
    )

    with pytest.raises(ValueError, match="workflow_graph_invalid"):
        node._run({"items": ["a"]})
