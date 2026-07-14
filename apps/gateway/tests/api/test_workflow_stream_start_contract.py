from apps.gateway.api.v1.endpoints.workflow import _workflow_stream_started_event


def test_workflow_stream_start_event_exposes_only_run_identifier() -> None:
    event = _workflow_stream_started_event("11111111-1111-1111-1111-111111111111")

    assert event == {
        "type": "workflow_start",
        "data": {"run_id": "11111111-1111-1111-1111-111111111111"},
    }
