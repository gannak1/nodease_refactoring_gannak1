# Knowledge/RAG 아키텍처

Status: Draft
Authority: Architecture
Source of Truth: Yes
Verified Against: dev @ ec576b4f24155697aed8843acc6e5a3fc835f7e1
Related ADRs: [ADR-202606271559-audit-log-rag-trace-storage](../decisions/ADR-202606271559-audit-log-rag-trace-storage.md), [ADR-202606290124-mvp2-classification-metadata-storage](../decisions/ADR-202606290124-mvp2-classification-metadata-storage.md), [ADR-202606301045-metadata-aware-hierarchical-rag-boundary](../decisions/ADR-202606301045-metadata-aware-hierarchical-rag-boundary.md)

## 목적

Knowledge/RAG 런타임에서 metadata filter, knowledge base 권한, document metadata policy, hierarchical retrieval, trace/citation 저장 경계를 정의한다.

## 용어

| 용어 | 의미 |
| --- | --- |
| Metadata-aware RAG | document/source/chunk metadata를 retrieval filter, policy decision, ranking hint, citation evidence에 사용하는 RAG |
| Permission-aware RAG | RAG 실행 경로에서 knowledge base `use` 권한과 document metadata policy를 강제하는 접근 제어 경계 |
| Hierarchical RAG | `knowledge base -> document/source -> section/parent chunk -> child chunk` 계층을 indexing/retrieval에 사용하는 검색 구조 |

RBAC 기반 접근 제어는 Hierarchical RAG가 아니다. RBAC는 누가 KB/RAG를 사용할 수 있는지 결정하고, Hierarchical RAG는 어떤 chunk 계층을 어떻게 검색할지 결정한다.

## Component View

```text
Client Search UI / Workflow Runtime
  -> RAG API / Workflow Engine
    -> KB Permission Gate
    -> Metadata Filter Normalizer
    -> Document Metadata Policy Evaluator
    -> Retrieval Service
      -> Vector Search
      -> Keyword Search
      -> RRF/Rerank
      -> Hierarchical Parent/Child Expansion
    -> Trace/Citation Writer
  -> Trace/Run Detail API
```

## 레이어 경계

Controller는 request parsing, auth dependency, response mapping만 담당한다. Permission, metadata policy, retrieval ranking, trace redaction business logic을 controller에 넣지 않는다.

Service/helper layer는 다음 orchestration을 담당한다.

- active actor/context 해석
- knowledge base `use` 권한 확인
- metadata filter normalization
- document metadata policy warn/block
- retrieval 호출
- trace/citation payload 생성

Gateway search-test와 Workflow Engine runtime retrieval은 같은 filter/policy semantics를 사용해야 한다. 이를 위해 shared helper를 우선한다.

후보 module:

- `apps/shared/services/rag_filters.py`
- `apps/shared/services/rag_policy.py`
- `apps/shared/services/rag_trace.py`
- `apps/shared/services/rag_retrieval_contracts.py`

## Metadata Architecture

`documents.meta_info`가 document metadata source of truth다.

표준 key 후보:

- `classification`
- `tags`
- `source_type`
- `source_hash`
- `document_version`
- `effective_from`
- `effective_to`
- `needs_reindex`
- `metadata_version`

`classification` 허용값은 `public`, `internal`, `confidential`, `pii`다. 누락 시 `internal`로 해석한다.

`document_chunks.metadata`는 retrieval/filter/citation 성능을 위한 denormalized cache다. `documents.meta_info`와 충돌하면 `documents.meta_info`를 우선한다. 문서 metadata가 바뀌면 chunk metadata를 동기화하거나 `documents.meta_info.needs_reindex=true`를 설정한다.

Metadata는 permission source of truth가 아니다. `owner_team_id`, `owner_user_id` 같은 metadata field를 권한 판정에 사용하지 않는다. Active organization membership은 KB organization scope와 resource permission subject의 전제 조건이며, 이 membership만으로 KB `read`/`use`를 허용하지 않는다. 실제 resource 허용은 organization manager override, `team_knowledge_permissions`, 목표 `user_knowledge_permissions`의 effective permission으로 판정한다.

## Permission Architecture

RAG execution path는 knowledge base `use` 권한을 요구한다.

적용 지점:

- RAG search-test API. Retrieval과 content preview를 수행하므로 KB `use` 권한을 요구한다.
- Workflow Engine LLM node retrieval 직전
- retrieval 실행과 연결되는 DB/API source 사용 경로

Scope prerequisite와 resource permission source:

- Scope prerequisite: active `organization_memberships` row와 KB의 `organization_id`가 요청의 active organization context 안에 있는지 확인한다.
- Resource permission source: organization manager override, `team_knowledge_permissions`, 목표 `user_knowledge_permissions`.

`user_knowledge_permissions`는 MVP 2 목표 table이다. MBA-75에서 함께 구현할지, 선행/후속 이슈로 분리할지는 구현 계획에서 결정할 수 있지만, 장기 effective permission은 team permission과 additive user direct permission을 합산한다.

Document별 permission table은 만들지 않는다. Document access/policy는 KB permission과 `documents.meta_info` 기반 metadata policy를 조합한다.

MBA-75 permission gate는 KB의 `organization_id`와 요청의 active organization context를 비교해야 한다. 현재 Knowledge/RAG API는 아직 `X-Organization-Id` header 방식을 적용하지 않고 primary organization fallback을 사용하므로, header 도입 여부와 legacy fallback 범위는 [knowledge-rag API 문서](../api/knowledge-rag.md)에서 먼저 확정한 뒤 구현한다.

## Document Metadata Policy

| classification | 기본 동작 |
| --- | --- |
| `public` | KB `use` 통과 시 허용 |
| `internal` | KB `use` 통과 시 허용 |
| `confidential` | KB `use` 통과 시 허용하되 audit/trace policy result 기록 |
| `pii` | external LLM prompt path에서는 `policy.block`, internal-only search preview에서는 `policy.warn` |

Audit action:

- RBAC 거부: `permission.denied`
- policy 경고: `policy.warn`
- policy 차단: `policy.block`
- 성공한 retrieval 감사: `rag.retrieve`

Policy result는 `audit_logs.audit_metadata.policy_result`에 저장한다.

## Metadata Filter Contract

Free-form dict filter를 받지 않는다. API는 allowlist 기반 `MetadataFilter`를 받는다.

허용 예시:

```json
{
  "classification": ["internal", "confidential"],
  "tags": {
    "mode": "contains_all",
    "values": ["policy", "hr"]
  },
  "source_type": ["FILE", "API", "DB"],
  "effective_at": "2026-06-30T00:00:00Z",
  "document_version": ["v1", "v2"]
}
```

허용 operator:

- scalar list: `in`
- tags: `contains_any`, `contains_all`
- time window: `effective_from <= effective_at < effective_to`

금지:

- arbitrary JSONPath
- raw SQL fragment
- nested free-form filter
- secret/header/cookie/auth/prompt/completion/raw response 관련 key

Vector search와 keyword search는 동일 filter semantics를 적용해야 한다. Keyword raw SQL이 필요한 경우 bind parameter만 사용한다.

## Hierarchical RAG

MBA-75의 hierarchical schema extension 후보는 `document_chunks`에 nullable field를 추가하는 방향이다.

- `parent_chunk_id`: nullable FK to `document_chunks.id`
- `chunk_level`: `parent | child | flat`
- `section_path`: text nullable
- `heading`: text nullable

`parent_chunk_id`와 `chunk_level`은 canonical column이다. JSON metadata에 같은 값을 중복 저장하지 않는다.

Retrieval flow:

1. KB `use` 권한 확인
2. metadata filter normalization
3. parent chunk 또는 section summary coarse retrieval
4. parent 후보 cap 적용
5. parent 후보의 child chunk pool 생성
6. child pool에서 vector/keyword/hybrid retrieval
7. rerank
8. child chunk를 final evidence로 반환
9. redaction-safe trace 저장

Fallback:

- parent chunk가 없는 KB는 flat retrieval
- hierarchy field가 일부 누락된 document는 해당 document만 flat fallback
- fallback 여부는 trace metadata에 기록

## Trace and Citation

신규 `rag_retrieval_traces` table은 만들지 않는다. RAG retrieval summary는 `trace_payloads` 또는 run/node trace metadata에 저장한다.

권장 payload convention:

```json
{
  "payload_kind": "rag.retrieval",
  "knowledge_base_id": "...",
  "workflow_run_id": "...",
  "workflow_node_run_id": "...",
  "node_id": "...",
  "retrieved_chunks": [
    {
      "document_id": "...",
      "chunk_id": "...",
      "parent_chunk_id": "...",
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

`audit_logs.action='rag.retrieve'`는 성공한 retrieval 감사 event 이름이고, `trace_payloads.payload_kind='rag.retrieval'`는 trace payload 분류값이다. 두 값을 같은 계약으로 합치지 않는다.

Boundary:

- search-test response는 KB `use` 권한을 통과한 user에게 chunk content preview를 반환할 수 있다.
- workflow trace/run detail 기본 응답은 raw chunk content 없이 citation metadata만 반환한다.
- raw content가 필요하면 기존 trace payload visibility/access policy를 따른다.
