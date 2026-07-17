from __future__ import annotations

import dataclasses
import hashlib

import pytest
from apps.shared.services.rag_retrieval_diagnostics import (
    RetrievalDiagnosticError,
    diagnostic_query_limit,
    keyword_stage_name,
    observe_bounded_candidates,
    vector_stage_name,
)


class Observer:
    def __init__(self, scan_cap=3, *, score_precision=8, fail=False):
        self._scan_cap = scan_cap
        self._score_precision = score_precision
        self.fail = fail
        self.events = []

    @property
    def scan_cap(self):
        return self._scan_cap

    @property
    def score_precision(self):
        return self._score_precision

    def reference_for(self, stage, internal_id):
        if self.fail:
            raise RuntimeError("RAW_DIAGNOSTIC_SENTINEL")
        digest = hashlib.sha256(f"{stage}:{internal_id}".encode()).hexdigest()[:32]
        return f"ev:{digest}"

    def observe(self, event):
        if self.fail:
            raise RuntimeError("RAW_DIAGNOSTIC_SENTINEL")
        self.events.append(event)


def test_default_query_limit_is_unchanged() -> None:
    assert diagnostic_query_limit(5, None) == 5
    assert diagnostic_query_limit(5, Observer(scan_cap=100)) == 101


def test_invalid_scan_cap_fails_before_query() -> None:
    with pytest.raises(ValueError, match="invalid_diagnostic_scan_cap"):
        diagnostic_query_limit(5, Observer(scan_cap=4))


def test_invalid_score_precision_fails_before_query() -> None:
    with pytest.raises(ValueError, match="invalid_diagnostic_score_precision"):
        diagnostic_query_limit(1, Observer(score_precision=16))


def test_cutoff_tie_beyond_cap_is_marked_without_internal_identity() -> None:
    observer = Observer(scan_cap=3)
    observe_bounded_candidates(
        observer=observer,
        stage="flat_candidate",
        requested_limit=2,
        rows=[("db-1", 0.9), ("db-2", 0.8), ("db-3", 0.8), ("db-4", 0.8)],
    )
    event = observer.events[0]
    assert event.tie_group_truncated is True
    assert event.observed_count == 3
    dumped = repr(dataclasses.asdict(event))
    assert "db-" not in dumped
    assert "content" not in dumped


def test_lower_score_after_cap_is_not_a_truncated_tie() -> None:
    observer = Observer(scan_cap=3)
    observe_bounded_candidates(
        observer=observer,
        stage="child_expansion",
        requested_limit=2,
        rows=[("1", 0.9), ("2", 0.8), ("3", 0.8), ("4", 0.7)],
    )
    assert observer.events[0].tie_group_truncated is False


def test_protocol_precision_controls_cutoff_tie_detection() -> None:
    rows = [
        ("internal-1", 0.9),
        ("internal-2", 0.80004),
        ("internal-3", 0.80003),
        ("internal-4", 0.80002),
    ]
    coarse = Observer(scan_cap=3, score_precision=3)
    fine = Observer(scan_cap=3, score_precision=5)

    observe_bounded_candidates(
        observer=coarse,
        stage="final_selection",
        requested_limit=2,
        rows=rows,
    )
    observe_bounded_candidates(
        observer=fine,
        stage="final_selection",
        requested_limit=2,
        rows=rows,
    )

    assert coarse.events[0].tie_group_truncated is True
    assert fine.events[0].tie_group_truncated is False


def test_observer_failure_is_sanitized() -> None:
    with pytest.raises(RetrievalDiagnosticError) as captured:
        observe_bounded_candidates(
            observer=Observer(fail=True),
            stage="flat_candidate",
            requested_limit=1,
            rows=[("RAW_INTERNAL_SENTINEL", 0.9)],
        )
    assert str(captured.value) == "diagnostic_observer_failed"
    assert "RAW" not in str(captured.value)


def test_unsorted_candidate_scores_fail_closed() -> None:
    with pytest.raises(RetrievalDiagnosticError, match="diagnostic_observer_failed"):
        observe_bounded_candidates(
            observer=Observer(),
            stage="final_selection",
            requested_limit=2,
            rows=[("first", 0.7), ("second", 0.8)],
        )


def test_stage_names_are_shared_for_gateway_and_worker() -> None:
    assert vector_stage_name(("parent",), parent_ids_present=False) == "parent_candidate"
    assert vector_stage_name(("child",), parent_ids_present=True) == "child_expansion"
    assert vector_stage_name((None, "flat"), parent_ids_present=False) == "flat_candidate"
    assert (
        keyword_stage_name(("parent",), parent_ids_present=False)
        == "parent_keyword_candidate"
    )
    assert (
        keyword_stage_name(("child",), parent_ids_present=True)
        == "child_keyword_expansion"
    )
