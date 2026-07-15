from uuid import uuid4

import pytest
from apps.shared.schemas.agent_builder import (
    AgentBuilderParameterCandidate,
    AgentBuilderParameterTask,
    AgentBuilderParameterTaskDecisionRequest,
)
from pydantic import ValidationError


def test_parameter_task_decision_accepts_confirm_without_value():
    payload = AgentBuilderParameterTaskDecisionRequest.model_validate(
        {
            "operation_id": str(uuid4()),
            "expected_task_version": 2,
            "action": "confirm",
        }
    )

    assert payload.action == "confirm"
    assert payload.value is None


def test_parameter_task_decision_rejects_value_for_confirm():
    with pytest.raises(ValidationError, match="only set accepts a value"):
        AgentBuilderParameterTaskDecisionRequest.model_validate(
            {
                "operation_id": str(uuid4()),
                "expected_task_version": 2,
                "action": "confirm",
                "value": {"kind": "text", "value": "not-accepted"},
            }
        )


def test_parameter_select_decision_uses_value_and_rejects_option_id():
    payload = AgentBuilderParameterTaskDecisionRequest.model_validate(
        {
            "operation_id": str(uuid4()),
            "expected_task_version": 1,
            "action": "set",
            "value": {"kind": "select", "value": "default"},
        }
    )

    assert payload.value is not None
    assert payload.value.kind == "select"
    assert payload.value.value == "default"

    with pytest.raises(ValidationError):
        AgentBuilderParameterTaskDecisionRequest.model_validate(
            {
                "operation_id": str(uuid4()),
                "expected_task_version": 1,
                "action": "set",
                "value": {"kind": "select", "option_id": "default"},
            }
        )


def test_parameter_candidate_exposes_optional_graph_reference_value():
    candidate = AgentBuilderParameterCandidate.model_validate(
        {
            "candidate_id": str(uuid4()),
            "kind": "resource_ref",
            "label": "Available model",
            "reference_value": "provider-model-id",
        }
    )

    assert candidate.reference_value == "provider-model-id"


def test_parameter_task_accepts_only_safe_recommendation_fingerprint():
    task = AgentBuilderParameterTask.model_validate(
        {
            "task_id": str(uuid4()),
            "group_id": str(uuid4()),
            "step_id": "step-schedule",
            "node_id": "schedule",
            "node_type": "scheduleTrigger",
            "parameter_key": "timezone",
            "label": "Timezone",
            "input_type": "text",
            "required": True,
            "status": "active",
            "task_version": 1,
            "stable_order": 0,
            "resolution_source": "catalog_default",
            "recommendation_fingerprint": "a" * 64,
            "reason": "The schedule needs a timezone.",
            "input_guidance": "Confirm or change the timezone.",
        }
    )

    assert task.recommendation_fingerprint == "a" * 64

    with pytest.raises(ValidationError):
        AgentBuilderParameterTask.model_validate(
            {
                **task.model_dump(),
                "recommendation_fingerprint": "raw-value",
            }
        )
