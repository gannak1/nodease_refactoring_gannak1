from apps.shared.services.workflow_node_catalog import (
    agent_builder_supported_node_types,
    implemented_node_types,
    load_workflow_node_catalog,
)


EXPECTED_IMPLEMENTED_NODE_TYPES = {
    "answerNode",
    "codeNode",
    "conditionNode",
    "fileExtractionNode",
    "githubNode",
    "httpRequestNode",
    "llmNode",
    "loopNode",
    "mailNode",
    "scheduleTrigger",
    "slackPostNode",
    "startNode",
    "templateNode",
    "variableExtractionNode",
    "webhookTrigger",
    "workflowNode",
}


def test_workflow_node_catalog_contains_every_implemented_node_in_builder_allowlist():
    catalog = load_workflow_node_catalog()

    assert catalog["version"] == 1
    assert implemented_node_types() == EXPECTED_IMPLEMENTED_NODE_TYPES
    assert agent_builder_supported_node_types() == EXPECTED_IMPLEMENTED_NODE_TYPES


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
