import logging

from apps.shared.audit import logger as audit_logger


def test_audit_publish_failure_does_not_log_raw_exception(monkeypatch, caplog):
    raw_detail = "private broker endpoint must not escape"
    monkeypatch.setattr(
        audit_logger.celery_app,
        "send_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(raw_detail)),
    )

    with caplog.at_level(logging.ERROR):
        audit_logger.record_audit("schedule.execute", "action")

    assert raw_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
