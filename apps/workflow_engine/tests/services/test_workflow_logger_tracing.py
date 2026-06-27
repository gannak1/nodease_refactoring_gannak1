import uuid

from apps.workflow_engine.workflow.core.workflow_logger import WorkflowLogger


def test_policy_failure_disables_payload_capture_and_redacts_compat_fields(monkeypatch):
    captured = {}

    def raise_policy_error(*args, **kwargs):
        raise RuntimeError("policy_unavailable")

    def capture_submit(self, task_name, data, countdown=0):
        captured["task_name"] = task_name
        captured["data"] = data

    monkeypatch.setattr(
        "apps.workflow_engine.workflow.core.workflow_logger."
        "TracePolicyService.resolve_redaction_policy",
        raise_policy_error,
    )
    monkeypatch.setattr(WorkflowLogger, "_submit_log", capture_submit)

    logger = WorkflowLogger()
    logger.create_run_log(
        workflow_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        user_input={"email": "person@example.com"},
        is_deployed=False,
        execution_context={"app_id": str(uuid.uuid4())},
    )

    data = captured["data"]
    assert captured["task_name"] == "log.create_run"
    assert data["trace_payloads"] == []
    assert data["payload_storage_mode"] == "metadata_only"
    assert data["user_input"]["email"] == "[REDACTED]"


def test_create_run_log_sanitizes_run_trace_metadata(monkeypatch):
    captured = {}

    def capture_submit(self, task_name, data, countdown=0):
        captured["task_name"] = task_name
        captured["data"] = data

    monkeypatch.setattr(WorkflowLogger, "_submit_log", capture_submit)

    logger = WorkflowLogger()
    logger.create_run_log(
        workflow_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        user_input={"value": "hello"},
        is_deployed=False,
        execution_context={
            "app_id": str(uuid.uuid4()),
            "trace_metadata": {
                "gateway": {
                    "status_code": 200,
                    "response": {"body": "raw"},
                },
                "prompt": "raw prompt",
            },
        },
    )

    assert captured["task_name"] == "log.create_run"
    assert captured["data"]["trace_metadata"] == {"gateway": {"status_code": 200}}
