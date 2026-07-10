import enum
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from apps.shared.db.base import Base
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


class KnowledgeBase(Base):
    """
    지식 베이스 모델.

    Legacy 구현은 여러 documents row를 둘 수 있지만, target 모델에서는
    document/source item 단위 permission/retrieval/sync/lifecycle atom이다.
    """

    __tablename__ = "knowledge_bases"
    __table_args__ = (
        CheckConstraint(
            "sync_state IN ('manual', 'pending', 'syncing', 'synced', 'failed', 'stale', 'source_deleted')",
            name="ck_knowledge_bases_sync_state",
        ),
        CheckConstraint(
            "lifecycle_state IN ('active', 'archived', 'deleted')",
            name="ck_knowledge_bases_lifecycle_state",
        ),
        UniqueConstraint(
            "source_identity_id",
            name="uq_knowledge_bases_source_identity_id",
        ),
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_knowledge_bases_id_organization_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    safe_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # 임베딩 모델 정보
    embedding_model: Mapped[str] = mapped_column(
        String(50), default="text-embedding-3-small", nullable=False
    )
    # 검색 설정
    top_k: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    similarity_threshold: Mapped[float] = mapped_column(
        Float, default=0.7, nullable=False
    )
    active_document_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_identity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_source_identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sync_state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="manual",
        server_default=text("'manual'"),
    )
    lifecycle_state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="active",
        server_default=text("'active'"),
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
    document_versions: Mapped[List["DocumentVersion"]] = relationship(
        "DocumentVersion",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        foreign_keys="DocumentVersion.knowledge_base_id",
    )
    active_document_version: Mapped[Optional["DocumentVersion"]] = relationship(
        "DocumentVersion",
        foreign_keys=[active_document_version_id],
        post_update=True,
    )
    source_identity: Mapped[Optional["KnowledgeSourceIdentity"]] = relationship(
        "KnowledgeSourceIdentity",
        foreign_keys=[source_identity_id],
    )
    answer_runs: Mapped[List["RAGAnswerRun"]] = relationship(
        "RAGAnswerRun", back_populates="knowledge_base"
    )


class KnowledgeCollection(Base):
    """Collection/grouping/routing/UX/ops 단위. 하위 KB content 권한을 상속하지 않는다."""

    __tablename__ = "knowledge_collections"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_knowledge_collections_org_name",
        ),
        CheckConstraint(
            "sync_state IN ('manual', 'pending', 'syncing', 'synced', 'failed', 'stale', 'source_deleted')",
            name="ck_knowledge_collections_sync_state",
        ),
        CheckConstraint(
            "lifecycle_state IN ('active', 'archived', 'deleted')",
            name="ck_knowledge_collections_lifecycle_state",
        ),
        Index(
            "ix_knowledge_collections_org_sync",
            "organization_id",
            "sync_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_identity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_source_identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_connector_ref: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    is_system_managed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    sync_state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="manual",
        server_default=text("'manual'"),
    )
    lifecycle_state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="active",
        server_default=text("'active'"),
    )
    safe_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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

    items: Mapped[List["KnowledgeCollectionItem"]] = relationship(
        "KnowledgeCollectionItem",
        back_populates="collection",
        cascade="all, delete-orphan",
    )
    source_identity: Mapped[Optional["KnowledgeSourceIdentity"]] = relationship(
        "KnowledgeSourceIdentity",
        foreign_keys=[source_identity_id],
    )


class KnowledgeCollectionItem(Base):
    """Collection과 document-level KB의 membership link."""

    __tablename__ = "knowledge_collection_items"
    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "knowledge_base_id",
            name="uq_knowledge_collection_items_collection_kb",
        ),
        Index(
            "ix_knowledge_collection_items_org_collection_rank",
            "organization_id",
            "collection_id",
            "rank",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    safe_source_path_ref: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    collection: Mapped["KnowledgeCollection"] = relationship(
        "KnowledgeCollection",
        back_populates="items",
    )
    knowledge_base: Mapped["KnowledgeBase"] = relationship("KnowledgeBase")


class KnowledgeSourceIdentity(Base):
    """Protected source item identity. Raw source values must not be user-facing."""

    __tablename__ = "knowledge_source_identities"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "source_system",
            "source_item_ref",
            "hmac_key_version",
            name="uq_knowledge_source_identities_org_source_ref_key",
        ),
        CheckConstraint(
            "display_policy_state IN ('unreviewed', 'approved', 'rejected')",
            name="ck_knowledge_source_identities_display_policy",
        ),
        Index(
            "ix_knowledge_source_identities_org_source",
            "organization_id",
            "source_system",
            "source_item_ref",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    source_item_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    source_parent_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_url_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_principal_ref: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    hmac_key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    safe_display_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    safe_display_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    safe_display_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    display_policy_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unreviewed",
        server_default=text("'unreviewed'"),
    )
    safe_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
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
    document_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
    document_version: Mapped[Optional["DocumentVersion"]] = relationship(
        "DocumentVersion",
        back_populates="chunks",
        foreign_keys=[document_version_id],
    )


class DocumentVersion(Base):
    """Document-level KB의 canonical content/index version."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "knowledge_base_id",
            "version_number",
            name="uq_document_versions_org_kb_version",
        ),
        CheckConstraint(
            "status IN ('staging', 'indexing', 'ready', 'failed', 'superseded')",
            name="ck_document_versions_status",
        ),
        CheckConstraint(
            "version_number > 0",
            name="ck_document_versions_version_positive",
        ),
        Index(
            "ix_document_versions_org_kb_status",
            "organization_id",
            "knowledge_base_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    legacy_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_identity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_source_identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="staging",
        server_default=text("'staging'"),
    )
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    chunking_fingerprint: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    embedding_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    processing_policy_version: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    source_tier: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    approval_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    safe_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
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
    ready_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase",
        back_populates="document_versions",
        foreign_keys=[knowledge_base_id],
    )
    legacy_document: Mapped[Optional["Document"]] = relationship(
        "Document",
        foreign_keys=[legacy_document_id],
    )
    source_identity: Mapped[Optional["KnowledgeSourceIdentity"]] = relationship(
        "KnowledgeSourceIdentity",
        foreign_keys=[source_identity_id],
    )
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document_version",
        foreign_keys="DocumentChunk.document_version_id",
    )


class SourcePolicyKBUseGrant(Base):
    """Source policy가 provision한 KB use allow row."""

    __tablename__ = "source_policy_kb_use_grants"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "knowledge_base_id",
            "subject_type",
            "subject_id",
            "source_policy_id",
            name="uq_source_policy_kb_use_grants_subject_policy",
        ),
        CheckConstraint(
            "subject_type IN ('organization', 'team', 'user')",
            name="ck_source_policy_kb_use_grants_subject_type",
        ),
        CheckConstraint(
            "permission_action = 'use'",
            name="ck_source_policy_kb_use_grants_action",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_source_policy_kb_use_grants_status",
        ),
        CheckConstraint(
            "freshness_epoch >= 0",
            name="ck_source_policy_kb_use_grants_epoch_nonnegative",
        ),
        Index(
            "ix_source_policy_grants_subject_active",
            "organization_id",
            "subject_type",
            "subject_id",
            "status",
            "freshness_epoch",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_identity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_source_identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    permission_action: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="use",
        server_default=text("'use'"),
    )
    source_policy_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provisioned_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revocation_behavior: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="deactivate_on_revoke",
        server_default=text("'deactivate_on_revoke'"),
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default=text("'active'"),
    )
    reason_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    freshness_epoch: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    safe_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
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

    knowledge_base: Mapped["KnowledgeBase"] = relationship("KnowledgeBase")
    source_identity: Mapped[Optional["KnowledgeSourceIdentity"]] = relationship(
        "KnowledgeSourceIdentity"
    )


class SourceAuthorizationProvenance(Base):
    """Source ACL authorization provenance. KB use grant가 아니다."""

    __tablename__ = "source_authorization_provenance"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "knowledge_base_id",
            "requester_subject_type",
            "requester_subject_id",
            "source_identity_id",
            name="uq_source_authorization_provenance_requester",
        ),
        CheckConstraint(
            "source_acl_state IN ('fresh', 'stale', 'unmapped', 'ambiguous', 'unverified', 'revoked', 'not_source_managed')",
            name="ck_source_authorization_acl_state",
        ),
        CheckConstraint(
            "requester_source_authorization IN ('allowed', 'denied', 'unknown', 'not_applicable')",
            name="ck_source_authorization_requester_result",
        ),
        CheckConstraint(
            "requester_subject_type IN ('user', 'team', 'organization', 'service_account')",
            name="ck_source_authorization_requester_type",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_source_authorization_status",
        ),
        CheckConstraint(
            "freshness_epoch >= 0",
            name="ck_source_authorization_epoch_nonnegative",
        ),
        Index(
            "ix_source_authorization_subject_freshness",
            "organization_id",
            "requester_subject_type",
            "requester_subject_id",
            "status",
            "freshness_expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_identity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_source_identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requester_subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    requester_subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    source_acl_state: Mapped[str] = mapped_column(String(32), nullable=False)
    requester_source_authorization: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    source_permission_action: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    source_principal_ref: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    hmac_key_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    freshness_epoch: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    freshness_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default=text("'active'"),
    )
    safe_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
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

    knowledge_base: Mapped["KnowledgeBase"] = relationship("KnowledgeBase")
    source_identity: Mapped[Optional["KnowledgeSourceIdentity"]] = relationship(
        "KnowledgeSourceIdentity"
    )


class KnowledgeIngestionOutbox(Base):
    """Active version finalization/cleanup side effect 조정 record."""

    __tablename__ = "knowledge_ingestion_outbox"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_knowledge_ingestion_outbox_org_idempotency",
        ),
        CheckConstraint(
            "status IN ('pending', 'leased', 'succeeded', 'retry_scheduled', 'dead_lettered', 'cancelled')",
            name="ck_knowledge_ingestion_outbox_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_knowledge_ingestion_outbox_attempt_nonnegative",
        ),
        CheckConstraint(
            "max_attempts > 0",
            name="ck_knowledge_ingestion_outbox_max_attempts_positive",
        ),
        Index(
            "ix_knowledge_ingestion_outbox_status_retry",
            "status",
            "next_retry_at",
        ),
        Index(
            "ix_knowledge_ingestion_outbox_lease",
            "status",
            "lease_expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    document_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_identity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_source_identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )
    owner_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    fencing_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default=text("5")
    )
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    safe_reason_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    dead_lettered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    redrive_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    target_ref: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    safe_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
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
