import pytest

from apps.shared.services.workflow_configuration_preflight import (
    WorkflowConfigurationPreflightError,
    enforce_workflow_configuration_preflight,
    workflow_configuration_issues,
)


def _graph(data):
    return {
        "nodes": [
            {
                "id": "slack",
                "type": "slackPostNode",
                "position": {"x": 0, "y": 0},
                "data": data,
            }
        ],
        "edges": [],
    }


def test_preflight_ignores_client_configuration_state_and_reports_missing_fields():
    issues = workflow_configuration_issues(
        _graph({"configuration_state": "resolved", "credential": "cred"})
    )

    assert len(issues) == 1
    assert issues[0].node_id == "slack"
    assert issues[0].missing_parameters == ("credential", "channel")


def test_unresolved_external_action_is_blocked_for_test_run_and_deployment():
    graph = _graph({"credential": "", "channel": ""})

    for surface in ("test", "run", "deployment"):
        with pytest.raises(WorkflowConfigurationPreflightError) as exc:
            enforce_workflow_configuration_preflight(graph, surface=surface)
        assert exc.value.surface == surface
        assert exc.value.issues[0].node_type == "slackPostNode"


def test_local_execution_preflight_ignores_client_configuration_state():
    graph = {
        "nodes": [
            {
                "id": "workflow-call",
                "type": "workflowNode",
                "data": {"configuration_state": "resolved"},
            }
        ],
        "edges": [],
    }

    issues = workflow_configuration_issues(graph)

    assert len(issues) == 1
    assert issues[0].node_type == "workflowNode"
    assert issues[0].missing_parameters == ("workflowId", "appId")


def test_local_execution_preflight_checks_loop_subgraph():
    graph = {
        "nodes": [
            {
                "id": "loop",
                "type": "loopNode",
                "data": {
                    "loop_key": "items",
                    "subGraph": {
                        "nodes": [
                            {
                                "id": "nested-workflow-call",
                                "type": "workflowNode",
                                "data": {"configuration_state": "resolved"},
                            }
                        ],
                        "edges": [],
                    },
                },
            },
        ],
        "edges": [],
    }

    issues = workflow_configuration_issues(graph)

    assert [(issue.node_id, issue.missing_parameters) for issue in issues] == [
        ("nested-workflow-call", ("workflowId", "appId"))
    ]


def test_resolved_external_action_passes_without_external_calls():
    enforce_workflow_configuration_preflight(
        _graph(
            {
                "authType": "bearer",
                "authConfig": {"token": "test-only-placeholder"},
                "body": '{"channel":"C123","text":"hello"}',
            }
        ),
        surface="run",
    )


def test_preflight_blocks_selector_that_no_longer_exists_in_source_output_contract():
    graph = {
        "nodes": [
            {
                "id": "extract",
                "type": "variableExtractionNode",
                "data": {"mappings": [{"name": "new_name"}]},
            },
            {
                "id": "draft",
                "type": "gmailDraftNode",
                "data": {
                    "credential_id": "credential-reference",
                    "processing_ref_selector": ["extract", "old_name"],
                    "reply_body_selector": ["extract", "new_name"],
                },
            },
        ],
        "edges": [{"id": "e1", "source": "extract", "target": "draft"}],
    }

    issues = workflow_configuration_issues(graph)

    assert issues[0].missing_parameters == ("processing_ref_selector",)
