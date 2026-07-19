from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from apps.workflow_engine.workflow.errors import NonRetryableWorkflowError


_SUBJECT_REQUIRED = "external_action_credential.execution_subject_required"


def required_external_action_credential_user_id(
    execution_context: Mapping[str, Any],
) -> uuid.UUID:
    """Resolve the user authorized to use an external action credential."""
    subject = execution_context.get("execution_subject")
    if subject is None and _is_schedule_execution(execution_context):
        subject = execution_context.get("credential_principal")

    if not isinstance(subject, Mapping):
        raise NonRetryableWorkflowError(_SUBJECT_REQUIRED)

    subject_type = subject.get("subject_type") or subject.get("type") or "user"
    subject_id = subject.get("subject_id") or subject.get("id")
    if subject_type != "user":
        raise NonRetryableWorkflowError(_SUBJECT_REQUIRED)
    try:
        return uuid.UUID(str(subject_id))
    except (TypeError, ValueError) as exc:
        raise NonRetryableWorkflowError(_SUBJECT_REQUIRED) from exc


def _is_schedule_execution(execution_context: Mapping[str, Any]) -> bool:
    trigger_mode = str(execution_context.get("trigger_mode") or "").lower()
    task_id = str(execution_context.get("workflow_task_id") or "")
    return (
        execution_context.get("user_id") is None
        and trigger_mode == "schedule"
        and task_id.startswith("schedule:")
    )
