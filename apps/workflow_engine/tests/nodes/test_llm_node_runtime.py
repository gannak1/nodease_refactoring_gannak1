"""
LLM 노드 런타임 최소 동작 테스트 [GEVENT] Sync 버전.
- 메시지 렌더링 → 클라이언트 호출 → 응답 파싱 경로를 검증한다.
- DB 세션 없이도 _client_override로 클라이언트를 주입해 실행 가능하도록 구성.
"""

import pathlib
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PARENT_OF_ROOT = ROOT.parent
for p in [ROOT, PARENT_OF_ROOT]:
    if str(p) not in sys.path:
        sys.path.append(str(p))

from apps.shared.schemas.rag import ChunkPreview  # noqa: E402
from apps.shared.services.tracing.metadata import TraceMetadataSanitizer  # noqa: E402
from apps.workflow_engine.services import llm_service as workflow_llm_service  # noqa: E402
from apps.workflow_engine.services.llm_service import (  # noqa: E402
    LLMCredentialNotAvailableError,
    LLMService,
)
from apps.workflow_engine.workflow.nodes.llm.entities import (  # noqa: E402
    KnowledgeBaseRef,
    LLMNodeData,
    LLMVariable,
)
from apps.workflow_engine.workflow.nodes.llm.llm_node import (  # noqa: E402
    SAFETY_SYSTEM_PROMPT,
    LLMNode,
)


class DummyClient:
    """동기 더미 클라이언트 [GEVENT]"""

    def __init__(self):
        self.calls = []

    def invoke_sync(self, messages, **kwargs):
        """동기 호출 메서드"""
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return {
            "choices": [{"message": {"content": "hello world"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }


class FailingClient:
    """동기 실패 클라이언트 [GEVENT]"""

    def __init__(self):
        self.calls = []

    def invoke_sync(self, messages, **kwargs):
        """동기 호출 - 실패"""
        self.calls.append({"messages": messages, "kwargs": kwargs})
        raise RuntimeError("primary model failed")


class SuccessClient:
    """동기 성공 클라이언트 [GEVENT]"""

    def __init__(self):
        self.calls = []

    def invoke_sync(self, messages, **kwargs):
        """동기 호출 - 성공"""
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return {
            "choices": [{"message": {"content": "fallback ok"}}],
            "usage": {},
        }


class FakeRuntimePriorityQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def options(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        if self.model is workflow_llm_service.LLMCredential:
            return self.db.credentials
        return []

    def first(self):
        if self.model is workflow_llm_service.LLMModel:
            return self.db.model
        if self.model is workflow_llm_service.LLMCredential:
            return self.db.credentials[0] if self.db.credentials else None
        if self.model is workflow_llm_service.LLMRelCredentialModel:
            return self.db.relations.pop(0)
        return None


class FakeRuntimePriorityDb:
    def __init__(self, credentials, model, relations):
        self.credentials = credentials
        self.model = model
        self.relations = list(relations)

    def query(self, *args, **kwargs):
        return FakeRuntimePriorityQuery(self, args[0])

    def refresh(self, row):
        self.refreshed = row


def test_llm_node_runs_with_override_client():
    """클라이언트 오버라이드로 LLM 노드 실행 테스트 [GEVENT] sync"""
    dummy_client = DummyClient()

    data = LLMNodeData(
        title="LLM",
        provider="openai",
        model_id="gpt-4o",
        system_prompt="sys {{var}}",
        user_prompt="user {{var}}",
        assistant_prompt="assistant {{var}}",
        referenced_variables=[
            LLMVariable(name="var", value_selector=["some_node", "var"])
        ],
        context_variable=None,
        parameters={},
    )

    node = LLMNode("llm-1", data)
    # DB 세션 대신 직접 클라이언트 주입
    node._client_override = dummy_client  # noqa: SLF001 - 테스트용

    # value_selector가 ["some_node", "var"]이므로 some_node의 var 값을 전달
    # [GEVENT] sync 호출
    result = node.execute({"some_node": {"var": "X"}})

    # 클라이언트 호출 검증
    assert dummy_client.calls
    called = dummy_client.calls[0]
    assert called["messages"] == [
        {"role": "system", "content": SAFETY_SYSTEM_PROMPT},
        {"role": "system", "content": "sys X"},
        {"role": "user", "content": "user X"},
        {"role": "assistant", "content": "assistant X"},
    ]

    # 응답 파싱 검증
    assert result["text"] == "hello world"
    assert result["usage"] == {"prompt_tokens": 1, "completion_tokens": 1}


def test_llm_node_uses_fallback_model_on_failure(monkeypatch):
    """폴백 모델 사용 테스트 [GEVENT] sync"""
    primary_client = FailingClient()
    fallback_client = SuccessClient()
    organization_id = uuid.uuid4()
    service_calls = []

    def fake_get_runtime_client_for_user(db, user_id, model_id, organization_id=None):
        service_calls.append(
            {"model_id": model_id, "organization_id": organization_id}
        )
        if model_id == "primary-model":
            return SimpleNamespace(
                client=primary_client,
                credential_id=uuid.uuid4(),
                model_id=model_id,
                organization_id=organization_id,
            )
        if model_id == "fallback-model":
            return SimpleNamespace(
                client=fallback_client,
                credential_id=uuid.uuid4(),
                model_id=model_id,
                organization_id=organization_id,
            )
        raise AssertionError(f"unexpected model_id: {model_id}")

    monkeypatch.setattr(
        LLMService, "get_runtime_client_for_user", fake_get_runtime_client_for_user
    )

    data = LLMNodeData(
        title="LLM",
        provider="openai",
        model_id="primary-model",
        fallback_model_id="fallback-model",
        system_prompt="sys",
        user_prompt="user",
        assistant_prompt=None,
        referenced_variables=[],
        context_variable=None,
        parameters={},
    )

    node = LLMNode(
        "llm-1",
        data,
        execution_context={
            "user_id": str(uuid.uuid4()),
            "organization_id": str(organization_id),
            "db": object(),
        },
    )

    # [GEVENT] sync 호출
    result = node.execute({})

    assert primary_client.calls
    assert fallback_client.calls
    assert result["text"] == "fallback ok"
    assert result["model"] == "fallback-model"
    assert service_calls == [
        {"model_id": "primary-model", "organization_id": organization_id},
        {"model_id": "fallback-model", "organization_id": organization_id},
    ]


def test_llm_node_logs_fallback_model_when_primary_client_selection_fails(
    monkeypatch,
):
    """Client selection fallback logs the actual executed model and credential. MBA-43"""
    fallback_client = SuccessClient()
    organization_id = uuid.uuid4()
    fallback_credential_id = uuid.uuid4()
    service_calls = []
    cost_calls = []
    log_calls = []

    def fake_get_runtime_client_for_user(db, user_id, model_id, organization_id=None):
        service_calls.append(
            {"model_id": model_id, "organization_id": organization_id}
        )
        if model_id == "primary-model":
            raise LLMCredentialNotAvailableError(
                "credential_use_denied",
                "primary denied",
                model_id=model_id,
                organization_id=organization_id,
            )
        if model_id == "fallback-model":
            return SimpleNamespace(
                client=fallback_client,
                credential_id=fallback_credential_id,
                model_id=model_id,
                organization_id=organization_id,
            )
        raise AssertionError(f"unexpected model_id: {model_id}")

    def fake_calculate_cost(db, model_id, prompt_tokens, completion_tokens):
        cost_calls.append(
            {
                "model_id": model_id,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        )
        return 0.0

    monkeypatch.setattr(
        LLMService, "get_runtime_client_for_user", fake_get_runtime_client_for_user
    )
    monkeypatch.setattr(LLMService, "calculate_cost", fake_calculate_cost)
    monkeypatch.setattr(
        LLMService, "log_usage", lambda **kwargs: log_calls.append(kwargs)
    )

    data = LLMNodeData(
        title="LLM",
        provider="openai",
        model_id="primary-model",
        fallback_model_id="fallback-model",
        system_prompt="sys",
        user_prompt="user",
        assistant_prompt=None,
        referenced_variables=[],
        context_variable=None,
        parameters={},
    )
    node = LLMNode(
        "llm-1",
        data,
        execution_context={
            "user_id": str(uuid.uuid4()),
            "organization_id": str(organization_id),
            "workflow_id": str(uuid.uuid4()),
            "workflow_run_id": str(uuid.uuid4()),
            "db": object(),
        },
    )

    result = node.execute({})

    assert fallback_client.calls
    assert result["text"] == "fallback ok"
    assert result["model"] == "fallback-model"
    assert data.model_id == "primary-model"
    assert service_calls == [
        {"model_id": "primary-model", "organization_id": organization_id},
        {"model_id": "fallback-model", "organization_id": organization_id},
    ]
    assert cost_calls[0]["model_id"] == "fallback-model"
    assert log_calls[0]["model_id"] == "fallback-model"
    assert log_calls[0]["credential_id"] == fallback_credential_id


def test_llm_node_logs_usage_with_selected_credential_id(monkeypatch):
    """Successful workflow LLM usage log keeps the executed credential id. MBA-43"""
    organization_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    log_calls = []

    def fake_get_runtime_client_for_user(db, user_id, model_id, organization_id=None):
        return SimpleNamespace(
            client=DummyClient(),
            credential_id=credential_id,
            model_id=model_id,
            organization_id=organization_id,
        )

    monkeypatch.setattr(
        LLMService, "get_runtime_client_for_user", fake_get_runtime_client_for_user
    )
    monkeypatch.setattr(LLMService, "calculate_cost", lambda *args, **kwargs: 0.0)
    monkeypatch.setattr(
        LLMService, "log_usage", lambda **kwargs: log_calls.append(kwargs)
    )

    data = LLMNodeData(
        title="LLM",
        provider="openai",
        model_id="primary-model",
        system_prompt="sys",
        user_prompt="user",
        assistant_prompt=None,
        referenced_variables=[],
        context_variable=None,
        parameters={},
    )
    node = LLMNode(
        "llm-1",
        data,
        execution_context={
            "user_id": str(uuid.uuid4()),
            "organization_id": str(organization_id),
            "workflow_id": str(uuid.uuid4()),
            "workflow_run_id": str(uuid.uuid4()),
            "db": object(),
        },
    )

    result = node.execute({})

    assert result["text"] == "hello world"
    assert log_calls
    assert log_calls[0]["credential_id"] == credential_id


def test_llm_node_records_one_audit_when_primary_and_fallback_selection_fail(
    monkeypatch,
):
    """Primary plus fallback credential selection failure records one final block. MBA-43"""
    organization_id = uuid.uuid4()
    primary_credential_id = uuid.uuid4()
    fallback_credential_id = uuid.uuid4()
    service_calls = []
    audit_calls = []

    def fake_get_runtime_client_for_user(db, user_id, model_id, organization_id=None):
        service_calls.append(model_id)
        if model_id == "primary-model":
            raise LLMCredentialNotAvailableError(
                "credential_use_denied",
                "primary denied",
                credential_id=primary_credential_id,
                model_id=model_id,
                organization_id=organization_id,
            )
        if model_id == "fallback-model":
            raise LLMCredentialNotAvailableError(
                "model_relation_not_verified",
                "fallback relation missing",
                credential_id=fallback_credential_id,
                model_id=model_id,
                organization_id=organization_id,
            )
        raise AssertionError(f"unexpected model_id: {model_id}")

    monkeypatch.setattr(
        LLMService, "get_runtime_client_for_user", fake_get_runtime_client_for_user
    )
    monkeypatch.setattr(
        "apps.workflow_engine.workflow.nodes.llm.llm_node.record_resource_permission_denied",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    data = LLMNodeData(
        title="LLM",
        provider="openai",
        model_id="primary-model",
        fallback_model_id="fallback-model",
        system_prompt="sys",
        user_prompt="user",
        assistant_prompt=None,
        referenced_variables=[],
        context_variable=None,
        parameters={},
    )
    node = LLMNode(
        "llm-1",
        data,
        execution_context={
            "user_id": str(uuid.uuid4()),
            "organization_id": str(organization_id),
            "workflow_id": str(uuid.uuid4()),
            "workflow_run_id": str(uuid.uuid4()),
            "db": object(),
        },
    )

    with pytest.raises(LLMCredentialNotAvailableError):
        node.execute({})

    assert service_calls == ["primary-model", "fallback-model"]
    assert len(audit_calls) == 1
    assert audit_calls[0]["resource_id"] == fallback_credential_id
    assert audit_calls[0]["organization_id"] == organization_id
    assert audit_calls[0]["metadata"]["model_id"] == "fallback-model"
    assert audit_calls[0]["metadata"]["reason"] == "model_relation_not_verified"


@pytest.mark.parametrize("organization_id", [None, "not-a-uuid"])
def test_llm_node_requires_valid_organization_scope_before_client_selection(
    monkeypatch, organization_id
):
    """Workflow LLM runtime은 credential 선택 전에 valid organization scope를 요구합니다. MBA-43"""
    service_calls = []
    audit_calls = []

    def fake_get_runtime_client_for_user(*args, **kwargs):
        service_calls.append(kwargs)
        raise AssertionError("LLM service should not be called without org scope")

    monkeypatch.setattr(
        LLMService, "get_runtime_client_for_user", fake_get_runtime_client_for_user
    )
    monkeypatch.setattr(
        "apps.workflow_engine.workflow.nodes.llm.llm_node.record_resource_permission_denied",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    data = LLMNodeData(
        title="LLM",
        provider="openai",
        model_id="primary-model",
        fallback_model_id="fallback-model",
        system_prompt="sys",
        user_prompt="user",
        assistant_prompt=None,
        referenced_variables=[],
        context_variable=None,
        parameters={},
    )
    execution_context = {
        "user_id": str(uuid.uuid4()),
        "workflow_id": str(uuid.uuid4()),
        "workflow_run_id": str(uuid.uuid4()),
        "db": object(),
    }
    if organization_id is not None:
        execution_context["organization_id"] = organization_id

    node = LLMNode("llm-1", data, execution_context=execution_context)

    with pytest.raises(LLMCredentialNotAvailableError) as exc:
        node.execute({})

    assert exc.value.reason == "organization_scope_missing"
    assert service_calls == []
    assert len(audit_calls) == 1
    assert audit_calls[0]["resource_type"] == "llm_credential"
    assert audit_calls[0]["resource_id"] == "unknown"
    assert audit_calls[0]["organization_id"] is None
    assert audit_calls[0]["metadata"]["reason"] == "organization_scope_missing"
    assert audit_calls[0]["metadata"]["model_id"] == "primary-model"
    assert audit_calls[0]["metadata"]["credential_id"] is None


def test_knowledge_trace_metadata_excludes_chunk_content():
    node = LLMNode.__new__(LLMNode)
    chunk_id = uuid.uuid4()
    parent_chunk_id = uuid.uuid4()
    chunk = ChunkPreview(
        chunk_id=chunk_id,
        parent_chunk_id=parent_chunk_id,
        content="검색 원문",
        document_id=uuid.uuid4(),
        filename="guide.md",
        page_number=3,
        similarity_score=0.91,
        score=0.92,
        rank=1,
        token_count=120,
        metadata_summary={"classification": "internal", "hierarchy_fallback": True},
        hierarchy_path=["Guide", "Intro"],
        metadata={"source": "kb"},
    )

    metadata = node._knowledge_trace_metadata("kb-1", chunk)  # noqa: SLF001 - 테스트용

    assert metadata["filename"] == "guide.md"
    assert metadata["page_number"] == 3
    assert metadata["knowledge_base_id"] == "kb-1"
    assert metadata["chunk_id"] == str(chunk_id)
    assert metadata["parent_chunk_id"] == str(parent_chunk_id)
    assert metadata["score"] == 0.92
    assert metadata["token_count"] == 120
    assert metadata["metadata_summary"] == {
        "classification": "internal",
        "hierarchy_fallback": True,
    }
    assert metadata["hierarchy_fallback"] is True
    assert TraceMetadataSanitizer.summarize_rag_metadata([metadata])[
        "hierarchy_fallback"
    ] is True
    assert metadata["hierarchy_path"] == ["Guide", "Intro"]
    assert "content" not in metadata
    assert "metadata" not in metadata


def test_rag_retrieval_trace_payload_uses_redacted_contract():
    node = LLMNode.__new__(LLMNode)
    node.id = "llm-1"
    node.execution_context = {"workflow_run_id": str(uuid.uuid4())}
    chunk = ChunkPreview(
        chunk_id=uuid.uuid4(),
        content="검색 원문",
        document_id=uuid.uuid4(),
        filename="guide.md",
        page_number=3,
        similarity_score=0.91,
        score=0.92,
        rank=1,
        token_count=120,
        metadata_summary={"classification": "internal"},
        hierarchy_path=["Guide", "Intro"],
        metadata={"source": "kb"},
    )
    metadata = node._knowledge_trace_metadata("kb-1", chunk)  # noqa: SLF001 - 테스트용

    payload = node._rag_retrieval_trace_payload([metadata])  # noqa: SLF001 - 테스트용

    assert payload["knowledge_base_ids"] == ["kb-1"]
    assert payload["result_count"] == 1
    assert payload["policy_result"] == "allow"
    assert payload["raw_content_returned"] is False
    assert payload["node_id"] == "llm-1"
    assert "workflow_node_run_id" not in payload
    assert "content" not in payload["retrieved_chunks"][0]
    assert "metadata" not in payload["retrieved_chunks"][0]


def test_llm_runtime_permission_denied_uses_detailed_reason_and_unknown_target(
    monkeypatch,
):
    node = LLMNode.__new__(LLMNode)
    node.id = "llm-1"
    node.execution_context = {
        "workflow_id": str(uuid.uuid4()),
        "workflow_run_id": str(uuid.uuid4()),
    }
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    audit_calls = []

    monkeypatch.setattr(
        "apps.workflow_engine.workflow.nodes.llm.llm_node.record_resource_permission_denied",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    error = LLMCredentialNotAvailableError(
        "model_relation_not_verified",
        "missing relation",
        model_id="gpt-4o-mini",
        organization_id=organization_id,
    )

    node._record_llm_runtime_permission_denied(  # noqa: SLF001 - MBA-43 audit helper
        user_id=user_id,
        model_id="ignored-model",
        organization_id=None,
        error=error,
    )

    assert audit_calls[0]["resource_type"] == "llm_credential"
    assert audit_calls[0]["resource_id"] == "unknown"
    assert audit_calls[0]["organization_id"] == organization_id
    assert audit_calls[0]["metadata"]["credential_id"] is None
    assert audit_calls[0]["metadata"]["model_id"] == "gpt-4o-mini"
    assert audit_calls[0]["metadata"]["reason"] == "model_relation_not_verified"


def test_workflow_llm_service_uses_relation_priority_before_credential_created_at(
    monkeypatch,
):
    """Workflow runtime credential selection follows relation priority first. MBA-43"""
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    provider = SimpleNamespace(id=uuid.uuid4(), name="openai")
    older_credential = SimpleNamespace(
        id=uuid.uuid4(),
        provider=provider,
        provider_id=provider.id,
        organization_id=organization_id,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        encrypted_config='{"apiKey": "older-key", "baseUrl": "https://older.example"}',
    )
    priority_credential = SimpleNamespace(
        id=uuid.uuid4(),
        provider=provider,
        provider_id=provider.id,
        organization_id=organization_id,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        encrypted_config='{"apiKey": "priority-key", "baseUrl": "https://priority.example"}',
    )
    model = SimpleNamespace(
        id=uuid.uuid4(),
        provider_id=provider.id,
        provider=provider,
        model_id_for_api_call="gpt-4o-mini",
        is_active=True,
    )
    db = FakeRuntimePriorityDb(
        credentials=[older_credential, priority_credential],
        model=model,
        relations=[
            SimpleNamespace(priority=10),
            SimpleNamespace(priority=1),
        ],
    )
    client_configs = []

    monkeypatch.setattr(
        workflow_llm_service,
        "has_llm_credential_permission",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        workflow_llm_service,
        "get_llm_client",
        lambda **kwargs: client_configs.append(kwargs["credentials"])
        or SimpleNamespace(),
    )

    runtime = LLMService.get_runtime_client_for_user(
        db,
        user_id=user_id,
        model_id="gpt-4o-mini",
        organization_id=organization_id,
    )

    assert runtime.credential_id == priority_credential.id
    assert client_configs == [
        {"apiKey": "priority-key", "baseUrl": "https://priority.example"}
    ]


@pytest.mark.parametrize("organization_id", [None, "not-a-uuid"])
def test_workflow_llm_service_requires_runtime_organization_scope(organization_id):
    """Workflow Engine LLM service는 runtime credential 조회 전에 org scope를 요구합니다. MBA-43"""
    with pytest.raises(LLMCredentialNotAvailableError) as exc:
        LLMService.get_client_for_user(
            object(),
            user_id=uuid.uuid4(),
            model_id="gpt-4o-mini",
            organization_id=organization_id,
        )

    assert exc.value.reason == "organization_scope_missing"
    assert exc.value.model_id == "gpt-4o-mini"
    assert exc.value.organization_id is None


def test_knowledge_search_requires_user_context():
    data = LLMNodeData(
        title="LLM",
        provider="openai",
        model_id="gpt-4o",
        user_prompt="user",
        knowledgeBases=[
            KnowledgeBaseRef(id=str(uuid.uuid4()), name="KB"),
        ],
    )
    node = LLMNode(
        "llm-1",
        data,
        execution_context={"organization_id": str(uuid.uuid4())},
    )

    with pytest.raises(PermissionError, match="active user context"):
        node._execute_knowledge_search("query", db_session=object())  # noqa: SLF001


def test_knowledge_search_preauthorizes_all_kbs_before_retrieval(monkeypatch):
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    allowed_kb_id = uuid.uuid4()
    denied_kb_id = uuid.uuid4()
    retrieval_calls = []
    audit_calls = []
    captured_init = {}

    class FakeRetrievalService:
        def __init__(self, db, user_id, organization_id=None):
            captured_init["organization_id"] = organization_id

        def search_documents_sync(self, *args, **kwargs):
            retrieval_calls.append(kwargs["knowledge_base_id"])
            return []

    def fake_auth_state(db, user_id, knowledge_base_id, organization_id=None):
        if str(knowledge_base_id) == str(allowed_kb_id):
            return "manager"
        if str(knowledge_base_id) == str(denied_kb_id):
            return "none"
        raise AssertionError(f"unexpected kb: {knowledge_base_id}")

    monkeypatch.setattr(
        "apps.workflow_engine.workflow.nodes.llm.llm_node.RetrievalService",
        FakeRetrievalService,
    )
    monkeypatch.setattr(
        "apps.workflow_engine.workflow.nodes.llm.llm_node.get_effective_knowledge_base_auth_state",
        fake_auth_state,
    )
    monkeypatch.setattr(
        "apps.workflow_engine.workflow.nodes.llm.llm_node.record_resource_permission_denied",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    data = LLMNodeData(
        title="LLM",
        provider="openai",
        model_id="gpt-4o",
        user_prompt="user",
        knowledgeBases=[
            KnowledgeBaseRef(id=str(allowed_kb_id), name="Allowed"),
            KnowledgeBaseRef(id=str(denied_kb_id), name="Denied"),
        ],
    )
    node = LLMNode(
        "llm-1",
        data,
        execution_context={
            "user_id": str(user_id),
            "organization_id": str(organization_id),
            "workflow_id": str(uuid.uuid4()),
            "workflow_run_id": str(uuid.uuid4()),
        },
    )

    with pytest.raises(PermissionError, match="Knowledge Base use permission"):
        node._execute_knowledge_search("query", db_session=object())  # noqa: SLF001

    assert captured_init["organization_id"] == organization_id
    assert retrieval_calls == []
    assert audit_calls[0]["resource_id"] == str(denied_kb_id)
    assert audit_calls[0]["effective_auth_state"] == "none"
    assert audit_calls[0]["organization_id"] == organization_id
