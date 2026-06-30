# Knowledge 및 RAG API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: dev @ ec576b4f24155697aed8843acc6e5a3fc835f7e1
Related ADRs: [ADR-202606271559-audit-log-rag-trace-storage](../decisions/ADR-202606271559-audit-log-rag-trace-storage.md), [ADR-202606290124-mvp2-classification-metadata-storage](../decisions/ADR-202606290124-mvp2-classification-metadata-storage.md), [ADR-202606301045-metadata-aware-hierarchical-rag-boundary](../decisions/ADR-202606301045-metadata-aware-hierarchical-rag-boundary.md)

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

현재 KB 생성과 upload 기반 신규 KB 생성은 `get_user_primary_organization_id`로 첫 active organization membership의 organization을 저장한다. 명시적인 `X-Organization-Id` header를 받는 active organization 방식은 아직 Knowledge/RAG API에 적용되어 있지 않다.

MBA-75 목표 계약에서 Knowledge/RAG 권한 검증은 KB의 `organization_id`와 요청의 active organization context를 비교한다. `X-Organization-Id`를 도입하는 경우 header organization이 KB organization과 다르거나 user scope 밖이면 `404 resource.not_found`로 숨긴다. Header 도입 전 legacy 경로는 primary organization fallback 범위를 이 문서에 명시하고, active organization membership만으로 KB `read`/`use`를 허용하지 않는다. 실제 허용은 organization manager override와 KB effective permission으로 판정한다.

현재 RAG endpoint의 owner 검증은 일관적이지 않다. `DELETE /rag/document/{document_id}`는 `KnowledgeBase.user_id == current_user.id`를 확인하지만, `analyze`, `confirm`, `progress`, 기존 KB upload 경로는 document/KB id 중심으로 동작한다. 이 차이는 MVP 2의 KB permission enforcement에서 정렬해야 한다.

## MBA-75 Proposed Search Contract

현재 `SearchQuery`는 `query`, `top_k`, `knowledge_base_id`, `generation_model` 중심이다. MBA-75는 기존 request shape를 깨지 않는 optional field로 metadata-aware/hierarchical retrieval 계약을 추가한다.

Proposed request extension:

| Field | Type | 설명 |
| --- | --- | --- |
| `metadata_filter` | `MetadataFilter \| null` | allowlist 기반 metadata filter. Free-form dict, JSONPath, raw SQL fragment는 허용하지 않음 |
| `classification_filter` | `string[] \| null` | `public`, `internal`, `confidential`, `pii` 중 선택 |
| `tags` | filter object 또는 `string[]` | `contains_any`, `contains_all` semantics를 명시해야 함 |
| `source_type` | `FILE/API/DB[] \| null` | source type filter |
| `effective_at` | datetime | `effective_from <= effective_at < effective_to` time window filter |
| `hierarchy_mode` | `auto/flat/parent_child` | 기존 KB는 `auto`에서 flat fallback 가능 |

`metadata_filter`와 top-level convenience field가 함께 오면 precedence를 API schema에서 명시해야 한다. 기본 정책은 동일 key 중복을 validation error로 거부하는 것이다.

Proposed response extension:

| Field | 위치 | 설명 |
| --- | --- | --- |
| `chunk_id` | `ChunkPreview` | 검색된 chunk id |
| `rank` | `ChunkPreview` | 최종 ranking 순서 |
| `metadata_summary` | `ChunkPreview` 또는 trace payload | redaction-safe metadata summary |
| `hierarchy_path` | `ChunkPreview` | section path, heading, parent/child 정보 |

Search-test response는 retrieval과 content preview를 수행하므로 KB `use` 권한을 통과한 user에게만 chunk `content` preview를 반환할 수 있다. KB 목록, 상세, document metadata 조회는 `read` 권한 기준으로 분리한다. Workflow trace/run detail 기본 응답은 raw chunk content 없이 citation metadata만 반환해야 한다.

## MBA-75 Trace/Citation Contract

RAG retrieval 전용 table은 만들지 않는다. Retrieval summary는 `trace_payloads` 또는 run/node trace metadata에 application-level convention으로 저장한다. 성공적인 retrieval의 audit event는 `audit_logs.action='rag.retrieve'`로 기록하고, 아래 `payload_kind='rag.retrieval'`은 trace payload 분류값으로만 사용한다.

권장 payload:

```json
{
  "payload_kind": "rag.retrieval",
  "knowledge_base_id": "uuid",
  "workflow_run_id": "uuid",
  "workflow_node_run_id": "uuid",
  "node_id": "llm-node-id",
  "retrieved_chunks": [
    {
      "document_id": "uuid",
      "chunk_id": "uuid",
      "parent_chunk_id": "uuid",
      "rank": 1,
      "score": 0.83,
      "token_count": 210,
      "metadata_summary": {
        "classification": "internal",
        "tags": ["policy"],
        "section_path": "Handbook > Leave",
        "heading": "Leave Policy"
      }
    }
  ],
  "raw_content_returned": false
}
```

Trace/audit metadata에는 raw chunk content, raw prompt, credential, provider raw response를 저장하지 않는다.

## MVP 2 변경 기준

- 현재 코드의 KB endpoint는 주로 owner/current-user scope지만, RAG endpoint 일부는 owner/scope 검증이 약하다. MVP 2에서 team-based KB `read/write/use` enforcement를 붙이고 RAG endpoint scope를 통일한다.
- RAG node runtime은 knowledge base `use` 권한을 평가한다.
- RAG search-test `chat`/`pure`는 retrieval과 content preview를 수행하므로 knowledge base `use` 권한을 평가한다. 단순 KB/detail/document metadata 조회는 `read` 권한 기준이다.
- `user_knowledge_permissions`는 현재 코드에 없으며 MVP 2에서 추가할 목표 table이다.
- document별 permission table은 만들지 않는다.
- document classification과 re-index flag는 `documents.meta_info` metadata convention으로 저장한다.
- RAG retrieval trace는 `rag_retrieval_traces` 신규 table이 아니라 trace payload/run metadata로 저장한다.
- Metadata filter는 allowlist 기반 schema로만 받는다. Metadata는 permission source of truth가 아니다.
- Hierarchical RAG는 nullable parent/child chunk schema와 flat fallback으로 도입한다.
