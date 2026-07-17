from __future__ import annotations

import pytest

from apps.shared.services.rag_retrieval_diagnostics import observe_bounded_candidates
from tests.evaluation.paired_runner import (
    BenchmarkOperationalError,
    RunnerConfig,
    WorkflowRetrievalAdapter,
)
from tests.evaluation.retrieval_observer import EvaluationRetrievalDiagnostics
from tests.evaluation.schemas import BenchmarkQuestion
from tests.evaluation.tests.support import make_protocol


FLAT_REF = "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
HIERARCHICAL_REF = "ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _question() -> BenchmarkQuestion:
    return BenchmarkQuestion(
        question_id="q1",
        sampling_cluster_ref="c1",
        split="development",
        category="single_fact",
        difficulty="easy",
        answerable=True,
        query="approved query",
        required_evidence_refs=(FLAT_REF,),
    )


class DiagnosticService:
    def __init__(self, diagnostics, rows):
        self._diagnostics = diagnostics
        self._rows = rows

    def search_documents_sync(self, *_args, top_k, **_kwargs):
        observe_bounded_candidates(
            observer=self._diagnostics,
            stage="final_selection",
            requested_limit=top_k,
            rows=self._rows,
        )
        return []


def _adapter(rows, mapping):
    diagnostics = EvaluationRetrievalDiagnostics(
        evidence_mapping=mapping,
        scan_cap=3,
        score_precision=8,
    )
    return WorkflowRetrievalAdapter(
        service=DiagnosticService(diagnostics, rows),
        knowledge_base_ids={"flat": "flat-kb", "hierarchical": "hierarchical-kb"},
        evidence_mapping=mapping,
        preflight=lambda _condition, _kb_id: None,
        diagnostics=diagnostics,
    )


def test_adapter_uses_complete_final_tie_group_instead_of_truncated_previews() -> None:
    mapping = {
        "flat": {
            "flat-1": FLAT_REF,
            "flat-2": HIERARCHICAL_REF,
            "flat-3": "ev:cccccccccccccccccccccccccccccccc",
        },
        "hierarchical": {},
    }
    adapter = _adapter(
        [("flat-1", 0.9), ("flat-2", 0.8), ("flat-3", 0.8)],
        mapping,
    )

    response = adapter.retrieve(
        condition="flat",
        question=_question(),
        query_vector=(0.1,),
        config=RunnerConfig(top_k=2),
    )

    assert response.tie_group_truncated is False
    assert [item.score for item in response.evidence] == [0.9, 0.8, 0.8]


def test_adapter_fails_closed_when_final_candidate_mapping_is_missing() -> None:
    mapping = {"flat": {"flat-1": FLAT_REF}, "hierarchical": {}}
    adapter = _adapter([("flat-1", 0.9), ("unknown", 0.8)], mapping)

    with pytest.raises(BenchmarkOperationalError, match="evidence_mapping_missing"):
        adapter.retrieve(
            condition="flat",
            question=_question(),
            query_vector=(0.1,),
            config=RunnerConfig(top_k=2),
        )


def test_adapter_marks_cutoff_tie_beyond_scan_cap_as_truncated() -> None:
    mapping = {
        "flat": {
            "flat-1": FLAT_REF,
            "flat-2": HIERARCHICAL_REF,
            "flat-3": "ev:cccccccccccccccccccccccccccccccc",
            "flat-4": "ev:dddddddddddddddddddddddddddddddd",
        },
        "hierarchical": {},
    }
    adapter = _adapter(
        [("flat-1", 0.9), ("flat-2", 0.8), ("flat-3", 0.8), ("flat-4", 0.8)],
        mapping,
    )

    response = adapter.retrieve(
        condition="flat",
        question=_question(),
        query_vector=(0.1,),
        config=RunnerConfig(top_k=2),
    )

    assert response.tie_group_truncated is True


def test_evaluation_observer_derives_tie_contract_from_protocol() -> None:
    protocol = make_protocol(
        RunnerConfig(),
        planned_answerable_n=1,
        planned_unanswerable_n=0,
    )
    diagnostics = EvaluationRetrievalDiagnostics.from_protocol(
        evidence_mapping={"flat": {}, "hierarchical": {}},
        protocol=protocol,
    )

    assert diagnostics.scan_cap == protocol.tie_policy.complete_tie_group_cap
    assert diagnostics.score_precision == protocol.tie_policy.score_precision
