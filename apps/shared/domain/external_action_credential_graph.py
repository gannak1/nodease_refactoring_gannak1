"""Workflow graph boundary for external-action credential references.

The graph is a durable, broadly replicated object.  It may therefore contain
only a provider-neutral credential identifier, never a provider secret or a
credential-shaped configuration object.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Iterable, Mapping
from typing import Any


EXTERNAL_ACTION_CREDENTIAL_GRAPH_INVALID = (
    "external_action_credential.graph_configuration_invalid"
)
EXTERNAL_ACTION_CREDENTIAL_LEGACY_SECRET_REQUIRES_MIGRATION = (
    "external_action_credential.legacy_secret_requires_migration"
)

# GitHub node data is persisted in workflow graphs and deployment snapshots.
# Keep this deliberately narrow so a future UI field is reviewed before it can
# become another durable storage path for credential-like material.
GITHUB_NODE_ALLOWED_FIELDS = frozenset(
    {
        "title",
        "description",
        "parameters",
        "action",
        "credential_id",
        "configuration_state",
        "repo_owner",
        "repo_name",
        "pr_number",
        "comment_body",
        "referenced_variables",
    }
)


class ExternalActionCredentialGraphBoundaryError(ValueError):
    def __init__(
        self,
        reason_code: str = EXTERNAL_ACTION_CREDENTIAL_GRAPH_INVALID,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def validate_github_credential_graph_boundary(
    nodes: Iterable[Any],
    *,
    require_resolved: bool = False,
) -> None:
    """Reject direct GitHub secrets and validate opaque credential references."""

    for node in _iter_nodes(nodes):
        node_type, node_id, data = _node_parts(node)
        if node_type != "githubNode":
            continue
        if not node_id or not isinstance(data, Mapping):
            raise ExternalActionCredentialGraphBoundaryError()
        _validate_github_data(data, require_resolved=require_resolved)


def redact_external_action_credential_graph(graph: Any) -> Any:
    """Return a deep-copied graph with deprecated direct credential fields removed.

    This is deliberately applied to old persisted graphs before they cross a
    response, copy, or execution boundary.  The remaining graph is unresolved
    and therefore cannot silently continue using a legacy secret.
    """

    if not isinstance(graph, Mapping):
        return graph
    result = copy.deepcopy(dict(graph))
    _redact_nodes(result.get("nodes"))
    return result


def _redact_nodes(nodes: Any) -> None:
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "")
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        if node_type == "slackPostNode":
            for field_name in (
                "url",
                "authConfig",
                "token",
                "headers",
                "body",
                "authType",
                "method",
                "timeout",
            ):
                data.pop(field_name, None)
            if data.get("parameters") not in (None, {}):
                data["parameters"] = {}
            if not data.get("credential_id"):
                data["configuration_state"] = "unresolved"
        elif node_type == "githubNode":
            for field_name in set(data).difference(GITHUB_NODE_ALLOWED_FIELDS):
                data.pop(field_name, None)
            if data.get("parameters") not in (None, {}):
                data["parameters"] = {}
            if not data.get("credential_id"):
                data["configuration_state"] = "unresolved"

        subgraph = data.get("subGraph")
        if isinstance(subgraph, dict):
            _redact_nodes(subgraph.get("nodes"))


def _iter_nodes(nodes: Iterable[Any]) -> Iterable[Any]:
    pending = list(nodes)
    while pending:
        node = pending.pop()
        yield node
        _, _, data = _node_parts(node)
        if not isinstance(data, Mapping):
            continue
        subgraph = data.get("subGraph")
        nested_nodes = subgraph.get("nodes") if isinstance(subgraph, Mapping) else None
        if isinstance(nested_nodes, list):
            pending.extend(nested_nodes)


def _node_parts(node: Any) -> tuple[str, str, Any]:
    if isinstance(node, Mapping):
        return str(node.get("type") or ""), str(node.get("id") or ""), node.get("data")
    return (
        str(getattr(node, "type", "") or ""),
        str(getattr(node, "id", "") or ""),
        getattr(node, "data", None),
    )


def _validate_github_data(data: Mapping[str, Any], *, require_resolved: bool) -> None:
    if "api_token" in data or "token" in data or "authConfig" in data:
        raise ExternalActionCredentialGraphBoundaryError(
            EXTERNAL_ACTION_CREDENTIAL_LEGACY_SECRET_REQUIRES_MIGRATION
        )
    if set(data).difference(GITHUB_NODE_ALLOWED_FIELDS):
        raise ExternalActionCredentialGraphBoundaryError()
    if data.get("parameters") not in (None, {}):
        raise ExternalActionCredentialGraphBoundaryError()
    if data.get("configuration_state") not in (None, "resolved", "unresolved"):
        raise ExternalActionCredentialGraphBoundaryError()
    credential_id = data.get("credential_id")
    if credential_id is not None:
        if not isinstance(credential_id, str) or not credential_id.strip():
            raise ExternalActionCredentialGraphBoundaryError()
        try:
            uuid.UUID(credential_id)
        except (TypeError, ValueError) as exc:
            raise ExternalActionCredentialGraphBoundaryError() from exc
    if require_resolved and (
        credential_id is None or data.get("configuration_state") == "unresolved"
    ):
        raise ExternalActionCredentialGraphBoundaryError()
