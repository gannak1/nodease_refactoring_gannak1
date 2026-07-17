from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.evaluation.assessment_resolver import (
    Adjudication,
    AssessmentBundle,
    BlindAssessment,
    RequiredEvidence,
    resolve_assessments,
)
from tests.evaluation.schemas import BlindPoolArtifact, BlindPoolRecord


SHA = "sha256:" + "a" * 64


def pool():
    return BlindPoolArtifact(
        sealed_output_hash=SHA,
        depth=5,
        tie_precision=8,
        pool_seed=3,
        records=(
            BlindPoolRecord(
                question_id="q1",
                evidence_ref="ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            ),
            BlindPoolRecord(
                question_id="q1",
                evidence_ref="ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            ),
        ),
    )


def assessment(ref, assessor, relevance):
    return BlindAssessment(
        question_id="q1",
        evidence_ref=ref,
        assessor_ref=assessor,
        relevance=relevance,
    )


def bundle(**values):
    return AssessmentBundle(
        qrels_version="qrels-v1",
        role_separation_attested=True,
        **values,
    )


def resolve(value):
    return resolve_assessments(
        pool(),
        value,
        protocol_hash=SHA,
        dataset_hash=SHA,
    )


def test_two_assessors_and_adjudication_produce_frozen_qrels() -> None:
    a = "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    b = "ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assessment_bundle = bundle(
        assessments=(
            assessment(a, "assessor_left", 2),
            assessment(a, "assessor_right", 2),
            assessment(b, "assessor_left", 0),
            assessment(b, "assessor_right", 1),
        ),
        adjudications=(Adjudication(question_id="q1", evidence_ref=b, final_relevance=0),),
        required_evidence=(RequiredEvidence(question_id="q1", evidence_ref=a),),
    )
    resolved = resolve(assessment_bundle)
    assert resolved.summary.percent_agreement == pytest.approx(0.5)
    assert resolved.summary.adjudication_count == 1
    assert resolved.summary.pool_coverage == 1.0
    assert [item.relevance for item in resolved.qrels.records] == [2, 0]
    assert resolved.qrels.records[0].required is True


def test_missing_second_assessment_and_unresolved_disagreement_fail() -> None:
    a = "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    b = "ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    with pytest.raises(ValueError, match="exactly_two_assessors_required"):
        resolve(
            bundle(
                assessments=(
                    assessment(a, "assessor_left", 1),
                    assessment(b, "assessor_left", 0),
                )
            ),
        )
    with pytest.raises(ValueError, match="unresolved_assessment_disagreement"):
        resolve(
            bundle(
                assessments=(
                    assessment(a, "assessor_left", 1),
                    assessment(a, "assessor_right", 0),
                    assessment(b, "assessor_left", 0),
                    assessment(b, "assessor_right", 0),
                )
            ),
        )


def test_single_class_kappa_is_reported_as_undefined_without_metric_switching() -> None:
    a = "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    b = "ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    resolved = resolve(
        bundle(
            assessments=(
                assessment(a, "assessor_left", 0),
                assessment(a, "assessor_right", 0),
                assessment(b, "assessor_left", 0),
                assessment(b, "assessor_right", 0),
            )
        ),
    )
    assert resolved.summary.cohen_kappa is None
    assert resolved.summary.cohen_kappa_undefined_reason == "single_class_marginals"
    assert resolved.summary.gwet_ac1 == pytest.approx(1.0)


def test_required_evidence_must_be_relevant_and_inside_pool() -> None:
    a = "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    b = "ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    with pytest.raises(ValueError, match="required_evidence_not_relevant"):
        resolve(
            bundle(
                assessments=(
                    assessment(a, "assessor_left", 0),
                    assessment(a, "assessor_right", 0),
                    assessment(b, "assessor_left", 0),
                    assessment(b, "assessor_right", 0),
                ),
                required_evidence=(RequiredEvidence(question_id="q1", evidence_ref=a),),
            ),
        )


def test_uncertain_label_and_missing_role_separation_attestation_block_freeze() -> None:
    a = "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    b = "ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    with pytest.raises(ValueError, match="uncertain_assessment_unresolved"):
        resolve(
            bundle(
                assessments=(
                    assessment(a, "assessor_left", "uncertain"),
                    assessment(a, "assessor_right", 1),
                    assessment(b, "assessor_left", 0),
                    assessment(b, "assessor_right", 0),
                )
            )
        )

    with pytest.raises(ValidationError, match="role_separation_attested"):
        AssessmentBundle.model_validate(
            {
                "qrels_version": "qrels-v1",
                "assessments": [],
            }
        )
