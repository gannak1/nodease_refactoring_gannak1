from __future__ import annotations

import itertools
import math

import pytest

from tests.evaluation.paired_metrics import (
    RankedEvidence,
    required_full_coverage_probability,
    tie_aware_metrics,
)


def ev(name: str, score: float) -> RankedEvidence:
    return RankedEvidence(evidence_ref=f"ev:{name.lower() * 32}", score=score)


def test_precision_uses_k_as_denominator_and_duplicates_count_once() -> None:
    relevant = {ev("A", 1.0).evidence_ref}
    metrics = tie_aware_metrics(
        [ev("A", 1.0), ev("A", 0.9), ev("B", 0.8)], relevant, k=5
    )
    assert metrics.precision == pytest.approx(0.2)
    assert metrics.recall == pytest.approx(1.0)


def test_empty_and_unanswerable_metrics_are_explicit() -> None:
    answerable = tie_aware_metrics([], {ev("A", 1.0).evidence_ref}, k=5)
    assert answerable.hit == 0
    assert answerable.recall == 0
    unanswerable = tie_aware_metrics([], set(), k=5, answerable=False)
    assert unanswerable.correct_abstention is True
    assert unanswerable.false_evidence is False
    false_evidence = tie_aware_metrics([ev("A", 1.0)], set(), k=5, answerable=False)
    assert false_evidence.false_evidence is True


def test_cutoff_tie_expected_values_match_all_permutations() -> None:
    a, b, c = ev("A", 0.5), ev("B", 0.5), ev("C", 0.5)
    relevant = {a.evidence_ref}
    actual = tie_aware_metrics([a, b, c], relevant, k=2)

    hits = []
    reciprocal_ranks = []
    dcgs = []
    for order in itertools.permutations([a, b, c]):
        refs = [item.evidence_ref for item in order[:2]]
        hits.append(float(a.evidence_ref in refs))
        reciprocal_ranks.append(
            1.0 / (refs.index(a.evidence_ref) + 1) if a.evidence_ref in refs else 0.0
        )
        dcgs.append(
            sum(
                1.0 / math.log2(index + 2)
                for index, ref in enumerate(refs)
                if ref == a.evidence_ref
            )
        )
    assert actual.hit == pytest.approx(sum(hits) / len(hits))
    assert actual.recall == pytest.approx(sum(hits) / len(hits))
    assert actual.precision == pytest.approx((2 / 3) / 2)
    assert actual.mrr == pytest.approx(sum(reciprocal_ranks) / len(reciprocal_ranks))
    assert actual.ndcg == pytest.approx(sum(dcgs) / len(dcgs))


def test_tie_result_is_db_order_invariant() -> None:
    candidates = [ev("A", 0.5), ev("B", 0.5), ev("C", 0.5)]
    relevant = {candidates[0].evidence_ref}
    assert tie_aware_metrics(candidates, relevant, k=2) == tie_aware_metrics(
        list(reversed(candidates)), relevant, k=2
    )


def test_canonical_precision_controls_ties() -> None:
    a, b = ev("A", 0.5000004), ev("B", 0.5000003)
    relevant = {a.evidence_ref}
    tied = tie_aware_metrics([a, b], relevant, k=1, score_precision=6)
    ordered = tie_aware_metrics([a, b], relevant, k=1, score_precision=7)
    assert tied.hit == pytest.approx(0.5)
    assert ordered.hit == pytest.approx(1.0)


def test_required_evidence_coverage_uses_required_subset() -> None:
    a, b = ev("A", 1.0), ev("B", 0.9)
    metrics = tie_aware_metrics(
        [a],
        {a.evidence_ref, b.evidence_ref},
        required_refs={a.evidence_ref, b.evidence_ref},
        k=5,
    )
    assert metrics.required_evidence_coverage == pytest.approx(0.5)


def test_required_full_coverage_uses_cutoff_tie_probability() -> None:
    a, b, c = ev("A", 0.5), ev("B", 0.5), ev("C", 0.5)

    probability = required_full_coverage_probability(
        [a, b, c],
        {a.evidence_ref, b.evidence_ref},
        k=2,
    )

    assert probability == pytest.approx(1 / 3)


def test_required_full_coverage_rejects_missing_or_truncated_evidence() -> None:
    a, b = ev("A", 1.0), ev("B", 0.9)

    assert required_full_coverage_probability(
        [a], {a.evidence_ref, b.evidence_ref}, k=5
    ) == pytest.approx(0.0)
    with pytest.raises(ValueError, match="tie_group_truncated"):
        required_full_coverage_probability(
            [a], {a.evidence_ref}, k=1, tie_group_truncated=True
        )


@pytest.mark.parametrize("score", [math.nan, math.inf, -math.inf])
def test_non_finite_score_is_rejected(score: float) -> None:
    with pytest.raises(ValueError, match="non_finite_score"):
        RankedEvidence(
            evidence_ref="ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", score=score
        )


def test_truncated_tie_group_is_rejected() -> None:
    with pytest.raises(ValueError, match="tie_group_truncated"):
        tie_aware_metrics(
            [ev("A", 0.5)],
            {ev("A", 0.5).evidence_ref},
            k=1,
            tie_group_truncated=True,
        )
