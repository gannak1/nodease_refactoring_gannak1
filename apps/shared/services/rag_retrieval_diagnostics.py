"""Evaluation-only, redaction-safe retrieval diagnostics boundary."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Protocol

_OPAQUE_REF = re.compile(r"^ev:[0-9a-f]{32}$")
_SAFE_STAGE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class RetrievalDiagnosticError(RuntimeError):
    """Sanitized error raised when an injected evaluation observer fails."""

    def __init__(self) -> None:
        super().__init__("diagnostic_observer_failed")
        self.safe_reason_code = "diagnostic_observer_failed"


@dataclass(frozen=True)
class RetrievalDiagnosticCandidate:
    evidence_ref: str
    score: float

    def __post_init__(self) -> None:
        if not _OPAQUE_REF.fullmatch(self.evidence_ref):
            raise ValueError("invalid_diagnostic_evidence_ref")
        if not math.isfinite(self.score):
            raise ValueError("non_finite_diagnostic_score")


@dataclass(frozen=True)
class RetrievalDiagnosticEvent:
    stage: str
    requested_limit: int
    observed_count: int
    cutoff_score: float | None
    candidates: tuple[RetrievalDiagnosticCandidate, ...]
    tie_group_truncated: bool

    def __post_init__(self) -> None:
        if not _SAFE_STAGE.fullmatch(self.stage):
            raise ValueError("invalid_diagnostic_stage")
        if self.requested_limit <= 0 or self.observed_count < 0:
            raise ValueError("invalid_diagnostic_count")
        if self.cutoff_score is not None and not math.isfinite(self.cutoff_score):
            raise ValueError("non_finite_diagnostic_cutoff")


class RetrievalDiagnosticsObserver(Protocol):
    @property
    def scan_cap(self) -> int: ...

    @property
    def score_precision(self) -> int: ...

    def reference_for(self, stage: str, internal_id: str) -> str: ...

    def observe(self, event: RetrievalDiagnosticEvent) -> None: ...


def diagnostic_query_limit(
    requested_limit: int,
    observer: RetrievalDiagnosticsObserver | None,
) -> int:
    if requested_limit <= 0:
        raise ValueError("invalid_retrieval_limit")
    if observer is None:
        return requested_limit
    if observer.scan_cap < requested_limit or observer.scan_cap > 10_000:
        raise ValueError("invalid_diagnostic_scan_cap")
    if not 0 <= observer.score_precision <= 15:
        raise ValueError("invalid_diagnostic_score_precision")
    return observer.scan_cap + 1


def _canonical_score(score: float, precision: int) -> Decimal:
    if not math.isfinite(score):
        raise ValueError("non_finite_diagnostic_score")
    return Decimal(str(score)).quantize(
        Decimal(1).scaleb(-precision), rounding=ROUND_HALF_EVEN
    )


def observe_bounded_candidates(
    *,
    observer: RetrievalDiagnosticsObserver | None,
    stage: str,
    requested_limit: int,
    rows: list[tuple[str, float]],
) -> None:
    if observer is None:
        return
    try:
        scan_cap = observer.scan_cap
        score_precision = observer.score_precision
        if not 0 <= score_precision <= 15:
            raise ValueError("invalid_diagnostic_score_precision")
        canonical_scores = [
            _canonical_score(score, score_precision) for _internal_id, score in rows
        ]
        if any(
            left < right
            for left, right in zip(canonical_scores, canonical_scores[1:])
        ):
            raise ValueError("diagnostic_candidate_order_mismatch")
        visible_rows = rows[:scan_cap]
        candidates = tuple(
            RetrievalDiagnosticCandidate(
                evidence_ref=observer.reference_for(stage, internal_id),
                score=score,
            )
            for internal_id, score in visible_rows
        )
        cutoff_score = (
            visible_rows[requested_limit - 1][1]
            if len(visible_rows) >= requested_limit
            else None
        )
        tie_group_truncated = False
        if cutoff_score is not None and len(rows) > scan_cap:
            tie_group_truncated = _canonical_score(
                rows[scan_cap][1], score_precision
            ) == _canonical_score(cutoff_score, score_precision)
        observer.observe(
            RetrievalDiagnosticEvent(
                stage=stage,
                requested_limit=requested_limit,
                observed_count=len(visible_rows),
                cutoff_score=cutoff_score,
                candidates=candidates,
                tie_group_truncated=tie_group_truncated,
            )
        )
    except RetrievalDiagnosticError:
        raise
    except Exception as exc:
        raise RetrievalDiagnosticError() from exc


def vector_stage_name(
    chunk_levels: tuple[str | None, ...] | None,
    *,
    parent_ids_present: bool,
) -> str:
    levels = set(chunk_levels or ())
    if "parent" in levels:
        return "parent_candidate"
    if "child" in levels or parent_ids_present:
        return "child_expansion"
    if levels.intersection({None, "flat"}):
        return "flat_candidate"
    return "vector_candidate"


def keyword_stage_name(
    chunk_levels: tuple[str | None, ...] | None,
    *,
    parent_ids_present: bool,
) -> str:
    levels = set(chunk_levels or ())
    if "parent" in levels:
        return "parent_keyword_candidate"
    if "child" in levels or parent_ids_present:
        return "child_keyword_expansion"
    if levels.intersection({None, "flat"}):
        return "flat_keyword_candidate"
    return "keyword_candidate"
