"""Blind candidate pooling and final qrels lineage."""

from __future__ import annotations

import random
from collections.abc import Iterable

from tests.evaluation.paired_metrics import canonical_score
from tests.evaluation.protocol import canonical_hash
from tests.evaluation.schemas import (
    BenchmarkRun,
    BlindPoolArtifact,
    BlindPoolRecord,
    QrelRecord,
    QrelsArtifact,
)


def build_blind_pool(
    run: BenchmarkRun,
    *,
    sealed_output_hash: str,
    depth: int,
    score_precision: int,
    pool_seed: int,
) -> BlindPoolArtifact:
    if depth <= 0 or depth > 100:
        raise ValueError("invalid_pool_depth")
    if not 0 <= score_precision <= 15:
        raise ValueError("invalid_score_precision")
    if pool_seed < 0:
        raise ValueError("invalid_pool_seed")

    records = {
        (sample.question_id, evidence_ref)
        for sample in run.samples
        for evidence_ref in sample.required_evidence_refs
    }
    for sample in run.samples:
        for outcome in (sample.flat, sample.hierarchical):
            if outcome.status != "success":
                continue
            if outcome.tie_group_truncated:
                raise ValueError("pool_cutoff_tie_truncated")
            selected = list(outcome.evidence[:depth])
            if len(outcome.evidence) > depth:
                cutoff = canonical_score(outcome.evidence[depth - 1].score, score_precision)
                selected.extend(
                    evidence
                    for evidence in outcome.evidence[depth:]
                    if canonical_score(evidence.score, score_precision) == cutoff
                )
            records.update(
                (sample.question_id, evidence.evidence_ref) for evidence in selected
            )

    ordered = sorted(records)
    random.Random(pool_seed).shuffle(ordered)
    return BlindPoolArtifact(
        sealed_output_hash=sealed_output_hash,
        depth=depth,
        tie_precision=score_precision,
        pool_seed=pool_seed,
        records=tuple(
            BlindPoolRecord(question_id=question_id, evidence_ref=evidence_ref)
            for question_id, evidence_ref in ordered
        ),
    )


def validate_qrels_pool(
    pool: BlindPoolArtifact,
    qrels: Iterable[QrelRecord],
) -> tuple[QrelRecord, ...]:
    qrel_records = tuple(qrels)
    expected = {(record.question_id, record.evidence_ref) for record in pool.records}
    actual = {(record.question_id, record.evidence_ref) for record in qrel_records}
    if len(actual) != len(qrel_records):
        raise ValueError("duplicate_qrel")
    if actual != expected:
        raise ValueError("qrels_pool_coverage_mismatch")
    return qrel_records


def freeze_qrels(
    pool: BlindPoolArtifact,
    qrels: Iterable[QrelRecord],
    *,
    protocol_hash: str,
    dataset_hash: str,
    sealed_output_hash: str,
    qrels_version: str,
) -> QrelsArtifact:
    qrel_records = validate_qrels_pool(pool, qrels)
    if sealed_output_hash != pool.sealed_output_hash:
        raise ValueError("sealed_output_pool_lineage_mismatch")
    return QrelsArtifact(
        protocol_hash=protocol_hash,
        dataset_hash=dataset_hash,
        sealed_output_hash=sealed_output_hash,
        judgment_pool_hash=canonical_hash(pool),
        qrels_version=qrels_version,
        records=tuple(sorted(qrel_records, key=lambda item: (item.question_id, item.evidence_ref))),
    )
