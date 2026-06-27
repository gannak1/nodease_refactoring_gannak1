import sys
import types
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from apps.shared.schemas.workflow import NodeSchema


if "gevent" not in sys.modules:
    gevent_stub = types.ModuleType("gevent")
    gevent_stub.Timeout = TimeoutError
    gevent_stub.sleep = lambda seconds: None
    pool_stub = types.ModuleType("gevent.pool")
    pool_stub.Pool = object
    queue_stub = types.ModuleType("gevent.queue")
    queue_stub.Queue = list
    sys.modules["gevent"] = gevent_stub
    sys.modules["gevent.pool"] = pool_stub
    sys.modules["gevent.queue"] = queue_stub

if "pymupdf4llm" not in sys.modules:
    pymupdf_stub = types.ModuleType("pymupdf4llm")
    pymupdf_stub.to_markdown = lambda *args, **kwargs: ""
    sys.modules["pymupdf4llm"] = pymupdf_stub

from apps.workflow_engine.workflow.core.workflow_engine import WorkflowEngine


def _engine_without_init():
    return object.__new__(WorkflowEngine)


def test_error_trace_metadata_excludes_raw_error_message():
    engine = _engine_without_init()
    started_at = datetime.now(timezone.utc)
    finished_at = datetime.now(timezone.utc)

    metadata = engine._build_error_trace_metadata(
        "modulyGuardrailNode",
        started_at,
        finished_at,
        RuntimeError("secret prompt token leaked"),
    )

    assert metadata["error"]["error_type"] == "RuntimeError"
    assert metadata["error"]["error_code"] == "node_error"
    assert "message" not in metadata["error"]
    assert "secret prompt token" not in str(metadata)
    assert metadata["guardrail"]["reason_redacted"] == "node_error"


def test_node_trace_metadata_applies_allowlist_and_denylist():
    engine = _engine_without_init()
    node = SimpleNamespace(
        _trace_metadata={
            "http": {
                "method": "POST",
                "status_code": 200,
                "body": "secret-body",
                "headers": {"authorization": "secret-token"},
            },
            "custom": {"content": "raw content"},
        }
    )

    metadata = engine._build_node_trace_metadata(
        "httpRequestNode",
        node,
        result={"body": "raw response"},
        process_data={},
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )

    assert metadata["http"]["method"] == "POST"
    assert metadata["http"]["status_code"] == 200
    assert "body" not in metadata["http"]
    assert "headers" not in metadata["http"]
    assert "custom" not in metadata
    assert "secret-body" not in str(metadata)
    assert "raw content" not in str(metadata)


def test_rag_metadata_keeps_source_fields_only():
    engine = _engine_without_init()
    node = SimpleNamespace(_trace_metadata={})

    metadata = engine._build_node_trace_metadata(
        "llmNode",
        node,
        result={
            "model": "test-model",
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            "metadata": {
                "knowledge_search": [
                    {
                        "knowledge_base_id": "kb-1",
                        "document_id": "doc-1",
                        "filename": "guide.pdf",
                        "page_number": 3,
                        "similarity_score": 0.8,
                        "content": "raw chunk text",
                        "body": "raw body",
                    }
                ]
            },
        },
        process_data={"provider": "test", "model": "test-model"},
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )

    retrieval = metadata["rag"]["retrieval_results"][0]
    assert retrieval == {
        "knowledge_base_id": "kb-1",
        "document_id": "doc-1",
        "filename": "guide.pdf",
        "page_number": 3,
        "similarity_score": 0.8,
    }
    assert "raw chunk text" not in str(metadata)


def test_tuple_graph_is_supported_explicitly():
    node = NodeSchema(
        id="start-1",
        type="startNode",
        position={"x": 0, "y": 0},
        data={"title": "Start"},
    )

    engine = WorkflowEngine(graph=([node], []))

    assert engine.node_schemas["start-1"].type == "startNode"
    engine.cleanup()


def test_running_node_timeout_closes_span_without_raw_message():
    engine = _engine_without_init()
    engine.is_subworkflow = False
    engine.logger = Mock()
    running_nodes = {
        "node-1": {
            "log_id": uuid.uuid4(),
            "node_type": "httpRequestNode",
            "inputs": {"url": "https://example.test"},
            "process_data": {},
            "started_at": datetime.now(timezone.utc),
            "sequence": 1,
        }
    }

    engine._mark_running_nodes_timeout(
        running_nodes, TimeoutError("secret timeout detail")
    )

    assert running_nodes == {}
    call = engine.logger.update_node_log_error.call_args
    assert call.args[2] == "timeout"
    trace_metadata = call.kwargs["trace_metadata"]
    assert trace_metadata["error"]["error_code"] == "timeout"
    assert "secret timeout detail" not in str(trace_metadata)
