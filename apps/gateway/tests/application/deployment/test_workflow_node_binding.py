import uuid

import pytest

from apps.gateway.application.deployment.models import WorkflowNodeTargetSnapshot
from apps.gateway.application.deployment.workflow_node_binding import (
    WorkflowNodeBindingUseCase,
)
from apps.shared.domain.workflow_node_binding import (
    WorkflowNodeBindingError,
    parse_workflow_node_bindings,
)


SIDE_EFFECTS = {
    "startNode": "none",
    "answerNode": "none",
    "workflowNode": "local_execution",
    "httpRequestNode": "external_write",
}


class _Repository:
    def __init__(self, targets):
        self.targets = targets

    def get_workflow_node_target(self, app_id, organization_id):
        return self.targets.get((app_id, "active"))

    def get_workflow_node_deployment(self, app_id, deployment_id, organization_id):
        return self.targets.get((app_id, deployment_id))


def _target(app_id, organization_id, *, graph, version=1):
    return WorkflowNodeTargetSnapshot(
        app_id=app_id,
        organization_id=organization_id,
        workflow_id=uuid.uuid4(),
        deployment_id=uuid.uuid4(),
        deployment_version=version,
        deployment_type="workflow_node",
        active_graph_snapshot=graph,
        active_pointer_valid=True,
    )


def test_binding_use_case_replaces_client_metadata_with_active_target() -> None:
    organization_id = uuid.uuid4()
    root_app_id = uuid.uuid4()
    child_app_id = uuid.uuid4()
    child = _target(
        child_app_id,
        organization_id,
        graph={"nodes": [{"id": "start", "type": "startNode", "data": {}}], "edges": []},
    )
    graph = {
        "nodes": [
            {
                "id": "workflow-1",
                "type": "workflowNode",
                "data": {"appId": str(child_app_id)},
            }
        ],
        "edges": [],
        "_nodease_runtime": {"workflow_node_bindings": {"forged": True}},
    }
    use_case = WorkflowNodeBindingUseCase(
        _Repository({(child_app_id, "active"): child}),
        organization_id=organization_id,
        side_effect_by_node_type=SIDE_EFFECTS,
    )

    bound = use_case.bind_graph(graph, root_app_id=root_app_id)
    binding = parse_workflow_node_bindings(bound)[0]

    assert binding.deployment_id == child.deployment_id
    assert binding.target_app_id == child_app_id


def test_legacy_child_with_transitive_effect_requires_redeployment() -> None:
    organization_id = uuid.uuid4()
    root_app_id = uuid.uuid4()
    child_app_id = uuid.uuid4()
    grandchild_app_id = uuid.uuid4()
    grandchild = _target(
        grandchild_app_id,
        organization_id,
        graph={
            "nodes": [
                {"id": "http", "type": "httpRequestNode", "data": {"method": "POST"}}
            ],
            "edges": [],
        },
    )
    child = _target(
        child_app_id,
        organization_id,
        graph={
            "nodes": [
                {
                    "id": "grandchild",
                    "type": "workflowNode",
                    "data": {"appId": str(grandchild_app_id)},
                }
            ],
            "edges": [],
        },
    )
    repository = _Repository(
        {
            (child_app_id, "active"): child,
            (grandchild_app_id, "active"): grandchild,
        }
    )
    use_case = WorkflowNodeBindingUseCase(
        repository,
        organization_id=organization_id,
        side_effect_by_node_type=SIDE_EFFECTS,
    )
    graph = {
        "nodes": [
            {
                "id": "child",
                "type": "workflowNode",
                "data": {"appId": str(child_app_id)},
            }
        ],
        "edges": [],
    }

    with pytest.raises(
        WorkflowNodeBindingError,
        match="workflow_node.child_redeployment_required",
    ):
        use_case.bind_graph(graph, root_app_id=root_app_id)
