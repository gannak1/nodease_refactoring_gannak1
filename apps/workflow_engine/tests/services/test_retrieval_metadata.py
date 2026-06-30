import asyncio
import uuid
from types import SimpleNamespace

from apps.shared.db.models.llm import LLMCredential, LLMProvider
from apps.shared.schemas.rag import ChunkPreview
from apps.workflow_engine.services.llm_service import LLMService
from apps.workflow_engine.services.retrieval import RetrievalService


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


def test_generate_answer_preserves_references_when_generation_model_missing(monkeypatch):
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

    response = asyncio.run(service.generate_answer("query", "kb-1"))

    assert response.references == [chunk]
