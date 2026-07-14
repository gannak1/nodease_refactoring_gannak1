import json

from apps.gateway.api.v1.endpoints.workflow import (
    _serialize_workflow_sse_event,
    _workflow_stream_started_event,
)


def test_workflow_stream_start_event_exposes_only_run_identifier() -> None:
    event = _workflow_stream_started_event("11111111-1111-1111-1111-111111111111")

    assert event == {
        "type": "workflow_start",
        "data": {"run_id": "11111111-1111-1111-1111-111111111111"},
    }


def test_workflow_stream_start_event_uses_real_sse_record_delimiter() -> None:
    started = _serialize_workflow_sse_event(
        _workflow_stream_started_event("11111111-1111-1111-1111-111111111111")
    )
    next_event = _serialize_workflow_sse_event(
        {"type": "node_start", "data": {"node_id": "start"}}
    )

    records = [record for record in (started + next_event).split("\n\n") if record]

    assert len(records) == 2
    assert json.loads(records[0].removeprefix("data: "))["type"] == "workflow_start"
    assert json.loads(records[1].removeprefix("data: "))["type"] == "node_start"
    assert "\\n" not in started
