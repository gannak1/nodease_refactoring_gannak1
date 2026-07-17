from __future__ import annotations

import pytest

from tests.evaluation.judgment_pool import build_blind_pool
from tests.evaluation.paired_runner import (
    PairedBenchmarkRunner,
    RetrievalResponse,
    RunnerConfig,
)
from tests.evaluation.protocol import canonical_hash
from tests.evaluation.schemas import BenchmarkQuestion, RetrievedEvidence
from tests.evaluation.tests.support import make_lineage, make_protocol


REFS = tuple(f"ev:{value * 32}" for value in "0123456")


class PoolRetriever:
    def __init__(self, *, truncated: bool = False) -> None:
        self._truncated = truncated

    def retrieve(self, *, condition, question, query_vector, config):
        evidence = tuple(
            RetrievedEvidence(
                evidence_ref=reference,
                score=score,
                rank=index,
            )
            for index, (reference, score) in enumerate(
                zip(REFS[1:], (0.9, 0.8, 0.7, 0.6, 0.5, 0.5)),
                start=1,
            )
        )
        return RetrievalResponse(
            evidence=evidence,
            tie_group_truncated=self._truncated and condition == "hierarchical",
        )


def _run(*, truncated: bool = False):
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
        required_evidence_refs=(REFS[0],),
    )
    run = PairedBenchmarkRunner(
        retriever=PoolRetriever(truncated=truncated),
        embed_query=lambda _query: (0.1,),
        config=config,
        protocol=protocol,
    ).run(
        [question],
        run_id="pool-run",
        artifact_lineage=make_lineage(protocol, config),
    )
    return run, protocol


def test_pool_includes_pre_authored_evidence_and_complete_cutoff_tie() -> None:
    run, protocol = _run()
    pool = build_blind_pool(
        run,
        sealed_output_hash=canonical_hash(run),
        depth=5,
        score_precision=8,
        pool_seed=protocol.seeds.pool,
    )
    refs = {record.evidence_ref for record in pool.records}
    assert REFS[0] in refs
    assert REFS[6] in refs
    assert len(refs) == 7


def test_pool_order_is_seeded_but_candidate_set_is_stable() -> None:
    run, _protocol = _run()
    first = build_blind_pool(
        run,
        sealed_output_hash=canonical_hash(run),
        depth=5,
        score_precision=8,
        pool_seed=1,
    )
    repeated = build_blind_pool(
        run,
        sealed_output_hash=canonical_hash(run),
        depth=5,
        score_precision=8,
        pool_seed=1,
    )
    different = build_blind_pool(
        run,
        sealed_output_hash=canonical_hash(run),
        depth=5,
        score_precision=8,
        pool_seed=2,
    )
    assert first.records == repeated.records
    assert first.records != different.records
    assert set(first.records) == set(different.records)


def test_pool_rejects_incomplete_cutoff_tie_observation() -> None:
    run, protocol = _run(truncated=True)
    with pytest.raises(ValueError, match="pool_cutoff_tie_truncated"):
        build_blind_pool(
            run,
            sealed_output_hash=canonical_hash(run),
            depth=5,
            score_precision=8,
            pool_seed=protocol.seeds.pool,
        )
