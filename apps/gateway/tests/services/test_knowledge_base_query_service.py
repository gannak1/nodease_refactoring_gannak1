import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

from apps.gateway.services import knowledge_base_query_service as service_module
from apps.gateway.services.knowledge_base_query_service import (
    DEFAULT_EMBEDDING_MODEL,
    KnowledgeBaseCreateFailed,
    KnowledgeBaseNotFound,
    KnowledgeBaseQueryService,
    KnowledgeSchemaNotReady,
    KnowledgeValidationError,
    evaluate_llm_rag_selectability,
)
from apps.shared.db.models.knowledge import SourceType
from apps.shared.services.knowledge_schema_readiness import (
    KnowledgeSchemaReadinessResult,
)


class FakeKnowledgeQuery:
    def __init__(self, rows):
        self.rows = rows

    def select_from(self, *_args, **_kwargs):
        return self

    def join(self, *_args, **_kwargs):
        return self

    def outerjoin(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def group_by(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows


class FakeKnowledgeDb:
    def __init__(self, rows):
        self.rows = rows
        self.query_entities = []

    def query(self, *entities):
        self.query_entities.append(entities)
        return FakeKnowledgeQuery(self.rows)


class FakeSelectableDb:
    def __init__(self, kbs):
        self.kbs = kbs
        self.query_entities = []

    def query(self, *entities):
        self.query_entities.append(entities)
        return FakeKnowledgeQuery(self.kbs)


class FakeDetailQuery:
    def __init__(self, *, first_value=None, all_value=None):
        self.first_value = first_value
        self.all_value = all_value or []
        self.filters = []

    def select_from(self, *_args, **_kwargs):
        return self

    def join(self, *_args, **_kwargs):
        return self

    def outerjoin(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        self.filters.extend(_args)
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def group_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.first_value

    def all(self):
        return self.all_value


class FakeDetailDb:
    def __init__(self, kb_row, doc_rows, chunk_rows=None):
        self.kb_row = kb_row
        self.doc_rows = doc_rows
        self.chunk_rows = chunk_rows or []
        self.query_count = 0
        self.query_entities = []
        self.queries = []

    def query(self, *entities):
        self.query_count += 1
        self.query_entities.append(entities)
        if self.query_count == 1:
            query = FakeDetailQuery(first_value=self.kb_row)
            self.queries.append(query)
            return query
        if self.query_count == 2:
            query = FakeDetailQuery(all_value=self.doc_rows)
            self.queries.append(query)
            return query
        query = FakeDetailQuery(all_value=self.chunk_rows)
        self.queries.append(query)
        return query


class FakeCreateDb:
    def __init__(self):
        self.added = None
        self.added_items = []
        self.committed = False
        self.rolled_back = False
        self.info = {}

    def add(self, item):
        self.added_items.append(item)
        if isinstance(item, service_module.KnowledgeBase):
            self.added = item

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, item):
        item.id = item.id or uuid.uuid4()
        item.created_at = item.created_at or datetime.now(timezone.utc)
        item.updated_at = item.updated_at or item.created_at


class FailingCreateDb(FakeCreateDb):
    def commit(self):
        raise SQLAlchemyError("simulated write failure")


def test_list_maps_legacy_documentless_rows_without_full_orm_load():
    kb_id = uuid.uuid4()
    row = (
        kb_id,
        None,
        "문서 없는 KB",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    db = FakeKnowledgeDb([row])

    response = KnowledgeBaseQueryService(db).list(
        user_id=uuid.uuid4(),
        organization_scope=None,
        has_organization_id=False,
    )

    assert all(
        entity is not service_module.KnowledgeBase
        for query_entities in db.query_entities
        for entity in query_entities
    )
    assert response[0].id == kb_id
    assert response[0].organization_id is None
    assert response[0].document_count == 0
    assert response[0].source_types == []
    assert response[0].embedding_model == DEFAULT_EMBEDDING_MODEL
    assert response[0].created_at is not None
    assert response[0].updated_at is not None


def test_list_normalizes_source_types_and_uses_latest_document_update():
    kb_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    created_at = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    kb_updated_at = datetime(2026, 7, 7, 2, tzinfo=timezone.utc)
    doc_updated_at = datetime(2026, 7, 7, 3, tzinfo=timezone.utc)
    row = (
        kb_id,
        organization_id,
        "휴가 정책 KB",
        "휴가 정책",
        "custom-embedding",
        created_at,
        kb_updated_at,
        2,
        doc_updated_at,
        [SourceType.FILE, " API ", None, '"CSV"', "'EMAIL'", SourceType.FILE],
    )

    response = KnowledgeBaseQueryService(FakeKnowledgeDb([row])).list(
        user_id=uuid.uuid4(),
        organization_scope=organization_id,
        has_organization_id=True,
    )

    assert response[0].organization_id == organization_id
    assert response[0].document_count == 2
    assert response[0].created_at == created_at
    assert response[0].updated_at == doc_updated_at
    assert response[0].source_types == ["FILE", "API", "CSV", "EMAIL"]
    assert response[0].embedding_model == "custom-embedding"


def test_list_normalizes_string_array_source_types():
    kb_id = uuid.uuid4()
    row = (
        kb_id,
        None,
        "문자열 source type KB",
        None,
        None,
        None,
        None,
        2,
        None,
        '{"FILE", "API"}',
    )

    response = KnowledgeBaseQueryService(FakeKnowledgeDb([row])).list(
        user_id=uuid.uuid4(),
        organization_scope=None,
        has_organization_id=False,
    )

    assert response[0].source_types == ["FILE", "API"]


def test_get_detail_maps_documents_without_full_kb_orm_load():
    knowledge_base_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    doc_id = uuid.uuid4()
    db = FakeDetailDb(
        (
            knowledge_base_id,
            organization_id,
            "사내 정책 KB",
            "테스트 상세",
            "text-embedding-3-small",
            now,
            None,
            None,
        ),
        [
            (
                doc_id,
                "policy.pdf",
                "completed",
                now,
                None,
                None,
                SourceType.FILE,
                {"category": "policy"},
            )
        ],
    )

    response = KnowledgeBaseQueryService(
        db,
        column_exists=lambda *_args, **_kwargs: False,
        finalize_processing_start=lambda *_args, **_kwargs: False,
        recover_processing_timeout=lambda *_args, **_kwargs: False,
    ).get_detail(
        knowledge_base_id,
        user_id=uuid.uuid4(),
        organization_scope=organization_id,
        has_organization_id=True,
    )

    assert all(
        entity is not service_module.KnowledgeBase
        for query_entities in db.query_entities
        for entity in query_entities
    )
    assert response.id == knowledge_base_id
    assert response.organization_id == organization_id
    assert response.document_count == 1
    assert response.source_types == ["FILE"]
    assert response.documents[0].id == doc_id
    assert response.documents[0].chunk_count == 0


def test_list_llm_selectable_uses_kb_use_permission_and_ready_boundary(monkeypatch):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    ready_allowed_id = uuid.uuid4()
    ready_denied_id = uuid.uuid4()
    not_ready_allowed_id = uuid.uuid4()
    kbs = [
        SimpleNamespace(
            id=ready_allowed_id,
            organization_id=organization_id,
            lifecycle_state="active",
            source_identity_id=None,
            name="권한 있는 완료 KB",
            description=None,
            embedding_model="text-embedding-3-small",
            created_at=now,
            updated_at=now,
        ),
        SimpleNamespace(
            id=ready_denied_id,
            organization_id=organization_id,
            lifecycle_state="active",
            source_identity_id=None,
            name="권한 없는 완료 KB",
            description=None,
            embedding_model="text-embedding-3-small",
            created_at=now,
            updated_at=now,
        ),
        SimpleNamespace(
            id=not_ready_allowed_id,
            organization_id=organization_id,
            lifecycle_state="active",
            source_identity_id=None,
            name="권한 있는 처리 전 KB",
            description=None,
            embedding_model="text-embedding-3-small",
            created_at=now,
            updated_at=now,
        ),
    ]
    captured = {}

    class FakePermissionHelper:
        def __init__(self, _db, *, user_id, organization_id):
            captured["user_id"] = user_id
            captured["organization_id"] = organization_id

        def bulk_evaluate_kb_use(self, kbs):
            return {
                kb.id: SimpleNamespace(allowed=kb.id != ready_denied_id)
                for kb in kbs
            }

    service = KnowledgeBaseQueryService(
        FakeSelectableDb(kbs),
        permission_helper_factory=FakePermissionHelper,
    )
    detail_by_id = {
        ready_allowed_id: service_module.KnowledgeBaseDetailResponse(
            id=ready_allowed_id,
            organization_id=organization_id,
            name="권한 있는 완료 KB",
            description=None,
            document_count=1,
            created_at=now,
            updated_at=now,
            source_types=["FILE"],
            embedding_model="text-embedding-3-small",
            documents=[
                service_module.DocumentResponse(
                    id=uuid.uuid4(),
                    filename="ready.md",
                    status="completed",
                    created_at=now,
                    updated_at=now,
                    chunk_count=1,
                    token_count=10,
                )
            ],
        ),
        ready_denied_id: service_module.KnowledgeBaseDetailResponse(
            id=ready_denied_id,
            organization_id=organization_id,
            name="권한 없는 완료 KB",
            description=None,
            document_count=1,
            created_at=now,
            updated_at=now,
            source_types=["FILE"],
            embedding_model="text-embedding-3-small",
            documents=[
                service_module.DocumentResponse(
                    id=uuid.uuid4(),
                    filename="denied.md",
                    status="completed",
                    created_at=now,
                    updated_at=now,
                    chunk_count=1,
                    token_count=10,
                )
            ],
        ),
        not_ready_allowed_id: service_module.KnowledgeBaseDetailResponse(
            id=not_ready_allowed_id,
            organization_id=organization_id,
            name="권한 있는 처리 전 KB",
            description=None,
            document_count=1,
            created_at=now,
            updated_at=now,
            source_types=["FILE"],
            embedding_model="text-embedding-3-small",
            documents=[
                service_module.DocumentResponse(
                    id=uuid.uuid4(),
                    filename="pending.md",
                    status="pending",
                    created_at=now,
                    updated_at=now,
                    chunk_count=0,
                    token_count=0,
                )
            ],
        ),
    }
    monkeypatch.setattr(
        service,
        "_detail_response_from_kb",
        lambda kb: detail_by_id[kb.id],
    )

    response = service.list_llm_selectable(
        user_id=user_id,
        organization_id=organization_id,
        schema_ready=True,
    )

    assert captured == {"user_id": user_id, "organization_id": organization_id}
    assert [item.id for item in response] == [ready_allowed_id]


def test_list_llm_selectable_excludes_completed_document_without_visible_chunks(
    monkeypatch,
):
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    kb_id = uuid.uuid4()
    kb = SimpleNamespace(
        id=kb_id,
        organization_id=organization_id,
        lifecycle_state="active",
        source_identity_id=None,
        name="완료됐지만 검색 불가 KB",
        description=None,
        embedding_model="text-embedding-3-small",
        created_at=now,
        updated_at=now,
    )

    class FakePermissionHelper:
        def __init__(self, _db, *, user_id, organization_id):
            pass

        def bulk_evaluate_kb_use(self, kbs):
            return {item.id: SimpleNamespace(allowed=True) for item in kbs}

    service = KnowledgeBaseQueryService(
        FakeSelectableDb([kb]),
        permission_helper_factory=FakePermissionHelper,
    )
    monkeypatch.setattr(
        service,
        "_detail_response_from_kb",
        lambda _kb: service_module.KnowledgeBaseDetailResponse(
            id=kb_id,
            organization_id=organization_id,
            name="완료됐지만 검색 불가 KB",
            description=None,
            document_count=1,
            created_at=now,
            updated_at=now,
            source_types=["FILE"],
            embedding_model="text-embedding-3-small",
            documents=[
                service_module.DocumentResponse(
                    id=uuid.uuid4(),
                    filename="empty-ready.md",
                    status="completed",
                    created_at=now,
                    updated_at=now,
                    chunk_count=0,
                    token_count=0,
                )
            ],
        ),
    )

    response = service.list_llm_selectable(
        user_id=user_id,
        organization_id=organization_id,
        schema_ready=True,
    )

    assert response == []


def test_get_detail_raises_not_found_for_missing_or_hidden_kb():
    db = FakeDetailDb(None, [])

    with pytest.raises(KnowledgeBaseNotFound):
        KnowledgeBaseQueryService(db).get_detail(
            uuid.uuid4(),
            user_id=uuid.uuid4(),
            organization_scope=uuid.uuid4(),
            has_organization_id=True,
        )


def test_get_detail_uses_chunk_counts_when_chunk_table_is_available():
    knowledge_base_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    ready_doc_id = uuid.uuid4()
    empty_doc_id = uuid.uuid4()
    db = FakeDetailDb(
        (
            knowledge_base_id,
            organization_id,
            "청크 집계 KB",
            None,
            "text-embedding-3-small",
            now,
            None,
            None,
        ),
        [
            (
                ready_doc_id,
                "ready.pdf",
                "completed",
                now,
                None,
                None,
                SourceType.FILE,
                {},
            ),
            (
                empty_doc_id,
                "empty.pdf",
                "completed",
                now,
                None,
                None,
                SourceType.FILE,
                {},
            ),
        ],
        [(ready_doc_id, 2)],
    )

    response = KnowledgeBaseQueryService(
        db,
        column_exists=lambda *_args, **_kwargs: True,
        finalize_processing_start=lambda *_args, **_kwargs: False,
        recover_processing_timeout=lambda *_args, **_kwargs: False,
    ).get_detail(
        knowledge_base_id,
        user_id=uuid.uuid4(),
        organization_scope=organization_id,
        has_organization_id=True,
    )

    assert {doc.id: doc.chunk_count for doc in response.documents} == {
        ready_doc_id: 2,
        empty_doc_id: 0,
    }


def test_get_detail_normalizes_non_dict_meta_info_to_safe_empty_dict():
    knowledge_base_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    document_id = uuid.uuid4()
    db = FakeDetailDb(
        (
            knowledge_base_id,
            organization_id,
            "비정상 메타데이터 KB",
            None,
            "text-embedding-3-small",
            now,
            None,
            None,
        ),
        [
            (
                document_id,
                "corrupt-meta.pdf",
                "completed",
                now,
                None,
                None,
                SourceType.FILE,
                ["unexpected", "metadata"],
            ),
        ],
        [(document_id, 1)],
    )

    response = KnowledgeBaseQueryService(
        db,
        column_exists=lambda *_args, **_kwargs: True,
        finalize_processing_start=lambda *_args, **_kwargs: False,
        recover_processing_timeout=lambda *_args, **_kwargs: False,
    ).get_detail(
        knowledge_base_id,
        user_id=uuid.uuid4(),
        organization_scope=organization_id,
        has_organization_id=True,
    )

    assert response.documents[0].meta_info == {}


def test_get_detail_counts_only_active_ready_version_chunks_for_selectability():
    knowledge_base_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    active_version_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    document_id = uuid.uuid4()
    db = FakeDetailDb(
        (
            knowledge_base_id,
            organization_id,
            "버전 청크 KB",
            None,
            "text-embedding-3-small",
            now,
            None,
            active_version_id,
        ),
        [
            (
                document_id,
                "versioned.pdf",
                "completed",
                now,
                None,
                None,
                SourceType.FILE,
                {},
            ),
        ],
        [(document_id, 1)],
    )

    response = KnowledgeBaseQueryService(
        db,
        column_exists=lambda *_args, **_kwargs: True,
        finalize_processing_start=lambda *_args, **_kwargs: False,
        recover_processing_timeout=lambda *_args, **_kwargs: False,
    ).get_detail(
        knowledge_base_id,
        user_id=uuid.uuid4(),
        organization_scope=organization_id,
        has_organization_id=True,
    )

    chunk_filter_sql = " ".join(str(item) for item in db.queries[2].filters)
    assert response.documents[0].chunk_count == 1
    assert "document_chunks.document_version_id" in chunk_filter_sql
    assert "document_versions.status" in chunk_filter_sql


def test_llm_rag_selectability_requires_completed_document_with_chunks():
    knowledge_base_id = uuid.uuid4()
    now = datetime(2026, 7, 7, 1, tzinfo=timezone.utc)
    completed_doc_id = uuid.uuid4()
    db = FakeDetailDb(
        (
            knowledge_base_id,
            None,
            "온보딩 KB",
            None,
            "text-embedding-3-small",
            now,
            None,
            None,
        ),
        [
            (
                completed_doc_id,
                "onboarding.pdf",
                "completed",
                now,
                None,
                None,
                SourceType.FILE,
                {},
            ),
            (
                uuid.uuid4(),
                "pending.pdf",
                "processing",
                now,
                None,
                None,
                SourceType.FILE,
                {},
            ),
        ],
        [(completed_doc_id, 3)],
    )

    selectability = KnowledgeBaseQueryService(
        db,
        column_exists=lambda *_args, **_kwargs: True,
        finalize_processing_start=lambda *_args, **_kwargs: False,
        recover_processing_timeout=lambda *_args, **_kwargs: False,
    ).get_llm_rag_selectability(
        knowledge_base_id,
        user_id=uuid.uuid4(),
        organization_scope=None,
        has_organization_id=False,
    )

    assert selectability.available is True
    assert selectability.state == "available"
    assert selectability.safe_reason_code == "completed_document_available"
    assert selectability.completed_document_count == 1
    assert selectability.document_count == 2


def test_llm_rag_selectability_reports_not_ready_when_completed_document_has_no_chunks():
    detail = service_module.KnowledgeBaseDetailResponse(
        id=uuid.uuid4(),
        organization_id=None,
        name="청크 없는 완료 KB",
        description=None,
        document_count=1,
        created_at=datetime(2026, 7, 7, 1, tzinfo=timezone.utc),
        updated_at=None,
        source_types=["FILE"],
        embedding_model="text-embedding-3-small",
        documents=[
            service_module.DocumentResponse(
                id=uuid.uuid4(),
                filename="empty-completed.pdf",
                status="completed",
                created_at=datetime(2026, 7, 7, 1, tzinfo=timezone.utc),
                chunk_count=0,
            )
        ],
    )

    selectability = evaluate_llm_rag_selectability(detail)

    assert selectability.available is False
    assert selectability.state == "not_ready"
    assert selectability.safe_reason_code == "no_completed_document_chunks"
    assert selectability.completed_document_count == 0
    assert selectability.document_count == 1


def test_llm_rag_selectability_reports_not_ready_without_completed_document():
    detail = service_module.KnowledgeBaseDetailResponse(
        id=uuid.uuid4(),
        organization_id=None,
        name="처리 중 KB",
        description=None,
        document_count=1,
        created_at=datetime(2026, 7, 7, 1, tzinfo=timezone.utc),
        updated_at=None,
        source_types=["FILE"],
        embedding_model="text-embedding-3-small",
        documents=[
            service_module.DocumentResponse(
                id=uuid.uuid4(),
                filename="pending.pdf",
                status="processing",
                created_at=datetime(2026, 7, 7, 1, tzinfo=timezone.utc),
            )
        ],
    )

    selectability = evaluate_llm_rag_selectability(detail)

    assert selectability.available is False
    assert selectability.state == "not_ready"
    assert selectability.safe_reason_code == "no_completed_documents"
    assert selectability.completed_document_count == 0
    assert selectability.document_count == 1


def test_llm_rag_selectability_reports_empty_kb_as_not_ready():
    detail = service_module.KnowledgeBaseDetailResponse(
        id=uuid.uuid4(),
        organization_id=None,
        name="빈 KB",
        description=None,
        document_count=0,
        created_at=datetime(2026, 7, 7, 1, tzinfo=timezone.utc),
        updated_at=None,
        source_types=[],
        embedding_model="text-embedding-3-small",
        documents=[],
    )

    selectability = evaluate_llm_rag_selectability(detail)

    assert selectability.available is False
    assert selectability.safe_reason_code == "no_documents"
    assert selectability.document_count == 0


def test_create_raises_schema_not_ready_without_http_dependency(monkeypatch):
    monkeypatch.setattr(
        service_module,
        "check_knowledge_schema_readiness",
        lambda *_args, **_kwargs: KnowledgeSchemaReadinessResult(
            missing_columns={"knowledge_bases": ["sync_state"]},
        ),
    )

    with pytest.raises(KnowledgeSchemaNotReady) as exc_info:
        KnowledgeBaseQueryService(FakeCreateDb()).create(
            service_module.KnowledgeBaseCreate(name="stale schema KB"),
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
        )

    assert exc_info.value.missing_columns == {"knowledge_bases": ["sync_state"]}


def test_create_rolls_back_on_write_failure():
    db = FailingCreateDb()

    with pytest.raises(KnowledgeBaseCreateFailed):
        KnowledgeBaseQueryService(db).create(
            service_module.KnowledgeBaseCreate(name="쓰기 실패 KB"),
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            schema_ready=True,
        )

    assert db.rolled_back is True


@pytest.mark.parametrize(
    ("name", "embedding_model", "reason"),
    [
        ("   ", "text-embedding-3-small", "name_required"),
        ("가" * 256, "text-embedding-3-small", "name_too_long"),
        ("정책 KB", "", "embedding_model_invalid"),
        ("정책 KB", "   ", "embedding_model_invalid"),
        ("정책 KB", "sk-secret-like-model", "embedding_model_invalid"),
        ("정책 KB", "../bad model", "embedding_model_invalid"),
    ],
)
def test_create_validates_request_before_db_write(name, embedding_model, reason):
    db = FakeCreateDb()

    with pytest.raises(KnowledgeValidationError) as exc_info:
        KnowledgeBaseQueryService(db).create(
            service_module.KnowledgeBaseCreate(
                name=name,
                embedding_model=embedding_model,
            ),
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            schema_ready=True,
        )

    assert exc_info.value.reason == reason
    assert db.added is None
    assert db.committed is False
    assert db.rolled_back is False


def test_create_trims_name_and_embedding_model_before_insert():
    db = FakeCreateDb()

    response = KnowledgeBaseQueryService(db).create(
        service_module.KnowledgeBaseCreate(
            name="  정책 KB  ",
            embedding_model=" text-embedding-3-small ",
        ),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        schema_ready=True,
    )

    assert response.name == "정책 KB"
    assert response.embedding_model == "text-embedding-3-small"
    assert db.added.name == "정책 KB"
    assert db.added.embedding_model == "text-embedding-3-small"


def test_create_allows_duplicate_display_names_with_distinct_ids():
    class TrackingCreateDb(FakeCreateDb):
        def __init__(self):
            super().__init__()
            self.knowledge_bases = []

        def add(self, item):
            super().add(item)
            if isinstance(item, service_module.KnowledgeBase):
                self.knowledge_bases.append(item)

    db = TrackingCreateDb()
    service = KnowledgeBaseQueryService(db)
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()

    first = service.create(
        service_module.KnowledgeBaseCreate(name="중복 표시명 KB"),
        user_id=user_id,
        organization_id=organization_id,
        schema_ready=True,
    )
    second = service.create(
        service_module.KnowledgeBaseCreate(name="중복 표시명 KB"),
        user_id=user_id,
        organization_id=organization_id,
        schema_ready=True,
    )

    assert first.name == second.name == "중복 표시명 KB"
    assert first.id != second.id
    assert [item.name for item in db.knowledge_bases] == [
        "중복 표시명 KB",
        "중복 표시명 KB",
    ]


def test_create_bootstraps_creator_manager_and_audits_in_one_commit():
    db = FakeCreateDb()
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()

    response = KnowledgeBaseQueryService(db).create(
        service_module.KnowledgeBaseCreate(name="원자 생성 KB"),
        user_id=user_id,
        organization_id=organization_id,
        schema_ready=True,
    )

    permissions = [
        item
        for item in db.added_items
        if isinstance(item, service_module.UserKnowledgePermission)
    ]
    audits = [
        item for item in db.added_items if isinstance(item, service_module.AuditLog)
    ]
    assert response.id == db.added.id
    assert len(permissions) == 1
    assert permissions[0].knowledge_base_id == response.id
    assert permissions[0].user_id == user_id
    assert permissions[0].auth_state == "manager"
    assert {audit.action for audit in audits} == {
        "knowledge.created",
        "user_knowledge_permission.created",
    }
    assert db.committed is True
