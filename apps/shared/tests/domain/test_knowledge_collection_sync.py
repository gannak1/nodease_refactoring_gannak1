import pytest
from apps.shared.domain.knowledge_collection_sync import (
    KnowledgeCollectionSyncStateError,
    collection_sync_state_for_job,
    max_job_attempts_for_targets,
    progress_category,
    retry_delay,
    safe_reason_code,
    terminal_job_status,
)


@pytest.mark.parametrize(
    "processed,expected",
    [(0, "started"), (1, "started"), (3, "progressing"), (8, "most")],
)
def test_progress_is_categorical(processed, expected) -> None:
    assert (
        progress_category(
            status="running",
            total_count=10,
            completed_count=processed,
            failed_count=0,
            skipped_count=0,
        )
        == expected
    )


def test_terminal_progress_and_status_do_not_expose_exact_child_identity() -> None:
    assert (
        progress_category(
            status="partially_failed",
            total_count=10,
            completed_count=1,
            failed_count=1,
            skipped_count=8,
        )
        == "complete"
    )
    assert terminal_job_status(
        succeeded_count=1, failed_count=0, skipped_count=1
    ) == "partially_failed"
    assert collection_sync_state_for_job("partially_failed") == "stale"


def test_unknown_reason_is_default_deny_projected() -> None:
    assert safe_reason_code("raw connector failure") == "sync.internal_error"
    assert safe_reason_code(None) is None


def test_invalid_counts_and_retry_attempt_fail_closed() -> None:
    with pytest.raises(KnowledgeCollectionSyncStateError):
        progress_category(
            status="running",
            total_count=1,
            completed_count=2,
            failed_count=0,
            skipped_count=0,
        )
    with pytest.raises(KnowledgeCollectionSyncStateError):
        retry_delay(0)


def test_job_attempt_budget_covers_batches_item_retries_and_stale_recovery() -> None:
    assert max_job_attempts_for_targets(1) == 8
    assert max_job_attempts_for_targets(100) == 225
    with pytest.raises(KnowledgeCollectionSyncStateError):
        max_job_attempts_for_targets(101)
