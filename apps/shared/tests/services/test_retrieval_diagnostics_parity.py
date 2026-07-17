from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from apps.gateway.services.retrieval import RetrievalService as GatewayRetrievalService
from apps.workflow_engine.services.retrieval import (
    RetrievalService as WorkflowRetrievalService,
)


class Observer:
    scan_cap = 3
    score_precision = 8

    def __init__(self):
        self.events = []

    def reference_for(self, stage, internal_id):
        digest = hashlib.sha256(f"{stage}:{internal_id}".encode()).hexdigest()[:32]
        return f"ev:{digest}"

    def observe(self, event):
        self.events.append(event)


@pytest.mark.parametrize(
    "service_type", [GatewayRetrievalService, WorkflowRetrievalService]
)
def test_gateway_and_workflow_vector_observer_have_identical_bounded_semantics(
    service_type,
) -> None:
    rows = [
        (SimpleNamespace(id=str(index)), SimpleNamespace(), distance)
        for index, distance in enumerate((0.1, 0.2, 0.2, 0.2), start=1)
    ]
    db = MagicMock()
    db.execute.return_value.all.return_value = rows
    observer = Observer()
    service = service_type(
        db,
        user_id="user",
        retrieval_diagnostics=observer,
    )

    returned = service._vector_search(
        [0.1, 0.2],
        "knowledge-base",
        2,
        chunk_levels=(None, "flat"),
    )

    assert returned == rows
    statement = db.execute.call_args.args[0]
    assert statement._limit_clause.value == 4
    assert len(statement._order_by_clauses) == 2
    assert len(observer.events) == 1
    assert observer.events[0].stage == "flat_candidate"
    assert observer.events[0].tie_group_truncated is True


@pytest.mark.parametrize(
    "service_type", [GatewayRetrievalService, WorkflowRetrievalService]
)
def test_observer_disabled_keeps_original_query_limit(service_type) -> None:
    rows = [
        (SimpleNamespace(id="1"), SimpleNamespace(), 0.1),
        (SimpleNamespace(id="2"), SimpleNamespace(), 0.2),
    ]
    db = MagicMock()
    db.execute.return_value.all.return_value = rows
    service = service_type(db, user_id="user")

    assert service._vector_search([0.1], "knowledge-base", 2) == rows
    statement = db.execute.call_args.args[0]
    assert statement._limit_clause.value == 2


@pytest.mark.parametrize(
    "service_type", [GatewayRetrievalService, WorkflowRetrievalService]
)
def test_gateway_and_workflow_keyword_observer_overfetch_and_tie_semantics(
    service_type,
) -> None:
    rows = [
        (
            str(index),
            "content",
            {},
            f"document-{index}",
            "safe.pdf",
            {},
            "file",
            None,
            "flat",
            [],
            None,
            1,
            None,
            rank,
        )
        for index, rank in enumerate((0.9, 0.8, 0.8, 0.8), start=1)
    ]
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = rows
    observer = Observer()
    service = service_type(db, user_id="user", retrieval_diagnostics=observer)

    returned = service._keyword_search(
        "approved query",
        "knowledge-base",
        2,
        chunk_levels=(None, "flat"),
    )

    assert returned == rows
    statement, params = db.execute.call_args.args
    assert params["top_k"] == 4
    assert "ORDER BY rank DESC, dc.id ASC" in str(statement)
    assert observer.events[0].stage == "flat_keyword_candidate"
    assert observer.events[0].tie_group_truncated is True


@pytest.mark.parametrize(
    "service_type", [GatewayRetrievalService, WorkflowRetrievalService]
)
def test_final_selection_observer_is_redaction_safe_and_shared(service_type) -> None:
    observer = Observer()
    service = service_type(
        MagicMock(),
        user_id="user",
        retrieval_diagnostics=observer,
    )

    service._observe_final_rows(
        [("internal-1", 0.9), ("internal-2", 0.8), ("internal-3", 0.8)],
        2,
    )

    event = observer.events[0]
    assert event.stage == "final_selection"
    assert [candidate.score for candidate in event.candidates] == [0.9, 0.8, 0.8]
    assert "internal-" not in repr(event)
