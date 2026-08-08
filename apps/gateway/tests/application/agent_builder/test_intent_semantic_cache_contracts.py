from __future__ import annotations

import pickle
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    IntentPlanL2SaveResult,
    IntentPlanL2StoredReceipt,
    IntentPlanSaveResult,
)
from apps.gateway.application.agent_builder.intent_semantic_cache import (
    SemanticExternalCallBinding,
    SemanticExternalCallAdmissionResult,
    SemanticQueryProjectionBuilder,
    SemanticVerificationResult,
)


def test_semantic_projection_accepts_exactly_240_code_points_without_slicing() -> None:
    projection = SemanticQueryProjectionBuilder().build("가" * 240)

    assert projection is not None
    assert projection.text == "가" * 240
    assert projection.version == "semantic-query-projection-v1"


def test_semantic_projection_rejects_241_code_points_with_a_different_tail() -> None:
    builder = SemanticQueryProjectionBuilder()

    assert builder.build(("가" * 240) + "아님") is None


@pytest.mark.parametrize(
    "message",
    [
        "Authorization: Bearer protected-value",
        "https://internal.example/private",
        "[REDACTED] request",
    ],
)
def test_semantic_projection_fails_closed_after_redaction(message: str) -> None:
    assert SemanticQueryProjectionBuilder().build(message) is None


def test_l2_stored_result_requires_an_opaque_same_transaction_receipt() -> None:
    receipt = IntentPlanL2StoredReceipt(
        parent_record_id=uuid4(),
        expires_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
        write_kind="inserted",
    )

    result = IntentPlanL2SaveResult(
        status="stored",
        receipt=receipt,
        reason=None,
    )

    assert result.status == "stored"
    assert result.receipt is receipt
    assert result.reason is None
    assert "parent_record_id" not in repr(receipt)
    assert "2026" not in repr(receipt)
    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.dumps(receipt)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "stored", "receipt": None, "reason": None},
        {
            "status": "unavailable",
            "receipt": IntentPlanL2StoredReceipt(
                parent_record_id=uuid4(),
                expires_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
                write_kind="unexpired_conflict",
            ),
            "reason": "cache_unavailable",
        },
        {"status": "unavailable", "receipt": None, "reason": None},
    ],
)
def test_l2_save_result_rejects_contradictory_states(kwargs) -> None:
    with pytest.raises((TypeError, ValueError)):
        IntentPlanL2SaveResult(**kwargs)


def test_l2_receipt_rejects_naive_expiry_and_unknown_write_kind() -> None:
    with pytest.raises((TypeError, ValueError)):
        IntentPlanL2StoredReceipt(
            parent_record_id=uuid4(),
            expires_at=datetime(2026, 9, 7),
            write_kind="inserted",
        )
    with pytest.raises((TypeError, ValueError)):
        IntentPlanL2StoredReceipt(
            parent_record_id=uuid4(),
            expires_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
            write_kind="unknown",
        )


def test_redis_save_result_does_not_gain_an_l2_receipt_field() -> None:
    redis_result = IntentPlanSaveResult(status="stored", reason=None)

    assert not hasattr(redis_result, "receipt")


@pytest.mark.parametrize(
    "decision",
    [
        SemanticExternalCallAdmissionResult(status="denied"),
        SemanticVerificationResult(status="uncertain"),
    ],
)
def test_transient_semantic_decisions_are_redacted_and_not_serializable(
    decision,
) -> None:
    assert "denied" not in repr(decision)
    assert "uncertain" not in repr(decision)
    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.dumps(decision)


def test_admitted_semantic_external_call_requires_an_opaque_binding() -> None:
    binding = SemanticExternalCallBinding(
        purpose="query_embedding",
    )

    admitted = SemanticExternalCallAdmissionResult(
        status="admitted",
        binding=binding,
    )

    assert admitted.binding is binding
    assert binding.purpose == "query_embedding"
    assert not hasattr(binding, "execution_ref")
    assert "query_embedding" not in repr(binding)
    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.dumps(binding)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "admitted", "binding": None},
        {
            "status": "denied",
            "binding": SemanticExternalCallBinding(
                purpose="query_embedding",
            ),
        },
        {
            "status": "unavailable",
            "binding": SemanticExternalCallBinding(
                purpose="semantic_verification",
            ),
        },
    ],
)
def test_semantic_external_call_admission_rejects_binding_state_mismatch(
    kwargs,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        SemanticExternalCallAdmissionResult(**kwargs)
