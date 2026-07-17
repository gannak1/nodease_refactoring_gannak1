"""Validate and compare independent AI reviews without exposing benchmark text."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tests.evaluation.protocol import atomic_create_json, canonical_hash
from tests.evaluation.schemas import OPAQUE_EVIDENCE_PATTERN, SAFE_ID_PATTERN


SemanticReview = Literal["pass", "revise", "reject"]
AnswerabilityReview = Literal[
    "confirm_answerable",
    "confirm_unanswerable",
    "revise_to_answerable",
    "revise_to_unanswerable",
    "ambiguous",
]
EvidenceReview = Literal["sufficient", "insufficient", "excess", "not_applicable"]
TemporalReview = Literal["clear", "unclear", "not_applicable"]
Decision = Literal["accept", "revise", "reject"]
Confidence = Literal["high", "medium", "low"]
ReasonCode = Literal[
    "awkward_query",
    "ambiguous_scope",
    "answerability_mismatch",
    "missing_required_evidence",
    "excess_required_evidence",
    "invalid_evidence_ref",
    "temporal_scope_unclear",
    "legal_interpretation_risk",
    "duplicate_question",
    "none",
]

SUBSTANTIVE_FIELDS = (
    "semantic_review",
    "answerability_review",
    "evidence_sufficiency_review",
    "temporal_scope_review",
    "decision",
    "reason_codes",
    "proposed_evidence_refs",
)
ALL_REVIEW_FIELDS = (*SUBSTANTIVE_FIELDS, "confidence")


class AIReviewJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    question_id: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    semantic_review: SemanticReview
    answerability_review: AnswerabilityReview
    evidence_sufficiency_review: EvidenceReview
    temporal_scope_review: TemporalReview
    decision: Decision
    confidence: Confidence
    reason_codes: tuple[ReasonCode, ...]
    proposed_evidence_refs: tuple[str, ...] = ()

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or tuple(sorted(set(values))) != values:
            raise ValueError("review_values_must_be_sorted_unique")
        return values

    @field_validator("proposed_evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("review_values_must_be_sorted_unique")
        for value in values:
            if not re.fullmatch(OPAQUE_EVIDENCE_PATTERN, value):
                raise ValueError("invalid_proposed_evidence_ref")
        return values

    @model_validator(mode="after")
    def validate_decision_consistency(self) -> "AIReviewJudgment":
        has_none = "none" in self.reason_codes
        if has_none != (self.reason_codes == ("none",)):
            raise ValueError("none_reason_must_be_exclusive")
        if self.decision == "accept":
            if (
                self.semantic_review != "pass"
                or self.answerability_review
                not in {"confirm_answerable", "confirm_unanswerable"}
                or self.evidence_sufficiency_review
                not in {"sufficient", "not_applicable"}
                or self.temporal_scope_review not in {"clear", "not_applicable"}
                or not has_none
                or self.proposed_evidence_refs
            ):
                raise ValueError("accept_review_is_not_clean")
        elif has_none:
            raise ValueError("non_accept_review_requires_reason")

        if self.answerability_review == "confirm_answerable" and (
            self.evidence_sufficiency_review == "not_applicable"
        ):
            raise ValueError("answerable_review_requires_evidence_judgment")
        if self.answerability_review == "confirm_unanswerable" and (
            self.evidence_sufficiency_review != "not_applicable"
        ):
            raise ValueError("unanswerable_review_cannot_have_evidence_judgment")
        if self.semantic_review == "reject" and self.decision != "reject":
            raise ValueError("semantic_reject_requires_reject_decision")
        return self


def load_review_jsonl(
    path: str | Path,
    *,
    expected_count: int | None = None,
) -> tuple[AIReviewJudgment, ...]:
    records: list[AIReviewJudgment] = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            raise ValueError(f"empty_review_row:{line_number}")
        try:
            raw = json.loads(line)
            records.append(AIReviewJudgment.model_validate(raw))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid_review_row:{line_number}") from exc

    ids = [record.question_id for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_review_question_id")
    if expected_count is not None and len(records) != expected_count:
        raise ValueError("review_question_count_mismatch")
    return tuple(sorted(records, key=lambda record: record.question_id))


def _agreement_rate(
    pass_one: tuple[AIReviewJudgment, ...],
    pass_two: tuple[AIReviewJudgment, ...],
    field: str,
) -> float:
    matches = sum(
        getattr(left, field) == getattr(right, field)
        for left, right in zip(pass_one, pass_two, strict=True)
    )
    return round(matches / len(pass_one), 6)


def _cohens_kappa(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    observed = sum(a == b for a, b in zip(left, right, strict=True)) / len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum(
        (left_counts[label] / len(left)) * (right_counts[label] / len(right))
        for label in set(left_counts) | set(right_counts)
    )
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return round((observed - expected) / (1 - expected), 6)


def build_agreement_summary(
    pass_one: tuple[AIReviewJudgment, ...],
    pass_two: tuple[AIReviewJudgment, ...],
    *,
    reviewer_model: str,
    reasoning_effort: str,
    protocol_hash: str,
) -> dict[str, object]:
    if not pass_one or not pass_two:
        raise ValueError("empty_review_pass")
    ids_one = tuple(record.question_id for record in pass_one)
    ids_two = tuple(record.question_id for record in pass_two)
    if ids_one != ids_two:
        raise ValueError("review_question_set_mismatch")

    disagreements: list[dict[str, object]] = []
    substantive_matches = 0
    all_field_matches = 0
    for left, right in zip(pass_one, pass_two, strict=True):
        changed = [
            field
            for field in ALL_REVIEW_FIELDS
            if getattr(left, field) != getattr(right, field)
        ]
        substantive_changed = [field for field in changed if field in SUBSTANTIVE_FIELDS]
        substantive_matches += not substantive_changed
        all_field_matches += not changed
        if changed:
            disagreements.append(
                {"question_id": left.question_id, "fields": sorted(changed)}
            )

    count = len(pass_one)
    return {
        "schema_version": "1",
        "review_method": "independent_ai_two_pass",
        "reviewer_model": reviewer_model,
        "reasoning_effort": reasoning_effort,
        "protocol_hash": protocol_hash,
        "question_count": count,
        "pass_one_hash": canonical_hash(
            [record.model_dump(mode="json") for record in pass_one]
        ),
        "pass_two_hash": canonical_hash(
            [record.model_dump(mode="json") for record in pass_two]
        ),
        "field_agreement_rate": {
            field: _agreement_rate(pass_one, pass_two, field)
            for field in ALL_REVIEW_FIELDS
        },
        "substantive_exact_agreement_count": substantive_matches,
        "substantive_exact_agreement_rate": round(substantive_matches / count, 6),
        "all_field_exact_agreement_count": all_field_matches,
        "all_field_exact_agreement_rate": round(all_field_matches / count, 6),
        "decision_kappa": _cohens_kappa(
            tuple(record.decision for record in pass_one),
            tuple(record.decision for record in pass_two),
        ),
        "pass_one_decision_counts": dict(
            sorted(Counter(record.decision for record in pass_one).items())
        ),
        "pass_two_decision_counts": dict(
            sorted(Counter(record.decision for record in pass_two).items())
        ),
        "disagreements": disagreements,
    }


def build_adjudicated_summary(
    pass_one: tuple[AIReviewJudgment, ...],
    pass_two: tuple[AIReviewJudgment, ...],
    adjudication: tuple[AIReviewJudgment, ...],
    *,
    reviewer_model: str,
    reasoning_effort: str,
    protocol_hash: str,
) -> tuple[tuple[AIReviewJudgment, ...], dict[str, object]]:
    summary = build_agreement_summary(
        pass_one,
        pass_two,
        reviewer_model=reviewer_model,
        reasoning_effort=reasoning_effort,
        protocol_hash=protocol_hash,
    )
    expected_ids = tuple(
        item["question_id"] for item in summary["disagreements"]  # type: ignore[index]
    )
    adjudication_by_id = {record.question_id: record for record in adjudication}
    if tuple(sorted(adjudication_by_id)) != expected_ids:
        raise ValueError("adjudication_question_set_mismatch")

    final: list[AIReviewJudgment] = []
    for left, right in zip(pass_one, pass_two, strict=True):
        if all(
            getattr(left, field) == getattr(right, field)
            for field in ALL_REVIEW_FIELDS
        ):
            final.append(left)
        else:
            final.append(adjudication_by_id[left.question_id])

    final_records = tuple(final)
    summary.update(
        {
            "adjudication_method": "blind_ai_third_pass",
            "adjudicated_question_count": len(adjudication),
            "adjudication_hash": canonical_hash(
                [record.model_dump(mode="json") for record in adjudication]
            ),
            "final_review_hash": canonical_hash(
                [record.model_dump(mode="json") for record in final_records]
            ),
            "final_decision_counts": dict(
                sorted(Counter(record.decision for record in final_records).items())
            ),
            "final_answerability_counts": dict(
                sorted(
                    Counter(
                        record.answerability_review for record in final_records
                    ).items()
                )
            ),
            "final_reason_counts": dict(
                sorted(
                    Counter(
                        reason
                        for record in final_records
                        for reason in record.reason_codes
                    ).items()
                )
            ),
        }
    )
    return final_records, summary


def _file_sha256(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pass-one", required=True)
    parser.add_argument("--pass-two", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--adjudication")
    parser.add_argument("--final-output")
    parser.add_argument("--expected-count", type=int, default=100)
    parser.add_argument("--reviewer-model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="max")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.expected_count < 1:
        raise ValueError("invalid_expected_review_count")
    pass_one = load_review_jsonl(args.pass_one, expected_count=args.expected_count)
    pass_two = load_review_jsonl(args.pass_two, expected_count=args.expected_count)
    summary = build_agreement_summary(
        pass_one,
        pass_two,
        reviewer_model=args.reviewer_model,
        reasoning_effort=args.reasoning_effort,
        protocol_hash=_file_sha256(args.protocol),
    )
    if bool(args.adjudication) != bool(args.final_output):
        raise ValueError("adjudication_and_final_output_must_be_paired")
    if args.adjudication:
        adjudication = load_review_jsonl(args.adjudication)
        final_records, summary = build_adjudicated_summary(
            pass_one,
            pass_two,
            adjudication,
            reviewer_model=args.reviewer_model,
            reasoning_effort=args.reasoning_effort,
            protocol_hash=_file_sha256(args.protocol),
        )
        atomic_create_json(
            args.final_output,
            [record.model_dump(mode="json") for record in final_records],
        )
    atomic_create_json(args.output, summary)


if __name__ == "__main__":
    main()
