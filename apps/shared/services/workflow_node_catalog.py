from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "workflow_node_catalog.json"
)


@lru_cache(maxsize=1)
def load_workflow_node_catalog() -> dict[str, Any]:
    catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    nodes = catalog.get("nodes")
    if catalog.get("version") != 1 or not isinstance(nodes, list):
        raise RuntimeError("Invalid workflow node capability catalog")

    node_types = [str(node.get("node_type") or "") for node in nodes]
    if any(not node_type for node_type in node_types):
        raise RuntimeError("Workflow node catalog contains an empty node type")
    if len(node_types) != len(set(node_types)):
        raise RuntimeError("Workflow node catalog contains duplicate node types")

    capabilities = [
        str(capability)
        for node in nodes
        for capability in node.get("capabilities") or []
    ]
    if len(capabilities) != len(set(capabilities)):
        raise RuntimeError("Workflow node catalog contains duplicate capabilities")
    return catalog


def implemented_node_types() -> set[str]:
    return {
        str(node["node_type"])
        for node in load_workflow_node_catalog()["nodes"]
        if node.get("implemented") is True
    }


def agent_builder_supported_node_types() -> set[str]:
    return {
        str(node["node_type"])
        for node in load_workflow_node_catalog()["nodes"]
        if node.get("implemented") is True
        and node.get("agent_builder_supported") is True
    }


def agent_builder_supported_capabilities() -> set[str]:
    return {
        str(capability)
        for node in load_workflow_node_catalog()["nodes"]
        if node.get("implemented") is True
        and node.get("agent_builder_supported") is True
        for capability in node.get("capabilities") or []
    }


def node_type_for_capability(capability: str) -> str | None:
    for node in load_workflow_node_catalog()["nodes"]:
        if capability in (node.get("capabilities") or []):
            return str(node["node_type"])
    return None


def node_definition(node_type: str) -> dict[str, Any] | None:
    for node in load_workflow_node_catalog()["nodes"]:
        if node.get("node_type") == node_type:
            return node
    return None
