from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.shared.services.workflow_node_catalog import (
    node_definition,
    node_output_keys,
    node_parameter_definitions,
    node_parameter_is_configured,
    validate_node_parameter_value,
)


@dataclass(frozen=True)
class WorkflowConfigurationIssue:
    node_id: str
    node_type: str
    missing_parameters: tuple[str, ...]


class WorkflowConfigurationPreflightError(ValueError):
    def __init__(
        self, surface: str, issues: list[WorkflowConfigurationIssue]
    ) -> None:
        self.surface = surface
        self.issues = issues
        super().__init__("workflow_configuration_unresolved")


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def workflow_configuration_issues(
    graph: dict[str, Any] | None,
) -> list[WorkflowConfigurationIssue]:
    issues: list[WorkflowConfigurationIssue] = []
    visited_graphs: set[int] = set()

    def parameter_selectors(value: Any) -> list[list[Any]]:
        if isinstance(value, list) and len(value) >= 2 and all(
            isinstance(item, str) for item in value
        ):
            return [value]
        if not isinstance(value, list):
            return []
        selectors: list[list[Any]] = []
        for item in value:
            if isinstance(item, list):
                selectors.append(item)
            elif isinstance(item, dict) and isinstance(item.get("value_selector"), list):
                selectors.append(item["value_selector"])
        return selectors

    def inspect_graph(current: dict[str, Any]) -> None:
        graph_identity = id(current)
        if graph_identity in visited_graphs:
            return
        visited_graphs.add(graph_identity)
        nodes = [
            node
            for node in current.get("nodes") or []
            if isinstance(node, dict)
        ]
        node_by_id = {
            str(node.get("id")): node for node in nodes if node.get("id")
        }

        def selector_valid(selector: Any) -> bool:
            if not isinstance(selector, list) or len(selector) < 2:
                return False
            source = node_by_id.get(str(selector[0]))
            if source is None:
                return False
            return str(selector[1]) in node_output_keys(
                str(source.get("type") or ""),
                source.get("data")
                if isinstance(source.get("data"), dict)
                else {},
            )

        for node in nodes:
            node_type = str(node.get("type") or "")
            definition = node_definition(node_type)
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            if definition is not None and definition.get("side_effect") in {
                "external_read",
                "external_write",
                "local_execution",
            }:
                deferred = {
                    str(key)
                    for key in data.get("_deferred_parameters", [])
                    if isinstance(key, str)
                }
                missing_items: list[str] = []
                for key in definition.get("required_configuration") or []:
                    parameter_key = str(key)
                    invalid = (
                        parameter_key in deferred
                        or not node_parameter_is_configured(
                            node_type, parameter_key, data
                        )
                        or (
                            node_type not in {"githubNode", "slackPostNode"}
                            and bool(
                                validate_node_parameter_value(
                                    node_type,
                                    parameter_key,
                                    data.get(parameter_key),
                                )
                            )
                        )
                    )
                    parameter = next(
                        (
                            item
                            for item in node_parameter_definitions(node_type)
                            if str(item.get("key")) == parameter_key
                        ),
                        None,
                    )
                    if (
                        parameter
                        and parameter.get("input_type") == "variable_selector"
                    ):
                        selectors = parameter_selectors(data.get(parameter_key))
                        invalid = invalid or not selectors or not all(
                            selector_valid(selector) for selector in selectors
                        )
                    if invalid:
                        missing_items.append(parameter_key)
                missing = tuple(missing_items)
                if missing:
                    issues.append(
                        WorkflowConfigurationIssue(
                            node_id=str(node.get("id") or ""),
                            node_type=node_type,
                            missing_parameters=missing,
                        )
                    )

            subgraph = data.get("subGraph") if node_type == "loopNode" else None
            if isinstance(subgraph, dict):
                inspect_graph(subgraph)

    if isinstance(graph, dict):
        inspect_graph(graph)
    return issues


def enforce_workflow_configuration_preflight(
    graph: dict[str, Any] | None,
    *,
    surface: str,
) -> None:
    issues = workflow_configuration_issues(graph)
    if issues:
        raise WorkflowConfigurationPreflightError(surface, issues)
