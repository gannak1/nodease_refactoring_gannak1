"""Stable-reference retrieval metrics with exact-score tie handling."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Set
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN

from tests.evaluation.schemas import OPAQUE_EVIDENCE_PATTERN


@dataclass(frozen=True)
class RankedEvidence:
    evidence_ref: str
    score: float

    def __post_init__(self) -> None:
        if not re.fullmatch(OPAQUE_EVIDENCE_PATTERN, self.evidence_ref):
            raise ValueError("invalid_evidence_ref")
        if not math.isfinite(self.score):
            raise ValueError("non_finite_score")


@dataclass(frozen=True)
class TieAwareMetrics:
    k: int
    hit: float
    recall: float
    precision: float
    mrr: float
    ndcg: float
    required_evidence_coverage: float
    correct_abstention: bool | None
    false_evidence: bool | None
    candidate_count: int
    tie_group_count: int


@dataclass(frozen=True)
class _TieGroup:
    score: Decimal
    refs: tuple[str, ...]


def canonical_score(score: float, precision: int) -> Decimal:
    if not math.isfinite(score):
        raise ValueError("non_finite_score")
    if not 0 <= precision <= 15:
        raise ValueError("invalid_score_precision")
    quantum = Decimal(1).scaleb(-precision)
    return Decimal(str(score)).quantize(quantum, rounding=ROUND_HALF_EVEN)


def _deduplicated_groups(
    candidates: list[RankedEvidence] | tuple[RankedEvidence, ...],
    precision: int,
) -> tuple[_TieGroup, ...]:
    highest_by_ref: dict[str, Decimal] = {}
    for candidate in candidates:
        score = canonical_score(candidate.score, precision)
        previous = highest_by_ref.get(candidate.evidence_ref)
        if previous is None or score > previous:
            highest_by_ref[candidate.evidence_ref] = score

    refs_by_score: dict[Decimal, list[str]] = {}
    for evidence_ref, score in highest_by_ref.items():
        refs_by_score.setdefault(score, []).append(evidence_ref)
    return tuple(
        _TieGroup(score=score, refs=tuple(sorted(refs)))
        for score, refs in sorted(refs_by_score.items(), reverse=True)
    )


def tie_group_signature(
    candidates: list[RankedEvidence] | tuple[RankedEvidence, ...],
    *,
    score_precision: int,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (str(group.score), group.refs)
        for group in _deduplicated_groups(candidates, score_precision)
    )


def cutoff_tie_group_signature(
    candidates: list[RankedEvidence] | tuple[RankedEvidence, ...],
    *,
    k: int,
    score_precision: int,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Describe only top-k selection groups, including the complete cutoff tie."""
    if k <= 0:
        raise ValueError("invalid_k")
    groups = _deduplicated_groups(candidates, score_precision)
    selected: list[_TieGroup] = []
    observed = 0
    for group in groups:
        selected.append(group)
        observed += len(group.refs)
        if observed >= k:
            break
    return tuple((str(group.score), group.refs) for group in selected)


def _expected_selected(
    groups: tuple[_TieGroup, ...], selected_refs: Set[str], k: int
) -> float:
    remaining = k
    expected = 0.0
    for group in groups:
        if remaining <= 0:
            break
        take = min(remaining, len(group.refs))
        selected = sum(ref in selected_refs for ref in group.refs)
        expected += take * selected / len(group.refs)
        remaining -= take
    return expected


def _expected_hit(groups: tuple[_TieGroup, ...], relevant: Set[str], k: int) -> float:
    remaining = k
    for group in groups:
        if remaining <= 0:
            return 0.0
        take = min(remaining, len(group.refs))
        relevant_count = sum(ref in relevant for ref in group.refs)
        if relevant_count:
            if take == len(group.refs):
                return 1.0
            no_hit_combinations = math.comb(
                len(group.refs) - relevant_count, take
            ) if len(group.refs) - relevant_count >= take else 0
            return 1.0 - no_hit_combinations / math.comb(len(group.refs), take)
        remaining -= take
    return 0.0


def _expected_mrr(groups: tuple[_TieGroup, ...], relevant: Set[str], k: int) -> float:
    preceding = 0
    for group in groups:
        relevant_count = sum(ref in relevant for ref in group.refs)
        if not relevant_count:
            preceding += len(group.refs)
            if preceding >= k:
                return 0.0
            continue
        denominator = math.comb(len(group.refs), relevant_count)
        max_local_rank = min(
            len(group.refs) - relevant_count + 1,
            k - preceding,
        )
        if max_local_rank <= 0:
            return 0.0
        expected = 0.0
        for local_rank in range(1, max_local_rank + 1):
            ways = math.comb(len(group.refs) - local_rank, relevant_count - 1)
            expected += (ways / denominator) / (preceding + local_rank)
        return expected
    return 0.0


def _expected_dcg(
    groups: tuple[_TieGroup, ...], grades: Mapping[str, int], k: int
) -> float:
    rank = 1
    dcg = 0.0
    for group in groups:
        if rank > k:
            break
        end_rank = min(k, rank + len(group.refs) - 1)
        average_gain = sum(
            (2 ** grades.get(ref, 0)) - 1 for ref in group.refs
        ) / len(group.refs)
        dcg += average_gain * sum(
            1.0 / math.log2(position + 1)
            for position in range(rank, end_rank + 1)
        )
        rank += len(group.refs)
    return dcg


def required_full_coverage_probability(
    candidates: list[RankedEvidence] | tuple[RankedEvidence, ...],
    required_refs: Set[str],
    *,
    k: int,
    score_precision: int = 8,
    tie_group_truncated: bool = False,
) -> float:
    """Return the probability that every required ref is selected within k.

    Candidates with the same canonical score are treated as a uniformly random
    permutation. This avoids deriving a deterministic advantage from database
    row order at the cutoff.
    """
    if k <= 0:
        raise ValueError("invalid_k")
    if not 0 <= score_precision <= 15:
        raise ValueError("invalid_score_precision")
    if tie_group_truncated:
        raise ValueError("tie_group_truncated")
    required = set(required_refs)
    if not required:
        return 1.0

    remaining_required = set(required)
    remaining_slots = k
    for group in _deduplicated_groups(candidates, score_precision):
        if remaining_slots <= 0:
            break
        take = min(remaining_slots, len(group.refs))
        required_in_group = remaining_required.intersection(group.refs)
        if take == len(group.refs):
            remaining_required.difference_update(required_in_group)
            remaining_slots -= take
            continue

        if remaining_required - required_in_group:
            return 0.0
        required_count = len(required_in_group)
        if required_count > take:
            return 0.0
        return math.comb(
            len(group.refs) - required_count,
            take - required_count,
        ) / math.comb(len(group.refs), take)

    return 1.0 if not remaining_required else 0.0


def tie_aware_metrics(
    candidates: list[RankedEvidence] | tuple[RankedEvidence, ...],
    relevant_refs: Set[str] | Mapping[str, int],
    *,
    k: int,
    required_refs: Set[str] | None = None,
    answerable: bool = True,
    score_precision: int = 8,
    tie_group_truncated: bool = False,
) -> TieAwareMetrics:
    if k <= 0:
        raise ValueError("invalid_k")
    if not 0 <= score_precision <= 15:
        raise ValueError("invalid_score_precision")
    if tie_group_truncated:
        raise ValueError("tie_group_truncated")

    if isinstance(relevant_refs, Mapping):
        grades = {ref: int(grade) for ref, grade in relevant_refs.items()}
    else:
        grades = {ref: 1 for ref in relevant_refs}
    if any(grade < 0 for grade in grades.values()):
        raise ValueError("negative_relevance_grade")
    relevant = {ref for ref, grade in grades.items() if grade > 0}
    required = set(required_refs or relevant)
    groups = _deduplicated_groups(candidates, score_precision)
    candidate_count = sum(len(group.refs) for group in groups)

    expected_relevant = _expected_selected(groups, relevant, k)
    expected_required = _expected_selected(groups, required, k)
    hit = _expected_hit(groups, relevant, k)
    recall = expected_relevant / len(relevant) if relevant else 0.0
    precision = expected_relevant / k
    mrr = _expected_mrr(groups, relevant, k)
    dcg = _expected_dcg(groups, grades, k)
    ideal_gains = sorted(
        ((2**grade) - 1 for grade in grades.values() if grade > 0), reverse=True
    )[:k]
    ideal_dcg = sum(
        gain / math.log2(rank + 1) for rank, gain in enumerate(ideal_gains, start=1)
    )
    ndcg = dcg / ideal_dcg if ideal_dcg else 0.0
    coverage = expected_required / len(required) if required else 0.0

    return TieAwareMetrics(
        k=k,
        hit=hit,
        recall=recall,
        precision=precision,
        mrr=mrr,
        ndcg=ndcg,
        required_evidence_coverage=coverage,
        correct_abstention=(candidate_count == 0) if not answerable else None,
        false_evidence=(candidate_count > 0) if not answerable else None,
        candidate_count=candidate_count,
        tie_group_count=sum(len(group.refs) > 1 for group in groups),
    )
