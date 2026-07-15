from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from apps.gateway.application.agent_builder.graph_mutation_builder import (
    canonical_graph_hash,
)
from apps.gateway.services.workflow_service import WorkflowService


def test_get_draft_normalizes_null_graph_to_empty_workflow_graph():
    workflow = SimpleNamespace(
        id=uuid4(),
        graph=None,
        features=None,
        updated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = workflow

    result = WorkflowService.get_draft(db, str(workflow.id), include_metadata=True)

    assert result == {
        "nodes": [],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "workflow_id": str(workflow.id),
        "graph_hash": canonical_graph_hash(None),
        "updated_at": workflow.updated_at.isoformat(),
    }
