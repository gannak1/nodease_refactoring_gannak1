from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.shared.domain.workflow_graph import MAX_WORKFLOW_GRAPH_NESTING_DEPTH
from apps.shared.services.workflow_node_catalog import (
    node_definition,
    node_output_keys,
    node_parameter_definitions,
    node_parameter_is_configured,
    validate_node_parameter_value,
)

SelectorKeys = frozenset[str] | None


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

    if not isinstance(graph, dict):
        return issues

    pending: list[
        tuple[dict[str, Any], int, dict[str, SelectorKeys], str | None]
    ] = [(graph, 0, {}, None)]
    while pending:
        current, depth, inherited_sources, owner_loop_id = pending.pop()
        if depth > MAX_WORKFLOW_GRAPH_NESTING_DEPTH:
            issues.append(
                WorkflowConfigurationIssue(
                    node_id=owner_loop_id or "",
                    node_type="loopNode",
                    missing_parameters=("subGraph",),
                )
            )
            continue

        nodes = [
            node
            for node in current.get("nodes") or []
            if isinstance(node, dict)
        ]
        node_by_id = {
            str(node.get("id")): node for node in nodes if node.get("id")
        }

        local_sources: dict[str, SelectorKeys] = {
            node_id: frozenset(
                str(key)
                for key in node_output_keys(
                    str(node.get("type") or ""),
                    node.get("data") if isinstance(node.get("data"), dict) else {},
                )
            )
            for node_id, node in node_by_id.items()
        }

        def selector_valid(selector: Any) -> bool:
            if not isinstance(selector, list) or len(selector) < 2:
                return False
            source_id = str(selector[0])
            if source_id in local_sources:
                allowed_keys = local_sources[source_id]
            elif source_id in inherited_sources:
                allowed_keys = inherited_sources[source_id]
            else:
                return False
            return allowed_keys is None or str(selector[1]) in allowed_keys

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
                child_sources = {**inherited_sources, **local_sources}
                mappings = data.get("inputs")
                if isinstance(mappings, list):
                    for mapping in mappings:
                        if not isinstance(mapping, dict):
                            continue
                        mapping_name = mapping.get("name")
                        if isinstance(mapping_name, str) and mapping_name.strip():
                            child_sources[mapping_name] = None
                child_sources["loop"] = frozenset({"item", "index"})
                pending.append(
                    (
                        subgraph,
                        depth + 1,
                        child_sources,
                        str(node.get("id") or ""),
                    )
                )

    return issues


def enforce_workflow_configuration_preflight(
    graph: dict[str, Any] | None,
    *,
    surface: str,
) -> None:
    issues = workflow_configuration_issues(graph)
    if issues:
        raise WorkflowConfigurationPreflightError(surface, issues)
