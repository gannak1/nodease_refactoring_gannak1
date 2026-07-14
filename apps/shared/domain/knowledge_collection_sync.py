from __future__ import annotations

from datetime import timedelta
from typing import Literal

KnowledgeCollectionSyncJobStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "partially_failed",
    "failed",
    "cancelled",
]
KnowledgeCollectionSyncItemStatus = Literal[
    "pending",
    "running",
    "succeeded",
    "failed",
    "skipped",
]
KnowledgeCollectionSyncProgress = Literal[
    "none",
    "started",
    "progressing",
    "most",
    "complete",
]

ACTIVE_JOB_STATUSES = frozenset({"queued", "running"})
TERMINAL_JOB_STATUSES = frozenset(
    {"succeeded", "partially_failed", "failed", "cancelled"}
)
TERMINAL_ITEM_STATUSES = frozenset({"succeeded", "failed", "skipped"})

MAX_SYNC_TARGETS = 100
SYNC_BATCH_SIZE = 5
DEFAULT_ITEM_MAX_ATTEMPTS = 3
STALE_JOB_RECOVERY_BUDGET = 5
DEFAULT_JOB_MAX_ATTEMPTS = (
    (MAX_SYNC_TARGETS + SYNC_BATCH_SIZE - 1) // SYNC_BATCH_SIZE
    + MAX_SYNC_TARGETS * (DEFAULT_ITEM_MAX_ATTEMPTS - 1)
    + STALE_JOB_RECOVERY_BUDGET
)
JOB_LEASE_SECONDS = 11 * 60
JOB_DEADLINE_SECONDS = 30 * 60
TERMINAL_RETENTION_DAYS = 30
RECOVERY_BATCH_SIZE = 25

SAFE_REASON_CODES = frozenset(
    {
        "sync.configuration_invalid",
        "sync.internal_error",
        "sync.no_eligible_targets",
        "sync.not_supported",
        "sync.permission_revoked",
        "sync.target_limit_exceeded",
        "sync.targets_changed",
        "sync.temporarily_unavailable",
        "sync.timeout",
        "sync.worker_interrupted",
    }
)


class KnowledgeCollectionSyncStateError(ValueError):
    pass


def max_job_attempts_for_targets(target_count: int) -> int:
    if target_count < 1 or target_count > MAX_SYNC_TARGETS:
        raise KnowledgeCollectionSyncStateError("sync target count is out of range")
    base_batches = (target_count + SYNC_BATCH_SIZE - 1) // SYNC_BATCH_SIZE
    item_retry_claims = target_count * (DEFAULT_ITEM_MAX_ATTEMPTS - 1)
    return base_batches + item_retry_claims + STALE_JOB_RECOVERY_BUDGET


def safe_reason_code(value: str | None) -> str | None:
    if value is None:
        return None
    if value in SAFE_REASON_CODES:
        return value
    return "sync.internal_error"


def progress_category(
    *,
    status: str,
    total_count: int,
    completed_count: int,
    failed_count: int,
    skipped_count: int,
) -> KnowledgeCollectionSyncProgress:
    counts = (total_count, completed_count, failed_count, skipped_count)
    if any(value < 0 for value in counts):
        raise KnowledgeCollectionSyncStateError("sync counts must be nonnegative")
    processed = completed_count + failed_count + skipped_count
    if processed > total_count:
        raise KnowledgeCollectionSyncStateError("processed sync count exceeds total")
    if status in TERMINAL_JOB_STATUSES:
        return "complete"
    if total_count == 0 or processed == 0:
        return "none" if status == "queued" else "started"
    ratio = processed / total_count
    if ratio < 0.25:
        return "started"
    if ratio < 0.75:
        return "progressing"
    if ratio < 1:
        return "most"
    return "complete"


def terminal_job_status(
    *,
    succeeded_count: int,
    failed_count: int,
    skipped_count: int,
) -> KnowledgeCollectionSyncJobStatus:
    if min(succeeded_count, failed_count, skipped_count) < 0:
        raise KnowledgeCollectionSyncStateError("sync counts must be nonnegative")
    if failed_count == 0 and skipped_count == 0:
        return "succeeded"
    if succeeded_count > 0:
        return "partially_failed"
    return "failed"


def collection_sync_state_for_job(status: str) -> str:
    mapping = {
        "queued": "pending",
        "running": "syncing",
        "succeeded": "synced",
        "partially_failed": "stale",
        "failed": "failed",
    }
    try:
        return mapping[status]
    except KeyError as exc:
        raise KnowledgeCollectionSyncStateError("job status has no collection state") from exc


def retry_delay(attempt_count: int) -> timedelta:
    if attempt_count < 1:
        raise KnowledgeCollectionSyncStateError("attempt count must be positive")
    return timedelta(seconds=min(15 * (2 ** (attempt_count - 1)), 5 * 60))
