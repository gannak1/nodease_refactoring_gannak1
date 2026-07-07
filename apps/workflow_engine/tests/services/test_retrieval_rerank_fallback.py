import pathlib
import sys
import uuid
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PARENT_OF_ROOT = ROOT.parent
for p in [ROOT, PARENT_OF_ROOT]:
    if str(p) not in sys.path:
        sys.path.append(str(p))

from apps.shared.db.models.knowledge import KnowledgeBase  # noqa: E402
from apps.shared.db.models.llm import LLMModel  # noqa: E402
from apps.workflow_engine.services.retrieval import RetrievalService  # noqa: E402
from apps.workflow_engine.services.llm_service import LLMService  # noqa: E402


def test_sync_search_threshold_uses_score_when_rerank_falls_back(monkeypatch):
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()

    class FakeQuery:
        def __init__(self, model):
            self.model = model

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            if self.model is KnowledgeBase:
                return SimpleNamespace(id=kb_id, embedding_model="text-embedding-test")
            if self.model is LLMModel:
                return SimpleNamespace(type="embedding")
            return None

    class FakeDb:
        def query(self, model):
            return FakeQuery(model)

    class FakeClient:
        def embed_sync(self, query):
            return [0.1, 0.2]

    chunk = SimpleNamespace(
        id=uuid.uuid4(),
        content="개발 직군 신입 보상 밴드 근거",
        metadata_={},
        parent_chunk_id=None,
        chunk_level="flat",
        token_count=12,
    )
    doc = SimpleNamespace(
        id=uuid.uuid4(),
        filename="compensation.md",
        meta_info={},
        source_type="FILE",
    )

    monkeypatch.setattr(
        LLMService,
        "get_client_for_user",
        lambda *args, **kwargs: FakeClient(),
    )

    service = RetrievalService(FakeDb(), user_id, organization_id=organization_id)
    monkeypatch.setattr(service, "_has_valid_hierarchy", lambda *_: False)
    monkeypatch.setattr(
        service,
        "_vector_search",
        lambda *args, **kwargs: [(chunk, doc, 0.1)],
    )
    monkeypatch.setattr(service, "_keyword_search", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        service,
        "_rerank",
        lambda _query, candidates, _top_k, **_kwargs: candidates,
    )

    result = service.search_documents_sync(
        "개발팀 신입 연봉 기준",
        knowledge_base_id=str(kb_id),
        threshold=0.3,
        hybrid_search=True,
        use_rerank=True,
    )

    assert [chunk.filename for chunk in result] == ["compensation.md"]
    assert result[0].score > 0


def test_sync_search_uses_precomputed_query_vector_without_embedding_client(monkeypatch):
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    vectors = []

    class FakeQuery:
        def __init__(self, model):
            self.model = model

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            if self.model is KnowledgeBase:
                return SimpleNamespace(id=kb_id, embedding_model="text-embedding-test")
            if self.model is LLMModel:
                return SimpleNamespace(type="embedding")
            return None

    class FakeDb:
        def query(self, model):
            return FakeQuery(model)

    chunk = SimpleNamespace(
        id=uuid.uuid4(),
        content="개발팀 커밋 컨벤션",
        metadata_={},
        parent_chunk_id=None,
        chunk_level="flat",
        token_count=8,
    )
    doc = SimpleNamespace(
        id=uuid.uuid4(),
        filename="commit-convention.md",
        meta_info={},
        source_type="FILE",
    )

    def fail_client_lookup(*_args, **_kwargs):
        raise AssertionError("precomputed query_vector must not request an embed client")

    monkeypatch.setattr(LLMService, "get_client_for_user", fail_client_lookup)

    service = RetrievalService(FakeDb(), user_id, organization_id=organization_id)
    monkeypatch.setattr(service, "_has_valid_hierarchy", lambda *_: False)

    def fake_vector_search(query_vector, *_args, **_kwargs):
        vectors.append(query_vector)
        return [(chunk, doc, 0.05)]

    monkeypatch.setattr(service, "_vector_search", fake_vector_search)

    result = service.search_documents_sync(
        "commit convention",
        knowledge_base_id=str(kb_id),
        threshold=0,
        hybrid_search=False,
        use_rerank=False,
        query_vector=[0.3, 0.7],
    )

    assert vectors == [[0.3, 0.7]]
    assert [chunk.filename for chunk in result] == ["commit-convention.md"]


def test_sync_search_rejects_non_embedding_model_before_vector_search(monkeypatch):
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()

    class FakeQuery:
        def __init__(self, model):
            self.model = model

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            if self.model is KnowledgeBase:
                return SimpleNamespace(id=kb_id, embedding_model="gpt-5.4-mini")
            if self.model is LLMModel:
                return SimpleNamespace(type="chat")
            return None

    class FakeDb:
        def query(self, model):
            return FakeQuery(model)

    service = RetrievalService(FakeDb(), user_id, organization_id=organization_id)
    monkeypatch.setattr(service, "_has_valid_hierarchy", lambda *_: False)
    monkeypatch.setattr(
        service,
        "_vector_search",
        lambda *_args, **_kwargs: pytest.fail("non-embedding model must not search"),
    )
    monkeypatch.setattr(
        LLMService,
        "get_client_for_user",
        lambda *_args, **_kwargs: pytest.fail("non-embedding model must not embed"),
    )

    assert (
        service.search_documents_sync(
            "질문",
            knowledge_base_id=str(kb_id),
            query_vector=[0.1, 0.2],
        )
        == []
    )
