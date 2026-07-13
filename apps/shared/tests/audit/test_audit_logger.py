import logging
from uuid import UUID

from apps.shared.audit import logger as audit_logger


def test_audit_id_is_created_before_publish_and_returned(monkeypatch):
    calls = []
    monkeypatch.setattr(
        audit_logger.celery_app,
        "send_task",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    audit_id = audit_logger.record_audit("schedule.execute", "action")

    assert isinstance(audit_id, UUID)
    assert len(calls) == 1
    task_args, task_kwargs = calls[0]
    assert task_args[0] == "audit.record"
    assert task_kwargs["args"][0]["id"] == str(audit_id)


def test_audit_publish_failure_does_not_log_raw_exception(monkeypatch, caplog):
    raw_detail = "private broker endpoint must not escape"
    monkeypatch.setattr(
        audit_logger.celery_app,
        "send_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(raw_detail)),
    )

    with caplog.at_level(logging.ERROR):
        audit_id = audit_logger.record_audit("schedule.execute", "action")

    assert audit_id is None
    assert raw_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
