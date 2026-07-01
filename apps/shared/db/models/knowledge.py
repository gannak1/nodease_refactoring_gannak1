import enum
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from apps.shared.db.base import Base
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


class KnowledgeBase(Base):
    """
    지식 베이스 모델: 여러 문서를 그룹화하는 최상위 개념
    """

    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 임베딩 모델 정보
    embedding_model: Mapped[str] = mapped_column(
        String(50), default="text-embedding-3-small", nullable=False
    )
    # 검색 설정
    top_k: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    similarity_threshold: Mapped[float] = mapped_column(
        Float, default=0.7, nullable=False
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationship
    documents: Mapped[List["Document"]] = relationship(
        "Document", back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    answer_runs: Mapped[List["RAGAnswerRun"]] = relationship(
        "RAGAnswerRun", back_populates="knowledge_base"
    )


class SourceType(str, enum.Enum):
    FILE = "FILE"
    API = "API"
    DB = "DB"


class Document(Base):
    """
    문서 모델: 업로드된 개별 파일 또는 API 소스
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id"), nullable=False, index=True
    )

    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # 소스 타입 (FILE/API)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType), default=SourceType.FILE, nullable=False
    )

    # 변경 감지용 해시 (API 소스 등에서 사용)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 상태 관리: pending -> indexing -> completed / failed / waiting_for_approval
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)

    # 실패 원인 담는 에러메세지
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 청킹 설정
    chunk_size: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50, nullable=False)

    # 메타 데이터 (파일 크기, 파싱 결과 요약 등)
    meta_info: Mapped[dict] = mapped_column(JSONB, default={})

    # 임베딩 생성 시 사용한 모델명
    embedding_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="documents"
    )
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    """
    문서 청크 모델 (Vector Store)
    실제 검색 대상이 되는 텍스트 조각과 벡터 임베딩을 저장
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index(
            "ix_document_chunks_knowledge_base_id_chunk_level",
            "knowledge_base_id",
            "chunk_level",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id"), nullable=False
    )
    # 바로 검색 가능하도록 성능 최적화를 위해 추가함
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id"), nullable=False
    )

    # 실제 검색될 텍스트 내용
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 벡터 데이터
    embedding: Mapped[list] = mapped_column(Vector(), nullable=False)

    # 문서 내 순서 (나중에 앞뒤 문맥 가져올 때 사용)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    parent_chunk_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # 기존 row의 NULL은 application layer에서 flat chunk로 해석한다.
    chunk_level: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )
    section_path: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    heading: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # 토큰 수 (LLM Context Window 계산용)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 청크별 메타데이터 (페이지 번호, 좌표 등 상세 정보)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default={}, nullable=False
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")


class RAGAnswerRun(Base):
    """
    Standalone RAG Agent answer 실행 기준 record.

    raw query, raw answer, raw prompt/completion, raw chunk content는 저장하지 않고
    redaction-safe summary와 correlation metadata만 저장한다.
    """

    __tablename__ = "rag_answer_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'running', 'completed', 'failed', 'cancelled', 'blocked')",
            name="ck_rag_answer_runs_status",
        ),
        Index(
            "ix_rag_answer_runs_org_correlation_created",
            "organization_id",
            "correlation_id",
            "created_at",
        ),
        Index("ix_rag_answer_runs_retention_expires_at", "retention_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_user_ref: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    knowledge_base_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    knowledge_base_ref: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="requested")
    query_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    retrieval_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    citation_summary: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    answer_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    answer_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    hash_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    policy_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    generation_model_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_models.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generation_model_snapshot: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )
    generation_credential_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_credentials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generation_credential_ref: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )
    usage_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    retention_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    knowledge_base: Mapped[Optional["KnowledgeBase"]] = relationship(
        "KnowledgeBase", back_populates="answer_runs"
    )
