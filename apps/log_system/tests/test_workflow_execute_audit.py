from types import SimpleNamespace
from uuid import uuid4

from apps.log_system.tasks import _record_workflow_execute_audit
from apps.shared.audit.actions import AuditAction
from apps.shared.db.models.workflow_run import RunTriggerMode


def test_record_workflow_execute_success_audit(monkeypatch):
    calls = []
    run = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        workflow_id=uuid4(),
        trigger_mode=RunTriggerMode.MANUAL,
        request_id="req-1",
        correlation_id="corr-1",
        error_message=None,
    )
    monkeypatch.setattr(
        "apps.log_system.tasks.record_audit",
        lambda **kwargs: calls.append(kwargs),
    )

    _record_workflow_execute_audit(run, "success")

    assert len(calls) == 1
    event = calls[0]
    assert event["action"] == AuditAction.WORKFLOW_EXECUTE
    assert event["actor_id"] == run.user_id
    assert event["target_type"] == "workflow"
    assert event["target_id"] == run.workflow_id
    assert event["status"] == "success"
    assert event["metadata"]["policy_result"] == "allow"
    assert event["metadata"]["workflow_run_id"] == str(run.id)
    assert event["metadata"]["trigger_mode"] == "manual"


def test_record_workflow_execute_failure_audit_omits_raw_error(monkeypatch):
    calls = []
    run = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        workflow_id=uuid4(),
        trigger_mode=RunTriggerMode.API,
        request_id=None,
        correlation_id=None,
        error_message="sensitive provider response",
    )
    monkeypatch.setattr(
        "apps.log_system.tasks.record_audit",
        lambda **kwargs: calls.append(kwargs),
    )

    _record_workflow_execute_audit(
        run,
        "failure",
        reason_code="workflow.execute_failed",
    )

    metadata = calls[0]["metadata"]
    assert calls[0]["status"] == "failure"
    assert metadata["reason_code"] == "workflow.execute_failed"
    assert metadata["error_present"] is True
    assert "sensitive provider response" not in str(metadata)


def test_system_schedule_execute_audit_has_no_user_actor(monkeypatch):
    calls = []
    run = SimpleNamespace(
        id=uuid4(),
        user_id=None,
        workflow_id=uuid4(),
        trigger_mode=RunTriggerMode.SCHEDULER,
        request_id=None,
        correlation_id=None,
        error_message=None,
    )
    monkeypatch.setattr(
        "apps.log_system.tasks.record_audit",
        lambda **kwargs: calls.append(kwargs),
    )

    _record_workflow_execute_audit(run, "success")

    assert calls[0]["actor_id"] is None
    assert calls[0]["actor_type"] == "system"
