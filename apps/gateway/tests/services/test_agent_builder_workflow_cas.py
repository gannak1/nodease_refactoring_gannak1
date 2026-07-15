from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from apps.gateway.adapters.db.agent_builder_repository import (
    AgentBuilderRepository,
    AgentBuilderRepositoryError,
)
from apps.gateway.application.agent_builder.graph_mutation_builder import (
    GraphMutationBuilder,
    apply_graph_operations,
)
from apps.gateway.application.agent_builder.workflow_cas import (
    WorkflowDraftCASService,
    WorkflowMutationConflict,
)
from apps.gateway.services.workflow_service import WorkflowService
from apps.shared.schemas.agent_builder import (
    AgentBuilderParameterGroup,
    AgentBuilderParameterTask,
    GraphMutationSafeEnvelope,
)
from apps.shared.schemas.workflow import WorkflowDraftRequest


def _node(node_id, node_type):
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": 0, "y": 0},
        "data": {"title": node_id},
    }


def _draft_request(payload):
    data = dict(payload)
    context = data.get("mutation_context")
    if isinstance(context, dict):
        data.setdefault("expected_graph_hash", context["expected_base_graph_hash"])
        data.setdefault("expected_updated_at", context["expected_workflow_updated_at"])
    return WorkflowDraftRequest.model_validate(data)


def _issued_mutation(now):
    base = {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}
    operations = [
        {"op": "add_node", "node": _node("start", "startNode")},
        {"op": "add_node", "node": _node("answer", "answerNode")},
        {
            "op": "add_edge",
            "edge": {"id": "e1", "source": "start", "target": "answer"},
        },
    ]
    mutation = GraphMutationBuilder().build(
        operation_id=uuid4(),
        kind="initial_graph",
        generation_mode="configure_and_generate",
        workflow_id=uuid4(),
        base_graph=base,
        expected_workflow_updated_at=now,
        operations=operations,
    )
    return base, mutation


def _request(mutation, base):
    result = apply_graph_operations(base, mutation.operations)
    return _draft_request(
        {
            **result,
            "mutation_context": {
                "operation_id": str(mutation.operation_id),
                "action": "apply",
                "expected_base_graph_hash": mutation.base_graph_hash,
                "expected_workflow_updated_at": mutation.expected_workflow_updated_at,
                "catalog_version": 3,
            },
        }
    )


def _revert_request(mutation, result_graph, now):
    return _draft_request(
        {
            **result_graph,
            "nodes": [],
            "edges": [],
            "mutation_context": {
                "operation_id": str(mutation.operation_id),
                "action": "revert",
                "expected_base_graph_hash": mutation.expected_result_graph_hash,
                "expected_workflow_updated_at": now,
                "catalog_version": 3,
            },
        }
    )


def _redo_request(mutation, result_graph, base_graph_hash, now):
    return _draft_request(
        {
            **result_graph,
            "mutation_context": {
                "operation_id": str(mutation.operation_id),
                "action": "redo",
                "expected_base_graph_hash": base_graph_hash,
                "expected_workflow_updated_at": now,
                "catalog_version": 3,
            },
        }
    )


def test_draft_save_refreshes_identity_map_before_row_lock(monkeypatch):
    now = datetime.now(timezone.utc)
    workflow = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        graph={"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}},
        features={},
        env_variables=[],
        runtime_variables=[],
        updated_at=now,
    )
    request = WorkflowDraftRequest.model_validate(
        {
            "nodes": [],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "expected_graph_hash": "0" * 64,
            "expected_updated_at": now,
        }
    )
    query = Mock()
    query.filter.return_value = query
    query.populate_existing.return_value = query
    query.with_for_update.return_value = query
    query.first.return_value = workflow
    db = Mock()
    db.query.return_value = query

    monkeypatch.setattr(WorkflowService, "validate_knowledge_references", Mock())
    monkeypatch.setattr(
        "apps.gateway.services.workflow_service.WorkflowDraftCASService.validate_expected_draft_state",
        Mock(),
    )
    monkeypatch.setattr(WorkflowService, "validate_mail_credential_references", Mock())
    db.refresh = Mock()

    WorkflowService.save_draft(db, str(workflow.id), request, user_id=str(uuid4()))

    query.populate_existing.assert_called_once_with()
    query.with_for_update.assert_called_once_with()


def test_cas_validation_returns_canonical_graph_acknowledgement():
    now = datetime.now(timezone.utc)
    base, mutation = _issued_mutation(now)
    workflow = SimpleNamespace(id=mutation.workflow_id, graph=base, updated_at=now)

    result = WorkflowDraftCASService.validate_candidate(
        workflow=workflow,
        request=_request(mutation, base),
        envelope=GraphMutationSafeEnvelope.from_mutation(mutation),
    )

    assert result.graph_hash == mutation.expected_result_graph_hash
    assert result.operation_id == mutation.operation_id
    assert all(
        node["data"]["configuration_state"] in {"resolved", "unresolved"}
        for node in result.graph["nodes"]
    )


def test_cas_candidate_ignores_react_flow_runtime_fields():
    now = datetime.now(timezone.utc)
    base, mutation = _issued_mutation(now)
    workflow = SimpleNamespace(id=mutation.workflow_id, graph=base, updated_at=now)
    candidate = _request(mutation, base).model_dump(mode="python")
    candidate["nodes"][0].update(
        {
            "measured": {"width": 240, "height": 96},
            "selected": True,
            "dragging": False,
        }
    )
    candidate["nodes"][0]["data"]["displayNumber"] = 7
    candidate["edges"][0]["selected"] = True

    result = WorkflowDraftCASService.validate_candidate(
        workflow=workflow,
        request=WorkflowDraftRequest.model_validate(candidate),
        envelope=GraphMutationSafeEnvelope.from_mutation(mutation),
    )

    assert result.graph_hash == mutation.expected_result_graph_hash
    assert all("measured" not in node for node in result.graph["nodes"])
    assert all("selected" not in node for node in result.graph["nodes"])
    assert all("dragging" not in node for node in result.graph["nodes"])
    assert all("selected" not in edge for edge in result.graph["edges"])
    assert all("displayNumber" not in node["data"] for node in result.graph["nodes"])


def test_graph_edit_hash_includes_server_derived_state_for_existing_nodes():
    now = datetime.now(timezone.utc)
    workflow_id = uuid4()
    base = {
        "nodes": [
            _node("start", "startNode"),
            _node("llm", "llmNode"),
            _node("answer", "answerNode"),
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "llm"},
            {"id": "e2", "source": "llm", "target": "answer"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    mutation = GraphMutationBuilder().build(
        operation_id=uuid4(),
        kind="graph_edit",
        generation_mode="structure_only",
        workflow_id=workflow_id,
        base_graph=base,
        expected_workflow_updated_at=now,
        operations=[
            {"op": "remove_edge", "edge_id": "e2"},
            {"op": "add_node", "node": _node("template", "templateNode")},
            {
                "op": "add_edge",
                "edge": {"id": "e3", "source": "llm", "target": "template"},
            },
            {
                "op": "add_edge",
                "edge": {"id": "e4", "source": "template", "target": "answer"},
            },
        ],
    )
    workflow = SimpleNamespace(id=workflow_id, graph=base, updated_at=now)

    result = WorkflowDraftCASService.validate_candidate(
        workflow=workflow,
        request=_request(mutation, base),
        envelope=GraphMutationSafeEnvelope.from_mutation(mutation),
    )

    assert result.graph_hash == mutation.expected_result_graph_hash
    assert all(
        node["data"]["configuration_state"] in {"resolved", "unresolved"}
        for node in result.graph["nodes"]
    )


@pytest.mark.parametrize("stale_field", ["graph", "updated_at", "result"])
def test_cas_validation_rejects_stale_or_noncanonical_candidate(stale_field):
    now = datetime.now(timezone.utc)
    base, mutation = _issued_mutation(now)
    workflow = SimpleNamespace(id=mutation.workflow_id, graph=base, updated_at=now)
    request = _request(mutation, base)
    if stale_field == "graph":
        workflow.graph = {"nodes": [_node("other", "startNode")], "edges": []}
    elif stale_field == "updated_at":
        workflow.updated_at = now + timedelta(seconds=1)
    else:
        request.nodes[0].data["title"] = "changed"

    with pytest.raises(WorkflowMutationConflict):
        WorkflowDraftCASService.validate_candidate(
            workflow=workflow,
            request=request,
            envelope=GraphMutationSafeEnvelope.from_mutation(mutation),
        )


def test_repository_persists_only_safe_envelope_and_acknowledges_idempotently():
    now = datetime.now(timezone.utc)
    _, mutation = _issued_mutation(now)
    request_row = SimpleNamespace(response_payload={})
    repository = AgentBuilderRepository()

    repository.store_envelope(
        request_row,
        GraphMutationSafeEnvelope.from_mutation(mutation),
    )
    persisted = request_row.response_payload["operation_envelopes"][0]

    assert "operations" not in persisted
    saving = repository.mark_envelope_pending_save(
        request_row,
        mutation.operation_id,
    )
    assert saving["status"] == "pending_save"
    repository.mark_envelope_saved(
        request_row,
        operation_id=mutation.operation_id,
        result_graph_hash=mutation.expected_result_graph_hash,
        workflow_updated_at=now,
    )
    first = repository.acknowledge_envelope(
        request_row,
        operation_id=mutation.operation_id,
        result_graph_hash=mutation.expected_result_graph_hash,
        workflow_updated_at=now,
    )
    second = repository.acknowledge_envelope(
        request_row,
        operation_id=mutation.operation_id,
        result_graph_hash=mutation.expected_result_graph_hash,
        workflow_updated_at=now,
    )
    assert first == second
    assert second["status"] == "acknowledged"


@pytest.mark.parametrize("status", ["blocked", "acknowledged", "reverted"])
def test_repository_rejects_save_transition_from_terminal_status(status):
    now = datetime.now(timezone.utc)
    _, mutation = _issued_mutation(now)
    request_row = SimpleNamespace(response_payload={})
    repository = AgentBuilderRepository()
    repository.store_envelope(
        request_row,
        GraphMutationSafeEnvelope.from_mutation(mutation),
    )
    envelope = repository.find_envelope(request_row, mutation.operation_id)
    repository._replace_envelope(  # noqa: SLF001
        request_row,
        mutation.operation_id,
        {**envelope, "status": status},
    )

    with pytest.raises(AgentBuilderRepositoryError, match="operation cannot be saved"):
        repository.mark_envelope_pending_save(
            request_row,
            mutation.operation_id,
        )


def test_cas_validation_rejects_blocked_operation_even_when_hashes_match():
    now = datetime.now(timezone.utc)
    base, mutation = _issued_mutation(now)
    workflow = SimpleNamespace(id=mutation.workflow_id, graph=base, updated_at=now)
    envelope = GraphMutationSafeEnvelope.from_mutation(mutation).model_copy(
        update={"status": "blocked", "blocked_reason": "operation_payload_unavailable"}
    )

    with pytest.raises(WorkflowMutationConflict, match="operation_not_applicable"):
        WorkflowDraftCASService.validate_candidate(
            workflow=workflow,
            request=_request(mutation, base),
            envelope=envelope,
        )


def test_repository_activates_pending_parameter_group_after_initial_ack():
    group_id = uuid4()
    first_task = AgentBuilderParameterTask(
        task_id=uuid4(),
        group_id=group_id,
        step_id="step_llm",
        node_id="llm",
        node_type="llmNode",
        parameter_key="model_id",
        label="LLM model",
        input_type="resource_ref",
        required=True,
        defer_policy="allow_unresolved",
        status="pending",
        task_version=1,
        stable_order=0,
        reason="model required",
        input_guidance="select a model",
    )
    second_task = first_task.model_copy(
        update={
            "task_id": uuid4(),
            "parameter_key": "prompt",
            "label": "Prompt",
            "input_type": "textarea",
            "defer_policy": "forbidden",
            "stable_order": 1,
        }
    )
    request_row = SimpleNamespace(response_payload={})
    repository = AgentBuilderRepository()
    repository.store_parameter_group(
        request_row,
        AgentBuilderParameterGroup(
            group_id=group_id,
            status="pending_ack",
            tasks=[first_task, second_task],
        ),
    )

    group = repository.activate_latest_parameter_group(request_row)

    assert group is not None
    assert group.status == "active"
    assert [task.status for task in group.tasks] == ["active", "pending"]
    assert request_row.response_payload["parameter_groups"][0]["status"] == "active"


def test_revert_validation_accepts_only_acknowledged_current_result_to_base():
    now = datetime.now(timezone.utc)
    base, mutation = _issued_mutation(now)
    result_graph = apply_graph_operations(base, mutation.operations)
    workflow = SimpleNamespace(
        id=mutation.workflow_id,
        graph=result_graph,
        updated_at=now,
    )
    envelope = GraphMutationSafeEnvelope.from_mutation(mutation).model_copy(
        update={
            "status": "acknowledged",
            "result_graph_hash": mutation.expected_result_graph_hash,
            "saved_workflow_updated_at": now,
        }
    )

    result = WorkflowDraftCASService.validate_revert_candidate(
        workflow=workflow,
        request=_revert_request(mutation, result_graph, now),
        envelope=envelope,
    )

    assert result.graph_hash == mutation.base_graph_hash
    assert result.graph["nodes"] == []


def test_revert_validation_rejects_graph_saved_after_latest_acknowledgement():
    acknowledged_at = datetime.now(timezone.utc)
    current_updated_at = acknowledged_at + timedelta(seconds=1)
    base, mutation = _issued_mutation(acknowledged_at)
    result_graph = apply_graph_operations(base, mutation.operations)
    workflow = SimpleNamespace(
        id=mutation.workflow_id,
        graph=result_graph,
        updated_at=current_updated_at,
    )
    envelope = GraphMutationSafeEnvelope.from_mutation(mutation).model_copy(
        update={
            "status": "acknowledged",
            "result_graph_hash": mutation.expected_result_graph_hash,
            "saved_workflow_updated_at": acknowledged_at,
        }
    )

    with pytest.raises(
        WorkflowMutationConflict,
        match="stale_workflow_updated_at",
    ):
        WorkflowDraftCASService.validate_revert_candidate(
            workflow=workflow,
            request=_revert_request(mutation, result_graph, current_updated_at),
            envelope=envelope,
        )


def test_redo_validation_restores_only_latest_final_graph_from_reverted_boundary():
    final_updated_at = datetime.now(timezone.utc)
    reverted_updated_at = final_updated_at + timedelta(seconds=1)
    base, mutation = _issued_mutation(final_updated_at)
    result_graph = apply_graph_operations(base, mutation.operations)
    boundary = {
        "operation_id": str(mutation.operation_id),
        "workflow_id": str(mutation.workflow_id),
        "status": "reverted",
        "pre_run_snapshot": {
            "graph_hash": mutation.base_graph_hash,
            "workflow_updated_at": mutation.expected_workflow_updated_at.isoformat(),
        },
        "latest_final_graph": {
            "graph_hash": mutation.expected_result_graph_hash,
            "workflow_updated_at": final_updated_at.isoformat(),
            "operation_id": str(mutation.operation_id),
        },
    }

    result = WorkflowDraftCASService.validate_redo_candidate(
        workflow=SimpleNamespace(
            id=mutation.workflow_id,
            graph=base,
            updated_at=reverted_updated_at,
        ),
        request=_redo_request(
            mutation,
            result_graph,
            mutation.base_graph_hash,
            reverted_updated_at,
        ),
        boundary=boundary,
    )

    assert result.operation_id == mutation.operation_id
    assert result.graph_hash == mutation.expected_result_graph_hash


def test_revert_hash_uses_schema_normalized_existing_base_graph():
    now = datetime.now(timezone.utc)
    workflow_id = uuid4()
    base = {
        "nodes": [
            _node("start", "startNode"),
            _node("llm", "llmNode"),
            _node("answer", "answerNode"),
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "llm"},
            {"id": "e2", "source": "llm", "target": "answer"},
        ],
    }
    mutation = GraphMutationBuilder().build(
        operation_id=uuid4(),
        kind="graph_edit",
        generation_mode="structure_only",
        workflow_id=workflow_id,
        base_graph=base,
        expected_workflow_updated_at=now,
        operations=[
            {"op": "remove_edge", "edge_id": "e2"},
            {"op": "add_node", "node": _node("template", "templateNode")},
            {
                "op": "add_edge",
                "edge": {"id": "e3", "source": "llm", "target": "template"},
            },
            {
                "op": "add_edge",
                "edge": {"id": "e4", "source": "template", "target": "answer"},
            },
        ],
    )
    applied = WorkflowDraftCASService.validate_candidate(
        workflow=SimpleNamespace(id=workflow_id, graph=base, updated_at=now),
        request=_request(mutation, base),
        envelope=GraphMutationSafeEnvelope.from_mutation(mutation),
    )
    envelope = GraphMutationSafeEnvelope.from_mutation(mutation).model_copy(
        update={
            "status": "acknowledged",
            "result_graph_hash": applied.graph_hash,
            "saved_workflow_updated_at": now,
        }
    )
    request = _draft_request(
        {
            **base,
            "mutation_context": {
                "operation_id": str(mutation.operation_id),
                "action": "revert",
                "expected_base_graph_hash": applied.graph_hash,
                "expected_workflow_updated_at": now,
                "catalog_version": 3,
            },
        }
    )

    reverted = WorkflowDraftCASService.validate_revert_candidate(
        workflow=SimpleNamespace(
            id=workflow_id,
            graph=applied.graph,
            updated_at=now,
        ),
        request=request,
        envelope=envelope,
    )

    assert reverted.graph_hash == mutation.base_graph_hash


def test_repository_marks_acknowledged_envelope_reverted_idempotently():
    now = datetime.now(timezone.utc)
    _, mutation = _issued_mutation(now)
    request_row = SimpleNamespace(response_payload={})
    repository = AgentBuilderRepository()
    repository.store_envelope(
        request_row, GraphMutationSafeEnvelope.from_mutation(mutation)
    )
    repository.mark_envelope_pending_save(request_row, mutation.operation_id)
    repository.mark_envelope_saved(
        request_row,
        operation_id=mutation.operation_id,
        result_graph_hash=mutation.expected_result_graph_hash,
        workflow_updated_at=now,
    )
    repository.acknowledge_envelope(
        request_row,
        operation_id=mutation.operation_id,
        result_graph_hash=mutation.expected_result_graph_hash,
        workflow_updated_at=now,
    )

    first = repository.mark_envelope_reverted(request_row, mutation.operation_id)
    second = repository.mark_envelope_reverted(request_row, mutation.operation_id)

    assert first == second
    assert second["status"] == "reverted"


@pytest.mark.parametrize("kind", ["initial_graph", "replace_workflow"])
def test_structural_graph_revert_cancels_parameter_group(kind):
    group_id = uuid4()
    task = AgentBuilderParameterTask(
        task_id=uuid4(),
        group_id=group_id,
        step_id="step_llm",
        node_id="llm",
        node_type="llmNode",
        parameter_key="model_id",
        label="LLM model",
        input_type="resource_ref",
        required=True,
        defer_policy="allow_unresolved",
        status="active",
        task_version=1,
        stable_order=0,
        reason="model required",
        input_guidance="select a model",
    )
    request_row = SimpleNamespace(response_payload={})
    repository = AgentBuilderRepository()
    repository.store_parameter_group(
        request_row,
        AgentBuilderParameterGroup(
            group_id=group_id,
            status="active",
            tasks=[task],
        ),
    )

    group = repository.revert_completion_state(
        request_row,
        {"kind": kind, "completion_context": None},
    )

    assert group is not None
    assert group.status == "canceled"
    assert group.tasks[0].status == "canceled"
