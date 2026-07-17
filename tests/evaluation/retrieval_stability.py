"""Tie-normalized repeatability check for paired retrieval artifacts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from tests.evaluation.paired_metrics import (
    RankedEvidence,
    cutoff_tie_group_signature,
)
from tests.evaluation.protocol import canonical_hash
from tests.evaluation.schemas import BenchmarkRun, SHA256_PATTERN, StrictModel


class RetrievalStabilitySummary(StrictModel):
    schema_version: Literal["2"] = "2"
    primary_output_hash: str = Field(pattern=SHA256_PATTERN)
    replicate_output_hash: str = Field(pattern=SHA256_PATTERN)
    protocol_hash: str = Field(pattern=SHA256_PATTERN)
    score_precision: int = Field(ge=0, le=15)
    selection_depth: int = Field(ge=1)
    compared_question_count: int = Field(ge=1)
    compared_condition_count: int = Field(ge=2)
    stable: Literal[True]


def verify_retrieval_stability(
    primary: BenchmarkRun,
    replicate: BenchmarkRun,
    *,
    score_precision: int,
    selection_depth: int,
) -> RetrievalStabilitySummary:
    if selection_depth < 1:
        raise ValueError("invalid_stability_selection_depth")
    if primary.lineage != replicate.lineage:
        raise ValueError("stability_lineage_mismatch")
    if (
        primary.study_phase != replicate.study_phase
        or primary.estimand != replicate.estimand
        or primary.seed != replicate.seed
    ):
        raise ValueError("stability_run_contract_mismatch")
    if not primary.valid or not replicate.valid:
        raise ValueError("stability_requires_valid_runs")

    primary_by_id = {sample.question_id: sample for sample in primary.samples}
    replicate_by_id = {sample.question_id: sample for sample in replicate.samples}
    if set(primary_by_id) != set(replicate_by_id):
        raise ValueError("stability_question_set_mismatch")

    compared_conditions = 0
    for question_id in sorted(primary_by_id):
        left_sample = primary_by_id[question_id]
        right_sample = replicate_by_id[question_id]
        if (
            left_sample.sampling_cluster_ref != right_sample.sampling_cluster_ref
            or left_sample.category != right_sample.category
            or left_sample.answerable != right_sample.answerable
            or left_sample.required_evidence_refs != right_sample.required_evidence_refs
        ):
            raise ValueError("stability_question_contract_mismatch")
        for condition in ("flat", "hierarchical"):
            left = getattr(left_sample, condition)
            right = getattr(right_sample, condition)
            if left.status != "success" or right.status != "success":
                raise ValueError("stability_incomplete_condition")
            if left.tie_group_truncated or right.tie_group_truncated:
                raise ValueError("stability_truncated_tie_group")
            left_signature = cutoff_tie_group_signature(
                [RankedEvidence(item.evidence_ref, item.score) for item in left.evidence],
                k=selection_depth,
                score_precision=score_precision,
            )
            right_signature = cutoff_tie_group_signature(
                [RankedEvidence(item.evidence_ref, item.score) for item in right.evidence],
                k=selection_depth,
                score_precision=score_precision,
            )
            if left_signature != right_signature:
                raise ValueError("non_tie_rank_drift")
            compared_conditions += 1

    return RetrievalStabilitySummary(
        primary_output_hash=canonical_hash(primary),
        replicate_output_hash=canonical_hash(replicate),
        protocol_hash=primary.lineage.protocol_hash,
        score_precision=score_precision,
        selection_depth=selection_depth,
        compared_question_count=len(primary_by_id),
        compared_condition_count=compared_conditions,
        stable=True,
    )
