from pathlib import Path
from runpy import run_path

ROOT_DIR = Path(__file__).resolve().parents[4]
MIGRATION = run_path(
    ROOT_DIR
    / "apps"
    / "shared"
    / "alembic"
    / "versions"
    / "d3e9f5a1b607_add_external_action_credentials.py"
)
_redact_legacy_external_action_credentials = MIGRATION[
    "_redact_legacy_external_action_credentials"
]


def test_legacy_graph_scrub_removes_direct_credentials_without_mutating_source():
    source = {
        "nodes": [
            {
                "id": "slack",
                "type": "slackPostNode",
                "data": {
                    "authConfig": {"token": "test-only-placeholder"},
                    "url": "https://hooks.slack.com/services/T/B/test",
                    "headers": [
                        {
                            "key": "Authorization",
                            "value": "test-only-placeholder",
                        }
                    ],
                    "parameters": {"secret": "test-only-placeholder"},
                },
            },
            {
                "id": "github",
                "type": "githubNode",
                "data": {
                    "api_token": "test-only-placeholder",
                    "authorization": "test-only-placeholder",
                    "parameters": {"secret": "test-only-placeholder"},
                },
            },
        ]
    }

    result = _redact_legacy_external_action_credentials(source)

    assert source["nodes"][0]["data"]["authConfig"] == {
        "token": "test-only-placeholder"
    }
    assert source["nodes"][1]["data"]["api_token"] == "test-only-placeholder"
    slack_data = result["nodes"][0]["data"]
    github_data = result["nodes"][1]["data"]
    assert {
        "url",
        "authConfig",
        "token",
        "headers",
        "body",
        "authType",
        "method",
        "timeout",
    }.isdisjoint(slack_data)
    assert slack_data.get("parameters") == {}
    assert {"api_token", "authConfig", "token", "authorization"}.isdisjoint(
        github_data
    )
    assert github_data.get("parameters") == {}
    assert slack_data["configuration_state"] == "unresolved"
    assert github_data["configuration_state"] == "unresolved"


def test_legacy_graph_scrub_preserves_existing_opaque_reference():
    result = _redact_legacy_external_action_credentials(
        {
            "type": "githubNode",
            "data": {
                "credential_id": "00000000-0000-0000-0000-000000000001",
                "api_token": "test-only-placeholder",
            },
        }
    )

    assert result["data"] == {
        "credential_id": "00000000-0000-0000-0000-000000000001"
    }
