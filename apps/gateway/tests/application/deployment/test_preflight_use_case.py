import uuid

import pytest

from apps.gateway.application.deployment.errors import DeploymentPreflightBlocked
from apps.gateway.application.deployment.models import (
    KnowledgeBaseSnapshot,
    KnowledgeCollectionPreflightSnapshot,
    WorkflowNodeTargetSnapshot,
)
from apps.gateway.application.deployment.preflight import DeploymentPreflightUseCase


class _Repository:
    def __init__(self) -> None:
        self.knowledge_bases: dict[uuid.UUID, KnowledgeBaseSnapshot] = {}
        self.collections: dict[
            uuid.UUID, KnowledgeCollectionPreflightSnapshot
        ] = {}
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

    def get_active_knowledge_collections(self, ids, organization_id):
        self.calls.append(("collection", organization_id))
        return {
            item_id: self.collections[item_id]
            for item_id in ids
            if item_id in self.collections
        }

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


def test_internal_chatbot_private_kb_uses_authenticated_audience():
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

    result = use_case.preview(
        deployment_type="internal_chatbot",
        graph_snapshot=_llm_graph(kb_id),
    )

    assert result.audience == "authenticated_user"
    assert result.status == "passed"
    assert repository.calls == []


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


@pytest.mark.parametrize(
    ("references", "expected_reason"),
    [
        ([{"id": "not-a-uuid"}], "knowledge_reference_invalid"),
        (
            [
                {"id": str(uuid.uuid4())}
                for _index in range(21)
            ],
            "knowledge_reference_limit_exceeded",
        ),
    ],
)
def test_malformed_or_over_limit_collection_graph_is_non_downgradable(
    references,
    expected_reason,
):
    repository = _Repository()
    result = DeploymentPreflightUseCase(
        repository,
        organization_id=uuid.uuid4(),
    ).preview(
        deployment_type="api",
        graph_snapshot=_collection_graph(references),
        is_active=False,
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == expected_reason
    assert repository.calls == []


def test_anonymous_private_collection_is_blocked_with_collection_action():
    organization_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    repository = _Repository()
    repository.collections[collection_id] = _collection_snapshot(
        collection_id,
        public=False,
    )

    result = DeploymentPreflightUseCase(
        repository,
        organization_id=organization_id,
    ).preview(
        deployment_type="api",
        graph_snapshot=_collection_graph([{"id": str(collection_id)}]),
    )

    assert result.status == "blocked"
    assert (
        result.safe_summary.blocked_reason
        == "private_collection_requires_execution_subject"
    )
    assert result.required_actions[0].action == (
        "remove_private_collection_or_use_authenticated_run"
    )
    assert result.safe_summary.affected_collection_count_bucket == "1"


def test_anonymous_public_manual_collection_passes():
    organization_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    repository = _Repository()
    repository.collections[collection_id] = _collection_snapshot(
        collection_id,
        public=True,
        candidate_member_count=3,
    )

    result = DeploymentPreflightUseCase(
        repository,
        organization_id=organization_id,
    ).preview(
        deployment_type="webhook",
        graph_snapshot=_collection_graph([{"id": str(collection_id)}]),
    )

    assert result.status == "passed"
    assert result.nodes == ()
    assert repository.calls == [("collection", organization_id)]


@pytest.mark.parametrize("source_managed_field", ["collection", "member"])
def test_public_collection_with_source_managed_content_is_blocked_without_identity(
    source_managed_field,
):
    organization_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    repository = _Repository()
    repository.collections[collection_id] = _collection_snapshot(
        collection_id,
        public=True,
        source_managed=source_managed_field == "collection",
        has_source_managed_members=source_managed_field == "member",
    )

    result = DeploymentPreflightUseCase(
        repository,
        organization_id=organization_id,
    ).preview(
        deployment_type="chatbot",
        graph_snapshot=_collection_graph(
            [{"id": str(collection_id), "safeLabel": "Hidden source"}]
        ),
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == "source_public_exposure_required"
    assert str(collection_id) not in str(result)
    assert "Hidden source" not in str(result)


def test_collection_lifecycle_is_checked_for_authenticated_and_inherited_audience():
    organization_id = uuid.uuid4()
    active_collection_id = uuid.uuid4()
    missing_collection_id = uuid.uuid4()
    repository = _Repository()
    repository.collections[active_collection_id] = _collection_snapshot(
        active_collection_id,
        public=False,
    )
    use_case = DeploymentPreflightUseCase(
        repository,
        organization_id=organization_id,
    )
    graph = _collection_graph(
        [
            {"id": str(active_collection_id)},
            {"id": str(missing_collection_id)},
        ]
    )

    authenticated = use_case.preview(
        deployment_type="api",
        graph_snapshot=graph,
        trusted_audience_override="authenticated_user",
    )
    inherited = use_case.preview(
        deployment_type="workflow_node",
        graph_snapshot=graph,
    )

    assert authenticated.status == "blocked"
    assert authenticated.audience == "authenticated_user"
    assert authenticated.safe_summary.blocked_reason == (
        "knowledge_collection_unavailable"
    )
    assert inherited.status == "blocked"
    assert inherited.warnings == ("workflow_node_execution_subject_inherited",)


def test_collection_candidate_budget_warning_is_conservative_and_bucketed():
    organization_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    repository = _Repository()
    repository.collections[collection_id] = _collection_snapshot(
        collection_id,
        public=True,
        candidate_member_count=21,
    )

    result = DeploymentPreflightUseCase(
        repository,
        organization_id=organization_id,
    ).preview(
        deployment_type="api",
        graph_snapshot=_collection_graph([{"id": str(collection_id)}]),
    )

    assert result.status == "warning"
    assert result.safe_summary.candidate_budget_limited is True
    assert result.nodes[0].candidate_budget_limited is True
    assert result.nodes[0].knowledge_collection_count_bucket == "1"
    assert result.warnings == ("knowledge_candidate_budget_limited",)
    assert "21" not in str(result)


def test_nested_loop_collection_is_evaluated_with_parent_audience():
    organization_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    repository = _Repository()
    repository.collections[collection_id] = _collection_snapshot(
        collection_id,
        public=False,
    )
    graph = {
        "nodes": [
            {
                "id": "loop-1",
                "type": "loopNode",
                "data": {
                    "subGraph": _collection_graph(
                        [{"id": str(collection_id)}]
                    )
                },
            }
        ],
        "edges": [],
    }

    result = DeploymentPreflightUseCase(
        repository,
        organization_id=organization_id,
    ).preview(
        deployment_type="chatbot",
        graph_snapshot=graph,
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == (
        "private_collection_requires_execution_subject"
    )


def test_deep_nested_subgraphs_are_evaluated_without_recursive_stack_usage():
    organization_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    repository = _Repository()
    repository.collections[collection_id] = _collection_snapshot(
        collection_id,
        public=False,
    )
    graph = _collection_graph([{"id": str(collection_id)}])
    for index in range(1_100):
        graph = {
            "nodes": [
                {
                    "id": f"loop-{index}",
                    "type": "loopNode",
                    "data": {"subGraph": graph},
                }
            ],
            "edges": [],
        }

    result = DeploymentPreflightUseCase(
        repository,
        organization_id=organization_id,
    ).preview(
        deployment_type="chatbot",
        graph_snapshot=graph,
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == (
        "private_collection_requires_execution_subject"
    )


def _llm_graph(kb_id: uuid.UUID) -> dict:
    return {
        "nodes": [
            {
                "id": "llm-1",
                "type": "llmNode",
                "data": {
                    "knowledgeBases": [{"id": str(kb_id), "name": "KB"}]
                },
            }
        ],
        "edges": [],
    }


def _collection_graph(references: list[dict]) -> dict:
    return {
        "nodes": [
            {
                "id": "llm-1",
                "type": "llmNode",
                "data": {"knowledgeCollections": references},
            }
        ],
        "edges": [],
    }


def _collection_snapshot(
    collection_id: uuid.UUID,
    *,
    public: bool,
    source_managed: bool = False,
    has_source_managed_members: bool = False,
    candidate_member_count: int = 0,
) -> KnowledgeCollectionPreflightSnapshot:
    return KnowledgeCollectionPreflightSnapshot(
        id=collection_id,
        public=public,
        source_managed=source_managed,
        has_source_managed_members=has_source_managed_members,
        candidate_member_count=candidate_member_count,
    )


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
