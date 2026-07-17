"""Two-assessor blind relevance resolution with explicit adjudication."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tests.evaluation.judgment_pool import freeze_qrels
from tests.evaluation.protocol import canonical_hash
from tests.evaluation.schemas import (
    BlindPoolArtifact,
    OPAQUE_EVIDENCE_PATTERN,
    QrelRecord,
    QrelsArtifact,
    SAFE_ID_PATTERN,
    SHA256_PATTERN,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )


class BlindAssessment(_StrictModel):
    question_id: str = Field(pattern=SAFE_ID_PATTERN)
    evidence_ref: str = Field(pattern=OPAQUE_EVIDENCE_PATTERN)
    assessor_ref: str = Field(pattern=r"^assessor_[A-Za-z0-9_-]{4,32}$")
    relevance: Literal[0, 1, 2, "uncertain"]


class Adjudication(_StrictModel):
    question_id: str = Field(pattern=SAFE_ID_PATTERN)
    evidence_ref: str = Field(pattern=OPAQUE_EVIDENCE_PATTERN)
    final_relevance: int = Field(ge=0, le=2)


class RequiredEvidence(_StrictModel):
    question_id: str = Field(pattern=SAFE_ID_PATTERN)
    evidence_ref: str = Field(pattern=OPAQUE_EVIDENCE_PATTERN)


class AssessmentBundle(_StrictModel):
    schema_version: Literal["1"] = "1"
    qrels_version: str = Field(pattern=SAFE_ID_PATTERN)
    role_separation_attested: Literal[True]
    assessments: tuple[BlindAssessment, ...]
    adjudications: tuple[Adjudication, ...] = ()
    required_evidence: tuple[RequiredEvidence, ...] = ()


class AssessmentSummary(_StrictModel):
    schema_version: Literal["1"] = "1"
    pool_record_count: int = Field(ge=1)
    protocol_hash: str = Field(pattern=SHA256_PATTERN)
    dataset_hash: str = Field(pattern=SHA256_PATTERN)
    sealed_output_hash: str = Field(pattern=SHA256_PATTERN)
    judgment_pool_hash: str = Field(pattern=SHA256_PATTERN)
    qrels_version: str = Field(pattern=SAFE_ID_PATTERN)
    qrels_hash: str = Field(pattern=SHA256_PATTERN)
    role_separation_attested: Literal[True]
    assessment_count: int = Field(ge=2)
    assessor_count: Literal[2]
    agreement_count: int = Field(ge=0)
    disagreement_count: int = Field(ge=0)
    adjudication_count: int = Field(ge=0)
    unresolved_count: Literal[0]
    percent_agreement: float = Field(ge=0, le=1)
    cohen_kappa: float | None = Field(default=None, ge=-1, le=1)
    cohen_kappa_undefined_reason: str | None = Field(default=None, pattern=SAFE_ID_PATTERN)
    gwet_ac1: float = Field(ge=-1, le=1)
    pool_coverage: Literal[1.0]

    @model_validator(mode="after")
    def validate_kappa_reason(self) -> "AssessmentSummary":
        if (self.cohen_kappa is None) == (self.cohen_kappa_undefined_reason is None):
            raise ValueError("kappa_value_reason_exclusivity")
        return self


class ResolvedJudgments(_StrictModel):
    qrels: QrelsArtifact
    summary: AssessmentSummary


def resolve_assessments(
    pool: BlindPoolArtifact,
    bundle: AssessmentBundle,
    *,
    protocol_hash: str,
    dataset_hash: str,
) -> ResolvedJudgments:
    pool_keys = {(record.question_id, record.evidence_ref) for record in pool.records}
    assessors = sorted({record.assessor_ref for record in bundle.assessments})
    if len(assessors) != 2:
        raise ValueError("exactly_two_assessors_required")

    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for assessment in bundle.assessments:
        if assessment.relevance == "uncertain":
            raise ValueError("uncertain_assessment_unresolved")
        key = (assessment.question_id, assessment.evidence_ref)
        if key not in pool_keys:
            raise ValueError("assessment_outside_pool")
        if assessment.assessor_ref in grouped[key]:
            raise ValueError("duplicate_assessor_judgment")
        grouped[key][assessment.assessor_ref] = assessment.relevance
    if set(grouped) != pool_keys or any(len(values) != 2 for values in grouped.values()):
        raise ValueError("assessment_pool_coverage_mismatch")

    adjudications = {
        (item.question_id, item.evidence_ref): item.final_relevance
        for item in bundle.adjudications
    }
    if len(adjudications) != len(bundle.adjudications):
        raise ValueError("duplicate_adjudication")

    final: dict[tuple[str, str], int] = {}
    agreement_count = 0
    labels_by_assessor = {assessor: [] for assessor in assessors}
    disagreement_keys = set()
    for key in sorted(pool_keys):
        left = grouped[key][assessors[0]]
        right = grouped[key][assessors[1]]
        labels_by_assessor[assessors[0]].append(left)
        labels_by_assessor[assessors[1]].append(right)
        if left == right:
            agreement_count += 1
            final[key] = left
        else:
            disagreement_keys.add(key)
            if key not in adjudications:
                raise ValueError("unresolved_assessment_disagreement")
            final[key] = adjudications[key]
    if set(adjudications) != disagreement_keys:
        raise ValueError("adjudication_scope_mismatch")

    required_keys = {
        (item.question_id, item.evidence_ref) for item in bundle.required_evidence
    }
    if len(required_keys) != len(bundle.required_evidence):
        raise ValueError("duplicate_required_evidence")
    if not required_keys.issubset(pool_keys):
        raise ValueError("required_evidence_outside_pool")
    if any(final[key] <= 0 for key in required_keys):
        raise ValueError("required_evidence_not_relevant")

    qrels = freeze_qrels(
        pool,
        [
            QrelRecord(
                question_id=question_id,
                evidence_ref=evidence_ref,
                relevance=relevance,
                required=(question_id, evidence_ref) in required_keys,
            )
            for (question_id, evidence_ref), relevance in sorted(final.items())
        ],
        protocol_hash=protocol_hash,
        dataset_hash=dataset_hash,
        sealed_output_hash=pool.sealed_output_hash,
        qrels_version=bundle.qrels_version,
    )

    count = len(pool_keys)
    observed_agreement = agreement_count / count
    first_counts = Counter(labels_by_assessor[assessors[0]])
    second_counts = Counter(labels_by_assessor[assessors[1]])
    kappa_expected = sum(
        (first_counts[label] / count) * (second_counts[label] / count)
        for label in range(3)
    )
    if kappa_expected == 1:
        kappa = None
        kappa_reason = "single_class_marginals"
    else:
        kappa = (observed_agreement - kappa_expected) / (1 - kappa_expected)
        kappa_reason = None

    average_marginals = [
        (first_counts[label] + second_counts[label]) / (2 * count)
        for label in range(3)
    ]
    ac1_expected = sum(value * (1 - value) for value in average_marginals) / 2
    gwet_ac1 = (
        1.0
        if ac1_expected == 1
        else (observed_agreement - ac1_expected) / (1 - ac1_expected)
    )
    summary = AssessmentSummary(
        pool_record_count=count,
        protocol_hash=protocol_hash,
        dataset_hash=dataset_hash,
        sealed_output_hash=pool.sealed_output_hash,
        judgment_pool_hash=canonical_hash(pool),
        qrels_version=bundle.qrels_version,
        qrels_hash=canonical_hash(qrels),
        role_separation_attested=True,
        assessment_count=len(bundle.assessments),
        assessor_count=2,
        agreement_count=agreement_count,
        disagreement_count=len(disagreement_keys),
        adjudication_count=len(adjudications),
        unresolved_count=0,
        percent_agreement=observed_agreement,
        cohen_kappa=kappa,
        cohen_kappa_undefined_reason=kappa_reason,
        gwet_ac1=gwet_ac1,
        pool_coverage=1.0,
    )
    return ResolvedJudgments(qrels=qrels, summary=summary)
