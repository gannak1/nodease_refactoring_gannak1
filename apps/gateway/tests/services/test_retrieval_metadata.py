import asyncio
import uuid
from types import SimpleNamespace

from apps.shared.db.models.knowledge import KnowledgeBase
from apps.shared.db.models.llm import LLMCredential, LLMProvider
from apps.shared.schemas.rag import ChunkPreview
from apps.gateway.services.llm_service import LLMService
from apps.gateway.services.retrieval import RetrievalService


class _FakeQuery:
    def __init__(self, rows, criteria):
        self.rows = rows
        self.criteria = criteria

    def filter(self, *criteria):
        self.criteria.extend(criteria)
        return self

    def all(self):
        return self.rows


class _FakeDb:
    def __init__(self, credential_rows, provider_rows, criteria):
        self.credential_rows = credential_rows
        self.provider_rows = provider_rows
        self.criteria = criteria

    def query(self, model):
        if model is LLMCredential:
            return _FakeQuery(self.credential_rows, self.criteria)
        if model is LLMProvider:
            return _FakeQuery(self.provider_rows, self.criteria)
        raise AssertionError(f"unexpected model: {model}")


def _criterion_compares_column(criteria, column_name, value):
    for criterion in criteria:
        left = getattr(criterion, "left", None)
        right = getattr(criterion, "right", None)
        if getattr(left, "name", None) == column_name and getattr(right, "value", None) == value:
            return True
    return False


def test_chunk_metadata_uses_hierarchy_columns_for_summary():
    service = RetrievalService(db=None, user_id=None)
    parent_chunk_id = uuid.uuid4()
    chunk = SimpleNamespace(
        metadata_={"page": 2, "classification": "internal", "tags": ["chunk"]},
        parent_chunk_id=parent_chunk_id,
        chunk_level="child",
        section_path=["Policy", "Access"],
        heading="Access rules",
        token_count=123,
    )
    document = SimpleNamespace(
        meta_info={"classification": "confidential", "tags": ["document"]},
        source_type="FILE",
    )

    metadata = service._chunk_metadata(chunk, document)

    assert metadata["classification"] == "confidential"
    assert metadata["tags"] == ["document"]
    assert metadata["page"] == 2
    assert metadata["source_type"] == "FILE"
    assert metadata["parent_chunk_id"] == str(parent_chunk_id)
    assert metadata["token_count"] == 123
    assert metadata["chunk_level"] == "child"
    assert metadata["section_path"] == ["Policy", "Access"]
    assert metadata["heading"] == "Access rules"
    assert service._hierarchy_path(metadata) == ["Policy", "Access"]
    summary = service._metadata_summary(metadata)
    assert summary["classification"] == "confidential"
    assert summary["parent_chunk_id"] == str(parent_chunk_id)
    assert summary["token_count"] == 123
    assert summary["chunk_level"] == "child"
    assert "api_config" not in service._metadata_summary({"api_config": {"key": "x"}})


def test_chunk_metadata_interprets_null_chunk_level_as_flat():
    service = RetrievalService(db=None, user_id=None)
    chunk = SimpleNamespace(metadata_={}, chunk_level=None)

    metadata = service._chunk_metadata(chunk)

    assert metadata["chunk_level"] == "flat"


def test_chunk_metadata_includes_safe_source_tier_from_document_version():
    service = RetrievalService(db=None, user_id=None)
    chunk = SimpleNamespace(
        metadata_={},
        chunk_level="flat",
        document_version=SimpleNamespace(source_tier="company_policy"),
    )

    metadata = service._chunk_metadata(chunk)

    assert metadata["source_tier"] == "company_policy"
    assert service._metadata_summary(metadata)["source_tier"] == "company_policy"


def test_metadata_summary_preserves_hierarchy_fallback_flag():
    service = RetrievalService(db=None, user_id=None)

    summary = service._metadata_summary(
        {
            "hierarchy_fallback": True,
            "classification": "internal",
            "content": "원문",
        }
    )

    assert summary["hierarchy_fallback"] is True
    assert summary["classification"] == "internal"
    assert "content" not in summary


def test_search_method_labels_hierarchical_paths():
    assert (
        RetrievalService._search_method(
            use_hierarchy=True,
            hybrid_search=True,
            use_rerank=True,
        )
        == "hierarchical_hybrid+rerank"
    )
    assert (
        RetrievalService._search_method(
            use_hierarchy=True,
            hybrid_search=False,
        )
        == "hierarchical"
    )


def test_rewrite_query_passes_active_organization_to_llm(monkeypatch):
    captured = {}
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()

    class FakeClient:
        async def invoke(self, messages, max_tokens):
            return {"choices": [{"message": {"content": "rewritten"}}]}

    def fake_get_client_for_user(db, user_id, model_id, organization_id=None):
        captured["user_id"] = user_id
        captured["model_id"] = model_id
        captured["organization_id"] = organization_id
        return FakeClient()

    monkeypatch.setattr(LLMService, "get_client_for_user", fake_get_client_for_user)

    service = RetrievalService(
        db=object(),
        user_id=user_id,
        organization_id=organization_id,
    )
    service._get_efficient_rewrite_model = lambda: "rewrite-model"

    assert asyncio.run(service._rewrite_query("original")) == "rewritten"
    assert captured == {
        "user_id": user_id,
        "model_id": "rewrite-model",
        "organization_id": organization_id,
    }


def test_rewrite_model_selection_filters_credentials_by_active_organization():
    criteria = []
    organization_id = uuid.uuid4()
    provider_id = uuid.uuid4()
    service = RetrievalService(
        db=_FakeDb(
            credential_rows=[SimpleNamespace(provider_id=provider_id)],
            provider_rows=[SimpleNamespace(id=provider_id, name="OpenAI")],
            criteria=criteria,
        ),
        user_id=uuid.uuid4(),
        organization_id=organization_id,
    )

    assert service._get_efficient_rewrite_model() == LLMService.EFFICIENT_MODELS["openai"]
    assert _criterion_compares_column(criteria, "organization_id", organization_id)


def test_search_documents_uses_resolved_embedding_model_client(monkeypatch):
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    embedding_model = SimpleNamespace(
        id=uuid.uuid4(),
        model_id_for_api_call="text-embedding-test",
        type="embedding",
        is_active=True,
    )
    captured = {}

    class FakeClient:
        async def embed(self, query):
            captured["embedded_query"] = query
            return [0.1, 0.2]

    class FakeKbQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return SimpleNamespace(id=kb_id, embedding_model="text-embedding-test")

        def all(self):
            return [self.first()]

    class FakeDb:
        def query(self, model):
            if model is KnowledgeBase:
                return FakeKbQuery()
            raise AssertionError(f"unexpected model lookup: {model}")

    def fake_get_client_for_model(db, checked_user_id, checked_model, organization_id=None):
        captured["user_id"] = checked_user_id
        captured["model"] = checked_model
        captured["organization_id"] = organization_id
        return FakeClient()

    monkeypatch.setattr(
        LLMService,
        "get_client_for_model",
        fake_get_client_for_model,
    )
    monkeypatch.setattr(
        LLMService,
        "get_client_for_user",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("model string helper must not be used")
        ),
    )

    service = RetrievalService(
        db=FakeDb(),
        user_id=user_id,
        organization_id=organization_id,
    )
    monkeypatch.setattr(service, "_has_valid_hierarchy", lambda *_: False)
    monkeypatch.setattr(service, "_vector_search", lambda *args, **kwargs: [])

    result = asyncio.run(
        service.search_documents(
            "policy",
            knowledge_base_id=str(kb_id),
            hybrid_search=False,
            use_rerank=False,
            embedding_model=embedding_model,
        )
    )

    assert result == []
    assert captured == {
        "embedded_query": "policy",
        "user_id": user_id,
        "model": embedding_model,
        "organization_id": organization_id,
    }


def test_search_documents_merges_multiple_authorized_kbs(monkeypatch):
    kb_a = uuid.uuid4()
    kb_b = uuid.uuid4()
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    embedded_queries = []

    class FakeClient:
        async def embed(self, query):
            embedded_queries.append(query)
            return [0.1, 0.2]

    class FakeKbQuery:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return [
                SimpleNamespace(id=kb_a, embedding_model="text-embedding-test"),
                SimpleNamespace(id=kb_b, embedding_model="text-embedding-test"),
            ]

    class FakeModelQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return SimpleNamespace(type="embedding", is_active=True)

    class FakeDb:
        def query(self, model):
            if model is KnowledgeBase:
                return FakeKbQuery()
            return FakeModelQuery()

    def fake_chunk(name):
        return SimpleNamespace(
            id=uuid.uuid4(),
            content=name,
            metadata_={},
            parent_chunk_id=None,
            chunk_level="flat",
            token_count=1,
        )

    def fake_doc(kb_id, filename):
        return SimpleNamespace(
            id=uuid.uuid4(),
            filename=filename,
            meta_info={"knowledge_base_id": str(kb_id)},
            source_type="FILE",
        )

    def fake_vector_search(_vector, knowledge_base_id, *_args, **_kwargs):
        if knowledge_base_id == str(kb_a):
            return [(fake_chunk("A"), fake_doc(kb_a, "a.md"), 0.2)]
        if knowledge_base_id == str(kb_b):
            return [(fake_chunk("B"), fake_doc(kb_b, "b.md"), 0.05)]
        return []

    monkeypatch.setattr(
        LLMService,
        "get_client_for_user",
        lambda *args, **kwargs: FakeClient(),
    )

    service = RetrievalService(
        db=FakeDb(),
        user_id=user_id,
        organization_id=organization_id,
    )
    monkeypatch.setattr(service, "_has_valid_hierarchy", lambda *_: False)
    monkeypatch.setattr(service, "_vector_search", fake_vector_search)

    result = asyncio.run(
        service.search_documents(
            "policy",
            knowledge_base_ids=[str(kb_a), str(kb_b)],
            top_k=2,
            threshold=0,
            hybrid_search=False,
            use_rerank=False,
        )
    )

    assert embedded_queries == ["policy", "policy"]
    assert [chunk.filename for chunk in result] == ["b.md", "a.md"]
    assert [chunk.content for chunk in result] == ["B", "A"]


def test_search_knowledge_base_ids_normalizes_single_string_and_dedupes():
    kb_a = uuid.uuid4()
    kb_b = uuid.uuid4()
    service = RetrievalService(db=None, user_id=None)

    result = service._search_knowledge_base_ids(
        knowledge_base_id=str(kb_a),
        knowledge_base_ids=[str(kb_a), str(kb_b)],
    )

    assert result == [str(kb_a), str(kb_b)]
    assert service._search_knowledge_base_ids(
        knowledge_base_id=None,
        knowledge_base_ids=str(kb_a),
    ) == [str(kb_a)]


def test_retrieve_context_passes_top_k_as_keyword(monkeypatch):
    captured = {}
    service = RetrievalService(db=object(), user_id=uuid.uuid4())

    async def fake_search_documents(
        query,
        *,
        knowledge_base_id,
        top_k,
        metadata_filter=None,
        hierarchy_mode="auto",
        **_kwargs,
    ):
        captured.update(
            {
                "query": query,
                "knowledge_base_id": knowledge_base_id,
                "top_k": top_k,
                "metadata_filter": metadata_filter,
                "hierarchy_mode": hierarchy_mode,
            }
        )
        return [SimpleNamespace(content="context")]

    monkeypatch.setattr(service, "search_documents", fake_search_documents)

    result = asyncio.run(
        service.retrieve_context(
            "policy",
            "kb-1",
            top_k=7,
            metadata_filter={"classification": ["internal"]},
            hierarchy_mode="flat",
        )
    )

    assert result == "context"
    assert captured == {
        "query": "policy",
        "knowledge_base_id": "kb-1",
        "top_k": 7,
        "metadata_filter": {"classification": ["internal"]},
        "hierarchy_mode": "flat",
    }

def test_generate_answer_for_test_preserves_references_when_generation_model_missing(monkeypatch):
    chunk = ChunkPreview(
        content="검색 결과",
        document_id=uuid.uuid4(),
        filename="guide.md",
        similarity_score=0.9,
    )
    service = RetrievalService(db=object(), user_id=uuid.uuid4(), organization_id=uuid.uuid4())

    async def fake_search_documents(*args, **kwargs):
        return [chunk]

    service.search_documents = fake_search_documents
    monkeypatch.setattr(
        LLMService,
        "get_client_for_user",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("missing credential")),
    )

    response = asyncio.run(service.generate_answer_for_test("query", "kb-1"))

    assert response.references == [chunk]
