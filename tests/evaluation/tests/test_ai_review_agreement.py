from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from tests.evaluation.ai_review_agreement import (
    AIReviewJudgment,
    build_adjudicated_summary,
    build_agreement_summary,
    load_review_jsonl,
)


def judgment(question_id: str, **updates) -> AIReviewJudgment:
    values = {
        "question_id": question_id,
        "semantic_review": "pass",
        "answerability_review": "confirm_answerable",
        "evidence_sufficiency_review": "sufficient",
        "temporal_scope_review": "clear",
        "decision": "accept",
        "confidence": "high",
        "reason_codes": ["none"],
        "proposed_evidence_refs": [],
    }
    values.update(updates)
    return AIReviewJudgment.model_validate(values)


def write_jsonl(path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_review_schema_rejects_unknown_or_inconsistent_values() -> None:
    with pytest.raises(ValidationError):
        judgment("q-1", unknown=True)
    with pytest.raises(ValidationError, match="accept_review_is_not_clean"):
        judgment("q-1", semantic_review="revise")
    with pytest.raises(ValidationError, match="non_accept_review_requires_reason"):
        judgment("q-1", decision="revise")
    with pytest.raises(ValidationError, match="review_values_must_be_sorted_unique"):
        judgment(
            "q-1",
            decision="revise",
            semantic_review="revise",
            reason_codes=["awkward_query", "awkward_query"],
        )


def test_review_schema_validates_opaque_proposed_evidence_refs() -> None:
    with pytest.raises(ValidationError, match="invalid_proposed_evidence_ref"):
        judgment(
            "q-1",
            decision="revise",
            semantic_review="revise",
            reason_codes=["missing_required_evidence"],
            proposed_evidence_refs=["raw-source-id"],
        )


def test_load_review_requires_complete_unique_jsonl(tmp_path) -> None:
    path = tmp_path / "review.jsonl"
    row = judgment("q-1").model_dump(mode="json")
    write_jsonl(path, [row, row])
    with pytest.raises(ValueError, match="duplicate_review_question_id"):
        load_review_jsonl(path)

    write_jsonl(path, [row])
    with pytest.raises(ValueError, match="review_question_count_mismatch"):
        load_review_jsonl(path, expected_count=2)


def test_load_review_error_does_not_echo_rejected_input(tmp_path) -> None:
    path = tmp_path / "review.jsonl"
    raw_sentinel = "RAW_QUERY_SENTINEL_MUST_NOT_LEAK"
    row = judgment("q-1").model_dump(mode="json")
    row["raw_query"] = raw_sentinel
    write_jsonl(path, [row])

    with pytest.raises(ValueError) as exc_info:
        load_review_jsonl(path)

    assert str(exc_info.value) == "invalid_review_row:1"
    assert raw_sentinel not in str(exc_info.value)


def test_agreement_summary_reports_safe_field_level_disagreements() -> None:
    pass_one = (judgment("q-1"), judgment("q-2"))
    pass_two = (
        judgment("q-1"),
        judgment(
            "q-2",
            semantic_review="revise",
            decision="revise",
            confidence="medium",
            reason_codes=["awkward_query"],
        ),
    )

    summary = build_agreement_summary(
        pass_one,
        pass_two,
        reviewer_model="gpt-5.6-sol",
        reasoning_effort="max",
        protocol_hash="sha256:" + "a" * 64,
    )

    assert summary["question_count"] == 2
    assert summary["substantive_exact_agreement_count"] == 1
    assert summary["all_field_exact_agreement_count"] == 1
    assert summary["field_agreement_rate"]["decision"] == 0.5
    assert summary["disagreements"] == [
        {
            "question_id": "q-2",
            "fields": ["confidence", "decision", "reason_codes", "semantic_review"],
        }
    ]
    serialized = json.dumps(summary, ensure_ascii=False)
    assert "raw question sentinel" not in serialized


def test_agreement_rejects_different_question_sets() -> None:
    with pytest.raises(ValueError, match="review_question_set_mismatch"):
        build_agreement_summary(
            (judgment("q-1"),),
            (judgment("q-2"),),
            reviewer_model="gpt-5.6-sol",
            reasoning_effort="max",
            protocol_hash="sha256:" + "a" * 64,
        )


def test_adjudication_replaces_only_disputed_rows() -> None:
    pass_one = (judgment("q-1"), judgment("q-2"))
    pass_two = (
        judgment("q-1"),
        judgment(
            "q-2",
            semantic_review="revise",
            decision="revise",
            confidence="medium",
            reason_codes=["awkward_query"],
        ),
    )
    adjudicated = (
        judgment(
            "q-2",
            semantic_review="revise",
            decision="revise",
            confidence="high",
            reason_codes=["awkward_query"],
        ),
    )

    final, summary = build_adjudicated_summary(
        pass_one,
        pass_two,
        adjudicated,
        reviewer_model="gpt-5.6-sol",
        reasoning_effort="max",
        protocol_hash="sha256:" + "a" * 64,
    )

    assert final == (pass_one[0], adjudicated[0])
    assert summary["adjudicated_question_count"] == 1
    assert summary["final_decision_counts"] == {"accept": 1, "revise": 1}


def test_adjudication_requires_exact_disagreement_set() -> None:
    with pytest.raises(ValueError, match="adjudication_question_set_mismatch"):
        build_adjudicated_summary(
            (judgment("q-1"),),
            (
                judgment(
                    "q-1",
                    semantic_review="revise",
                    decision="revise",
                    reason_codes=["awkward_query"],
                ),
            ),
            (judgment("q-unrelated"),),
            reviewer_model="gpt-5.6-sol",
            reasoning_effort="max",
            protocol_hash="sha256:" + "a" * 64,
        )
