from copy import deepcopy
from uuid import uuid4

import pytest
from apps.shared.domain.external_action_credential_graph import (
    EXTERNAL_ACTION_CREDENTIAL_LEGACY_SECRET_REQUIRES_MIGRATION,
    ExternalActionCredentialGraphBoundaryError,
    redact_external_action_credential_graph,
    validate_github_credential_graph_boundary,
)


def _github_node(data=None):
    return {
        "id": "github",
        "type": "githubNode",
        "data": {
            "credential_id": str(uuid4()),
            "repo_owner": "octo",
            "repo_name": "repo",
            "pr_number": "1",
            **(data or {}),
        },
    }


def test_github_graph_accepts_opaque_credential_reference():
    validate_github_credential_graph_boundary([_github_node()], require_resolved=True)


def test_github_graph_accepts_safe_editor_metadata():
    validate_github_credential_graph_boundary(
        [
            _github_node(
                {
                    "displayNumber": 3,
                    "visibleProperties": ["credential_id", "repo_owner"],
                }
            )
        ],
        require_resolved=True,
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"displayNumber": 0},
        {"displayNumber": True},
        {"visibleProperties": [""]},
        {"visibleProperties": [123]},
    ],
)
def test_github_graph_rejects_invalid_editor_metadata(metadata):
    with pytest.raises(ExternalActionCredentialGraphBoundaryError):
        validate_github_credential_graph_boundary(
            [_github_node(metadata)],
            require_resolved=True,
        )


@pytest.mark.parametrize(
    "field",
    ["api_token", "token", "authConfig"],
)
def test_github_graph_rejects_direct_credential_material(field):
    with pytest.raises(ExternalActionCredentialGraphBoundaryError) as error:
        validate_github_credential_graph_boundary(
            [_github_node({field: "test-only-placeholder"})],
            require_resolved=True,
        )

    assert error.value.reason_code == EXTERNAL_ACTION_CREDENTIAL_LEGACY_SECRET_REQUIRES_MIGRATION


@pytest.mark.parametrize("field", ["authorization", "headers", "secret", "password"])
def test_github_graph_rejects_unknown_durable_data_fields(field):
    with pytest.raises(ExternalActionCredentialGraphBoundaryError):
        validate_github_credential_graph_boundary(
            [_github_node({field: "test-only-placeholder"})],
            require_resolved=True,
        )


def test_github_graph_rejects_nonempty_generic_parameters():
    with pytest.raises(ExternalActionCredentialGraphBoundaryError):
        validate_github_credential_graph_boundary(
            [
                _github_node(
                    {"parameters": {"authorization": "test-only-placeholder"}}
                )
            ],
            require_resolved=True,
        )


def test_redaction_removes_legacy_material_before_response_or_execution_copy():
    graph = {
        "nodes": [
            _github_node(
                {
                    "api_token": "test-only-placeholder",
                    "authorization": "test-only-placeholder",
                    "parameters": {"secret": "test-only-placeholder"},
                }
            ),
            {
                "id": "loop",
                "type": "loopNode",
                "data": {
                    "subGraph": {
                        "nodes": [
                            {
                                "id": "slack",
                                "type": "slackPostNode",
                                "data": {
                                    "url": "https://hooks.slack.com/services/T/B/test",
                                    "authConfig": {"token": "test-only-placeholder"},
                                    "headers": [
                                        {
                                            "key": "Authorization",
                                            "value": "test-only-placeholder",
                                        }
                                    ],
                                    "parameters": {
                                        "secret": "test-only-placeholder"
                                    },
                                },
                            }
                        ]
                    }
                },
            },
        ]
    }
    original = deepcopy(graph)

    redacted = redact_external_action_credential_graph(graph)

    assert graph == original
    github_data = redacted["nodes"][0]["data"]
    slack_data = redacted["nodes"][1]["data"]["subGraph"]["nodes"][0]["data"]
    assert set(github_data).issubset(
        {
            "credential_id",
            "repo_owner",
            "repo_name",
            "pr_number",
            "parameters",
            "configuration_state",
        }
    )
    assert github_data.get("parameters") in (None, {})
    assert github_data["credential_id"] == graph["nodes"][0]["data"]["credential_id"]
    assert "configuration_state" not in github_data
    assert {
        "url",
        "token",
        "authConfig",
        "headers",
        "body",
        "authType",
        "method",
        "timeout",
    }.isdisjoint(slack_data)
    assert slack_data.get("parameters") in (None, {})
    assert slack_data["configuration_state"] == "unresolved"
