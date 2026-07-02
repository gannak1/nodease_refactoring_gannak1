from apps.shared.services.tracing.policy import ResolvedRedactionPolicy
from apps.shared.services.tracing.redaction import TraceRedactionService


def test_redaction_masks_pii_and_sensitive_headers():
    result = TraceRedactionService.redact_payload(
        {
            "email": "person@example.com",
            "phone": "+82 10-1234-5678",
            "headers": {
                "Authorization": "Bearer should-not-survive",
                "X-API-Key": "should-not-survive",
            },
        },
        ResolvedRedactionPolicy(),
    )

    assert result.redaction_applied is True
    assert result.pii_detected is True
    assert result.secret_detected is True
    assert result.redacted_payload["email"] == "[REDACTED]"
    assert result.redacted_payload["phone"] == "[REDACTED]"
    assert result.redacted_payload["headers"]["Authorization"] == "[REDACTED]"
    assert result.redacted_payload["headers"]["X-API-Key"] == "[REDACTED]"


def test_secret_redaction_stays_enabled_when_policy_redaction_disabled():
    result = TraceRedactionService.redact_payload(
        {
            "password": "should-not-survive",
            "message": "person@example.com",
        },
        ResolvedRedactionPolicy(redaction_enabled=False, pii_detection_enabled=False),
    )

    assert result.secret_detected is True
    assert result.redacted_payload["password"] == "[REDACTED]"
    assert result.redacted_payload["message"] == "person@example.com"


def test_sensitive_json_path_redaction_records_metadata_without_values():
    result = TraceRedactionService.redact_payload(
        {"input": {"account": {"number": "1234567890"}}},
        ResolvedRedactionPolicy(sensitive_json_paths=("payload.input.account.number",)),
    )

    metadata = result.redaction_metadata["redaction"]
    assert result.redacted_payload["input"]["account"]["number"] == "[REDACTED]"
    assert "payload.input.account.number" in metadata["fields"]
    assert "1234567890" not in str(metadata)


def test_redaction_keeps_llm_usage_token_metrics():
    result = TraceRedactionService.redact_payload(
        {
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "total_tokens": 200,
                "prompt_tokens_details": {"cached_tokens": 10},
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
            "oauth_token": "should-not-survive",
        },
        ResolvedRedactionPolicy(),
    )

    assert result.secret_detected is True
    assert result.redacted_payload["usage"]["prompt_tokens"] == 120
    assert result.redacted_payload["usage"]["completion_tokens"] == 80
    assert result.redacted_payload["usage"]["total_tokens"] == 200
    assert result.redacted_payload["usage"]["prompt_tokens_details"] == {
        "cached_tokens": 10
    }
    assert result.redacted_payload["usage"]["completion_tokens_details"] == {
        "reasoning_tokens": 0
    }
    assert result.redacted_payload["oauth_token"] == "[REDACTED]"
