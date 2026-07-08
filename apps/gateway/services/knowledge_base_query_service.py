import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from sqlalchemy import and_, func, literal
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.gateway.services.ingestion.service import (
    finalize_stale_processing_start,
    recover_timed_out_document_with_artifacts,
)
from apps.shared.db.models.knowledge import (
    Document,
    DocumentChunk,
    DocumentVersion,
    KnowledgeBase,
)
from apps.shared.schemas.rag import (
    DocumentResponse,
    KnowledgeBaseCreate,
    KnowledgeBaseDetailResponse,
    KnowledgeBaseResponse,
)
from apps.shared.services.knowledge_schema_readiness import (
    check_knowledge_schema_readiness,
    table_has_column,
)

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
KNOWLEDGE_BASE_MUTATION_COLUMNS = {
    "knowledge_bases": {
        "organization_id",
        "active_document_version_id",
        "source_identity_id",
        "sync_state",
        "lifecycle_state",
    }
}

ColumnExistsFn = Callable[[Session, str, str], bool]
DocumentRecoveryFn = Callable[[Session, UUID], bool]


class KnowledgeBaseQueryServiceError(Exception):
    """Base exception for Knowledge Base query service failures."""


class KnowledgeSchemaNotReady(KnowledgeBaseQueryServiceError):
    def __init__(
        self,
        missing_columns: dict[str, list[str]],
        *,
        reason: str | None = None,
    ):
        self.missing_columns = missing_columns
        self.reason = reason
        super().__init__("Knowledge database schema is not ready.")


class KnowledgeBaseCreateFailed(KnowledgeBaseQueryServiceError):
    pass


class KnowledgeBaseNotFound(KnowledgeBaseQueryServiceError):
    pass


class KnowledgeBaseHiddenOrForbidden(KnowledgeBaseNotFound):
    pass


class KnowledgeValidationError(KnowledgeBaseQueryServiceError):
    pass


class KnowledgeConflict(KnowledgeBaseQueryServiceError):
    pass


@dataclass(frozen=True)
class LLMRAGSelectability:
    state: str
    safe_reason_code: str
    completed_document_count: int
    document_count: int

    @property
    def available(self) -> bool:
        return self.state == "available"


def _clean_source_types(source_types) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    if isinstance(source_types, str):
        stripped = source_types.strip("{}")
        source_types = [
            value.strip().strip('"').strip("'")
            for value in stripped.split(",")
            if value.strip()
        ]
    for source_type in source_types or []:
        if source_type is None:
            continue
        value = getattr(source_type, "value", source_type)
        if value is None:
            continue
        value = str(value).strip().strip('"').strip("'")
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def _clean_source_type(source_type) -> str:
    value = getattr(source_type, "value", source_type)
    if value is None:
        return "FILE"
    return str(value)


def _safe_meta_info(meta_info) -> dict:
    if isinstance(meta_info, dict):
        return meta_info
    return {}


def _max_datetime_or_now(*values):
    candidates = [value for value in values if value is not None]
    if candidates:
        return max(candidates)
    return datetime.now(timezone.utc)


def evaluate_llm_rag_selectability(
    detail: KnowledgeBaseDetailResponse,
) -> LLMRAGSelectability:
    completed_count = sum(
        1
        for doc in detail.documents
        if doc.status == "completed" and (doc.chunk_count or 0) > 0
    )
    if completed_count > 0:
        return LLMRAGSelectability(
            state="available",
            safe_reason_code="completed_document_available",
            completed_document_count=completed_count,
            document_count=len(detail.documents),
        )
    has_completed_documents = any(doc.status == "completed" for doc in detail.documents)
    return LLMRAGSelectability(
        state="not_ready",
        safe_reason_code=(
            "no_documents"
            if not detail.documents
            else (
                "no_completed_document_chunks"
                if has_completed_documents
                else "no_completed_documents"
            )
        ),
        completed_document_count=0,
        document_count=len(detail.documents),
    )


class KnowledgeBaseQueryService:
    def __init__(
        self,
        db: Session,
        *,
        column_exists: ColumnExistsFn = table_has_column,
        finalize_processing_start: DocumentRecoveryFn = finalize_stale_processing_start,
        recover_processing_timeout: DocumentRecoveryFn = (
            recover_timed_out_document_with_artifacts
        ),
    ):
        self.db = db
        self._column_exists = column_exists
        self._finalize_processing_start = finalize_processing_start
        self._recover_processing_timeout = recover_processing_timeout

    def has_column(self, table_name: str, column_name: str) -> bool:
        return self._column_exists(self.db, table_name, column_name)

    def ensure_schema_ready(self, required_columns: dict[str, set[str]]) -> None:
        result = check_knowledge_schema_readiness(self.db, required_columns)
        if not result.ready:
            raise KnowledgeSchemaNotReady(
                result.missing_columns,
                reason=result.reason,
            )

    def create(
        self,
        kb_in: KnowledgeBaseCreate,
        *,
        user_id: UUID,
        organization_id: UUID | None,
        schema_ready: bool = False,
    ) -> KnowledgeBaseResponse:
        if not schema_ready:
            self.ensure_schema_ready(KNOWLEDGE_BASE_MUTATION_COLUMNS)
        kb = KnowledgeBase(
            name=kb_in.name,
            description=kb_in.description,
            embedding_model=kb_in.embedding_model,
            organization_id=organization_id,
            user_id=user_id,
        )
        self.db.add(kb)
        try:
            self.db.commit()
            self.db.refresh(kb)
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("knowledge.create.failed")
            raise KnowledgeBaseCreateFailed from None

        return KnowledgeBaseResponse(
            id=kb.id,
            organization_id=kb.organization_id,
            name=kb.name,
            description=kb.description,
            document_count=0,
            created_at=kb.created_at,
            updated_at=kb.updated_at,
            source_types=[],
            embedding_model=kb.embedding_model,
        )

    def list(
        self,
        *,
        user_id: UUID,
        organization_scope: UUID | None,
        has_organization_id: bool,
    ) -> list[KnowledgeBaseResponse]:
        organization_id_column = (
            KnowledgeBase.organization_id
            if has_organization_id
            else literal(None).label("organization_id")
        )
        group_by_columns = [
            KnowledgeBase.id,
            KnowledgeBase.name,
            KnowledgeBase.description,
            KnowledgeBase.embedding_model,
            KnowledgeBase.created_at,
            KnowledgeBase.updated_at,
        ]
        if has_organization_id:
            group_by_columns.append(KnowledgeBase.organization_id)

        query = (
            self.db.query(
                KnowledgeBase.id,
                organization_id_column,
                KnowledgeBase.name,
                KnowledgeBase.description,
                KnowledgeBase.embedding_model,
                KnowledgeBase.created_at,
                KnowledgeBase.updated_at,
                func.count(Document.id).label("document_count"),
                func.max(Document.updated_at).label("last_updated_at"),
                func.array_agg(Document.source_type).label("source_types"),
            )
            .select_from(KnowledgeBase)
            .outerjoin(Document, KnowledgeBase.id == Document.knowledge_base_id)
            .filter(KnowledgeBase.user_id == user_id)
        )
        if organization_scope is not None:
            query = query.filter(KnowledgeBase.organization_id == organization_scope)
        results = (
            query.group_by(*group_by_columns)
            .order_by(KnowledgeBase.created_at.desc())
            .all()
        )

        response: list[KnowledgeBaseResponse] = []
        for (
            kb_id,
            organization_id,
            name,
            description,
            embedding_model,
            created_at,
            updated_at,
            doc_count,
            last_updated_at,
            source_types,
        ) in results:
            created_at = created_at or _max_datetime_or_now(
                updated_at, last_updated_at
            )
            final_updated_at = _max_datetime_or_now(
                updated_at, last_updated_at, created_at
            )
            response.append(
                KnowledgeBaseResponse(
                    id=kb_id,
                    organization_id=organization_id,
                    name=name,
                    description=description,
                    document_count=int(doc_count or 0),
                    created_at=created_at,
                    updated_at=final_updated_at,
                    source_types=_clean_source_types(source_types),
                    embedding_model=embedding_model or DEFAULT_EMBEDDING_MODEL,
                )
            )
        return response

    def get_detail(
        self,
        kb_id: UUID,
        *,
        user_id: UUID,
        organization_scope: UUID | None,
        has_organization_id: bool,
    ) -> KnowledgeBaseDetailResponse:
        organization_id_column = (
            KnowledgeBase.organization_id
            if has_organization_id
            else literal(None).label("organization_id")
        )
        has_active_document_version_id = self.has_column(
            "knowledge_bases",
            "active_document_version_id",
        )
        active_document_version_id_column = (
            KnowledgeBase.active_document_version_id
            if has_active_document_version_id
            else literal(None).label("active_document_version_id")
        )

        kb_query = (
            self.db.query(
                KnowledgeBase.id,
                organization_id_column,
                KnowledgeBase.name,
                KnowledgeBase.description,
                KnowledgeBase.embedding_model,
                KnowledgeBase.created_at,
                KnowledgeBase.updated_at,
                active_document_version_id_column,
            )
            .select_from(KnowledgeBase)
            .filter(KnowledgeBase.id == kb_id, KnowledgeBase.user_id == user_id)
        )
        if organization_scope is not None:
            kb_query = kb_query.filter(KnowledgeBase.organization_id == organization_scope)
        kb = kb_query.first()

        if not kb:
            raise KnowledgeBaseNotFound

        (
            kb_id,
            organization_id,
            name,
            description,
            embedding_model,
            created_at,
            updated_at,
            active_document_version_id,
        ) = kb

        doc_rows_query = (
            self.db.query(
                Document.id,
                Document.filename,
                Document.status,
                Document.created_at,
                Document.updated_at,
                Document.error_message,
                Document.source_type,
                Document.meta_info,
            )
            .select_from(Document)
            .filter(Document.knowledge_base_id == kb_id)
            .order_by(Document.created_at.asc())
        )
        doc_rows = doc_rows_query.all()
        if self._recover_document_rows(doc_rows):
            doc_rows = doc_rows_query.all()

        chunk_counts = self._retrieval_visible_chunk_counts(
            kb_id,
            active_document_version_id=active_document_version_id,
        )
        doc_responses = []
        for (
            document_id,
            filename,
            document_status,
            document_created_at,
            document_updated_at,
            error_message,
            source_type,
            meta_info,
        ) in doc_rows:
            doc_responses.append(
                DocumentResponse(
                    id=document_id,
                    filename=filename,
                    status=document_status or "pending",
                    created_at=document_created_at or _max_datetime_or_now(),
                    updated_at=document_updated_at,
                    error_message=error_message,
                    chunk_count=chunk_counts.get(document_id, 0),
                    token_count=0,
                    source_type=_clean_source_type(source_type),
                    meta_info=_safe_meta_info(meta_info),
                )
            )

        return KnowledgeBaseDetailResponse(
            id=kb_id,
            organization_id=organization_id,
            name=name,
            description=description,
            document_count=len(doc_responses),
            created_at=created_at or _max_datetime_or_now(updated_at),
            updated_at=updated_at or created_at,
            source_types=_clean_source_types([row[6] for row in doc_rows]),
            embedding_model=embedding_model or DEFAULT_EMBEDDING_MODEL,
            documents=doc_responses,
        )

    def get_llm_rag_selectability(
        self,
        kb_id: UUID,
        *,
        user_id: UUID,
        organization_scope: UUID | None,
        has_organization_id: bool,
    ) -> LLMRAGSelectability:
        detail = self.get_detail(
            kb_id,
            user_id=user_id,
            organization_scope=organization_scope,
            has_organization_id=has_organization_id,
        )
        return evaluate_llm_rag_selectability(detail)

    def _recover_document_rows(self, doc_rows) -> bool:
        document_status_changed = False
        for document_id, *_ in doc_rows:
            if self._finalize_processing_start(
                self.db,
                document_id,
            ) or self._recover_processing_timeout(self.db, document_id):
                document_status_changed = True
        return document_status_changed

    def _retrieval_visible_chunk_counts(
        self,
        kb_id: UUID,
        *,
        active_document_version_id: UUID | None,
    ) -> dict[UUID, int]:
        if not self.has_column("document_chunks", "id"):
            return {}
        query = (
            self.db.query(
                DocumentChunk.document_id,
                func.count(DocumentChunk.id).label("chunk_count"),
            )
            .select_from(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(
                DocumentChunk.knowledge_base_id == kb_id,
                Document.status == "completed",
            )
        )
        if not self.has_column("document_chunks", "document_version_id"):
            return {
                document_id: int(chunk_count or 0)
                for document_id, chunk_count in query.group_by(
                    DocumentChunk.document_id
                ).all()
            }
        if active_document_version_id is None:
            query = query.filter(DocumentChunk.document_version_id.is_(None))
        else:
            if not self.has_column("document_versions", "status"):
                return {}
            query = (
                query.outerjoin(
                    DocumentVersion,
                    DocumentChunk.document_version_id == DocumentVersion.id,
                )
                .filter(
                    and_(
                        DocumentChunk.document_version_id
                        == active_document_version_id,
                        DocumentVersion.status == "ready",
                    )
                )
            )
        return {
            document_id: int(chunk_count or 0)
            for document_id, chunk_count in (
                query.group_by(DocumentChunk.document_id).all()
            )
        }
