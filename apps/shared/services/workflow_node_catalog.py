from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "workflow_node_catalog.json"
)

_CONNECTION_ROLES = {"entry", "intermediate", "branch", "terminal"}
_CONNECTION_CARDINALITIES = {"forbidden", "allowed", "required"}
_OUTGOING_HANDLE_POLICIES = {"standard", "condition_cases", "unrestricted"}


@dataclass(frozen=True)
class WorkflowConnectionPolicyIssue:
    code: str
    edge_id: str | None
    source_node_id: str | None
    target_node_id: str | None


@lru_cache(maxsize=1)
def load_workflow_node_catalog() -> dict[str, Any]:
    catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    nodes = catalog.get("nodes")
    if catalog.get("version") != 2 or not isinstance(nodes, list):
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

    for node in nodes:
        policy = node.get("connection_policy")
        if not isinstance(policy, dict):
            raise RuntimeError("Workflow node catalog is missing connection policy")
        if policy.get("role") not in _CONNECTION_ROLES:
            raise RuntimeError("Workflow node catalog has an invalid connection role")
        if policy.get("incoming") not in _CONNECTION_CARDINALITIES:
            raise RuntimeError("Workflow node catalog has an invalid incoming policy")
        if policy.get("outgoing") not in _CONNECTION_CARDINALITIES:
            raise RuntimeError("Workflow node catalog has an invalid outgoing policy")
        if policy.get("outgoing_handles") not in _OUTGOING_HANDLE_POLICIES:
            raise RuntimeError("Workflow node catalog has an invalid handle policy")
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


def connection_policy_for_node_type(node_type: str) -> dict[str, str] | None:
    definition = node_definition(node_type)
    if definition is None:
        return None
    policy = definition.get("connection_policy")
    return dict(policy) if isinstance(policy, dict) else None


def _condition_source_handles(node: dict[str, Any]) -> set[str]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    cases = data.get("cases") if isinstance(data.get("cases"), list) else []
    return {
        "default",
        *(
            str(case.get("id"))
            for case in cases
            if isinstance(case, dict) and case.get("id")
        ),
    }


def validate_workflow_graph_connections(
    graph: dict[str, Any] | None,
) -> list[WorkflowConnectionPolicyIssue]:
    graph = graph or {}
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    node_by_id = {
        str(node.get("id")): node
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }
    issues: list[WorkflowConnectionPolicyIssue] = []

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        source_node = node_by_id.get(source_id)
        target_node = node_by_id.get(target_id)
        if source_node is None or target_node is None:
            continue

        source_type = str(source_node.get("type") or "")
        target_type = str(target_node.get("type") or "")
        source_policy = connection_policy_for_node_type(source_type)
        target_policy = connection_policy_for_node_type(target_type)
        edge_id = str(edge.get("id")) if edge.get("id") is not None else None

        if target_policy and target_policy.get("incoming") == "forbidden":
            issues.append(
                WorkflowConnectionPolicyIssue(
                    code=(
                        "START_NODE_HAS_INCOMING_EDGE"
                        if target_type == "startNode"
                        else "TRIGGER_NODE_HAS_INCOMING_EDGE"
                    ),
                    edge_id=edge_id,
                    source_node_id=source_id,
                    target_node_id=target_id,
                )
            )
        if source_policy and source_policy.get("outgoing") == "forbidden":
            issues.append(
                WorkflowConnectionPolicyIssue(
                    code="TERMINAL_NODE_HAS_OUTGOING_EDGE",
                    edge_id=edge_id,
                    source_node_id=source_id,
                    target_node_id=target_id,
                )
            )
        if (
            source_policy
            and source_policy.get("outgoing_handles") == "condition_cases"
            and str(edge.get("sourceHandle") or "default")
            not in _condition_source_handles(source_node)
        ):
            issues.append(
                WorkflowConnectionPolicyIssue(
                    code="INVALID_CONDITION_SOURCE_HANDLE",
                    edge_id=edge_id,
                    source_node_id=source_id,
                    target_node_id=target_id,
                )
            )

    return issues
