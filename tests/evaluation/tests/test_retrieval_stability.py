from __future__ import annotations

import pytest

from tests.evaluation.paired_runner import PairedBenchmarkRunner, RunnerConfig
from tests.evaluation.retrieval_stability import verify_retrieval_stability
from tests.evaluation.schemas import BenchmarkQuestion, RetrievedEvidence
from tests.evaluation.tests.support import make_lineage, make_protocol


A = "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
B = "ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
C = "ev:cccccccccccccccccccccccccccccccc"
D = "ev:dddddddddddddddddddddddddddddddd"
E = "ev:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
F = "ev:ffffffffffffffffffffffffffffffff"
G = "ev:00000000000000000000000000000000"


class Retriever:
    def __init__(self, *, reverse_tie: bool = False, drift: bool = False) -> None:
        self._reverse_tie = reverse_tie
        self._drift = drift

    def retrieve(self, *, condition, question, query_vector, config):
        refs = [A, B]
        if self._reverse_tie:
            refs.reverse()
        scores = [0.8, 0.8]
        if self._drift:
            scores = [0.9, 0.7]
        return tuple(
            RetrievedEvidence(evidence_ref=ref, score=scores[index], rank=index + 1)
            for index, ref in enumerate(refs)
        )


class TailDriftRetriever:
    def __init__(self, *, drift: bool = False) -> None:
        self._drift = drift

    def retrieve(self, *, condition, question, query_vector, config):
        refs = [A, B, C, D, E, G if self._drift else F]
        scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.3 if self._drift else 0.4]
        return tuple(
            RetrievedEvidence(evidence_ref=ref, score=scores[index], rank=index + 1)
            for index, ref in enumerate(refs)
        )


def _run(retriever, run_id):
    config = RunnerConfig()
    protocol = make_protocol(
        config,
        planned_answerable_n=1,
        planned_unanswerable_n=0,
    )
    question = BenchmarkQuestion(
        question_id="q1",
        sampling_cluster_ref="c1",
        split="development",
        category="single_fact",
        difficulty="easy",
        answerable=True,
        query="approved query",
        required_evidence_refs=(A,),
    )
    run = PairedBenchmarkRunner(
        retriever=retriever,
        embed_query=lambda _query: (0.1,),
        config=config,
        protocol=protocol,
    ).run(
        [question],
        run_id=run_id,
        artifact_lineage=make_lineage(protocol, config),
    )
    return run, protocol


def test_tie_order_changes_are_stable_after_normalization() -> None:
    primary, protocol = _run(Retriever(), "primary")
    replicate, _ = _run(Retriever(reverse_tie=True), "replicate")
    summary = verify_retrieval_stability(
        primary,
        replicate,
        score_precision=protocol.tie_policy.score_precision,
        selection_depth=protocol.pooling_plan.depth,
    )
    assert summary.stable is True
    assert summary.compared_condition_count == 2


def test_non_tie_rank_or_score_drift_is_rejected() -> None:
    primary, protocol = _run(Retriever(), "primary")
    replicate, _ = _run(Retriever(drift=True), "replicate")
    with pytest.raises(ValueError, match="non_tie_rank_drift"):
        verify_retrieval_stability(
            primary,
            replicate,
            score_precision=protocol.tie_policy.score_precision,
            selection_depth=protocol.pooling_plan.depth,
        )


def test_non_tie_drift_after_selection_depth_is_ignored() -> None:
    primary, protocol = _run(TailDriftRetriever(), "primary")
    replicate, _ = _run(TailDriftRetriever(drift=True), "replicate")

    summary = verify_retrieval_stability(
        primary,
        replicate,
        score_precision=protocol.tie_policy.score_precision,
        selection_depth=protocol.pooling_plan.depth,
    )

    assert summary.stable is True
    assert summary.selection_depth == 5
