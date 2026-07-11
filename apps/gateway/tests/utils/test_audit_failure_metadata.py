from fastapi import HTTPException

from apps.gateway.utils.audit import _safe_failure_metadata


class _CodedError(Exception):
    code = "mail.credential_persistence_failed"


def test_audit_failure_metadata_uses_safe_domain_code():
    assert _safe_failure_metadata(_CodedError("sensitive detail")) == {
        "error_code": "mail.credential_persistence_failed"
    }


def test_audit_failure_metadata_does_not_serialize_exception_detail():
    metadata = _safe_failure_metadata(
        RuntimeError("mailbox@example.test synthetic-ciphertext")
    )

    assert metadata == {"error_code": "internal.request_failed"}


def test_audit_failure_metadata_keeps_only_http_status():
    metadata = _safe_failure_metadata(
        HTTPException(status_code=409, detail="sensitive detail")
    )

    assert metadata == {
        "error_code": "http.request_failed",
        "status_code": 409,
    }
