from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from apps.shared.schemas.agent_builder import (
    AgentBuilderParameterGroup,
    AgentBuilderParameterGuidanceHint,
    AgentBuilderParameterTask,
)
from apps.shared.services.workflow_node_catalog import (
    apply_node_parameter_value,
    derive_node_configuration_state,
    node_parameter_definitions,
    node_parameter_is_applicable,
    node_parameter_is_configured,
    parameter_definition,
    validate_node_parameter_value,
)
from apps.shared.services.tracing.policy import TracePolicyService
from apps.shared.services.tracing.redaction import TraceRedactionService
from apps.gateway.application.agent_builder.parameter_suggestions import (
    ParameterSuggestionError,
    ParameterSuggestionResolver,
)


class ParameterTaskConflict(ValueError):
    pass


class ParameterTaskSafetyError(ValueError):
    pass


@dataclass(frozen=True)
class ParameterTaskPlan:
    group_id: UUID
    graph: dict[str, Any]
    tasks: list[AgentBuilderParameterTask]


@dataclass(frozen=True)
class PreparedParameterDecision:
    operation_id: UUID
    task_id: UUID
    action: Literal["set", "confirm", "defer", "skip", "previous"]
    expected_task_version: int
    awaiting_persistence_ack: bool
    graph_data_patch: dict[str, Any] | None


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def canonical_parameter_value_fingerprint(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ParameterTaskConflict("parameter value is not canonical") from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_node_parameter_value(
    node_type: str,
    parameter_key: str,
    node_data: dict[str, Any],
) -> tuple[bool, Any]:
    if parameter_key in node_data:
        return True, node_data[parameter_key]
    if node_type == "githubNode" and parameter_key == "credential":
        return ("credential_id" in node_data), node_data.get("credential_id")
    if node_type == "slackPostNode" and parameter_key == "credential":
        return ("credential_id" in node_data), node_data.get("credential_id")
    if node_type == "slackPostNode" and parameter_key == "channel":
        return ("channel" in node_data), node_data.get("channel")
    return False, None


def recommendation_matches_canonical_graph(
    task: AgentBuilderParameterTask,
    graph: dict[str, Any] | None,
) -> bool:
    if task.recommendation_fingerprint is None:
        return False
    node = next(
        (
            item
            for item in (graph or {}).get("nodes") or []
            if isinstance(item, dict)
            and str(item.get("id")) == task.node_id
            and str(item.get("type") or "") == task.node_type
        ),
        None,
    )
    data = node.get("data") if isinstance(node, dict) else None
    if not isinstance(data, dict):
        return False
    found, value = _canonical_node_parameter_value(
        task.node_type,
        task.parameter_key,
        data,
    )
    return found and (
        canonical_parameter_value_fingerprint(value)
        == task.recommendation_fingerprint
    )


def _deterministic_group_id(step_node_ids: dict[str, str]) -> UUID:
    identity = ";".join(f"{step}:{node}" for step, node in step_node_ids.items())
    return uuid5(NAMESPACE_URL, f"agent-builder-parameter-group:{identity}")


def _explicit_value_is_allowed(
    node_type: str,
    parameter: dict[str, Any],
    value: Any,
) -> bool:
    if parameter.get("sensitivity") != "safe":
        return False
    if parameter.get("input_type") in {"credential_ref", "resource_ref"}:
        return False
    redaction = TraceRedactionService.redact_payload(
        value,
        policy=TracePolicyService.fail_closed_redaction_policy(),
        payload_kind="agent_builder_explicit_parameter",
    )
    if redaction.failed or redaction.secret_detected:
        return False
    return not validate_node_parameter_value(
        node_type,
        str(parameter["key"]),
        value,
    )


def validate_direct_set_value(
    *,
    node_type: str,
    parameter_key: str,
    task_input_type: str,
    value: Any,
) -> list[str]:
    """Validate direct-edit values before they can become a graph patch."""
    parameter = parameter_definition(node_type, parameter_key)
    if parameter is None or parameter.get("input_type") != task_input_type:
        raise ParameterTaskSafetyError("catalog parameter mismatch")
    if (
        parameter.get("sensitivity") == "reference_only"
        and task_input_type not in {"credential_ref", "resource_ref"}
    ):
        raise ParameterTaskSafetyError("reference-only parameter mismatch")

    redaction = TraceRedactionService.redact_payload(
        value,
        policy=TracePolicyService.fail_closed_redaction_policy(),
        payload_kind="agent_builder_direct_parameter",
    )
    if redaction.failed or redaction.secret_detected:
        raise ParameterTaskSafetyError("unsafe parameter value")

    return validate_node_parameter_value(node_type, parameter_key, value)


class ParameterTaskPlanner:
    def plan(
        self,
        *,
        graph: dict[str, Any],
        step_node_ids: dict[str, str],
        explicit_values: dict[tuple[str, str], Any],
        upstream_candidates: dict[tuple[str, str], list[list[str]]],
        guidance_hints: list[AgentBuilderParameterGuidanceHint],
        step_purposes: dict[str, str] | None = None,
        group_id: UUID | None = None,
        externally_managed_parameters: set[tuple[str, str]] | None = None,
        base_node_ids: set[str] | None = None,
    ) -> ParameterTaskPlan:
        materialized = copy.deepcopy(graph)
        node_by_id = {
            str(node.get("id")): node
            for node in materialized.get("nodes") or []
            if isinstance(node, dict) and node.get("id")
        }
        group_id = group_id or _deterministic_group_id(step_node_ids)
        hints = {
            (hint.step_id, hint.parameter_key): hint for hint in guidance_hints
        }
        step_purposes = step_purposes or {}
        externally_managed_parameters = externally_managed_parameters or set()
        base_node_ids = base_node_ids or set(node_by_id)
        tasks: list[AgentBuilderParameterTask] = []
        actionable_indexes: list[int] = []

        for step_id, node_id in step_node_ids.items():
            node = node_by_id.get(node_id)
            if node is None:
                raise ParameterTaskConflict("step node is missing")
            node_type = str(node.get("type") or "")
            data = node.setdefault("data", {})
            if not isinstance(data, dict):
                raise ParameterTaskConflict("node data is invalid")
            for parameter in node_parameter_definitions(node_type):
                parameter_key = str(parameter["key"])
                if not node_parameter_is_applicable(
                    node_type, parameter_key, data
                ):
                    continue
                if parameter.get("agent_builder_task") is False:
                    continue
                identity = (step_id, parameter_key)
                if identity in externally_managed_parameters:
                    continue
                source = None
                if identity in explicit_values and _explicit_value_is_allowed(
                    node_type,
                    parameter,
                    explicit_values[identity],
                ):
                    node["data"] = apply_node_parameter_value(
                        node_type,
                        parameter_key,
                        data,
                        explicit_values[identity],
                    )
                    data = node["data"]
                    source = "user_request"
                elif (
                    str(node_id) in base_node_ids
                    and node_parameter_is_configured(node_type, parameter_key, data)
                ):
                    source = "existing_graph"
                else:
                    candidates = upstream_candidates.get(identity) or []
                    if (
                        len(candidates) == 1
                        and node_parameter_is_configured(
                            node_type, parameter_key, data
                        )
                        and data.get(parameter_key) == candidates[0]
                    ):
                        source = "upstream_selector"
                    elif len(candidates) == 1:
                        node["data"] = apply_node_parameter_value(
                            node_type,
                            parameter_key,
                            data,
                            candidates[0],
                        )
                        data = node["data"]
                        source = "upstream_selector"
                    elif "default" in parameter:
                        node["data"] = apply_node_parameter_value(
                            node_type,
                            parameter_key,
                            data,
                            parameter["default"],
                        )
                        data = node["data"]
                        source = "catalog_default"
                hint = hints.get(identity)
                label = str(parameter["label"])
                status = "pending"
                editor_credential_setup = False
                recommendation_fingerprint = None
                if source is not None:
                    found, recommendation_value = _canonical_node_parameter_value(
                        node_type,
                        parameter_key,
                        data,
                    )
                    if not found:
                        raise ParameterTaskConflict(
                            "automatic parameter value is missing"
                        )
                    recommendation_fingerprint = (
                        canonical_parameter_value_fingerprint(recommendation_value)
                    )
                task = AgentBuilderParameterTask(
                    task_id=uuid5(
                        NAMESPACE_URL,
                        f"{group_id}:{node_id}:{parameter_key}",
                    ),
                    group_id=group_id,
                    step_id=step_id,
                    node_id=node_id,
                    node_type=node_type,
                    parameter_key=parameter_key,
                    label=label,
                    input_type=str(parameter["input_type"]),
                    required=bool(parameter["required"]),
                    defer_policy=str(parameter.get("defer_policy") or "forbidden"),
                    status=status,
                    task_version=1,
                    stable_order=len(tasks),
                    resolution_source=source,
                    recommendation_fingerprint=recommendation_fingerprint,
                    reason=(
                        "Credential은 저장 후 노드 설정에서 연결해야 합니다."
                        if editor_credential_setup
                        else hint.reason
                        if hint is not None
                        else f"{label} 설정이 필요합니다."
                    ),
                    input_guidance=(
                        "현재 Agent Builder에서는 credential 값을 수집하지 않습니다."
                        if editor_credential_setup
                        else hint.input_guidance
                        if hint is not None
                        else f"{label} 값을 입력하세요."
                    ),
                    node_label=str(data.get("title") or node_id),
                    node_purpose=str(step_purposes.get(step_id) or ""),
                    validation=copy.deepcopy(parameter.get("validation") or {}),
                    sensitivity=str(parameter.get("sensitivity") or "safe"),
                )
                tasks.append(task)
                if not editor_credential_setup:
                    actionable_indexes.append(len(tasks) - 1)

        if actionable_indexes:
            first = actionable_indexes[0]
            tasks[first] = tasks[first].model_copy(update={"status": "active"})
        configuration_by_node = {
            node_id: derive_node_configuration_state(
                str(node.get("type") or ""),
                node.get("data") if isinstance(node.get("data"), dict) else {},
            )
            for node_id, node in node_by_id.items()
        }
        tasks = [
            task.model_copy(
                update={
                    "configuration_state": configuration_by_node.get(
                        task.node_id,
                        "unresolved",
                    )
                }
            )
            for task in tasks
        ]
        return ParameterTaskPlan(group_id=group_id, graph=materialized, tasks=tasks)


def refresh_parameter_group_configuration(
    group: AgentBuilderParameterGroup | None,
    graph: dict[str, Any] | None,
) -> AgentBuilderParameterGroup | None:
    if group is None:
        return None
    node_by_id = {
        str(node.get("id")): node
        for node in (graph or {}).get("nodes") or []
        if isinstance(node, dict) and node.get("id")
    }
    tasks = []
    for task in group.tasks:
        node = node_by_id.get(task.node_id)
        state = "unresolved"
        if node is not None:
            state = derive_node_configuration_state(
                str(node.get("type") or ""),
                node.get("data") if isinstance(node.get("data"), dict) else {},
            )
        tasks.append(task.model_copy(update={"configuration_state": state}))
    return group.model_copy(update={"tasks": tasks})


def remove_direct_edit_knowledge_parameter_tasks(
    group: AgentBuilderParameterGroup | None,
) -> AgentBuilderParameterGroup | None:
    """Remove persisted generic KB tasks superseded by direct knowledge resolution."""
    if group is None:
        return None
    if group.status in {"pending_save", "pending_ack"}:
        return group
    tasks = [
        task
        for task in group.tasks
        if not (task.node_type == "llmNode" and task.parameter_key == "knowledgeBases")
    ]
    if len(tasks) == len(group.tasks):
        return group

    normalized = group.model_copy(update={"tasks": tasks})
    if group.status != "active" or any(task.status == "active" for task in tasks):
        return normalized

    terminal_statuses = {"completed", "skipped", "deferred"}
    if all(task.status in terminal_statuses for task in tasks):
        return normalized.model_copy(update={"status": "completed"})

    next_pending_index = next(
        (
            index
            for index, task in sorted(
                enumerate(tasks), key=lambda item: item[1].stable_order
            )
            if task.status == "pending"
        ),
        None,
    )
    if next_pending_index is None:
        return normalized
    tasks[next_pending_index] = tasks[next_pending_index].model_copy(
        update={"status": "active"}
    )
    return normalized.model_copy(update={"tasks": tasks})


def remove_direct_edit_external_credential_tasks(
    group: AgentBuilderParameterGroup | None,
) -> AgentBuilderParameterGroup | None:
    """Drop legacy Slack/GitHub credential tasks from direct-edit sessions."""
    if group is None or group.status in {"pending_save", "pending_ack"}:
        return group
    tasks = [
        task
        for task in group.tasks
        if not (
            task.input_type == "credential_ref"
            and task.node_type in {"slackPostNode", "githubNode"}
        )
    ]
    if len(tasks) == len(group.tasks):
        return group

    normalized = group.model_copy(update={"tasks": tasks})
    if group.status != "active" or any(task.status == "active" for task in tasks):
        return normalized

    terminal_statuses = {"completed", "skipped", "deferred"}
    if all(task.status in terminal_statuses for task in tasks):
        return normalized.model_copy(update={"status": "completed"})

    next_pending_index = next(
        (
            index
            for index, task in sorted(
                enumerate(tasks), key=lambda item: item[1].stable_order
            )
            if task.status == "pending"
        ),
        None,
    )
    if next_pending_index is None:
        return normalized
    tasks[next_pending_index] = tasks[next_pending_index].model_copy(
        update={"status": "active"}
    )
    return normalized.model_copy(update={"tasks": tasks})


def refresh_parameter_group_suggestions(
    group: AgentBuilderParameterGroup | None,
    graph: dict[str, Any] | None,
) -> AgentBuilderParameterGroup | None:
    if group is None:
        return None
    canonical_graph = graph or {"nodes": [], "edges": []}
    node_by_id = {
        str(node.get("id")): node
        for node in canonical_graph.get("nodes") or []
        if isinstance(node, dict) and node.get("id")
    }
    resolver = ParameterSuggestionResolver()
    tasks = [task.model_copy(deep=True) for task in group.tasks]
    invalid_indexes: list[int] = []
    for index, task in enumerate(tasks):
        if task.input_type != "variable_selector":
            continue
        try:
            suggestions = resolver.resolve(
                graph=canonical_graph,
                target_node_id=task.node_id,
                parameter_key=task.parameter_key,
            )
        except ParameterSuggestionError:
            suggestions = []
        updated = task.model_copy(update={"suggestions": suggestions})
        node = node_by_id.get(task.node_id)
        data = node.get("data") if isinstance(node, dict) else {}
        selected = data.get(task.parameter_key) if isinstance(data, dict) else None
        valid_selectors = [item.value_selector for item in suggestions]
        if (
            task.status == "completed"
            and task.resolution_source == "upstream_selector"
            and selected not in valid_selectors
        ):
            updated = updated.model_copy(
                update={
                    "status": "invalid",
                    "task_version": task.task_version + 1,
                }
            )
            invalid_indexes.append(index)
        tasks[index] = updated

    if invalid_indexes:
        first_invalid = invalid_indexes[0]
        tasks = [
            task.model_copy(update={"status": "pending"})
            if task.status == "active" and index != first_invalid
            else task
            for index, task in enumerate(tasks)
        ]
        tasks[first_invalid] = tasks[first_invalid].model_copy(
            update={"status": "active"}
        )
        return group.model_copy(update={"status": "active", "tasks": tasks})
    return group.model_copy(update={"tasks": tasks})


def _task_index(tasks: list[AgentBuilderParameterTask], task_id: UUID) -> int:
    for index, task in enumerate(tasks):
        if task.task_id == task_id:
            return index
    raise ParameterTaskConflict("task is missing")


def prepare_task_decision(
    *,
    tasks: list[AgentBuilderParameterTask],
    task_id: UUID,
    operation_id: UUID,
    expected_task_version: int,
    action: Literal["set", "confirm", "defer", "skip", "previous"],
    value: Any,
) -> PreparedParameterDecision:
    index = _task_index(tasks, task_id)
    task = tasks[index]
    if task.task_version != expected_task_version:
        raise ParameterTaskConflict("task version conflict")
    if action == "set":
        if task.status not in {"active", "completed", "skipped", "deferred", "invalid"}:
            raise ParameterTaskConflict("task is not settable")
        if value is None:
            raise ParameterTaskConflict("set value is required")
        return PreparedParameterDecision(
            operation_id=operation_id,
            task_id=task_id,
            action=action,
            expected_task_version=expected_task_version,
            awaiting_persistence_ack=True,
            graph_data_patch={task.parameter_key: copy.deepcopy(value)},
        )
    if action == "previous":
        if task.status not in {"active", "completed", "skipped", "deferred"}:
            raise ParameterTaskConflict("task is not reopenable")
        previous_reopenable_task_id(tasks, task_id)
        return PreparedParameterDecision(
            operation_id=operation_id,
            task_id=task_id,
            action=action,
            expected_task_version=expected_task_version,
            awaiting_persistence_ack=False,
            graph_data_patch=None,
        )
    if task.status != "active":
        raise ParameterTaskConflict("task is not active")
    if action == "confirm":
        if task.resolution_source is None:
            raise ParameterTaskConflict("task has no automatic resolution")
        return PreparedParameterDecision(
            operation_id=operation_id,
            task_id=task_id,
            action=action,
            expected_task_version=expected_task_version,
            awaiting_persistence_ack=False,
            graph_data_patch=None,
        )
    if action == "defer":
        if task.defer_policy != "allow_unresolved":
            raise ParameterTaskConflict("defer is forbidden")
        return PreparedParameterDecision(
            operation_id=operation_id,
            task_id=task_id,
            action=action,
            expected_task_version=expected_task_version,
            awaiting_persistence_ack=True,
            graph_data_patch={"_deferred_parameter": task.parameter_key},
        )
    if action == "skip":
        if task.required:
            raise ParameterTaskConflict("required task cannot be skipped")
        return PreparedParameterDecision(
            operation_id=operation_id,
            task_id=task_id,
            action=action,
            expected_task_version=expected_task_version,
            awaiting_persistence_ack=False,
            graph_data_patch=None,
        )
    raise ParameterTaskConflict("invalid decision")


def _activate_next(
    tasks: list[AgentBuilderParameterTask], completed_index: int
) -> list[AgentBuilderParameterTask]:
    if any(task.status == "active" for task in tasks):
        return tasks
    for index in range(completed_index + 1, len(tasks)):
        if tasks[index].status == "pending":
            tasks[index] = tasks[index].model_copy(update={"status": "active"})
            break
    return tasks


def previous_reopenable_task_id(
    tasks: list[AgentBuilderParameterTask],
    current_task_id: UUID,
) -> UUID:
    """Resolve UI navigation without changing canonical task completion state."""
    index = _task_index(tasks, current_task_id)
    stable_indexes = sorted(
        range(len(tasks)),
        key=lambda task_index: tasks[task_index].stable_order,
    )
    stable_position = stable_indexes.index(index)
    for previous_index in reversed(stable_indexes[:stable_position]):
        previous = tasks[previous_index]
        if previous.status in {"completed", "skipped", "deferred"}:
            return previous.task_id
    raise ParameterTaskConflict("previous task is missing")


def acknowledge_parameter_binding(
    tasks: list[AgentBuilderParameterTask],
    *,
    affected_node_ids: set[str],
    parameter_key: str,
) -> list[AgentBuilderParameterTask]:
    updated = [task.model_copy(deep=True) for task in tasks]
    changed = False
    for index, task in enumerate(updated):
        if (
            task.node_id not in affected_node_ids
            or task.parameter_key != parameter_key
            or task.status in {"completed", "canceled"}
        ):
            continue
        updated[index] = task.model_copy(
            update={
                "status": "completed",
                "task_version": task.task_version + 1,
                "resolution_source": "user_request",
            }
        )
        changed = True
    if not changed or any(task.status == "active" for task in updated):
        return updated
    next_index = next(
        (
            index
            for index, task in sorted(
                enumerate(updated), key=lambda item: item[1].stable_order
            )
            if task.status == "pending"
        ),
        None,
    )
    if next_index is not None:
        updated[next_index] = updated[next_index].model_copy(
            update={"status": "active"}
        )
    return updated


def apply_local_task_decision(
    tasks: list[AgentBuilderParameterTask],
    decision: PreparedParameterDecision,
) -> list[AgentBuilderParameterTask]:
    if decision.awaiting_persistence_ack:
        raise ParameterTaskConflict("persistence acknowledgement is required")
    updated = [task.model_copy(deep=True) for task in tasks]
    index = _task_index(updated, decision.task_id)
    task = updated[index]
    if decision.action == "skip":
        updated[index] = task.model_copy(
            update={"status": "skipped", "task_version": task.task_version + 1}
        )
        return _activate_next(updated, index)
    if decision.action == "confirm":
        if task.resolution_source is None:
            raise ParameterTaskConflict("task has no automatic resolution")
        updated[index] = task.model_copy(
            update={"status": "completed", "task_version": task.task_version + 1}
        )
        return _activate_next(updated, index)
    if decision.action == "previous":
        previous_reopenable_task_id(updated, decision.task_id)
        return updated
    raise ParameterTaskConflict("decision is not local")


def acknowledge_task_decision(
    tasks: list[AgentBuilderParameterTask],
    decision: PreparedParameterDecision,
) -> list[AgentBuilderParameterTask]:
    if not decision.awaiting_persistence_ack:
        raise ParameterTaskConflict("decision does not require acknowledgement")
    updated = [task.model_copy(deep=True) for task in tasks]
    index = _task_index(updated, decision.task_id)
    task = updated[index]
    if task.task_version != decision.expected_task_version:
        raise ParameterTaskConflict("task version conflict")
    status = "deferred" if decision.action == "defer" else "completed"
    resolution_source = task.resolution_source
    if decision.action == "set":
        resolution_source = "user_request"
    updated[index] = task.model_copy(
        update={
            "status": status,
            "task_version": task.task_version + 1,
            "resolution_source": resolution_source,
            "recommendation_fingerprint": (
                None
                if decision.action == "set"
                else task.recommendation_fingerprint
            ),
        }
    )
    return _activate_next(updated, index)


def cancel_parameter_group(
    group: AgentBuilderParameterGroup,
    *,
    expected_task_id: UUID,
    expected_task_version: int,
) -> AgentBuilderParameterGroup:
    active = next((task for task in group.tasks if task.status == "active"), None)
    if active is None or active.task_id != expected_task_id:
        raise ParameterTaskConflict("active task conflict")
    if active.task_version != expected_task_version:
        raise ParameterTaskConflict("task version conflict")
    tasks = [
        task
        if task.status in {"completed", "skipped", "deferred", "canceled"}
        else task.model_copy(
            update={"status": "canceled", "task_version": task.task_version + 1}
        )
        for task in group.tasks
    ]
    return group.model_copy(update={"status": "canceled", "tasks": tasks})
