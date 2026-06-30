# Knowledge 및 RAG API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: feature/mba-78 @ HEAD (base dev caaa4cd)
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
| Implemented | `POST` | `/api/v1/rag/search-test/chat` | `SearchQuery` | `RAGResponse` | `X-Organization-Id` 필수; KB `use` 권한 필요 |
| Implemented | `POST` | `/api/v1/rag/search-test/pure` | `SearchQuery` | `ChunkPreview[]` | `X-Organization-Id` 필수; KB `use` 권한 필요 |
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

현재 KB 생성과 upload 기반 신규 KB 생성은 `get_user_primary_organization_id`로 첫 active organization membership의 organization을 저장한다. 명시적인 `X-Organization-Id` header를 받는 active organization 방식은 RAG search-test `chat`/`pure`에 먼저 적용되어 있으며, 나머지 Knowledge/RAG 생성/문서 API는 아직 primary organization fallback 또는 owner/current-user scope를 사용한다.

MBA-75/MVP 2 목표 계약에서 Knowledge/RAG org-scoped API는 `X-Organization-Id` header를 사용한다. Header가 없으면 `400 organization.required`, header organization이 KB `organization_id`와 다르거나 요청 user scope 밖이면 `404 resource.not_found`로 숨긴다. Org-scoped RAG는 KB의 `organization_id`가 반드시 있어야 하며, legacy KB의 `organization_id`가 `null`이면 요청 header organization으로 보정하지 않고 backfill/reassignment 전까지 scope 밖 resource로 처리한다. Header 도입 전 primary organization fallback은 current behavior 호환 경로일 뿐 장기 계약이 아니다. Active organization membership만으로 KB `read`/`use`를 허용하지 않으며, 실제 허용은 organization manager override와 KB effective permission으로 판정한다.

현재 RAG endpoint의 owner 검증은 일관적이지 않다. `DELETE /rag/document/{document_id}`는 `KnowledgeBase.user_id == current_user.id`를 확인하지만, `analyze`, `confirm`, `progress`, 기존 KB upload 경로는 document/KB id 중심으로 동작한다. 이 차이는 MVP 2의 KB permission enforcement에서 정렬해야 한다.

## MBA-75/MBA-78 Search Contract

`SearchQuery`는 기존 `query`, `top_k`, `knowledge_base_id`, `generation_model` request shape를 깨지 않는 optional field로 metadata-aware/hierarchical retrieval 계약을 확장한다.

Request extension:

| Field | Type | 설명 |
| --- | --- | --- |
| `metadata_filter` | `MetadataFilter \| null` | allowlist 기반 metadata filter. Free-form dict, JSONPath, raw SQL fragment는 허용하지 않음 |
| `classification_filter` | `string[] \| null` | `public`, `internal`, `confidential`, `pii` 중 선택 |
| `tags` | `TagFilter \| null` | `{ "mode": "contains_any" \| "contains_all", "values": string[] }`. `string[]` shorthand는 허용하지 않음 |
| `source_type` | `("FILE" \| "API" \| "DB")[] \| null` | source type filter |
| `effective_at` | datetime | `effective_from <= effective_at < effective_to` time window filter. 비교 기준은 UTC ISO 문자열(`YYYY-MM-DDTHH:MM:SS+00:00`) |
| `hierarchy_mode` | `auto/flat/parent_child` | 기존 KB는 `auto`에서 flat fallback 가능 |

`metadata_filter`와 top-level convenience field가 함께 오면 동일 key 중복을 validation error로 거부한다.

중복 validation:

| Top-level field | Canonical metadata key | 중복 조건 |
| --- | --- | --- |
| `classification_filter` | `metadata_filter.classification` | 둘 다 있으면 validation error |
| `tags` | `metadata_filter.tags` | 둘 다 있으면 validation error |
| `source_type` | `metadata_filter.source_type` | 둘 다 있으면 validation error |
| `effective_at` | `metadata_filter.effective_at` | 둘 다 있으면 validation error |

`hierarchy_mode`는 metadata key가 아니라 retrieval mode다. `metadata_filter.hierarchy_mode`는 허용하지 않는다.

`effective_from`/`effective_to`의 canonical 비교 값은 `documents.meta_info`에 저장된 UTC ISO 문자열(`YYYY-MM-DDTHH:MM:SS+00:00`)이다. 값이 비어 있거나 누락되면 열린 구간으로 해석하고, 값이 있지만 이 형식을 따르지 않으면 filter match에서 제외해 fail-closed로 처리한다. `document_chunks.metadata`에 복제된 값은 denormalized cache/citation evidence이며, MBA-78 1차 filter source로 보지 않는다. `Z`, offset이 다른 timestamp, 날짜 전용 문자열은 ingest/backfill 단계에서 `+00:00` 형식으로 정규화해야 한다.

MBA-78 1차 구현에서 `hierarchy_mode=auto`와 `flat`은 기존 flat retrieval을 사용한다. 명시적 `parent_child` 요청은 hierarchy data/index가 아직 없으면 `422 hierarchy_unavailable`로 닫는다.

`TagFilter` validation:

- `mode`는 `contains_any` 또는 `contains_all`만 허용한다.
- `values`는 비어 있으면 validation error로 거부한다.
- tag 값은 trim 후 빈 문자열이면 거부하고, 비교 정규화는 소문자 기준으로 한다.
- 중복 tag는 정규화 후 하나로 합산한다.
- 구현 기본값은 최대 20개 tag, tag 하나당 최대 64자다.
- top-level `tags`와 `metadata_filter.tags`가 함께 오면 중복 조건으로 보고 validation error로 거부한다.

Response extension:

| Field | 위치 | 설명 |
| --- | --- | --- |
| `chunk_id` | `ChunkPreview` | 검색된 chunk id |
| `parent_chunk_id` | `ChunkPreview` 또는 trace payload | parent-child hierarchy에서 상위 chunk id. flat chunk는 `null` 가능 |
| `rank` | `ChunkPreview` | 최종 ranking 순서 |
| `score` | `ChunkPreview` 또는 trace payload | 최종 ranking score. 기존 `similarity_score`는 response 호환 필드로 유지 |
| `token_count` | `ChunkPreview` 또는 trace payload | chunk token 수. 없으면 `null` 가능 |
| `metadata_summary` | `ChunkPreview` 또는 trace payload | redaction-safe metadata summary |
| `hierarchy_path` | `ChunkPreview` | section path, heading, parent/child 정보 |

`ChunkPreview.metadata`는 기존 UI 호환 필드로 유지하지만, MBA-78 1차부터 `metadata_summary`와 같은 redaction-safe summary만 담는다. Full `documents.meta_info` 또는 `document_chunks.metadata` 원문은 search-test response에 그대로 반환하지 않는다.

Search-test response는 retrieval과 content preview를 수행하므로 KB `use` 권한을 통과한 user에게만 chunk `content` preview를 반환할 수 있다. KB 목록, 상세, document metadata 조회는 `read` 권한 기준으로 분리한다. Workflow trace/run detail 기본 응답은 raw chunk content 없이 citation metadata만 반환해야 한다.

## MBA-75 Trace/Citation Contract

RAG retrieval 전용 table은 만들지 않는다. Per-chunk retrieval evidence는 `trace_payloads.payload_kind='rag.retrieval'`의 redacted payload convention으로 저장하고, run/node trace metadata에는 redaction-safe summary allowlist만 저장한다. 성공적인 retrieval의 audit event는 `audit_logs.action='rag.retrieve'`로 기록하고, 아래 `payload_kind='rag.retrieval'`은 trace payload 분류값으로만 사용한다.

권장 trace payload record:

```json
{
  "payload_kind": "rag.retrieval",
  "workflow_node_run_id": "uuid",
  "redacted_payload": {
    "knowledge_base_ids": ["uuid"],
    "workflow_run_id": "uuid",
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
          "section_path": ["Handbook", "Leave"],
          "heading": "Leave Policy"
        }
      }
    ],
    "result_count": 1,
    "policy_result": "allow",
    "raw_content_returned": false
  }
}
```

Runtime node가 logger로 넘기는 payload body에는 `workflow_node_run_id`를 넣지 않는다. `WorkflowLogger`가 저장 시 `trace_payloads.workflow_node_run_id` 컬럼으로 연결한다.

Run/node trace metadata allowlist는 `knowledge_base_id`, `retrieved_chunk_count`, `document_ids`, `citation_ids`, score summary, hierarchy fallback flag, `raw_content_returned` 같은 요약 field로 제한한다. `retrieved_chunks` 배열, raw chunk content, prompt/completion, provider raw response는 run/node metadata에 복사하지 않는다.

현재 `TraceMetadataSanitizer`는 run/node RAG metadata에서 `knowledge_base_id`, `retrieved_chunk_count`, `document_ids`, `citation_ids`, `score_summary`, `hierarchy_fallback`, `raw_content_returned`, `latency_ms`, `retrieval_payload_id`, `retrieved_context_payload_id` 같은 summary field만 허용한다. Legacy `retrieval_results` 입력은 저장하지 않고 summary field로 변환한다. Raw chunk content와 `retrieved_chunks` 배열은 run/node metadata allowlist에 포함하지 않는다.

Trace/audit metadata에는 raw chunk content, raw prompt, credential 원문, API key, token, encrypted_config, secret value, provider raw response를 저장하지 않는다. `credential_id` 같은 식별자는 권한 보호된 trace 응답 whitelist 안에서만 허용할 수 있다.

## MVP 2 변경 기준

- 현재 코드의 KB endpoint는 주로 owner/current-user scope다. RAG search-test `chat`/`pure`와 Workflow Engine runtime retrieval은 KB `use` 권한 평가를 시작했지만, 나머지 Knowledge/RAG endpoint scope 정렬은 후속 범위다.
- RAG node runtime은 knowledge base `use` 권한을 평가한다.
- RAG search-test `chat`/`pure`는 retrieval과 content preview를 수행하므로 knowledge base `use` 권한을 평가한다. 단순 KB/detail/document metadata 조회는 `read` 권한 기준이다.
- `user_knowledge_permissions`는 현재 코드에 없으며 MVP 2에서 추가할 목표 table이다.
- document별 permission table은 만들지 않는다.
- document classification과 re-index flag는 `documents.meta_info` metadata convention으로 저장한다.
- RAG retrieval trace는 `rag_retrieval_traces` 신규 table이 아니라 trace payload/run metadata로 저장한다. Per-chunk evidence는 `trace_payloads`, run/node metadata는 summary allowlist로 분리한다.
- Metadata filter는 allowlist 기반 schema로만 받는다. Metadata는 permission source of truth가 아니다.
- `policy.warn`/`policy.block` document metadata enforcement는 후속 구현 범위다. MBA-78 1차는 action naming, KB `use` enforcement, `permission.denied`/`rag.retrieve` audit 경계를 먼저 고정한다.
- Hierarchical RAG는 nullable parent/child chunk schema와 flat fallback으로 도입한다.
