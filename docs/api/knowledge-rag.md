# Knowledge 및 RAG API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: dev @ c990b54e931b4de8023822f6dff14f43fc1d415f

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
| Implemented | `POST` | `/api/v1/rag/upload` | multipart/form-data | `IngestionResponse` | authenticated; 신규 KB는 current user owner, 기존 `knowledgeBaseId`는 현재 owner 검증 없음 |
| Implemented | `POST` | `/api/v1/rag/document/{document_id}/analyze` | 없음 | `DocumentAnalyzeResponse` | authenticated; 현재 owner/KB scope 검증 없음 |
| Implemented | `POST` | `/api/v1/rag/document/{document_id}/confirm` | confirm payload | result | authenticated; 현재 owner/KB scope 검증 없음 |
| Implemented | `DELETE` | `/api/v1/rag/document/{document_id}` | 없음 | result | current user owner scope |
| Implemented | `POST` | `/api/v1/rag/search-test/chat` | `SearchQuery` | `RAGResponse` | authenticated; retrieval service uses current user context |
| Implemented | `POST` | `/api/v1/rag/search-test/pure` | `SearchQuery` | `ChunkPreview[]` | authenticated; retrieval service uses current user context |
| Implemented | `GET` | `/api/v1/rag/document/{document_id}/progress` | 없음 | `text/event-stream` | authenticated; event generator는 현재 document id만 조회 |
| Implemented | `POST` | `/api/v1/rag/proxy/preview` | `ApiPreviewRequest` | proxy result | authenticated |

## 기본 Chunking 값

`POST /api/v1/rag/upload`와 document preview/process API의 기본값은 서로 다르다.

### `POST /api/v1/rag/upload` Form 기본값

| Field | Default |
| --- | --- |
| `topK` | `5` |
| `similarity` | `0.7` |
| `chunkSize` | `1000` |
| `chunkOverlap` | `200` |

### `DocumentPreviewRequest` / process 기본값

| Field | Default |
| --- | --- |
| `chunk_size` | `500` |
| `chunk_overlap` | `50` |
| `segment_identifier` | `\n\n` |
| `remove_urls_emails` | `false` |
| `remove_whitespace` | `true` |
| `strategy` | `general` |
| `source_type` | `FILE` |
| `selection_mode` | `all` |

이 값은 구현 기본값이다. 저장량, retrieval 품질, 재색인 비용에 큰 영향을 주는 정책으로 확정하면 별도 ADR 후보로 올린다.

## Source Type 처리

현재 `POST /api/v1/rag/upload`는 `FILE`, `API`, `DB` source type을 처리한다.

| Source Type | 입력 | 저장되는 주요 metadata | 권한 기준 |
| --- | --- | --- | --- |
| `FILE` | `file` 또는 `s3FileUrl` + `s3FileKey` | `upload_method`, S3 key 등 | authenticated user |
| `API` | `apiUrl`, `apiMethod`, `apiHeaders`, `apiBody` | encrypted headers, parsed body | authenticated user |
| `DB` | `connectionId` | connection id/type/name | 현재 코드 기준 `connections.user_id == current_user.id` |

새 KB를 동시에 생성하는 upload 요청은 `embeddingModel`이 필수다. 기존 KB에 추가하는 요청은 기존 KB의 `embedding_model`을 사용한다. 현재 기존 `knowledgeBaseId` 경로는 KB 존재 여부만 확인하고 current user owner/scope를 확인하지 않는다.

현재 KB 생성과 upload 기반 신규 KB 생성은 `get_user_primary_organization_id`로 첫 active team membership의 organization을 저장한다. 명시적인 `X-Organization-Id` header를 받는 active organization 방식은 아직 Knowledge/RAG API에 적용되어 있지 않다.

현재 RAG endpoint의 owner 검증은 일관적이지 않다. `DELETE /rag/document/{document_id}`는 `KnowledgeBase.user_id == current_user.id`를 확인하지만, `analyze`, `confirm`, `progress`, 기존 KB upload 경로는 document/KB id 중심으로 동작한다. 이 차이는 MVP 2의 KB permission enforcement에서 정렬해야 한다.

## MVP 2 변경 기준

- 현재 코드의 KB endpoint는 주로 owner/current-user scope지만, RAG endpoint 일부는 owner/scope 검증이 약하다. MVP 2에서 team-based KB `read/write/use` enforcement를 붙이고 RAG endpoint scope를 통일한다.
- RAG node runtime은 knowledge base `use` 권한을 평가한다.
- `user_knowledge_permissions`는 현재 코드에 없으며 MVP 2에서 추가할 목표 table이다.
- document별 permission table은 만들지 않는다.
- document classification과 re-index flag는 `documents.meta_info` metadata convention으로 저장한다.
- RAG retrieval trace는 `rag_retrieval_traces` 신규 table이 아니라 trace payload/run metadata로 저장한다.
