from types import SimpleNamespace

import pytest

from apps.workflow_engine.workflow.core.workflow_engine import WorkflowEngine


def _engine_with_nodes(*, entry_node_id: str | None) -> WorkflowEngine:
    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine.start_node_id = entry_node_id
    engine.node_schemas = {
        "body": SimpleNamespace(type="templateNode"),
    }
    return engine


def test_validated_entry_node_allows_triggerless_loop_body() -> None:
    engine = _engine_with_nodes(entry_node_id="body")

    engine._check_start_nodes()

    assert engine.start_node_id == "body"


def test_triggerless_graph_without_validated_entry_remains_invalid() -> None:
    engine = _engine_with_nodes(entry_node_id=None)

    with pytest.raises(ValueError, match="시작 노드"):
        engine._check_start_nodes()


def test_unknown_validated_entry_is_rejected() -> None:
    engine = _engine_with_nodes(entry_node_id="missing")

    with pytest.raises(ValueError, match="진입 노드"):
        engine._check_start_nodes()
