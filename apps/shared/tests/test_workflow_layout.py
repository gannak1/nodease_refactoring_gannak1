import json
from pathlib import Path

from apps.shared.services.workflow_layout import calculate_workflow_auto_layout


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "workflow_layout_cases.json"
)


def test_workflow_layout_matches_canonical_fixtures():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for case in fixture["cases"]:
        layouted = calculate_workflow_auto_layout(
            {"nodes": case["nodes"], "edges": case["edges"]}
        )
        positions = {
            node["id"]: node["position"] for node in layouted["nodes"]
        }
        assert positions == case["expected_positions"], case["name"]
