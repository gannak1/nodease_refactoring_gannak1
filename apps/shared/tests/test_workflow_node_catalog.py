from apps.shared.services.workflow_node_catalog import (
    agent_builder_supported_node_types,
    capability_output_contract,
    capability_output_keys,
    classify_catalog_version,
    derive_node_configuration_state,
    implemented_node_types,
    load_workflow_node_catalog,
    node_parameter_definitions,
    validate_node_parameter_value,
    validate_workflow_graph_connections,
    validate_workflow_node_catalog,
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

    assert catalog["version"] == 3
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


def test_workflow_node_catalog_v3_declares_typed_parameters_for_required_configuration():
    catalog = load_workflow_node_catalog()

    for node in catalog["nodes"]:
        parameters = node["parameters"]
        assert isinstance(parameters, list)
        parameter_keys = [parameter["key"] for parameter in parameters]
        assert len(parameter_keys) == len(set(parameter_keys))
        assert set(node["required_configuration"]) <= set(parameter_keys)
        for parameter in parameters:
            assert parameter["input_type"] in {
                "boolean",
                "code",
                "credential_ref",
                "json",
                "number",
                "resource_ref",
                "text",
                "textarea",
                "variable_selector",
            }
            assert parameter["defer_policy"] in {
                "forbidden",
                "allow_unresolved",
            }
            assert isinstance(parameter["required"], bool)
            assert isinstance(parameter.get("agent_builder_task", True), bool)
        assert {output["capability"] for output in node["outputs"]} == set(
            node["capabilities"]
        )


def test_catalog_marks_empty_start_and_answer_schema_as_non_tasks():
    start = node_parameter_definitions("startNode")
    answer = node_parameter_definitions("answerNode")

    assert [(item["key"], item["agent_builder_task"]) for item in start] == [
        ("variables", False)
    ]
    assert [(item["key"], item["agent_builder_task"]) for item in answer] == [
        ("outputs", False)
    ]


def test_catalog_output_contract_preserves_runtime_dynamic_output_names():
    assert capability_output_contract("file_extraction") == {
        "capability": "file_extraction",
        "mode": "parameter_names",
        "parameter_key": "referenced_variables",
        "name_key": "name",
        "value_type": "text",
    }
    assert capability_output_contract("variable_extraction") == {
        "capability": "variable_extraction",
        "mode": "parameter_names",
        "parameter_key": "mappings",
        "name_key": "name",
        "value_type": "unknown",
    }


def test_catalog_resolves_static_and_parameter_driven_output_keys_from_node_data():
    assert capability_output_keys("llm", {"output_format": {"type": "text"}}) == [
        "text"
    ]
    assert capability_output_keys(
        "file_extraction",
        {
            "referenced_variables": [
                {"name": "document_text", "value_selector": ["input", "file"]}
            ]
        },
    ) == ["document_text"]
    assert capability_output_keys(
        "variable_extraction",
        {"mappings": [{"name": "author"}, {"name": "title"}]},
    ) == ["author", "title"]
    assert capability_output_keys("variable_extraction", {"mappings": []}) == []


def test_catalog_version_recovery_only_accepts_v3_as_current():
    assert classify_catalog_version(None) == "legacy_stale"
    assert classify_catalog_version(2) == "legacy_stale"
    assert classify_catalog_version(3) == "current"


def test_catalog_validation_rejects_missing_required_parameter_and_invalid_defer_policy():
    invalid_missing = {
        "version": 3,
        "nodes": [
            {
                "node_type": "exampleNode",
                "implemented": True,
                "agent_builder_supported": True,
                "connection_policy": {
                    "role": "intermediate",
                    "incoming": "allowed",
                    "outgoing": "allowed",
                    "outgoing_handles": "standard",
                },
                "capabilities": ["example"],
                "side_effect": "none",
                "required_configuration": ["value"],
                "configuration_labels": {"value": "Value"},
                "parameters": [],
            }
        ],
    }
    invalid_defer = {
        **invalid_missing,
        "nodes": [
            {
                **invalid_missing["nodes"][0],
                "required_configuration": [],
                "parameters": [
                    {
                        "key": "value",
                        "label": "Value",
                        "input_type": "text",
                        "required": False,
                        "defer_policy": "always",
                    }
                ],
            }
        ],
    }

    for invalid in (invalid_missing, invalid_defer):
        try:
            validate_workflow_node_catalog(invalid)
        except RuntimeError:
            pass
        else:
            raise AssertionError("invalid catalog must be rejected")


def test_node_configuration_state_is_derived_from_all_required_parameters():
    definitions = node_parameter_definitions("slackPostNode")
    assert {definition["key"] for definition in definitions} >= {
        "credential",
        "channel",
    }

    assert derive_node_configuration_state(
        "slackPostNode",
        {"credential": "cred-id", "channel": "C123", "configuration_state": "resolved"},
    ) == "unresolved"
    assert derive_node_configuration_state(
        "slackPostNode",
        {"credential": "cred-id", "channel": "", "configuration_state": "resolved"},
    ) == "unresolved"


def test_external_node_configuration_uses_runtime_fields_not_virtual_task_keys():
    assert derive_node_configuration_state(
        "slackPostNode",
        {
            "authType": "bearer",
            "authConfig": {"token": "test-only-placeholder"},
            "body": '{"channel":"C123","text":"hello"}',
        },
    ) == "resolved"
    assert derive_node_configuration_state(
        "githubNode",
        {
            "credential": "ignored-virtual-reference",
            "repo_owner": "octo",
            "repo_name": "repo",
            "pr_number": 1,
        },
    ) == "unresolved"
    assert derive_node_configuration_state(
        "githubNode",
        {
            "api_token": "test-only-placeholder",
            "repo_owner": "octo",
            "repo_name": "repo",
            "pr_number": 1,
        },
    ) == "resolved"


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


def test_connection_policy_rejects_condition_edge_without_explicit_handle():
    graph = {
        "nodes": [
            {
                "id": "condition",
                "type": "conditionNode",
                "data": {"cases": [{"id": "case-1"}]},
            },
            {"id": "answer", "type": "answerNode", "data": {}},
        ],
        "edges": [
            {
                "id": "implicit-default",
                "source": "condition",
                "target": "answer",
            }
        ],
    }

    issues = validate_workflow_graph_connections(graph)

    assert [issue.code for issue in issues] == [
        "INVALID_CONDITION_SOURCE_HANDLE"
    ]


def test_catalog_parameter_validation_drives_configuration_state():
    assert validate_node_parameter_value(
        "httpRequestNode", "url", "not-a-url"
    ) == ["pattern_mismatch"]
    assert derive_node_configuration_state(
        "httpRequestNode", {"url": "not-a-url"}
    ) == "unresolved"
    assert derive_node_configuration_state(
        "httpRequestNode", {"url": "https://example.com/api"}
    ) == "resolved"


def test_catalog_exposes_effective_validation_and_sensitivity_metadata():
    http_url = next(
        parameter
        for parameter in node_parameter_definitions("httpRequestNode")
        if parameter["key"] == "url"
    )
    slack_credential = next(
        parameter
        for parameter in node_parameter_definitions("slackPostNode")
        if parameter["key"] == "credential"
    )
    loop_key = next(
        parameter
        for parameter in node_parameter_definitions("loopNode")
        if parameter["key"] == "loop_key"
    )

    assert http_url["validation"]["max_length"] == 2048
    assert http_url["sensitivity"] == "secret_forbidden"
    assert slack_credential["sensitivity"] == "reference_only"
    assert loop_key["input_type"] == "text"
