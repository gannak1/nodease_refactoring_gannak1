from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "workflow_node_catalog.json"
)

_CONNECTION_ROLES = {"entry", "intermediate", "branch", "terminal"}
_CONNECTION_CARDINALITIES = {"forbidden", "allowed", "required"}
_OUTGOING_HANDLE_POLICIES = {"standard", "condition_cases", "unrestricted"}
_PARAMETER_INPUT_TYPES = {
    "boolean",
    "code",
    "credential_ref",
    "json",
    "number",
    "resource_ref",
    "select",
    "text",
    "textarea",
    "variable_selector",
}
_DEFER_POLICIES = {"forbidden", "allow_unresolved"}
_PARAMETER_SENSITIVITIES = {"safe", "reference_only", "secret_forbidden"}
_OUTPUT_MODES = {"static", "parameter_names"}


@dataclass(frozen=True)
class WorkflowConnectionPolicyIssue:
    code: str
    edge_id: str | None
    source_node_id: str | None
    target_node_id: str | None


@lru_cache(maxsize=1)
def load_workflow_node_catalog() -> dict[str, Any]:
    catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    validate_workflow_node_catalog(catalog)
    return catalog


def validate_workflow_node_catalog(catalog: dict[str, Any]) -> None:
    nodes = catalog.get("nodes")
    if catalog.get("version") != 3 or not isinstance(nodes, list):
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
        parameters = node.get("parameters")
        if not isinstance(parameters, list):
            raise RuntimeError("Workflow node catalog is missing parameter definitions")
        parameter_keys = [
            str(parameter.get("key") or "")
            for parameter in parameters
            if isinstance(parameter, dict)
        ]
        if len(parameter_keys) != len(parameters) or any(
            not key for key in parameter_keys
        ):
            raise RuntimeError("Workflow node catalog has an invalid parameter key")
        if len(parameter_keys) != len(set(parameter_keys)):
            raise RuntimeError("Workflow node catalog has duplicate parameter keys")
        required_configuration = node.get("required_configuration") or []
        if not isinstance(required_configuration, list) or not set(
            map(str, required_configuration)
        ).issubset(set(parameter_keys)):
            raise RuntimeError(
                "Workflow node catalog required configuration has no parameter"
            )
        for parameter in parameters:
            if parameter.get("input_type") not in _PARAMETER_INPUT_TYPES:
                raise RuntimeError("Workflow node catalog has an invalid input type")
            if not isinstance(parameter.get("required"), bool):
                raise RuntimeError("Workflow node catalog parameter required is invalid")
            if (
                "agent_builder_task" in parameter
                and not isinstance(parameter["agent_builder_task"], bool)
            ):
                raise RuntimeError(
                    "Workflow node catalog agent builder task flag is invalid"
                )
            if parameter.get("defer_policy", "forbidden") not in _DEFER_POLICIES:
                raise RuntimeError("Workflow node catalog has an invalid defer policy")
            if parameter.get("sensitivity", "safe") not in _PARAMETER_SENSITIVITIES:
                raise RuntimeError("Workflow node catalog parameter sensitivity is invalid")
            validation = parameter.get("validation", {})
            if not isinstance(validation, dict):
                raise RuntimeError("Workflow node catalog parameter validation is invalid")
        outputs = node.get("outputs")
        if not isinstance(outputs, list):
            raise RuntimeError("Workflow node catalog is missing output contracts")
        output_capabilities: set[str] = set()
        for output in outputs:
            if not isinstance(output, dict):
                raise RuntimeError("Workflow node catalog output contract is invalid")
            capability = str(output.get("capability") or "")
            if capability not in node.get("capabilities", []):
                raise RuntimeError("Workflow node catalog output capability is invalid")
            if capability in output_capabilities:
                raise RuntimeError("Workflow node catalog has duplicate output contracts")
            output_capabilities.add(capability)
            mode = output.get("mode")
            if mode not in _OUTPUT_MODES:
                raise RuntimeError("Workflow node catalog output mode is invalid")
            if mode == "static" and not all(
                isinstance(key, str) and key for key in output.get("keys", [])
            ):
                raise RuntimeError("Workflow node catalog static output keys are invalid")
            if mode == "parameter_names":
                if output.get("parameter_key") not in parameter_keys:
                    raise RuntimeError(
                        "Workflow node catalog dynamic output parameter is invalid"
                    )
                if not isinstance(output.get("name_key"), str):
                    raise RuntimeError(
                        "Workflow node catalog dynamic output name key is invalid"
                    )
        if set(node.get("capabilities") or []) != output_capabilities:
            raise RuntimeError("Workflow node catalog is missing capability outputs")


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


def node_side_effect_mapping():
    return MappingProxyType(
        {
            str(node["node_type"]): str(node.get("side_effect") or "external_write")
            for node in load_workflow_node_catalog()["nodes"]
        }
    )


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


def node_parameter_definitions(node_type: str) -> list[dict[str, Any]]:
    definition = node_definition(node_type)
    if definition is None:
        return []
    return [
        {
            **dict(parameter),
            "defer_policy": parameter.get("defer_policy", "forbidden"),
            "agent_builder_task": parameter.get("agent_builder_task", True),
            "sensitivity": parameter.get(
                "sensitivity",
                "reference_only"
                if parameter.get("input_type") in {"resource_ref", "credential_ref"}
                else "safe",
            ),
            "validation": dict(parameter.get("validation") or {}),
        }
        for parameter in definition.get("parameters") or []
        if isinstance(parameter, dict)
    ]


def parameter_definition(node_type: str, parameter_key: str) -> dict[str, Any] | None:
    return next(
        (
            parameter
            for parameter in node_parameter_definitions(node_type)
            if str(parameter.get("key")) == parameter_key
        ),
        None,
    )


def validate_node_parameter_value(
    node_type: str,
    parameter_key: str,
    value: Any,
) -> list[str]:
    parameter = parameter_definition(node_type, parameter_key)
    if parameter is None:
        return ["unknown_parameter"]
    input_type = str(parameter.get("input_type") or "")
    validation = dict(parameter.get("validation") or {})
    if value is None:
        return ["required"] if parameter.get("required") else []
    if input_type in {"text", "textarea", "code"}:
        if not isinstance(value, str):
            return ["invalid_type"]
        if len(value) < int(validation.get("min_length", 0)):
            return ["too_short"]
        if len(value) > int(validation.get("max_length", 1_000_000)):
            return ["too_long"]
        pattern = validation.get("pattern")
        if pattern and re.fullmatch(str(pattern), value) is None:
            return ["pattern_mismatch"]
    elif input_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return ["invalid_type"]
        if "min" in validation and value < validation["min"]:
            return ["below_minimum"]
        if "max" in validation and value > validation["max"]:
            return ["above_maximum"]
    elif input_type == "boolean" and not isinstance(value, bool):
        return ["invalid_type"]
    options = validation.get("options")
    if isinstance(options, list) and value not in options:
        return ["option_not_allowed"]
    return []


def capability_output_contract(capability: str) -> dict[str, Any] | None:
    for node in load_workflow_node_catalog()["nodes"]:
        for output in node.get("outputs") or []:
            if output.get("capability") == capability:
                return dict(output)
    return None


def capability_output_keys(
    capability: str,
    node_data: dict[str, Any] | None,
) -> list[str]:
    contract = capability_output_contract(capability)
    if contract is None:
        return []
    if contract.get("mode") == "static":
        return list(dict.fromkeys(str(key) for key in contract.get("keys") or []))

    data = node_data if isinstance(node_data, dict) else {}
    values = data.get(str(contract.get("parameter_key") or ""))
    if not isinstance(values, list):
        return []
    name_key = str(contract.get("name_key") or "")
    return list(
        dict.fromkeys(
            str(item[name_key])
            for item in values
            if isinstance(item, dict) and item.get(name_key)
        )
    )


def node_output_keys(
    node_type: str,
    node_data: dict[str, Any] | None,
) -> list[str]:
    definition = node_definition(node_type)
    if definition is None:
        return []
    return list(
        dict.fromkeys(
            key
            for capability in definition.get("capabilities") or []
            for key in capability_output_keys(str(capability), node_data)
        )
    )


def classify_catalog_version(catalog_version: Any) -> str:
    return "current" if catalog_version == 3 else "legacy_stale"


def _configuration_value_is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def node_parameter_is_applicable(
    node_type: str,
    parameter_key: str,
    node_data: dict[str, Any] | None,
) -> bool:
    data = node_data if isinstance(node_data, dict) else {}
    return not (
        node_type == "slackPostNode"
        and parameter_key == "channel"
        and data.get("slackMode") == "webhook"
    )


def node_required_configuration(
    node_type: str,
    node_data: dict[str, Any] | None,
) -> list[str]:
    definition = node_definition(node_type)
    if definition is None:
        return []
    return [
        str(key)
        for key in definition.get("required_configuration") or []
        if node_parameter_is_applicable(node_type, str(key), node_data)
    ]


def node_parameter_is_configured(
    node_type: str,
    parameter_key: str,
    node_data: dict[str, Any] | None,
) -> bool:
    data = node_data if isinstance(node_data, dict) else {}
    if not node_parameter_is_applicable(node_type, parameter_key, data):
        return True
    if node_type == "githubNode" and parameter_key == "credential":
        return _configuration_value_is_present(data.get("credential_id"))
    if node_type == "slackPostNode" and parameter_key == "credential":
        return _configuration_value_is_present(data.get("credential_id"))
    if node_type == "slackPostNode" and parameter_key == "channel":
        return _configuration_value_is_present(data.get("channel"))
    return _configuration_value_is_present(data.get(parameter_key))


def apply_node_parameter_value(
    node_type: str,
    parameter_key: str,
    node_data: dict[str, Any],
    value: Any,
) -> dict[str, Any]:
    data = copy.deepcopy(node_data)
    if node_type in {"githubNode", "slackPostNode"} and parameter_key == "credential":
        data.pop("api_token", None)
        data.pop("authConfig", None)
        data.pop("url", None)
        data["credential_id"] = copy.deepcopy(value)
        data["configuration_state"] = "resolved" if value else "unresolved"
        return data
    data[parameter_key] = copy.deepcopy(value)
    return data


def derive_node_configuration_state(
    node_type: str, node_data: dict[str, Any] | None
) -> str:
    definition = node_definition(node_type)
    if definition is None:
        return "unresolved"
    data = node_data if isinstance(node_data, dict) else {}
    deferred = {
        str(key)
        for key in data.get("_deferred_parameters", [])
        if isinstance(key, str)
    }
    for key in node_required_configuration(node_type, data):
        if (
            str(key) in deferred
            or not node_parameter_is_configured(node_type, str(key), data)
            or (
                node_type not in {"githubNode", "slackPostNode"}
                and validate_node_parameter_value(node_type, str(key), data.get(key))
            )
        ):
            return "unresolved"
    return "resolved"


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
            and (
                not isinstance(edge.get("sourceHandle"), str)
                or not edge.get("sourceHandle")
                or edge["sourceHandle"]
                not in _condition_source_handles(source_node)
            )
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
