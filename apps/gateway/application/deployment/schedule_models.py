from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ScheduleDefinitionSnapshot:
    schedule_id: uuid.UUID
    deployment_id: uuid.UUID
    organization_id: uuid.UUID | None
    workflow_id: uuid.UUID | None
    deployment_type: object
    cron_expression: str
    timezone: str


@dataclass(frozen=True, slots=True)
class ScheduleOccurrenceSnapshot(ScheduleDefinitionSnapshot):
    scheduled_for: datetime


@dataclass(frozen=True, slots=True)
class DispatchClaimSnapshot:
    claim_id: uuid.UUID
    schedule_id: uuid.UUID
    deployment_id: uuid.UUID
    organization_id: uuid.UUID
    idempotency_key: str
    attempt_count: int
    status: str


@dataclass(frozen=True, slots=True)
class DispatchCanonicalContext:
    app_exists: bool
    schedule_id: uuid.UUID | None
    deployment_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    workflow_id: uuid.UUID | None
    deployment_type: object | None
    deployment_active: bool
    deployment_current: bool


@dataclass(frozen=True, slots=True)
class SchedulePublishRequest:
    claim_id: uuid.UUID
    task_id: str
    lease_owner: str


@dataclass(frozen=True, slots=True)
class SchedulePublishResult:
    claim_id: uuid.UUID
    task_id: str
    lease_owner: str
    accepted: bool


@dataclass(frozen=True, slots=True)
class WorkflowRunVisibilityGap:
    claim_id: uuid.UUID
    organization_id: uuid.UUID
    workflow_run_id: uuid.UUID
