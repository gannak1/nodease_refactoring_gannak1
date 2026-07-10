from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

MODE_DISABLED = "disabled"
MODE_DRAIN = "drain"
MODE_CLAIM = "claim"
SCHEDULE_DISPATCH_MODES = frozenset({MODE_DISABLED, MODE_DRAIN, MODE_CLAIM})

STATUS_PENDING = "pending"
STATUS_DISPATCHING = "dispatching"
STATUS_ENQUEUED = "enqueued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_CANCELED = "canceled"
STATUS_DEAD_LETTERED = "dead_lettered"
SCHEDULE_DISPATCH_STATUSES = frozenset(
    {
        STATUS_PENDING,
        STATUS_DISPATCHING,
        STATUS_ENQUEUED,
        STATUS_RUNNING,
        STATUS_SUCCEEDED,
        STATUS_CANCELED,
        STATUS_DEAD_LETTERED,
    }
)
TERMINAL_STATUSES = frozenset(
    {STATUS_SUCCEEDED, STATUS_CANCELED, STATUS_DEAD_LETTERED}
)

REASON_BROKER_ENQUEUE_FAILED = "broker_enqueue_failed"
REASON_BUDGET_EVALUATION_FAILED = "budget_evaluation_failed"
REASON_BUDGET_BLOCKED = "budget_blocked"
REASON_SCHEDULE_NOT_FOUND = "schedule_not_found"
REASON_SCHEDULE_DEPLOYMENT_MISMATCH = "schedule_deployment_mismatch"
REASON_DEPLOYMENT_NOT_FOUND = "deployment_not_found"
REASON_DEPLOYMENT_INACTIVE = "deployment_inactive"
REASON_DEPLOYMENT_NOT_CURRENT = "deployment_not_current"
REASON_DEPLOYMENT_TYPE_NOT_ALLOWED = "deployment_type_not_allowed"
REASON_APP_NOT_FOUND = "app_not_found"
REASON_ORGANIZATION_SCOPE_MISSING = "organization_scope_missing"
REASON_ORGANIZATION_SCOPE_MISMATCH = "organization_scope_mismatch"
REASON_ENQUEUE_ATTEMPTS_EXHAUSTED = "enqueue_attempts_exhausted"
REASON_EXECUTION_FAILED_AFTER_ADMISSION = "execution_failed_after_admission"
REASON_EXECUTION_OUTCOME_UNKNOWN = "execution_outcome_unknown"

PENDING_REASONS = frozenset(
    {REASON_BROKER_ENQUEUE_FAILED, REASON_BUDGET_EVALUATION_FAILED}
)
CANCELED_REASONS = frozenset(
    {
        REASON_BUDGET_BLOCKED,
        REASON_SCHEDULE_NOT_FOUND,
        REASON_SCHEDULE_DEPLOYMENT_MISMATCH,
        REASON_DEPLOYMENT_NOT_FOUND,
        REASON_DEPLOYMENT_INACTIVE,
        REASON_DEPLOYMENT_NOT_CURRENT,
        REASON_DEPLOYMENT_TYPE_NOT_ALLOWED,
        REASON_APP_NOT_FOUND,
        REASON_ORGANIZATION_SCOPE_MISSING,
        REASON_ORGANIZATION_SCOPE_MISMATCH,
    }
)
DEAD_LETTER_REASONS = frozenset(
    {
        REASON_ENQUEUE_ATTEMPTS_EXHAUSTED,
        REASON_BUDGET_EVALUATION_FAILED,
        REASON_EXECUTION_FAILED_AFTER_ADMISSION,
        REASON_EXECUTION_OUTCOME_UNKNOWN,
    }
)
SCHEDULE_DISPATCH_REASONS = PENDING_REASONS | CANCELED_REASONS | DEAD_LETTER_REASONS

RESOLUTION_CONFIRMED_COMPLETED = "confirmed_completed"
RESOLUTION_CONFIRMED_FAILED_NO_REPLAY = "confirmed_failed_no_replay"
RESOLUTION_ACCEPTED_UNKNOWN_NO_REPLAY = "accepted_unknown_no_replay"
OUTCOME_RESOLUTIONS = frozenset(
    {
        RESOLUTION_CONFIRMED_COMPLETED,
        RESOLUTION_CONFIRMED_FAILED_NO_REPLAY,
        RESOLUTION_ACCEPTED_UNKNOWN_NO_REPLAY,
    }
)

_TRANSITIONS = {
    STATUS_PENDING: frozenset(
        {STATUS_DISPATCHING, STATUS_CANCELED, STATUS_DEAD_LETTERED}
    ),
    STATUS_DISPATCHING: frozenset(
        {
            STATUS_PENDING,
            STATUS_ENQUEUED,
            STATUS_RUNNING,
            STATUS_CANCELED,
            STATUS_DEAD_LETTERED,
        }
    ),
    STATUS_ENQUEUED: frozenset(
        {STATUS_PENDING, STATUS_RUNNING, STATUS_CANCELED, STATUS_DEAD_LETTERED}
    ),
    STATUS_RUNNING: frozenset({STATUS_SUCCEEDED, STATUS_DEAD_LETTERED}),
    STATUS_SUCCEEDED: frozenset(),
    STATUS_CANCELED: frozenset(),
    STATUS_DEAD_LETTERED: frozenset(),
}


class ScheduleDispatchDomainError(ValueError):
    pass


def canonical_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ScheduleDispatchDomainError("scheduled_for must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScheduleDispatchDomainError("scheduled_for must be timezone-aware")
    return value.astimezone(timezone.utc)


def schedule_idempotency_key(schedule_id: uuid.UUID, scheduled_for: datetime) -> str:
    if not isinstance(schedule_id, uuid.UUID):
        raise ScheduleDispatchDomainError("schedule_id must be a UUID")
    canonical_time = canonical_utc(scheduled_for)
    canonical_name = (
        f"nodease:schedule:{str(schedule_id).lower()}:"
        f"{canonical_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')}"
    )
    return f"schedule:{uuid.uuid5(uuid.NAMESPACE_URL, canonical_name)}"


def ensure_transition_allowed(current: str, target: str) -> None:
    if current not in SCHEDULE_DISPATCH_STATUSES:
        raise ScheduleDispatchDomainError("unknown current schedule dispatch status")
    if target not in SCHEDULE_DISPATCH_STATUSES:
        raise ScheduleDispatchDomainError("unknown target schedule dispatch status")
    if target not in _TRANSITIONS[current]:
        raise ScheduleDispatchDomainError("schedule dispatch transition is not allowed")


def retry_delay_seconds(attempt: int, *, base_seconds: int = 5) -> int:
    if attempt < 1:
        raise ScheduleDispatchDomainError("attempt must be positive")
    if not 1 <= base_seconds <= 300:
        raise ScheduleDispatchDomainError("retry base is outside the supported range")
    return min(base_seconds * (2 ** (attempt - 1)), 300)


@dataclass(frozen=True, slots=True)
class ScheduleDispatchSettings:
    mode: Literal["disabled", "drain", "claim"] = MODE_DISABLED
    poll_seconds: int = 5
    occurrence_batch_size: int = 50
    dispatch_batch_size: int = 10
    recovery_batch_size: int = 50
    cleanup_batch_size: int = 100
    lease_seconds: int = 60
    delivery_timeout_seconds: int = 120
    execution_deadline_seconds: int = 900
    workflow_run_visibility_timeout_seconds: int = 120
    max_attempts: int = 5
    retry_base_seconds: int = 5
    retention_days: int = 30
    dead_letter_retention_days: int = 180

    def __post_init__(self) -> None:
        if self.mode not in SCHEDULE_DISPATCH_MODES:
            raise ScheduleDispatchDomainError("unknown schedule dispatch mode")
        _range("poll_seconds", self.poll_seconds, 1, 60)
        _range("occurrence_batch_size", self.occurrence_batch_size, 1, 500)
        _range("dispatch_batch_size", self.dispatch_batch_size, 1, 100)
        _range("recovery_batch_size", self.recovery_batch_size, 1, 500)
        _range("cleanup_batch_size", self.cleanup_batch_size, 1, 1000)
        _range("lease_seconds", self.lease_seconds, 5, 300)
        _range("delivery_timeout_seconds", self.delivery_timeout_seconds, 30, 900)
        _range("execution_deadline_seconds", self.execution_deadline_seconds, 600, 86400)
        _range(
            "workflow_run_visibility_timeout_seconds",
            self.workflow_run_visibility_timeout_seconds,
            30,
            1800,
        )
        _range("max_attempts", self.max_attempts, 1, 20)
        _range("retry_base_seconds", self.retry_base_seconds, 1, 300)
        _range("retention_days", self.retention_days, 1, 365)
        _range(
            "dead_letter_retention_days",
            self.dead_letter_retention_days,
            30,
            3650,
        )
        if self.dead_letter_retention_days < self.retention_days:
            raise ScheduleDispatchDomainError(
                "dead-letter retention must not be shorter than terminal retention"
            )

    @property
    def claims_new_occurrences(self) -> bool:
        return self.mode == MODE_CLAIM

    @property
    def processes_existing_claims(self) -> bool:
        return self.mode in {MODE_DRAIN, MODE_CLAIM}


@dataclass(frozen=True, slots=True)
class ScheduleDispatchClaimState:
    status: str
    idempotency_key: str
    organization_id: uuid.UUID
    attempt_count: int = 0
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    execution_deadline_at: datetime | None = None
    next_attempt_at: datetime | None = None
    celery_task_id: str | None = None
    workflow_run_id: uuid.UUID | None = None
    safe_reason_code: str | None = None
    outcome_reviewed_at: datetime | None = None
    outcome_review_audit_id: uuid.UUID | None = None
    outcome_resolution_code: str | None = None
    claimed_at: datetime | None = None
    enqueued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def validate(self) -> None:
        if self.status not in SCHEDULE_DISPATCH_STATUSES:
            raise ScheduleDispatchDomainError("unknown schedule dispatch status")
        if not isinstance(self.organization_id, uuid.UUID):
            raise ScheduleDispatchDomainError("organization_id must be a UUID")
        if not self.idempotency_key.startswith("schedule:") or len(
            self.idempotency_key
        ) > 128:
            raise ScheduleDispatchDomainError("invalid schedule idempotency key")
        if self.attempt_count < 0:
            raise ScheduleDispatchDomainError("attempt_count must be non-negative")
        if self.claimed_at is None:
            raise ScheduleDispatchDomainError("claimed_at is required")
        if self.celery_task_id is not None and self.celery_task_id != self.idempotency_key:
            raise ScheduleDispatchDomainError("celery task id must match idempotency key")
        self._validate_status_fields()
        self._validate_reason()
        self._validate_outcome_review()
        self._validate_timestamps()

    def _validate_status_fields(self) -> None:
        if self.status == STATUS_PENDING:
            _require_none(
                self.lease_owner,
                self.lease_expires_at,
                self.execution_deadline_at,
                self.started_at,
                self.completed_at,
            )
        elif self.status == STATUS_DISPATCHING:
            _require_present(self.lease_owner, self.lease_expires_at, self.celery_task_id)
            _require_none(self.execution_deadline_at, self.started_at, self.completed_at)
        elif self.status == STATUS_ENQUEUED:
            _require_present(
                self.celery_task_id, self.enqueued_at, self.lease_expires_at
            )
            _require_none(
                self.lease_owner,
                self.execution_deadline_at,
                self.started_at,
                self.completed_at,
            )
        elif self.status == STATUS_RUNNING:
            _require_present(
                self.lease_owner,
                self.celery_task_id,
                self.workflow_run_id,
                self.enqueued_at,
                self.started_at,
                self.execution_deadline_at,
            )
            _require_none(self.lease_expires_at, self.completed_at)
        else:
            _require_present(self.completed_at)
            _require_none(
                self.lease_owner, self.lease_expires_at, self.execution_deadline_at
            )
            if self.status == STATUS_SUCCEEDED:
                _require_present(
                    self.workflow_run_id, self.enqueued_at, self.started_at
                )
            elif self.status == STATUS_CANCELED:
                _require_none(self.workflow_run_id, self.started_at)
            elif self.started_at is not None:
                _require_present(self.workflow_run_id, self.enqueued_at)
        if self.status != STATUS_PENDING and self.next_attempt_at is not None:
            raise ScheduleDispatchDomainError(
                "next_attempt_at is only valid for pending claims"
            )

    def _validate_reason(self) -> None:
        if self.status == STATUS_PENDING:
            if self.safe_reason_code is not None and self.safe_reason_code not in PENDING_REASONS:
                raise ScheduleDispatchDomainError("invalid pending reason")
        elif self.status == STATUS_CANCELED:
            if self.safe_reason_code not in CANCELED_REASONS:
                raise ScheduleDispatchDomainError("invalid canceled reason")
        elif self.status == STATUS_DEAD_LETTERED:
            if self.safe_reason_code not in DEAD_LETTER_REASONS:
                raise ScheduleDispatchDomainError("invalid dead-letter reason")
        elif self.safe_reason_code is not None:
            raise ScheduleDispatchDomainError("reason is not valid for this status")

    def _validate_outcome_review(self) -> None:
        fields = (
            self.outcome_reviewed_at,
            self.outcome_review_audit_id,
            self.outcome_resolution_code,
        )
        if any(value is not None for value in fields) and not all(
            value is not None for value in fields
        ):
            raise ScheduleDispatchDomainError("outcome review fields must be all-or-none")
        if all(value is None for value in fields):
            return
        if not (
            self.status == STATUS_DEAD_LETTERED
            and self.safe_reason_code == REASON_EXECUTION_OUTCOME_UNKNOWN
        ):
            raise ScheduleDispatchDomainError(
                "outcome review is only valid for unknown outcomes"
            )
        if self.outcome_resolution_code not in OUTCOME_RESOLUTIONS:
            raise ScheduleDispatchDomainError("unknown outcome resolution")

    def _validate_timestamps(self) -> None:
        values = (
            self.claimed_at,
            self.next_attempt_at,
            self.lease_expires_at,
            self.execution_deadline_at,
            self.enqueued_at,
            self.started_at,
            self.completed_at,
            self.outcome_reviewed_at,
        )
        for value in values:
            if value is not None:
                canonical_utc(value)
        ordered = (
            self.claimed_at,
            self.enqueued_at,
            self.started_at,
            self.completed_at,
        )
        previous = None
        for value in ordered:
            if value is None:
                continue
            current = canonical_utc(value)
            if previous is not None and current < previous:
                raise ScheduleDispatchDomainError("claim timestamps are not monotonic")
            previous = current


def _range(name: str, value: int, minimum: int, maximum: int) -> None:
    if not minimum <= value <= maximum:
        raise ScheduleDispatchDomainError(f"{name} is outside the supported range")


def _require_present(*values: object | None) -> None:
    if any(value is None for value in values):
        raise ScheduleDispatchDomainError("required claim field is missing")


def _require_none(*values: object | None) -> None:
    if any(value is not None for value in values):
        raise ScheduleDispatchDomainError("claim field is not valid for this status")
