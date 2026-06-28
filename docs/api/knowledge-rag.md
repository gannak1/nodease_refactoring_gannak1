# Knowledge 및 RAG API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: feature/mba-59 @ b92bc9e0f38588495d228fc0d17b10dfaaed03c1

## 범위

Knowledge base, document, chunk preview, RAG search test, ingestion 계약을 정의한다.

## Knowledge Base 엔드포인트

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/knowledge` | `KnowledgeBaseCreate` | `KnowledgeBaseResponse` | authenticated; primary organization fallback |
| Implemented | `GET` | `/api/v1/knowledge` | 없음 | `KnowledgeBaseResponse[]` | current user owner scope |
| Implemented | `GET` | `/api/v1/knowledge/{kb_id}` | 없음 | `KnowledgeBaseDetailResponse` | current user owner scope |
| Implemented | `PATCH` | `/api/v1/knowledge/{kb_id}` | `KnowledgeUpdate` | `204` | current user owner scope |
| Implemented | `DELETE` | `/api/v1/knowledge/{kb_id}` | 없음 | `204` | current user owner scope |
| Implemented | `GET` | `/api/v1/knowledge/{kb_id}/documents/{document_id}` | 없음 | `DocumentResponse` | current user owner scope |
| Implemented | `GET` | `/api/v1/knowledge/{kb_id}/documents/{document_id}/content` | 없음 | file/html/redirect | current user owner scope |
| Implemented | `POST` | `/api/v1/knowledge/{kb_id}/documents/{document_id}/process` | `DocumentPreviewRequest` | `202` processing status | current user owner scope |
| Implemented | `POST` | `/api/v1/knowledge/{kb_id}/documents/{document_id}/preview` | `DocumentPreviewRequest` | `DocumentPreviewResponse` | current user owner scope |
| Implemented | `POST` | `/api/v1/knowledge/{kb_id}/documents/{document_id}/sync` | 없음 | `202` sync status | current user owner scope |

## RAG 엔드포인트

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/rag/upload/presigned-url` | file metadata | presigned URL | authenticated |
| Implemented | `POST` | `/api/v1/rag/upload` | multipart/form-data | `IngestionResponse` | authenticated/current user ingestion scope |
| Implemented | `POST` | `/api/v1/rag/document/{document_id}/analyze` | 없음 | `DocumentAnalyzeResponse` | current user ingestion scope |
| Implemented | `POST` | `/api/v1/rag/document/{document_id}/confirm` | confirm payload | result | current user ingestion scope |
| Implemented | `DELETE` | `/api/v1/rag/document/{document_id}` | 없음 | result | current user owner scope |
| Implemented | `POST` | `/api/v1/rag/search-test/chat` | `SearchQuery` | `RAGResponse` | authenticated; retrieval service uses current user context |
| Implemented | `POST` | `/api/v1/rag/search-test/pure` | `SearchQuery` | `ChunkPreview[]` | authenticated; retrieval service uses current user context |
| Implemented | `GET` | `/api/v1/rag/document/{document_id}/progress` | 없음 | `text/event-stream` | current user document progress scope |
| Implemented | `POST` | `/api/v1/rag/proxy/preview` | `ApiPreviewRequest` | proxy result | authenticated |

## 기본 Chunking 값

| Field | Default |
| --- | --- |
| `chunk_size` | `500` |
| `chunk_overlap` | `50` |
| `segment_identifier` | `\n\n` |
| `remove_urls_emails` | `false` |
| `remove_whitespace` | `true` |
| `strategy` | `general` |

이 값은 구현 기본값이다. 저장량, retrieval 품질, 재색인 비용에 큰 영향을 주는 정책으로 확정하면 별도 ADR 후보로 올린다.

## MVP 2 변경 기준

- 현재 코드의 KB/RAG endpoint는 주로 owner/current-user scope다. MVP 2에서 team-based KB `read/write/use` enforcement를 붙인다.
- RAG node runtime은 knowledge base `use` 권한을 평가한다.
- `user_knowledge_permissions`는 현재 코드에 없으며 MVP 2에서 추가할 목표 table이다.
- document별 permission table은 만들지 않는다.
- document classification과 re-index flag는 `documents.meta_info` metadata convention으로 저장한다.
- RAG retrieval trace는 `rag_retrieval_traces` 신규 table이 아니라 trace payload/run metadata로 저장한다.
