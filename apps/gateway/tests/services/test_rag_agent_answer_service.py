import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from apps.gateway.services import rag_agent_answer_service as service_module
from apps.gateway.services.rag_agent_answer_service import RAGAgentAnswerService
from apps.gateway.utils.api_errors import raise_api_error
from apps.shared.audit.actions import AuditAction
from apps.shared.schemas.rag import (
    ChunkPreview,
    RAGAgentAnswerRequest,
    RAGCitation,
    RAGRetrievalSummary,
    RAGUsageSummary,
)


class NoopDb:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.last_added = obj
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.last_refreshed = obj


class FakeRelationQuery:
    def __init__(self, value=None):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.value


class FakeRelationDb(NoopDb):
    def __init__(self, relation=None):
        super().__init__()
        self.relation = relation

    def query(self, *args, **kwargs):
        return FakeRelationQuery(self.relation)


def _request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.request_id = "test-request-id"
    return request


def _service() -> RAGAgentAnswerService:
    return RAGAgentAnswerService(
        db=NoopDb(),
        current_user=SimpleNamespace(id=uuid.uuid4()),
        request=_request(),
        organization_id=uuid.uuid4(),
    )


def _run() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        correlation_id="corr-1",
        status="running",
        knowledge_base_id=uuid.uuid4(),
    )


def _agent_payload(**overrides) -> RAGAgentAnswerRequest:
    values = {
        "knowledge_base_id": uuid.uuid4(),
        "query": "policy",
        "generation_model_id": uuid.uuid4(),
        "credential_id": uuid.uuid4(),
    }
    values.update(overrides)
    return RAGAgentAnswerRequest(**values)


def _visible_resources(payload: RAGAgentAnswerRequest, organization_id: uuid.UUID):
    kb = SimpleNamespace(
        id=payload.knowledge_base_id,
        name="KB",
        organization_id=organization_id,
    )
    model = SimpleNamespace(
        id=payload.generation_model_id,
        name="GPT Test",
        provider_name="openai",
        model_id_for_api_call="gpt-test",
        type="chat",
        is_active=True,
    )
    credential = SimpleNamespace(
        id=payload.credential_id,
        organization_id=organization_id,
        provider=SimpleNamespace(name="openai"),
        is_valid=True,
    )
    return kb, model, credential


@pytest.mark.parametrize("top_k", [0, 9])
def test_answer_rejects_top_k_outside_contract_before_run_creation(
    top_k, monkeypatch
):
    service = _service()
    payload = RAGAgentAnswerRequest(
        knowledge_base_id=uuid.uuid4(),
        query="policy",
        generation_model_id=uuid.uuid4(),
        credential_id=uuid.uuid4(),
        top_k=top_k,
    )
    create_run_called = False

    def fail_if_called(**kwargs):
        nonlocal create_run_called
        create_run_called = True

    monkeypatch.setattr(service, "_create_run", fail_if_called)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.answer(payload))

    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "validation.failed"
    assert exc.value.detail["error"]["details"] == {
        "field": "top_k",
        "min": service_module.MIN_TOP_K,
        "max": service_module.MAX_TOP_K,
    }
    assert create_run_called is False


@pytest.mark.parametrize("correlation_id", ["contains space", "trace-sk-testSecretValue"])
def test_answer_rejects_invalid_correlation_id_before_run_creation(
    correlation_id, monkeypatch
):
    service = _service()
    payload = RAGAgentAnswerRequest(
        knowledge_base_id=uuid.uuid4(),
        query="policy",
        generation_model_id=uuid.uuid4(),
        credential_id=uuid.uuid4(),
        correlation_id=correlation_id,
    )
    create_run_called = False

    def fail_if_called(**kwargs):
        nonlocal create_run_called
        create_run_called = True

    monkeypatch.setattr(service, "_create_run", fail_if_called)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.answer(payload))

    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "invalid_correlation_id"
    assert exc.value.detail["error"]["details"] == {"field": "correlation_id"}
    assert create_run_called is False


def test_prepare_execution_rejects_non_chat_model_before_run_creation(monkeypatch):
    service = _service()
    payload = _agent_payload()
    kb, model, credential = _visible_resources(payload, service.organization_id)
    model.type = "embedding"
    create_run_called = False

    def fail_if_called(**kwargs):
        nonlocal create_run_called
        create_run_called = True

    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_create_run", fail_if_called)

    with pytest.raises(HTTPException) as exc:
        service.prepare_execution(payload)

    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "validation.failed"
    assert exc.value.detail["error"]["details"] == {"field": "generation_model_id"}
    assert create_run_called is False


def test_prepare_execution_rejects_parent_child_without_run_creation(monkeypatch):
    service = _service()
    payload = _agent_payload(hierarchy_mode="parent_child")
    kb, model, credential = _visible_resources(payload, service.organization_id)
    create_run_called = False

    def fail_if_called(**kwargs):
        nonlocal create_run_called
        create_run_called = True

    def reject_hierarchy(*args):
        raise_api_error(
            service.request,
            422,
            "hierarchy_unavailable",
            "Hierarchical retrieval data is not available for this Knowledge Base.",
        )

    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_ensure_hierarchy_available", reject_hierarchy)
    monkeypatch.setattr(service, "_create_run", fail_if_called)

    with pytest.raises(HTTPException) as exc:
        service.prepare_execution(payload)

    assert exc.value.status_code == 422
    assert exc.value.detail["error"]["code"] == "hierarchy_unavailable"
    assert create_run_called is False


@pytest.mark.parametrize(
    ("failing_method", "message"),
    [
        ("_visible_knowledge_base", "Knowledge Base not found."),
        ("_visible_generation_model", "Generation model not found."),
        ("_visible_credential", "Credential not found."),
    ],
)
def test_prepare_execution_resource_hiding_errors_do_not_create_run(
    failing_method, message, monkeypatch
):
    service = _service()
    payload = _agent_payload()
    kb, model, credential = _visible_resources(payload, service.organization_id)
    create_run_called = False

    def raise_hidden(*_args):
        service._raise_not_found(message)

    def fail_if_called(**kwargs):
        nonlocal create_run_called
        create_run_called = True

    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, failing_method, raise_hidden)
    monkeypatch.setattr(service, "_create_run", fail_if_called)

    with pytest.raises(HTTPException) as exc:
        service.prepare_execution(payload)

    assert exc.value.status_code == 404
    assert exc.value.detail["error"]["code"] == "resource.not_found"
    assert create_run_called is False


def test_prepare_execution_blocks_kb_use_after_run_creation(monkeypatch):
    service = _service()
    payload = _agent_payload()
    kb, model, credential = _visible_resources(payload, service.organization_id)
    run = _run()
    run.status = "requested"
    lifecycle_actions = []
    denied_audits = []

    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_ensure_hierarchy_available", lambda *_: None)
    monkeypatch.setattr(service, "_create_run", lambda **_: run)
    monkeypatch.setattr(
        service,
        "_record_lifecycle",
        lambda action, *_args, **_kwargs: lifecycle_actions.append(action),
    )
    monkeypatch.setattr(
        service_module,
        "get_effective_knowledge_base_auth_state",
        lambda *args, **kwargs: "viewer",
    )
    monkeypatch.setattr(
        service_module,
        "record_resource_permission_denied",
        lambda **kwargs: denied_audits.append(kwargs),
    )
    monkeypatch.setattr(
        service,
        "_ensure_credential_use_and_relation",
        lambda *_: pytest.fail("credential preflight should not run after KB denial"),
    )

    with pytest.raises(HTTPException) as exc:
        service.prepare_execution(payload)

    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["code"] == "permission.denied"
    assert getattr(exc.value, "audit_recorded") is True
    assert run.status == "blocked"
    assert run.error_code == "kb_use_denied"
    assert lifecycle_actions == [AuditAction.RAG_ANSWER_REQUESTED]
    assert denied_audits[0]["resource_type"] == "knowledge_base"
    assert denied_audits[0]["action"] == "use"
    assert denied_audits[0]["metadata"]["reason_code"] == "kb_use_denied"


def test_prepare_execution_blocks_credential_use_after_run_creation(monkeypatch):
    service = RAGAgentAnswerService(
        db=FakeRelationDb(relation=SimpleNamespace(id=uuid.uuid4())),
        current_user=SimpleNamespace(id=uuid.uuid4()),
        request=_request(),
        organization_id=uuid.uuid4(),
    )
    payload = _agent_payload()
    kb, model, credential = _visible_resources(payload, service.organization_id)
    run = _run()
    run.status = "requested"
    denied_audits = []

    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_ensure_hierarchy_available", lambda *_: None)
    monkeypatch.setattr(service, "_create_run", lambda **_: run)
    monkeypatch.setattr(service, "_record_lifecycle", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_ensure_kb_use", lambda *_: None)
    monkeypatch.setattr(
        service_module,
        "get_effective_llm_credential_auth_state",
        lambda *args, **kwargs: "viewer",
    )
    monkeypatch.setattr(
        service_module,
        "llm_credential_auth_state_allows",
        lambda state, action: False,
    )
    monkeypatch.setattr(
        service_module,
        "record_resource_permission_denied",
        lambda **kwargs: denied_audits.append(kwargs),
    )

    with pytest.raises(HTTPException) as exc:
        service.prepare_execution(payload)

    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["code"] == "permission.denied"
    assert exc.value.detail["error"]["details"]["reason_code"] == (
        "credential_use_denied"
    )
    assert getattr(exc.value, "audit_recorded") is True
    assert run.status == "blocked"
    assert run.error_code == "credential_use_denied"
    assert denied_audits == [
        {
            "user_id": service.current_user.id,
            "resource_type": "llm_credential",
            "resource_id": credential.id,
            "action": "use",
            "effective_auth_state": "viewer",
            "organization_id": service.organization_id,
            "metadata": {
                "request_id": "test-request-id",
                "path": "/",
                "answer_run_id": str(run.id),
                "correlation_id": run.correlation_id,
                "reason_code": "credential_use_denied",
            },
        }
    ]


def test_prepare_execution_blocks_unverified_model_credential_relation(monkeypatch):
    service = RAGAgentAnswerService(
        db=FakeRelationDb(relation=None),
        current_user=SimpleNamespace(id=uuid.uuid4()),
        request=_request(),
        organization_id=uuid.uuid4(),
    )
    payload = _agent_payload()
    kb, model, credential = _visible_resources(payload, service.organization_id)
    run = _run()
    run.status = "requested"
    denied_audits = []

    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_ensure_hierarchy_available", lambda *_: None)
    monkeypatch.setattr(service, "_create_run", lambda **_: run)
    monkeypatch.setattr(service, "_record_lifecycle", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_ensure_kb_use", lambda *_: None)
    monkeypatch.setattr(
        service_module,
        "get_effective_llm_credential_auth_state",
        lambda *args, **kwargs: "operator",
    )
    monkeypatch.setattr(
        service_module,
        "llm_credential_auth_state_allows",
        lambda state, action: True,
    )
    monkeypatch.setattr(
        service_module,
        "record_resource_permission_denied",
        lambda **kwargs: denied_audits.append(kwargs),
    )

    with pytest.raises(HTTPException) as exc:
        service.prepare_execution(payload)

    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["details"]["reason_code"] == (
        "credential_model_relation_denied"
    )
    assert run.status == "blocked"
    assert run.error_code == "credential_model_relation_denied"
    assert denied_audits == [
        {
            "user_id": service.current_user.id,
            "resource_type": "llm_model",
            "resource_id": model.id,
            "action": "use",
            "effective_auth_state": "operator",
            "organization_id": service.organization_id,
            "metadata": {
                "request_id": "test-request-id",
                "path": "/",
                "answer_run_id": str(run.id),
                "correlation_id": run.correlation_id,
                "reason_code": "credential_model_relation_denied",
                "credential_id": str(credential.id),
            },
        }
    ]


def test_prepare_execution_marks_run_failed_on_unexpected_post_create_error(
    monkeypatch,
):
    service = _service()
    payload = _agent_payload(correlation_id="corr-preflight")
    kb, model, credential = _visible_resources(payload, service.organization_id)
    run = _run()
    run.status = "requested"
    run.correlation_id = payload.correlation_id
    lifecycle_actions = []

    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_ensure_hierarchy_available", lambda *_: None)
    monkeypatch.setattr(service, "_create_run", lambda **_: run)
    monkeypatch.setattr(
        service,
        "_record_lifecycle",
        lambda action, *_args, **_kwargs: lifecycle_actions.append(action),
    )
    monkeypatch.setattr(
        service,
        "_ensure_kb_use",
        lambda *_: (_ for _ in ()).throw(RuntimeError("credential secret leaked")),
    )
    monkeypatch.setattr(
        service,
        "_ensure_credential_use_and_relation",
        lambda *_: pytest.fail("credential preflight should not run after failure"),
    )

    with pytest.raises(HTTPException) as exc:
        service.prepare_execution(payload)

    assert exc.value.status_code == 500
    assert exc.value.detail["error"]["code"] == "generation.failed"
    assert exc.value.detail["error"]["message"] == "RAG answer preflight failed."
    assert "secret" not in exc.value.detail["error"]["message"]
    assert exc.value.detail["error"]["details"] == {
        "answer_run_id": str(run.id),
        "correlation_id": payload.correlation_id,
    }
    assert run.status == "failed"
    assert run.error_code == "generation.failed"
    assert lifecycle_actions == [
        AuditAction.RAG_ANSWER_REQUESTED,
        AuditAction.RAG_ANSWER_FAILED,
    ]


def test_content_preview_redacts_common_secret_shapes_and_caps_length():
    service = _service()
    preview = service._content_preview(
        "문의 user@example.com Authorization: Bearer abcdefghijkl "
        "api_key=plainSecret and sk-testSecretValue " + ("x" * 400)
    )

    assert "user@example.com" not in preview
    assert "plainSecret" not in preview
    assert "sk-testSecretValue" not in preview
    assert "Bearer abcdefghijkl" not in preview
    assert "[REDACTED]" in preview
    assert len(preview) <= 300


def test_policy_block_sets_audit_marker_and_never_persists_content_preview(monkeypatch):
    service = _service()
    run = _run()
    audit_calls = []
    monkeypatch.setattr(
        service_module,
        "record_audit",
        lambda **event: audit_calls.append(event),
    )
    citation = RAGCitation(
        citation_id="c1",
        document_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        rank=1,
        score=0.9,
        filename="policy.md",
        metadata_summary={"classification": "pii"},
        content_preview="redacted user-facing preview",
    )
    retrieval_summary = RAGRetrievalSummary(
        knowledge_base_id=uuid.uuid4(),
        hierarchy_mode="auto",
        retrieved_chunk_count=1,
        document_ids=[citation.document_id],
        citation_ids=["c1"],
        raw_content_returned=False,
    )

    with pytest.raises(HTTPException) as exc:
        service._block_policy(run, retrieval_summary, [citation])

    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["code"] == "policy.blocked"
    assert getattr(exc.value, "audit_recorded") is True
    assert run.status == "blocked"
    assert run.citation_summary == [
        citation.model_dump(mode="json", exclude={"content_preview"})
    ]
    assert "content_preview" not in run.citation_summary[0]
    assert audit_calls[0]["action"] == AuditAction.POLICY_BLOCK


def test_permission_block_returns_safe_error_details_and_audit_marker():
    service = _service()
    run = _run()

    with pytest.raises(HTTPException) as exc:
        service._block_permission(run, "kb_use_denied")

    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["code"] == "permission.denied"
    assert getattr(exc.value, "audit_recorded") is True
    assert run.status == "blocked"
    assert run.error_code == "kb_use_denied"
    assert exc.value.detail["error"]["details"] == {
        "answer_run_id": str(run.id),
        "correlation_id": "corr-1",
        "status": "blocked",
        "reason_code": "kb_use_denied",
    }


def test_context_for_chunks_respects_internal_token_budget():
    service = _service()
    chunks = [
        SimpleNamespace(content="first", token_count=7900),
        SimpleNamespace(content="second", token_count=200),
    ]

    assert service._context_for_chunks(chunks) == "first"


def test_record_usage_log_keeps_rag_answer_fk_out_of_usage_domain():
    service = _service()
    model_id = uuid.uuid4()
    credential_id = uuid.uuid4()

    service._record_usage_log(
        SimpleNamespace(id=model_id),
        SimpleNamespace(id=credential_id),
        prompt_tokens=3,
        completion_tokens=4,
        total_cost=0.001,
        latency_ms=12,
    )

    usage_log = service.db.added[-1]
    assert usage_log.user_id == service.current_user.id
    assert usage_log.organization_id == service.organization_id
    assert usage_log.model_id == model_id
    assert usage_log.credential_id == credential_id
    assert usage_log.workflow_id is None
    assert usage_log.workflow_run_id is None
    assert not hasattr(usage_log, "rag_answer_run_id")


def test_record_retrieval_does_not_prejudge_policy_result(monkeypatch):
    service = _service()
    run = _run()
    audit_calls = []
    monkeypatch.setattr(
        service_module,
        "record_audit",
        lambda **event: audit_calls.append(event),
    )

    service._record_retrieval(run, metadata_filter=None, result_count=1, mode="auto")

    metadata = audit_calls[0]["metadata"]
    assert audit_calls[0]["action"] == AuditAction.RAG_RETRIEVE
    assert metadata["result_count"] == 1
    assert "policy_result" not in metadata


def test_generate_answer_enforces_provider_timeout(monkeypatch):
    service = _service()
    run = _run()
    model = SimpleNamespace(
        id=uuid.uuid4(),
        name="GPT Test",
        provider_name="openai",
        model_id_for_api_call="gpt-test",
    )
    credential = SimpleNamespace(id=uuid.uuid4())
    payload = RAGAgentAnswerRequest(
        knowledge_base_id=uuid.uuid4(),
        query="policy",
        generation_model_id=model.id,
        credential_id=credential.id,
    )
    llm_audits = []

    class SlowClient:
        async def invoke(self, *args, **kwargs):
            await asyncio.sleep(0.05)
            return {}

    monkeypatch.setattr(service_module, "PROVIDER_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(service, "_client_for", lambda *_: SlowClient())
    monkeypatch.setattr(
        service,
        "_record_llm_call",
        lambda *_args, **kwargs: llm_audits.append(kwargs),
    )

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(service._generate_answer(payload, [], model, credential, run))

    assert llm_audits == [{"status": "failure"}]


def test_stream_events_emits_terminal_error_on_idle_timeout(monkeypatch):
    service = _service()
    run = _run()
    payload = RAGAgentAnswerRequest(
        knowledge_base_id=uuid.uuid4(),
        query="policy",
        generation_model_id=uuid.uuid4(),
        credential_id=uuid.uuid4(),
    )
    execution = service_module.RAGAnswerExecution(
        payload=payload,
        correlation_id=run.correlation_id,
        metadata_filter=None,
        kb=SimpleNamespace(id=payload.knowledge_base_id),
        model=SimpleNamespace(),
        credential=SimpleNamespace(),
        run=run,
    )

    class SlowRetrievalService:
        def __init__(self, *args, **kwargs):
            pass

        async def search_documents(self, *args, **kwargs):
            await asyncio.sleep(0.05)
            return []

    monkeypatch.setattr(service_module, "RetrievalService", SlowRetrievalService)
    monkeypatch.setattr(service_module, "SSE_IDLE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(service, "_record_lifecycle", lambda *args, **kwargs: None)

    async def collect():
        return [event async for event in service.stream_events(execution)]

    events = asyncio.run(collect())

    assert events[0][0] == "retrieval.started"
    assert events[1] == (
        "error",
        {
            "answer_run_id": str(run.id),
            "correlation_id": run.correlation_id,
            "status": "failed",
            "reason_code": "stream.timeout",
            "retryable": True,
        },
    )
    assert run.status == "failed"
    assert run.error_code == "stream.timeout"


def test_stream_events_classifies_generation_timeout_as_provider_timeout(monkeypatch):
    service = _service()
    run = _run()
    payload = RAGAgentAnswerRequest(
        knowledge_base_id=uuid.uuid4(),
        query="policy",
        generation_model_id=uuid.uuid4(),
        credential_id=uuid.uuid4(),
    )
    chunk = ChunkPreview(
        chunk_id=uuid.uuid4(),
        content="evidence",
        document_id=uuid.uuid4(),
        filename="policy.md",
        similarity_score=0.9,
        score=0.9,
        rank=1,
        metadata_summary={"classification": "internal"},
    )
    execution = service_module.RAGAnswerExecution(
        payload=payload,
        correlation_id=run.correlation_id,
        metadata_filter=None,
        kb=SimpleNamespace(id=payload.knowledge_base_id),
        model=SimpleNamespace(
            id=payload.generation_model_id,
            name="GPT Test",
            provider_name="openai",
        ),
        credential=SimpleNamespace(id=payload.credential_id),
        run=run,
    )

    class FakeRetrievalService:
        def __init__(self, *args, **kwargs):
            pass

        async def search_documents(self, *args, **kwargs):
            return [chunk]

    async def timeout_generate_answer(*args, **kwargs):
        raise asyncio.TimeoutError

    monkeypatch.setattr(service_module, "RetrievalService", FakeRetrievalService)
    monkeypatch.setattr(service, "_record_retrieval", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_record_lifecycle", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_generate_answer", timeout_generate_answer)

    async def collect():
        return [event async for event in service.stream_events(execution)]

    events = asyncio.run(collect())

    assert events[-1] == (
        "error",
        {
            "answer_run_id": str(run.id),
            "correlation_id": run.correlation_id,
            "status": "failed",
            "reason_code": "provider.timeout",
            "retryable": True,
        },
    )
    assert run.status == "failed"
    assert run.error_code == "provider.timeout"


def test_stream_events_success_contract_excludes_internal_usage_ids(monkeypatch):
    service = _service()
    run = _run()
    payload = _agent_payload(correlation_id=run.correlation_id)
    model = SimpleNamespace(
        id=payload.generation_model_id,
        name="GPT Test",
        provider_name="openai",
    )
    credential = SimpleNamespace(id=payload.credential_id)
    chunk = ChunkPreview(
        chunk_id=uuid.uuid4(),
        content="safe evidence",
        document_id=uuid.uuid4(),
        filename="policy.md",
        similarity_score=0.9,
        score=0.9,
        rank=1,
        metadata_summary={"classification": "internal"},
    )
    execution = service_module.RAGAnswerExecution(
        payload=payload,
        correlation_id=run.correlation_id,
        metadata_filter=None,
        kb=SimpleNamespace(id=payload.knowledge_base_id),
        model=model,
        credential=credential,
        run=run,
    )

    class FakeRetrievalService:
        def __init__(self, *args, **kwargs):
            pass

        async def search_documents(self, *args, **kwargs):
            return [chunk]

    async def fake_generate_answer(*args, **kwargs):
        return "요약 답변", RAGUsageSummary(
            prompt_tokens=3,
            completion_tokens=4,
            total_tokens=7,
            total_cost=0.001,
            latency_ms=10,
            model_name=model.name,
            provider=model.provider_name,
        )

    monkeypatch.setattr(service_module, "RetrievalService", FakeRetrievalService)
    monkeypatch.setattr(service, "_record_retrieval", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_record_lifecycle", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_generate_answer", fake_generate_answer)

    async def collect():
        return [event async for event in service.stream_events(execution)]

    events = asyncio.run(collect())
    event_names = [event_name for event_name, _payload in events]

    assert event_names == [
        "retrieval.started",
        "retrieval.completed",
        "answer.delta",
        "usage",
        "summary",
        "answer.completed",
    ]
    assert events[2][1]["index"] == 0
    assert "credential_id" not in events[3][1]["usage_summary"]
    assert "model_id" not in events[3][1]["usage_summary"]
    assert "content_preview" not in events[4][1]["citation_summary"][0]
    assert run.usage_summary["credential_id"] == str(credential.id)
    assert run.usage_summary["model_id"] == str(model.id)


def test_answer_provider_timeout_marks_failed_and_returns_safe_error(monkeypatch):
    service = _service()
    payload = _agent_payload(correlation_id="corr-timeout")
    kb, model, credential = _visible_resources(payload, service.organization_id)
    run = _run()
    run.correlation_id = payload.correlation_id
    chunk = ChunkPreview(
        chunk_id=uuid.uuid4(),
        content="evidence",
        document_id=uuid.uuid4(),
        filename="policy.md",
        similarity_score=0.9,
        score=0.9,
        rank=1,
        metadata_summary={"classification": "internal"},
    )
    lifecycle_actions = []

    class FakeRetrievalService:
        def __init__(self, *args, **kwargs):
            pass

        async def search_documents(self, *args, **kwargs):
            return [chunk]

    async def timeout_generate_answer(*args, **kwargs):
        raise asyncio.TimeoutError

    monkeypatch.setattr(service_module, "RetrievalService", FakeRetrievalService)
    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_ensure_generation_model", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_hierarchy_available", lambda *_: None)
    monkeypatch.setattr(service, "_create_run", lambda **_: run)
    monkeypatch.setattr(service, "_ensure_kb_use", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_credential_use_and_relation", lambda *_: None)
    monkeypatch.setattr(service, "_record_retrieval", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_generate_answer", timeout_generate_answer)
    monkeypatch.setattr(
        service,
        "_record_lifecycle",
        lambda action, *_args, **_kwargs: lifecycle_actions.append(action),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.answer(payload))

    assert exc.value.status_code == 504
    assert exc.value.detail["error"]["code"] == "provider.timeout"
    assert exc.value.detail["error"]["details"] == {
        "answer_run_id": str(run.id),
        "correlation_id": payload.correlation_id,
    }
    assert run.status == "failed"
    assert run.error_code == "provider.timeout"
    assert lifecycle_actions == [
        AuditAction.RAG_ANSWER_REQUESTED,
        AuditAction.RAG_ANSWER_FAILED,
    ]


def test_answer_retrieval_timeout_is_sanitized_generation_failure(monkeypatch):
    service = _service()
    payload = _agent_payload(correlation_id="corr-retrieval-timeout")
    kb, model, credential = _visible_resources(payload, service.organization_id)
    run = _run()
    run.correlation_id = payload.correlation_id
    lifecycle_actions = []

    class TimeoutRetrievalService:
        def __init__(self, *args, **kwargs):
            pass

        async def search_documents(self, *args, **kwargs):
            raise asyncio.TimeoutError

    monkeypatch.setattr(service_module, "RetrievalService", TimeoutRetrievalService)
    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_ensure_generation_model", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_hierarchy_available", lambda *_: None)
    monkeypatch.setattr(service, "_create_run", lambda **_: run)
    monkeypatch.setattr(service, "_ensure_kb_use", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_credential_use_and_relation", lambda *_: None)
    monkeypatch.setattr(
        service,
        "_generate_answer",
        lambda *args, **kwargs: pytest.fail("retrieval timeout must not call LLM"),
    )
    monkeypatch.setattr(
        service,
        "_record_lifecycle",
        lambda action, *_args, **_kwargs: lifecycle_actions.append(action),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.answer(payload))

    rendered_detail = str(exc.value.detail)
    assert exc.value.status_code == 500
    assert exc.value.detail["error"]["code"] == "generation.failed"
    assert "provider.timeout" not in rendered_detail
    assert run.status == "failed"
    assert run.error_code == "generation.failed"
    assert lifecycle_actions == [
        AuditAction.RAG_ANSWER_REQUESTED,
        AuditAction.RAG_ANSWER_FAILED,
    ]


def test_answer_no_retrieval_results_completes_without_llm_call_or_usage_log(
    monkeypatch,
):
    service = _service()
    payload = _agent_payload(correlation_id="corr-empty")
    kb, model, credential = _visible_resources(payload, service.organization_id)
    run = _run()
    run.correlation_id = payload.correlation_id
    lifecycle_actions = []
    retrieval_audits = []

    class EmptyRetrievalService:
        def __init__(self, *args, **kwargs):
            pass

        async def search_documents(self, *args, **kwargs):
            return []

    monkeypatch.setattr(service_module, "RetrievalService", EmptyRetrievalService)
    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_ensure_generation_model", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_hierarchy_available", lambda *_: None)
    monkeypatch.setattr(service, "_create_run", lambda **_: run)
    monkeypatch.setattr(service, "_ensure_kb_use", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_credential_use_and_relation", lambda *_: None)
    monkeypatch.setattr(
        service,
        "_generate_answer",
        lambda *args, **kwargs: pytest.fail("empty retrieval must not call LLM"),
    )
    monkeypatch.setattr(
        service,
        "_record_usage_log",
        lambda *args, **kwargs: pytest.fail("empty retrieval must not log usage"),
    )
    monkeypatch.setattr(
        service,
        "_record_lifecycle",
        lambda action, *_args, **_kwargs: lifecycle_actions.append(action),
    )
    monkeypatch.setattr(
        service,
        "_record_retrieval",
        lambda *_args, **_kwargs: retrieval_audits.append(True),
    )

    response = asyncio.run(service.answer(payload))

    assert response.status == "completed"
    assert response.citations == []
    assert response.retrieval_summary.retrieved_chunk_count == 0
    assert response.usage_summary.total_tokens == 0
    assert "credential_id" not in response.usage_summary.model_dump(mode="json")
    assert run.status == "completed"
    assert run.answer_summary["completion_status"] == "completed"
    assert run.usage_summary["credential_id"] == str(credential.id)
    assert run.usage_summary["model_id"] == str(model.id)
    assert retrieval_audits == [True]
    assert lifecycle_actions == [
        AuditAction.RAG_ANSWER_REQUESTED,
        AuditAction.RAG_ANSWER_COMPLETED,
    ]


def test_answer_retrieval_exception_returns_sanitized_generation_failure(
    monkeypatch,
):
    service = _service()
    payload = _agent_payload(correlation_id="corr-retrieval-fail")
    kb, model, credential = _visible_resources(payload, service.organization_id)
    run = _run()
    run.correlation_id = payload.correlation_id
    lifecycle_actions = []

    class FailingRetrievalService:
        def __init__(self, *args, **kwargs):
            pass

        async def search_documents(self, *args, **kwargs):
            raise RuntimeError("database failed with api_key=raw-secret")

    monkeypatch.setattr(service_module, "RetrievalService", FailingRetrievalService)
    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_ensure_generation_model", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_hierarchy_available", lambda *_: None)
    monkeypatch.setattr(service, "_create_run", lambda **_: run)
    monkeypatch.setattr(service, "_ensure_kb_use", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_credential_use_and_relation", lambda *_: None)
    monkeypatch.setattr(
        service,
        "_record_lifecycle",
        lambda action, *_args, **_kwargs: lifecycle_actions.append(action),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.answer(payload))

    rendered_detail = str(exc.value.detail)
    assert exc.value.status_code == 500
    assert exc.value.detail["error"]["code"] == "generation.failed"
    assert "raw-secret" not in rendered_detail
    assert "api_key" not in rendered_detail
    assert run.status == "failed"
    assert run.error_code == "generation.failed"
    assert lifecycle_actions == [
        AuditAction.RAG_ANSWER_REQUESTED,
        AuditAction.RAG_ANSWER_FAILED,
    ]


def test_answer_generation_exception_returns_sanitized_generation_failure(
    monkeypatch,
):
    service = _service()
    payload = _agent_payload(correlation_id="corr-generation-fail")
    kb, model, credential = _visible_resources(payload, service.organization_id)
    run = _run()
    run.correlation_id = payload.correlation_id
    chunk = ChunkPreview(
        chunk_id=uuid.uuid4(),
        content="evidence",
        document_id=uuid.uuid4(),
        filename="policy.md",
        similarity_score=0.9,
        score=0.9,
        rank=1,
        metadata_summary={"classification": "internal"},
    )
    lifecycle_actions = []

    class FakeRetrievalService:
        def __init__(self, *args, **kwargs):
            pass

        async def search_documents(self, *args, **kwargs):
            return [chunk]

    async def fail_generate_answer(*args, **kwargs):
        raise RuntimeError("provider returned sk-testSecretValue")

    monkeypatch.setattr(service_module, "RetrievalService", FakeRetrievalService)
    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_ensure_generation_model", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_hierarchy_available", lambda *_: None)
    monkeypatch.setattr(service, "_create_run", lambda **_: run)
    monkeypatch.setattr(service, "_ensure_kb_use", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_credential_use_and_relation", lambda *_: None)
    monkeypatch.setattr(service, "_record_retrieval", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_generate_answer", fail_generate_answer)
    monkeypatch.setattr(
        service,
        "_record_lifecycle",
        lambda action, *_args, **_kwargs: lifecycle_actions.append(action),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.answer(payload))

    rendered_detail = str(exc.value.detail)
    assert exc.value.status_code == 500
    assert exc.value.detail["error"]["code"] == "generation.failed"
    assert "sk-testSecretValue" not in rendered_detail
    assert run.status == "failed"
    assert run.error_code == "generation.failed"
    assert lifecycle_actions == [
        AuditAction.RAG_ANSWER_REQUESTED,
        AuditAction.RAG_ANSWER_FAILED,
    ]


def test_answer_invalid_credential_config_returns_sanitized_generation_failure(
    monkeypatch,
):
    service = _service()
    payload = _agent_payload(correlation_id="corr-invalid-credential")
    kb, model, credential = _visible_resources(payload, service.organization_id)
    credential.provider = SimpleNamespace(name="openai")
    credential.encrypted_config = "sk-testSecretValue"
    run = _run()
    run.correlation_id = payload.correlation_id
    chunk = ChunkPreview(
        chunk_id=uuid.uuid4(),
        content="evidence",
        document_id=uuid.uuid4(),
        filename="policy.md",
        similarity_score=0.9,
        score=0.9,
        rank=1,
        metadata_summary={"classification": "internal"},
    )

    class FakeRetrievalService:
        def __init__(self, *args, **kwargs):
            pass

        async def search_documents(self, *args, **kwargs):
            return [chunk]

    monkeypatch.setattr(service_module, "RetrievalService", FakeRetrievalService)
    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_ensure_generation_model", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_hierarchy_available", lambda *_: None)
    monkeypatch.setattr(service, "_create_run", lambda **_: run)
    monkeypatch.setattr(service, "_ensure_kb_use", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_credential_use_and_relation", lambda *_: None)
    monkeypatch.setattr(service, "_record_retrieval", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_record_lifecycle", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_record_llm_call", lambda *args, **kwargs: None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.answer(payload))

    rendered_detail = str(exc.value.detail)
    assert exc.value.status_code == 500
    assert exc.value.detail["error"]["code"] == "generation.failed"
    assert "sk-testSecretValue" not in rendered_detail
    assert "encrypted_config" not in rendered_detail
    assert run.status == "failed"
    assert run.error_code == "generation.failed"


def test_stream_events_cancelled_error_marks_run_cancelled(monkeypatch):
    service = _service()
    run = _run()
    payload = _agent_payload(correlation_id=run.correlation_id)
    lifecycle_actions = []
    execution = service_module.RAGAnswerExecution(
        payload=payload,
        correlation_id=run.correlation_id,
        metadata_filter=None,
        kb=SimpleNamespace(id=payload.knowledge_base_id),
        model=SimpleNamespace(
            id=payload.generation_model_id,
            name="GPT Test",
            provider_name="openai",
        ),
        credential=SimpleNamespace(id=payload.credential_id),
        run=run,
    )

    class CancelledRetrievalService:
        def __init__(self, *args, **kwargs):
            pass

        async def search_documents(self, *args, **kwargs):
            raise asyncio.CancelledError

    monkeypatch.setattr(service_module, "RetrievalService", CancelledRetrievalService)
    monkeypatch.setattr(
        service,
        "_record_lifecycle",
        lambda action, *_args, **_kwargs: lifecycle_actions.append(action),
    )

    async def collect():
        return [event async for event in service.stream_events(execution)]

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(collect())

    assert run.status == "cancelled"
    assert run.error_code == "client.cancelled"
    assert lifecycle_actions == [AuditAction.RAG_ANSWER_CANCELLED]


def test_stream_events_policy_block_stops_before_answer_usage_and_completion(
    monkeypatch,
):
    service = _service()
    run = _run()
    payload = _agent_payload(correlation_id=run.correlation_id)
    chunk = ChunkPreview(
        chunk_id=uuid.uuid4(),
        content="private evidence",
        document_id=uuid.uuid4(),
        filename="policy.md",
        similarity_score=0.9,
        score=0.9,
        rank=1,
        metadata_summary={"classification": "pii"},
    )
    execution = service_module.RAGAnswerExecution(
        payload=payload,
        correlation_id=run.correlation_id,
        metadata_filter=None,
        kb=SimpleNamespace(id=payload.knowledge_base_id),
        model=SimpleNamespace(
            id=payload.generation_model_id,
            name="GPT Test",
            provider_name="openai",
        ),
        credential=SimpleNamespace(id=payload.credential_id),
        run=run,
    )
    audit_calls = []

    class FakeRetrievalService:
        def __init__(self, *args, **kwargs):
            pass

        async def search_documents(self, *args, **kwargs):
            return [chunk]

    monkeypatch.setattr(service_module, "RetrievalService", FakeRetrievalService)
    monkeypatch.setattr(service, "_record_retrieval", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_record_lifecycle", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        service,
        "_generate_answer",
        lambda *args, **kwargs: pytest.fail("policy block must prevent LLM call"),
    )
    monkeypatch.setattr(
        service_module,
        "record_audit",
        lambda **event: audit_calls.append(event),
    )

    async def collect():
        return [event async for event in service.stream_events(execution)]

    events = asyncio.run(collect())

    assert [event_name for event_name, _payload in events] == [
        "retrieval.started",
        "error",
    ]
    assert events[-1][1] == {
        "answer_run_id": str(run.id),
        "correlation_id": run.correlation_id,
        "status": "blocked",
        "reason_code": "pii_policy_blocked",
        "retryable": False,
    }
    assert run.status == "blocked"
    assert run.error_code == "pii_policy_blocked"
    assert audit_calls[0]["action"] == AuditAction.POLICY_BLOCK


def test_stream_events_marks_running_run_cancelled_when_generator_closes(monkeypatch):
    service = _service()
    run = _run()
    run.status = "running"
    payload = _agent_payload(correlation_id=run.correlation_id)
    execution = service_module.RAGAnswerExecution(
        payload=payload,
        correlation_id=run.correlation_id,
        metadata_filter=None,
        kb=SimpleNamespace(id=payload.knowledge_base_id),
        model=SimpleNamespace(id=payload.generation_model_id),
        credential=SimpleNamespace(id=payload.credential_id),
        run=run,
    )
    lifecycle_actions = []

    monkeypatch.setattr(
        service,
        "_record_lifecycle",
        lambda action, *_args, **_kwargs: lifecycle_actions.append(action),
    )

    async def consume_first_event_then_close():
        generator = service.stream_events(execution)
        first_event = await anext(generator)
        await generator.aclose()
        return first_event

    first_event = asyncio.run(consume_first_event_then_close())

    assert first_event[0] == "retrieval.started"
    assert run.status == "cancelled"
    assert run.error_code == "client.cancelled"
    assert lifecycle_actions == [AuditAction.RAG_ANSWER_CANCELLED]


def test_answer_success_stores_redaction_safe_summaries(monkeypatch):
    service = _service()
    payload = RAGAgentAnswerRequest(
        knowledge_base_id=uuid.uuid4(),
        query="policy",
        generation_model_id=uuid.uuid4(),
        credential_id=uuid.uuid4(),
        correlation_id="corr-1",
    )
    kb = SimpleNamespace(id=payload.knowledge_base_id, name="KB")
    model = SimpleNamespace(
        id=payload.generation_model_id,
        name="GPT Test",
        provider_name="openai",
        type="chat",
        model_id_for_api_call="gpt-test",
    )
    credential = SimpleNamespace(id=payload.credential_id)
    run = _run()
    run.correlation_id = payload.correlation_id
    chunk = ChunkPreview(
        chunk_id=uuid.uuid4(),
        content="원문 evidence",
        document_id=uuid.uuid4(),
        filename="policy.md",
        similarity_score=0.92,
        score=0.92,
        rank=1,
        metadata_summary={"classification": "internal"},
        hierarchy_path=["Policy"],
    )
    lifecycle_actions = []
    retrieval_audits = []

    class FakeRetrievalService:
        def __init__(self, *args, **kwargs):
            pass

        async def search_documents(self, *args, **kwargs):
            return [chunk]

    monkeypatch.setattr(
        service_module,
        "RetrievalService",
        FakeRetrievalService,
    )
    monkeypatch.setattr(service, "_visible_knowledge_base", lambda *_: kb)
    monkeypatch.setattr(service, "_visible_generation_model", lambda *_: model)
    monkeypatch.setattr(service, "_visible_credential", lambda *_: credential)
    monkeypatch.setattr(service, "_ensure_generation_model", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_hierarchy_available", lambda *_: None)
    monkeypatch.setattr(service, "_create_run", lambda **_: run)
    monkeypatch.setattr(service, "_ensure_kb_use", lambda *_: None)
    monkeypatch.setattr(
        service,
        "_ensure_credential_use_and_relation",
        lambda *_: None,
    )
    monkeypatch.setattr(
        service,
        "_record_lifecycle",
        lambda action, *_args, **_kwargs: lifecycle_actions.append(action),
    )
    monkeypatch.setattr(
        service,
        "_record_retrieval",
        lambda *_args, **_kwargs: retrieval_audits.append(True),
    )

    async def fake_generate_answer(*args, **kwargs):
        return "요약 답변", RAGUsageSummary(
            prompt_tokens=3,
            completion_tokens=4,
            total_tokens=7,
            total_cost=0.001,
            latency_ms=10,
            model_name=model.name,
            provider=model.provider_name,
        )

    monkeypatch.setattr(service, "_generate_answer", fake_generate_answer)

    response = asyncio.run(service.answer(payload))

    assert response.answer == "요약 답변"
    assert response.citations[0].content_preview == "원문 evidence"
    assert run.status == "completed"
    assert run.citation_summary == [
        response.citations[0].model_dump(mode="json", exclude={"content_preview"})
    ]
    assert "content_preview" not in run.citation_summary[0]
    assert run.answer_summary["answer_length"] == len("요약 답변")
    assert run.policy_result == {
        "result": "allow",
        "evidence_classifications": ["internal"],
    }
    assert run.usage_summary["model_id"] == str(model.id)
    assert run.usage_summary["credential_id"] == str(credential.id)
    assert lifecycle_actions == [
        AuditAction.RAG_ANSWER_REQUESTED,
        AuditAction.RAG_ANSWER_COMPLETED,
    ]
    assert retrieval_audits == [True]
