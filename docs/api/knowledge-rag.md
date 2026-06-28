# Knowledge 및 RAG API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d

## 범위

Knowledge base, document, chunk preview, RAG search test, ingestion 계약을 정의한다.

## Knowledge Base 엔드포인트

아래 `Status`는 route 존재 여부를 뜻한다. MVP 2의 최종 권한 enforcement는 MVP 2-0 organization membership foundation 완료 후 `organization_memberships` 선검증과 KB permission helper를 붙이는 방식으로 확정한다.

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/knowledge` | `KnowledgeBaseCreate` | `KnowledgeBaseResponse` | KB create scope |
| Implemented | `GET` | `/api/v1/knowledge` | 없음 | `KnowledgeBaseResponse[]` | KB `read` |
| Implemented | `GET` | `/api/v1/knowledge/{kb_id}` | 없음 | `KnowledgeBaseDetailResponse` | KB `read` |
| Implemented | `PATCH` | `/api/v1/knowledge/{kb_id}` | `KnowledgeUpdate` | `204` | KB `write` |
| Implemented | `DELETE` | `/api/v1/knowledge/{kb_id}` | 없음 | `204` | KB `manage` |
| Implemented | `GET` | `/api/v1/knowledge/{kb_id}/documents/{document_id}` | 없음 | `DocumentResponse` | KB `read` |
| Implemented | `GET` | `/api/v1/knowledge/{kb_id}/documents/{document_id}/content` | 없음 | file/html/redirect | KB `read` |
| Implemented | `POST` | `/api/v1/knowledge/{kb_id}/documents/{document_id}/preview` | `DocumentPreviewRequest` | `DocumentPreviewResponse` | KB `read` |
| Planned | `PATCH` | `/api/v1/knowledge/{kb_id}/classification` | classification metadata | `204` | KB `write` |
| Planned | `PATCH` | `/api/v1/knowledge/{kb_id}/documents/{document_id}/classification` | classification metadata | `204` | KB `write` |

## RAG 엔드포인트

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/rag/upload/presigned-url` | file metadata | presigned URL | authenticated |
| Implemented | `POST` | `/api/v1/rag/upload` | multipart/form-data | `IngestionResponse` | KB `write` |
| Implemented | `POST` | `/api/v1/rag/document/{document_id}/analyze` | 없음 | `DocumentAnalyzeResponse` | KB `read` + document metadata policy |
| Implemented | `POST` | `/api/v1/rag/document/{document_id}/confirm` | confirm payload | result | KB `write` |
| Implemented | `DELETE` | `/api/v1/rag/document/{document_id}` | 없음 | result | KB `write` |
| Implemented | `POST` | `/api/v1/rag/search-test/chat` | `SearchQuery` | `RAGResponse` | KB `use` |
| Implemented | `POST` | `/api/v1/rag/search-test/pure` | `SearchQuery` | `ChunkPreview[]` | KB `use` |
| Implemented | `GET` | `/api/v1/rag/document/{document_id}/progress` | 없음 | `text/event-stream` | KB `read` + document metadata policy |
| Implemented | `POST` | `/api/v1/rag/proxy/preview` | `ApiPreviewRequest` | proxy result | authenticated |
| Planned | `POST` | `/api/v1/knowledge/{kb_id}/reindex` | re-index options | re-index result | KB `write` |
| Planned | `POST` | `/api/v1/knowledge/{kb_id}/documents/{document_id}/reindex` | re-index options | re-index result | KB `write` |

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

- RAG node runtime은 knowledge base `use` 권한을 평가한다.
- document별 permission table은 만들지 않는다.
- document 접근 차단은 active organization membership, knowledge base 권한, document metadata policy로 처리한다. Document owner 표현은 KB 권한과 metadata policy를 우회하는 별도 허용 규칙으로 사용하지 않는다.
- KB `read/write/use/manage` 권한은 `team_knowledge_permissions`와 `user_knowledge_permissions`의 effective permission으로 계산한다.
- `user_knowledge_permissions` grant 대상은 active organization member여야 하며, team membership은 필수 조건이 아니다.
- invited, suspended, removed, non-member user는 KB permission row가 있어도 fail-closed 처리한다.
- classification은 `knowledge_bases.classification`, `documents.classification` 신규 column 없이 metadata/audit/trace payload convention으로 처리한다.
- re-index 필요 상태는 `documents.meta_info.needs_reindex` 같은 metadata flag로 처리한다.
- RAG retrieval trace는 `rag_retrieval_traces` 신규 table이 아니라 trace payload/run metadata로 저장한다.
- classification 변경과 re-index action은 `audit_logs`에 남긴다.
