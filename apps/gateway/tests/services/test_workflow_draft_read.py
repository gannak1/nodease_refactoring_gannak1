from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from apps.gateway.services.workflow_service import WorkflowService


@pytest.mark.parametrize("stored_graph", [None, {}])
def test_get_draft_materializes_empty_graph_contract(stored_graph):
    workflow_id = uuid4()
    updated_at = datetime(2026, 7, 15, tzinfo=timezone.utc)
    workflow = SimpleNamespace(
        id=workflow_id,
        graph=stored_graph,
        features=None,
        updated_at=updated_at,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = workflow

    result = WorkflowService.get_draft(
        db,
        str(workflow_id),
        include_metadata=True,
    )

    assert result["nodes"] == []
    assert result["edges"] == []
    assert result["viewport"] == {"x": 0, "y": 0, "zoom": 1}
    assert result["workflow_id"] == str(workflow_id)
    assert isinstance(result["graph_hash"], str)
    assert result["updated_at"] == updated_at.isoformat()


@pytest.mark.parametrize("stored_graph", [None, {}])
def test_get_draft_without_metadata_preserves_empty_graph_guard(stored_graph):
    workflow_id = uuid4()
    workflow = SimpleNamespace(
        id=workflow_id,
        graph=stored_graph,
        features=None,
        updated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = workflow

    result = WorkflowService.get_draft(db, str(workflow_id))

    assert result == {}
