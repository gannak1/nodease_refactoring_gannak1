from apps.shared.services.tracing.payload import TracePayloadService
from apps.shared.services.tracing.policy import (
    ResolvedRedactionPolicy,
    ResolvedRetentionPolicy,
)


def test_payload_records_store_redacted_copy_without_raw_by_default():
    records = TracePayloadService.prepare_payload_records(
        [{"payload_kind": "input", "payload": {"email": "person@example.com"}}],
        redaction_policy=ResolvedRedactionPolicy(),
        retention_policy=ResolvedRetentionPolicy(),
        default_scope="trace",
    )

    assert len(records) == 1
    assert records[0]["redacted_payload"]["email"] == "[REDACTED]"
    assert records[0]["raw_payload_encrypted"] is None
    assert records[0]["storage_mode"] == "redacted_only"


def test_payload_records_are_append_only_envelopes_with_distinct_ids():
    records = TracePayloadService.prepare_payload_records(
        [
            {"payload_kind": "output", "payload": {"value": "first"}},
            {"payload_kind": "output", "payload": {"value": "second"}},
        ],
        redaction_policy=ResolvedRedactionPolicy(),
        retention_policy=ResolvedRetentionPolicy(),
        default_scope="span",
    )

    assert len(records) == 2
    assert records[0]["id"] != records[1]["id"]
    assert records[0]["sequence"] == 1
    assert records[1]["sequence"] == 2


def test_prompt_completion_disabled_stores_metadata_only():
    records = TracePayloadService.prepare_payload_records(
        [{"payload_kind": "prompt", "payload": {"messages": ["hello"]}}],
        redaction_policy=ResolvedRedactionPolicy(
            prompt_completion_storage_enabled=False
        ),
        retention_policy=ResolvedRetentionPolicy(),
        default_scope="span",
    )

    assert records[0]["redacted_payload"] is None
    assert records[0]["raw_payload_encrypted"] is None
    assert records[0]["storage_mode"] == "metadata_only"


def test_empty_payload_summary_reports_metadata_only():
    summary = TracePayloadService.summarize_payload_records([])

    assert summary["payload_storage_mode"] == "metadata_only"
    assert summary["redaction_applied"] is False


def test_secret_payload_never_gets_raw_storage_even_when_policy_allows_raw():
    records = TracePayloadService.prepare_payload_records(
        [{"payload_kind": "http_request", "payload": {"Authorization": "Bearer abc"}}],
        redaction_policy=ResolvedRedactionPolicy(
            raw_payload_storage_enabled=True,
            store_redacted_copy_only=False,
        ),
        retention_policy=ResolvedRetentionPolicy(),
        default_scope="span",
    )

    assert records[0]["secret_detected"] is True
    assert records[0]["raw_payload_encrypted"] is None
    assert records[0]["redacted_payload"]["Authorization"] == "[REDACTED]"
