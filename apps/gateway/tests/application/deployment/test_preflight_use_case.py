import uuid

import pytest

from apps.gateway.application.deployment.errors import DeploymentPreflightBlocked
from apps.gateway.application.deployment.models import (
    KnowledgeBaseSnapshot,
    WorkflowNodeTargetSnapshot,
)
from apps.gateway.application.deployment.preflight import DeploymentPreflightUseCase


class _Repository:
    def __init__(self) -> None:
        self.knowledge_bases: dict[uuid.UUID, KnowledgeBaseSnapshot] = {}
        self.public_ids: set[uuid.UUID] = set()
        self.targets: dict[uuid.UUID, WorkflowNodeTargetSnapshot] = {}
        self.calls: list[tuple[str, uuid.UUID | None]] = []

    def get_active_knowledge_bases(self, ids, organization_id):
        self.calls.append(("knowledge", organization_id))
        return {item_id: self.knowledge_bases[item_id] for item_id in ids if item_id in self.knowledge_bases}

    def get_public_runtime_eligible_knowledge_base_ids(
        self,
        ids,
        organization_id,
    ):
        self.calls.append(("public", organization_id))
        return set(ids) & self.public_ids

    def get_workflow_node_target(self, app_id, organization_id):
        self.calls.append(("workflow_node", organization_id))
        return self.targets.get(app_id)


def test_blocking_result_is_application_error_without_http_dependency():
    organization_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    repository = _Repository()
    repository.knowledge_bases[kb_id] = KnowledgeBaseSnapshot(
        id=kb_id,
        source_managed=False,
    )
    use_case = DeploymentPreflightUseCase(
        repository,
        organization_id=organization_id,
    )

    with pytest.raises(DeploymentPreflightBlocked) as exc_info:
        use_case.enforce_active_publish(
            deployment_type="chatbot",
            graph_snapshot=_llm_graph(kb_id),
        )

    assert exc_info.value.result.status == "blocked"
    assert (
        exc_info.value.result.safe_summary.blocked_reason
        == "private_kb_requires_execution_subject"
    )
    assert repository.calls == [
        ("knowledge", organization_id),
        ("public", organization_id),
    ]


def test_inactive_preview_downgrades_publish_blocker_but_not_structural_target_error():
    organization_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    repository = _Repository()
    repository.knowledge_bases[kb_id] = KnowledgeBaseSnapshot(
        id=kb_id,
        source_managed=False,
    )
    use_case = DeploymentPreflightUseCase(
        repository,
        organization_id=organization_id,
    )

    private_result = use_case.preview(
        deployment_type="api",
        graph_snapshot=_llm_graph(kb_id),
        is_active=False,
    )
    unavailable_result = use_case.preview(
        deployment_type="workflow_node",
        graph_snapshot=_workflow_node_graph(uuid.uuid4()),
        is_active=False,
    )

    assert private_result.status == "warning"
    assert unavailable_result.status == "blocked"
    assert (
        unavailable_result.safe_summary.blocked_reason
        == "workflow_node_target_unavailable"
    )


def test_candidate_workflow_node_graph_requires_existing_scoped_target_and_type():
    organization_id = uuid.uuid4()
    target_app_id = uuid.uuid4()
    repository = _Repository()
    use_case = DeploymentPreflightUseCase(
        repository,
        organization_id=organization_id,
        candidate_graphs_by_app_id={target_app_id: {"nodes": [], "edges": []}},
        candidate_deployment_types_by_app_id={target_app_id: "workflow_node"},
    )

    missing_result = use_case.preview(
        deployment_type="workflow_node",
        graph_snapshot=_workflow_node_graph(target_app_id),
    )
    repository.targets[target_app_id] = WorkflowNodeTargetSnapshot(
        app_id=target_app_id,
        active_graph_snapshot=None,
    )
    present_result = use_case.preview(
        deployment_type="workflow_node",
        graph_snapshot=_workflow_node_graph(target_app_id),
    )

    assert missing_result.status == "blocked"
    assert present_result.status == "blocked"
    assert (
        present_result.safe_summary.blocked_reason
        == "workflow_node_cycle_detected"
    )


def test_source_managed_public_kb_remains_blocked():
    organization_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    repository = _Repository()
    repository.knowledge_bases[kb_id] = KnowledgeBaseSnapshot(
        id=kb_id,
        source_managed=True,
    )
    repository.public_ids.add(kb_id)
    use_case = DeploymentPreflightUseCase(
        repository,
        organization_id=organization_id,
    )

    result = use_case.preview(
        deployment_type="webhook",
        graph_snapshot=_llm_graph(kb_id),
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == "source_public_exposure_required"


def _llm_graph(kb_id: uuid.UUID) -> dict:
    return {
        "nodes": [
            {
                "id": "llm-1",
                "type": "llmNode",
                "data": {"knowledgeBases": [{"id": str(kb_id)}]},
            }
        ],
        "edges": [],
    }


def _workflow_node_graph(app_id: uuid.UUID) -> dict:
    return {
        "nodes": [
            {
                "id": "workflow-1",
                "type": "workflowNode",
                "data": {"appId": str(app_id)},
            }
        ],
        "edges": [],
    }
