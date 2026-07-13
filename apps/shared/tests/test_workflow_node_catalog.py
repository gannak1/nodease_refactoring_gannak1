from apps.shared.services.workflow_node_catalog import (
    agent_builder_supported_node_types,
    implemented_node_types,
    load_workflow_node_catalog,
    validate_workflow_graph_connections,
)

EXPECTED_IMPLEMENTED_NODE_TYPES = {
    "answerNode",
    "codeNode",
    "conditionNode",
    "fileExtractionNode",
    "gmailDraftNode",
    "githubNode",
    "httpRequestNode",
    "llmNode",
    "loopNode",
    "mailNode",
    "mailAcknowledgeNode",
    "scheduleTrigger",
    "slackPostNode",
    "startNode",
    "templateNode",
    "variableExtractionNode",
    "webhookTrigger",
    "workflowNode",
}
EXPECTED_AGENT_BUILDER_NODE_TYPES = EXPECTED_IMPLEMENTED_NODE_TYPES - {"loopNode"}
COMMON_EXTERNAL_EFFECT_NODES = {"httpRequestNode", "slackPostNode", "githubNode"}
MAIL_LEDGER_EXTERNAL_EFFECT_NODES = {"gmailDraftNode", "mailAcknowledgeNode"}
FAIL_CLOSED_EXTERNAL_EFFECT_NODES = {"pluginNode"}


def test_workflow_node_catalog_excludes_product_unavailable_nodes_from_builder_allowlist():
    catalog = load_workflow_node_catalog()

    assert catalog["version"] == 2
    assert implemented_node_types() == EXPECTED_IMPLEMENTED_NODE_TYPES
    assert agent_builder_supported_node_types() == EXPECTED_AGENT_BUILDER_NODE_TYPES


def test_workflow_node_catalog_declares_safe_generation_contract_for_every_node():
    catalog = load_workflow_node_catalog()

    for node in catalog["nodes"]:
        assert isinstance(node["capabilities"], list)
        assert node["side_effect"] in {
            "none",
            "local_execution",
            "external_read",
            "external_write",
        }
        assert isinstance(node["required_configuration"], list)
        if node["agent_builder_supported"]:
            assert node["implemented"] is True
            assert node["capabilities"]
            assert set(node["required_configuration"]) <= set(
                node.get("configuration_labels") or {}
            )


def test_external_write_nodes_have_an_explicit_idempotency_owner() -> None:
    catalog = load_workflow_node_catalog()
    external_write_nodes = {
        node["node_type"]
        for node in catalog["nodes"]
        if node["side_effect"] == "external_write"
    }

    assert external_write_nodes == (
        COMMON_EXTERNAL_EFFECT_NODES
        | MAIL_LEDGER_EXTERNAL_EFFECT_NODES
        | FAIL_CLOSED_EXTERNAL_EFFECT_NODES
    )


def test_workflow_node_catalog_declares_connection_policy_for_every_node():
    catalog = load_workflow_node_catalog()

    for node in catalog["nodes"]:
        policy = node["connection_policy"]
        assert policy["role"] in {"entry", "intermediate", "branch", "terminal"}
        assert policy["incoming"] in {"forbidden", "allowed", "required"}
        assert policy["outgoing"] in {"forbidden", "allowed", "required"}
        assert policy["outgoing_handles"] in {
            "standard",
            "condition_cases",
            "unrestricted",
        }


def test_connection_policy_rejects_entry_terminal_and_condition_violations():
    graph = {
        "nodes": [
            {"id": "start", "type": "startNode", "data": {}},
            {"id": "answer", "type": "answerNode", "data": {}},
            {
                "id": "condition",
                "type": "conditionNode",
                "data": {"cases": [{"id": "case-1"}]},
            },
            {"id": "llm", "type": "llmNode", "data": {}},
        ],
        "edges": [
            {"id": "into-start", "source": "llm", "target": "start"},
            {"id": "from-answer", "source": "answer", "target": "llm"},
            {
                "id": "bad-condition",
                "source": "condition",
                "sourceHandle": "missing-case",
                "target": "llm",
            },
        ],
    }

    issues = validate_workflow_graph_connections(graph)

    assert {issue.code for issue in issues} == {
        "START_NODE_HAS_INCOMING_EDGE",
        "TERMINAL_NODE_HAS_OUTGOING_EDGE",
        "INVALID_CONDITION_SOURCE_HANDLE",
    }
