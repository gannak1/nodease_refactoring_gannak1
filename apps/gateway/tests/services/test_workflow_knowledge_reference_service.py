import uuid
from types import SimpleNamespace

import pytest

from apps.gateway.services.workflow_knowledge_reference_service import (
    WorkflowKnowledgeReferenceService,
    WorkflowKnowledgeReferenceUnavailable,
)


def _graph(kb_id, collection_id):
    return {
        "nodes": [
            {
                "id": "llm",
                "type": "llmNode",
                "data": {
                    "knowledgeBases": [{"id": str(kb_id), "name": "KB"}],
                    "knowledgeCollections": [
                        {"id": str(collection_id), "safeLabel": "Collection"}
                    ],
                },
            }
        ]
    }


def _service(monkeypatch, *, allow_kb=True, allow_collection=True, ready=True):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    service = WorkflowKnowledgeReferenceService(
        None,
        user_id=user_id,
        organization_id=organization_id,
    )
    kb = SimpleNamespace(id=kb_id, organization_id=organization_id)
    collection = SimpleNamespace(id=collection_id, organization_id=organization_id)
    monkeypatch.setattr(service, "_load_direct_kbs", lambda ids: [kb])
    monkeypatch.setattr(service, "_load_collections", lambda ids: [collection])
    monkeypatch.setattr(
        service,
        "_retrieval_ready_ids",
        lambda ids: {kb_id} if ready else set(),
    )
    monkeypatch.setattr(
        service.permission_helper,
        "bulk_evaluate_kb_use",
        lambda kbs: {kb_id: SimpleNamespace(allowed=allow_kb)},
    )
    monkeypatch.setattr(
        service.permission_helper,
        "bulk_evaluate_collection_action",
        lambda collections, action: {
            collection_id: SimpleNamespace(allowed=allow_collection)
        },
    )
    return service, kb_id, collection_id


def test_editable_graph_checks_direct_use_readiness_and_collection_route(monkeypatch):
    service, kb_id, collection_id = _service(monkeypatch)

    parsed = service.validate_editable_graph(_graph(kb_id, collection_id))

    assert len(parsed) == 1
    assert parsed[0].direct_kb_ids == (kb_id,)
    assert parsed[0].collection_ids == (collection_id,)


@pytest.mark.parametrize(
    ("allow_kb", "allow_collection", "ready", "expected_field"),
    [
        (False, True, True, "graph.nodes[0].data.knowledgeBases[0]"),
        (True, True, False, "graph.nodes[0].data.knowledgeBases[0]"),
        (True, False, True, "graph.nodes[0].data.knowledgeCollections[0]"),
    ],
)
def test_unavailable_references_use_generic_code_and_index_path(
    monkeypatch,
    allow_kb,
    allow_collection,
    ready,
    expected_field,
):
    service, kb_id, collection_id = _service(
        monkeypatch,
        allow_kb=allow_kb,
        allow_collection=allow_collection,
        ready=ready,
    )

    with pytest.raises(WorkflowKnowledgeReferenceUnavailable) as error:
        service.validate_editable_graph(_graph(kb_id, collection_id))

    assert error.value.reason_code == "knowledge_reference_unavailable"
    assert error.value.field_path == expected_field
    assert str(kb_id) not in str(error.value)
    assert str(collection_id) not in str(error.value)


def test_empty_graph_does_not_query_permission_or_collection_children(monkeypatch):
    service = WorkflowKnowledgeReferenceService(
        None,
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(
        service,
        "_load_direct_kbs",
        lambda ids: pytest.fail("direct KB query must not run"),
    )
    monkeypatch.setattr(
        service,
        "_load_collections",
        lambda ids: pytest.fail("Collection query must not run"),
    )

    assert service.validate_editable_graph({"nodes": []}) == ()
