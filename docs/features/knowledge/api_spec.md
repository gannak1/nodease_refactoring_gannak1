# Knowledge API Spec

Status: Draft
Verified Against: feature/mba-302 @ b2d6467002b7becf1daa0badfe6fc155b3edaa57
이 문서는 Knowledge feature의 현재 API baseline과 목표 KB 통합 API 계약을 함께 기록한다. MBA-105 목표 API는 [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)의 임시 구현 baseline, Workflow RAG anonymous public-only runtime은 [ADR-0018](../../decisions/ADR-0018-workflow-rag-anonymous-public-only-runtime.md), MCP/API source connector와 incremental sync 경계는 [ADR-0020](../../decisions/ADR-0020-knowledge-mcp-incremental-sync-boundary.md), MBA-231 위임 관리와 KB RBAC cutover는 [ADR-0034](../../decisions/ADR-0034-knowledge-delegated-administration-and-rbac-boundary.md), direct KB와 명시 selected Collection의 internal runtime resolver는 [ADR-0036](../../decisions/ADR-0036-knowledge-runtime-candidate-resolution.md), KC 운영 관리 계약은 [ADR-0044](../../decisions/ADR-0044-knowledge-collection-operational-management-boundary.md), 세부 구현 기준은 [implementation_baseline.md](implementation_baseline.md)를 따른다. Knowledge Skill 관련 API 경계는 [ADR-0015](../../decisions/ADR-0015-knowledge-skill-context-routing-boundary.md)를 따른다.
KC sync 요청·상태 조회와 durable execution 계약은 [ADR-0048](../../decisions/ADR-0048-knowledge-collection-sync-execution-boundary.md)을 따른다.

## Current Baseline Endpoints

| Method | Path | 목적 | 권한 경계 |
| --- | --- | --- | --- |
| GET | `/api/v1/knowledge` | 현재 KB 목록 | Active organization에서 KB `read`가 허용된 active KB만 반환하고 unauthorized row/count는 생략한다 |
| GET | `/api/v1/knowledge/llm-selectable` | Workflow LLM node RAG picker용 KB 후보 목록 | `X-Organization-Id` active organization 필수. active lifecycle이고 `sync_state != source_deleted`이며 caller가 KB `use` 권한을 가진 KB만 반환한다. 반환 후보는 retrieval-visible `completed` document chunk가 1개 이상 있어야 하며, runtime은 실행 시점 execution subject 기준으로 다시 권한을 평가한다 |
| POST | `/api/v1/knowledge` | 빈 KB 생성 | Active organization에 KB, 생성자의 user-direct `manager`, canonical audit를 한 transaction에서 생성한다. 필수 schema가 준비되지 않으면 `503 knowledge.schema_not_ready`로 fail-closed 처리한다 |
| GET | `/api/v1/knowledge/{kb_id}` | 현재 KB 상세와 문서 상태 | Active organization + KB `read`. Detail capability는 `can_read/use/write/read_content/manage`와 빈 active manual KB에 최초 source를 등록할 수 있는 `can_register_initial_document`를 반환한다 |
| GET | `/api/v1/knowledge/{kb_id}/documents/{document_id}/edit-config` | Document preview/process 설정 복원 | Active organization + KB `write`. Bounded property/aggregate/serialized-size allowlist만 반환하고 read detail과 encrypted source config를 재사용하지 않는다. 성공 응답은 `Cache-Control: no-store`다 |
| POST | `/api/v1/knowledge/{kb_id}/documents/{document_id}/preview` | Document 설정 미리보기 | Active organization + KB `write`. DB source는 submitted/fallback opaque Connection reference가 current user 소유인지 확인한 뒤 processor를 호출한다. Resolver 저장소 장애는 `503 connection.reference_unavailable`, processor 직전 재검증의 temporary failure는 `503 source.temporarily_unavailable`로 닫는다 |
| POST | `/api/v1/knowledge/{kb_id}/documents/{document_id}/process` | Document 설정 저장과 durable 처리 시작 | Active organization + KB `write`. DB source는 Connection owner 검증과 설정 allowlist를 통과한 뒤 owner Connection row를 잠그고 sanitized metadata·queued Document projection·job commit까지 유지해 Connector 삭제와 직렬화한다. Worker는 dial 직전에 같은 owner 정책을 재검증한다. 성공한 `202`는 opaque `job_id`, `reused`, `dispatch_deferred`만 추가 반환한다. Missing/malformed/other-owner reference는 `404 resource.hidden`, lock 또는 commit의 transient contention은 `503 connection.reference_busy`, 기타 persistence failure는 `503 connection.reference_unavailable`로 닫는다 |
| POST | `/api/v1/knowledge/{kb_id}/documents/{document_id}/sync` | 기존 설정으로 durable sync 시작 | Active organization + KB `write` 및 source sync에는 `sync_manage`. DB Connection reference를 다시 잠그고 job UUID만 발행한다 |
| GET | `/api/v1/knowledge/{kb_id}/documents/{document_id}/ingestion` | 최신 ingestion job safe status | Active organization + KB `read`. `Cache-Control: no-store`; raw source/provider/error/token 없이 operation, status, attempt, retryability와 safe reason/timestamp만 반환한다 |
| POST | `/api/v1/knowledge/{kb_id}/documents/{document_id}/ingestion/retry` | Retryable dead-letter의 새 generation 생성 | Active organization + KB `write`; 이전 operation이 sync면 `sync_manage`도 재검사한다. Latest job ID를 고정해 권한 확인과 redrive 사이 TOCTOU를 차단한다 |
| GET | `/api/v1/knowledge/{kb_id}/safe-metadata` | allowlisted KB recommendation metadata 조회 | active organization, KB `manage`; 권한 없는 resource는 404로 숨긴다 |
| PATCH | `/api/v1/knowledge/{kb_id}/safe-metadata` | `safe_label`, `kb_safe_description`, `kb_safe_topics` 수정 | active organization, KB `manage`, sanitizer, audit. 일반 KB 설정 PATCH와 분리한다 |
| POST | `/api/v1/knowledge/{kb_id}/archive`, `/restore` | Manual KB lifecycle 전이 | KB `manage` 또는 domain `lifecycle_manage`; source-managed KB는 source-owned로 차단 |
| DELETE | `/api/v1/knowledge/{kb_id}?acknowledged_hard_delete=true` | Manual KB hard delete | Organization manager 전용, explicit acknowledgement, approved retention/legal-hold gate. Production gate가 연결되지 않은 현재 baseline은 `403 policy.denied`로 fail-closed하며, allow된 경우에만 permission cleanup과 audit를 같은 DB transaction에서 처리한다 |
| POST | `/api/v1/knowledge/candidates/resolve` | Builder/deployment preflight용 safe KB 후보 조회 | active organization, collection route 또는 explicit KB helper |
| POST | `/api/v1/knowledge/rag-recommendations` | Workflow Builder용 LLM node RAG option 추천 | active organization, candidate resolver safe set, KB 단위 recommendation |
| POST | `/api/v1/rag/upload` | 빈 manual KB의 최초 문서 등록/색인 요청 | `X-Organization-Id` active organization 필수. 신규 KB는 active organization에 귀속하며 primary organization fallback을 사용하지 않는다. 기존 KB는 KB `write`, active/manual/non-source-managed와 빈 document slot을 요구한다. DB source는 owner preflight 후 KB/slot을 먼저 확인하고, 등록 직전에 MBA-273 reference lock을 획득해 document commit까지 유지한다. Manual KB에서는 active version pointer가 있는 completed Document를 포함해 모든 상태의 기존 Document가 slot을 점유하며 두 번째 독립 source는 `409 knowledge.document_slot_occupied`다. Source-managed/non-manual KB는 slot 존재를 노출하기 전에 `knowledge.document_registration_not_allowed`로 거부한다 |
| POST | `/api/v1/rag/upload/presigned-url` | FILE 또는 Workflow 입력용 임시 upload URL | Knowledge 최초 등록 호출은 `knowledgeBaseId`를 전달하고 active organization, KB `write`와 현재 빈 document slot을 fast precheck한다. 기존 Workflow 입력 파일 호출은 KB 식별자 없이 사용할 수 있다. 최종 Knowledge `/rag/upload`는 KB row lock 아래에서 cardinality를 다시 검증한다 |
| POST | `/api/v1/rag/search-test/pure` | 검색 테스트 | active organization, KB use |
| POST | `/api/v1/rag/search-test/chat` | 검색+답변 테스트 | active organization, KB use, LLM credential |
| POST | `/api/v1/rag/agent/answer` | 명시 `knowledge_base_id` 기반 standalone Agent answer | KB use, generation model/credential use |
| POST | `/api/v1/rag/agent/answer/stream` | standalone Agent answer SSE | KB use, generation model/credential use |
| GET | `/api/v1/rag/document/{document_id}/progress?organizationId={active_organization_id}` | 문서 처리 상태 SSE | Native EventSource의 custom header 제약 때문에 active organization을 query parameter로 전달한다. Gateway는 stream 생성 전에 active organization + KB `read`를 검증하며, 권한 없는 document의 상태·오류·Redis progress를 노출하지 않는다. 응답은 `Cache-Control: no-cache, no-store`, `X-Accel-Buffering: no`를 사용한다 |
| POST | `/api/v1/rag/document/{document_id}/confirm?strategy={strategy}` | 승인 대기 Document의 durable resume | Active organization + KB `write`, `waiting_for_approval`, allowlisted strategy를 요구한다. Job UUID만 queue에 발행하고 `job_id/reused/dispatch_deferred`를 반환한다 |
| GET | `/api/v1/permissions/knowledge-bases/{knowledge_base_id}` | KB에 부여된 team/user direct permission 목록 | manager 또는 KB `manage`, active organization |
| PUT | `/api/v1/permissions/knowledge-bases/{knowledge_base_id}/teams/{team_id}` | team KB permission 생성/갱신 | manager 또는 KB `manage`, active organization |
| PUT | `/api/v1/permissions/knowledge-bases/{knowledge_base_id}/users/{user_id}` | user direct KB permission 생성/갱신 | manager 또는 KB `manage`, active organization |
| DELETE | `/api/v1/permissions/knowledge-bases/{knowledge_base_id}/teams/{team_id}` | team KB permission 회수 | manager 또는 KB `manage`, active organization |
| DELETE | `/api/v1/permissions/knowledge-bases/{knowledge_base_id}/users/{user_id}` | user direct KB permission 회수 | manager 또는 KB `manage`, active organization |

현재 `POST /api/v1/knowledge`는 공백뿐인 `name`, 255자를 초과하는 `name`, 비어 있거나 secret-like/token-like 또는 allowlist 밖 문자를 포함한 `embedding_model`을 DB insert 전에 safe validation error로 거부한다. Validation error response는 raw request value를 echo하지 않고 reason code만 반환한다. KB `name`은 사용자 표시용 label이며 resource identity가 아니므로 같은 organization 안의 동일 `name` 생성을 이름만으로 거부하지 않는다. 같은 제목의 서로 다른 문서, 수동 KB, source-managed KB는 `knowledge_base_id`, protected source identity, sync/lifecycle state, safe metadata로 구분한다. 단, 같은 문서의 version은 여러 개가 동시에 retrieval-visible한 resource로 취급하지 않는다. 내부 문서는 active/head pointer가 가리키는 ready version만 검색 노출하고, 외부 source-managed 문서는 정상 sync/finalization이 완료되면 최신 active ready version으로 교체한다. Sync 실패나 stale 상태에서는 기존 active ready version만 warning과 함께 유지할 수 있으며, 이전/superseded/pre-finalized version은 selectable-ready 또는 retrieval evidence 후보가 아니다. Source-managed KB의 동일 source item 중복 방지는 `source_identity_id`와 source sync lineage invariant로 다루며, KB `name` conflict로 대체하지 않는다.

MBA-231 cutover 이후 `/api/v1/knowledge/*`의 list/detail/settings/document/process/preview/sync와 `/api/v1/rag/upload`, document analyze/confirm/delete/progress는 active organization과 canonical KB action helper를 사용한다. `knowledge_bases.user_id`는 생성자/귀속 정보이며 이 표면의 권한 우회가 아니다. MBA-273부터 Knowledge 최초 등록을 위한 presigned upload 호출은 대상 `knowledgeBaseId`를 전달하고 active organization, KB `write`, initial document slot fast precheck를 통과해야 한다. 같은 endpoint를 사용하는 Workflow 입력 파일은 아직 KB가 확정되지 않은 별도 storage surface이므로 KB 식별자 없이 기존 authenticated storage 경계를 따른다. URL/proxy preview처럼 아직 KB가 확정되지 않은 표면은 별도 storage/egress 경계를 따르며, raw/source-derived content는 승인된 `content_read` 또는 후속 raw/compliance 정책 없이 노출하지 않는다.

`GET /api/v1/knowledge/{kb_id}`의 `can_register_initial_document`는 서버가 계산한 UI capability다. Caller가 KB `write`를 가지고, KB가 active manual/non-source-managed이며 현재 `Document`가 없을 때만 true다. Field 누락이나 false는 fail-closed다. 이 값은 mutation authorization token이 아니며 `/rag/upload`는 동일 정책을 KB row lock 아래에서 다시 확인한다. 과거 삭제가 남긴 active version pointer는 canonical registration에서 version의 `legacy_document_id`와 `source_identity_id`가 이미 제거된 경우에만 `superseded`로 전환하고 pointer를 해제한다. Live document/source identity 또는 source-managed state는 자동 복구하지 않는다. Independent source append conflict는 raw filename/path나 기존 document identity를 포함하지 않는 다음 safe response를 사용한다.

```json
{
  "detail": {
    "error": {
      "code": "knowledge.document_slot_occupied",
      "message": "This Knowledge Base already has a source document.",
      "request_id": "<request-id>",
      "details": {}
    }
  }
}
```

Document `read` response의 `meta_info`는 status/progress allowlist이며 edit form의
source가 아니다. `GET /knowledge/{kb_id}/documents/{document_id}/edit-config`는 KB
`write`를 통과한 caller에게 `chunk_size`, `chunk_overlap`, `chunking_mode`,
`segment_identifier`, processing option, selection option과 DB edit allowlist를
반환한다. DB allowlist는 opaque `connection_id`, bounded table/column selection,
sensitive-column marking, alias, template와 join shape만 허용한다. API source는 method,
configured/header/body presence 같은 safe summary만 반환하고 URL/header/body 원문,
encrypted field, connection credential/detail은 반환하지 않는다. Stored config가
malformed 또는 bound 밖이면 raw fallback 대신 `editable=false`와 safe reason code를
반환하고 Client는 preview/process를 차단한다. 개별 field cap을 모두 통과하더라도
aggregate item 또는 serialized response budget을 초과하면 같은 unavailable 결과로
닫는다. Client는 권한과 hydration 상태를 현재 KB/document id scope에 결박하고, route
전환 뒤 늦게 도착한 이전 scope 응답이나 fetch failure로 action을 다시 열지 않는다.

DB source upload/process/preview의 `connection_id`는 opaque input일 뿐 권한 증명이 아니다.
Gateway는 document/설정 mutation 전에 Shared Connection Use Resolver로
`Connection.user_id == current_user.id`를 확인하고, process 저장 시 nested config에서
Connection reference와 Connection detail field를 제거해 top-level opaque `connection_id`만
canonical reference로 남긴다. Background Gateway ingestion과 Workflow Engine KC sync는 외부
DB dial 직전에 current execution subject로 같은 resolver를 다시 호출해 최신 권한 스냅샷을 확인한다.
Missing, malformed, deleted, owner 변경과 non-owner reference는 모두 `404
resource.hidden`으로 일반화하며 Connection id/name/owner/host/database/username/credential을
응답·audit·processing metadata에 넣지 않는다. Credential 복호화 실패는
`configuration.invalid`로 닫고 저장 암호문을 adapter credential로 fallback하지 않는다.
Resolver 저장소 장애는 Gateway에서 `503 connection.reference_unavailable`, processor에서
`source.temporarily_unavailable`로 정규화한다. Runtime row lock과 실행 도중 revoke 취소는
MBA-302의 별도 transaction/lock 계약 범위다.

KB detail/direct document의 `error_message`와 progress SSE의 `message`/`error`는
persisted 원문이 아니다. Gateway가 status를 fixed public message로 투영하며 failure는
generic safe message만 반환한다. SSE progress는 0..100 범위로 제한하고 unauthorized
또는 concurrent-delete path에서도 raw DB/Redis/exception text를 event에 넣지 않는다.
Redis progress는 `indexing`/`processing`에서만 사용하며 `pending`과
`waiting_for_approval`은 stale Redis 값과 무관하게 0이다.

## Target Endpoint Groups

| 그룹 | 목표 path | 목적 |
| --- | --- | --- |
| Collections | `/api/v1/knowledge/collections`, `/api/v1/knowledge/collections/{collection_id}` | Collection 목록, safe metadata, route/manage/sync operation |
| Collection items | `/api/v1/knowledge/collections/{collection_id}/items` | Document-level KB link/unlink. KB content permission을 부여하지 않음 |
| Collection permissions | `/api/v1/knowledge/collections/{collection_id}/permissions` | Collection `read`/`route`/`manage`/`sync` grant/revoke. Additive allow만 제공 |
| Collection visibility | `/api/v1/knowledge/collections/{collection_id}/visibility` | Anonymous public-only runtime 후보 여부를 safe metadata flag로 전환. Source-managed KB public exposure approval은 별도 정책 row로 검증 |
| Document-level KBs | `/api/v1/knowledge/kbs/{kb_id}` | KB detail, active version, sync state, remediation summary |
| Document versions | `/api/v1/knowledge/kbs/{kb_id}/versions/*` | Version history, active version, re-index state |
| Raw/compliance view | `/api/v1/knowledge/kbs/{kb_id}/raw-artifacts/*` | Raw/compliance gate 이후 선택적 protected raw content access. RAG answer API에서 사용하지 않음 |
| Source connectors | `/api/v1/knowledge/sources/*` | Source connection, sync, tombstone, ACL status, remediation |
| Knowledge skills | `/api/v1/knowledge/skills/*` | Provider-neutral skill registry, version, freshness/eval status, safe metadata. 주 사용처는 빌더 단계 LLM node의 RAG 옵션 구성 |
| 실행 시점 RAG candidate resolution/retrieval | 내부 service call | MBA-232는 direct KB + 명시 selected Collection을 current audience로 재평가하는 Workflow Engine internal resolver contract만 제공한다. Builder/preflight `/api/v1/knowledge/candidates/resolve`, public API, graph/LLM/retrieval wiring은 분리하며 실제 연결은 MBA-233 범위다 |
| Knowledge domain permissions | `/api/v1/knowledge/domain-permissions`, `/api/v1/knowledge/domain-capabilities` | Organization manager가 Team/User 관리 action을 위임하고 caller의 safe capability를 조회 |

공개 HTTP path가 필요한 경우에는 별도 API gate review에서 path 이름과 JSON/SSE shape를 확정한다. MBA-105의 필수 계약은 collection listing(`collection.read`), collection routing(`collection.route`), KB content permission, source ACL state, document version citation identity의 분리다. Skill authoring, test, submit-for-review, publish/deprecate, Workflow Playground skill binding API는 아직 승인된 계약이 아니다.

### MBA-232 Workflow Runtime Candidate Resolver

이 계약은 public HTTP request/response가 아니라 Workflow Engine 내부 application/port
contract다. Gateway의 Builder/deployment-preview `KnowledgeCandidateResolver`와 다른
책임을 가진다. MBA-232에서 `/api/v1/*` path, Workflow graph field, Client schema,
deployment preflight와 LLM node wiring은 추가하거나 변경하지 않는다.

Input:

| 필드 | 규칙 |
| --- | --- |
| `audience` | `AuthenticatedAudience(organization_id, user_id)` 또는 `AnonymousPublicAudience(organization_id)` closed union. Owner/builder/deployment owner/credential principal/service account fallback 금지 |
| `direct_kb_ids` | Server-owned configured order. Duplicate는 first position 유지. Defensive cap 20 |
| `collection_ids` | Server-owned 명시 selected Collection configured order. Missing/empty는 stream 0개이며 organization-wide fallback 금지. Defensive cap 20 |
| `candidate_budget` | Server-owned unique KB cap. 1 이상 20 이하 |
| `candidate_scan_cap` | Server operations cap. Selected Collection을 공정하게 scan하며 response에 exact hidden 구조를 노출하지 않음 |

Authenticated resolution은 direct KB에 KB `use`와 applicable materialized source gate를
요구하고 Collection `route`는 요구하지 않는다. Collection child는 active Collection
`route`, membership, child KB `use`, applicable materialized source gate를 모두 요구한다.
Knowledge domain permission과 Collection `read/manage/sync`는 이 gate를 대체하지 않는다.

Anonymous resolution은 selected active public Collection child 또는 active public
Collection에 연결된 direct manual KB만 허용한다. Team/User/domain grant를 사용하지
않는다. Source/connector public exposure primitive가 현재 없으므로 source-managed KB는
모두 제외한다.

Output:

| 필드 | 규칙 |
| --- | --- |
| `status` | `resolved` 또는 `safe_no_result` |
| `candidates` | 최대 20개의 authorized canonical KB identity와 internal first provenance. Direct configured order 우선, Collection round-robin, canonical KB dedupe |
| `routing_mode` | `direct`, `collection`, `mixed`, `none` 중 fixed safe value |
| count summary | Configured/evaluated/eligible 수의 safe bucket만 허용. Hidden/denied exact count 금지 |
| `budget_limited` / warning | Deterministic budget 또는 bounded scan 도달 여부와 fixed safe warning |

Candidate policy exclusion은 safe omission이고 candidate 0개는 provider/retrieval 전
`safe_no_result`다. DB session, PostgreSQL snapshot, repository 또는 authorization helper
infrastructure failure는 partial candidate를 반환하지 않는 typed retryable
whole-resolution error다. Error는 fixed code/retryability만 가지며 raw SQL/exception,
identifier, source metadata 또는 payload를 포함하지 않는다. Partial KB retrieval timeout은
이 internal resolver output이 아니라 MBA-233/downstream Retrieval Orchestrator 계약이다.

Resolver adapter는 invocation마다 fresh PostgreSQL transaction을 열고 첫 query 전에
`REPEATABLE READ, READ ONLY`를 적용한다. Current Collection/membership/KB
lifecycle/readiness/permission/materialized provenance는 같은 snapshot에서 읽고 candidate
또는 authorization 결과를 invocation 사이에 cache하지 않는다. Live connector
`check_access*`와 runtime source authorization cache는 MBA-232에서 호출하지 않는다.
Membership은 configured Collection별 ordered LATERAL cap을 먼저 적용한 bounded
intermediate relation에서 round-robin ranking한다. Source-policy/provenance expiry는 같은
transaction에서 한 번 읽은 `transaction_timestamp()`를 전체 invocation에 재사용한다.

### MBA-233 Workflow Builder Collection Picker

`GET /api/v1/knowledge/llm-selectable-collections`는 authenticated Workflow Builder
전용 route-safe projection이다. Collection 관리 목록이나 MBA-232 runtime resolver
response를 재사용하지 않는다.

Request context:

| 항목 | 규칙 |
| --- | --- |
| Authentication | 로그인 사용자 필수 |
| Organization | `X-Organization-Id`로 해석한 active organization |
| Permission | active lifecycle이고 `sync_state != source_deleted`인 Collection에 대한 current user effective `route` |

서버는 organization/lifecycle과 effective `route`를 SQL query scope에 먼저 적용한 뒤
최신순 최대 500개를 반환한다. Unauthorized 최근 row를 먼저 500개로 자른 뒤
authorization하지 않는다. 따라서 500개보다 오래된 authorized Collection도 authorized
result cap 안에 있으면 후보에 포함된다.

Response:

```json
{
  "collections": [
    {
      "id": "00000000-0000-0000-0000-000000000000",
      "safe_label": "사내 문서"
    }
  ]
}
```

`safe_label`은 optional이며 approved safe metadata에 값이 없거나 display policy를
통과하지 못하면 `null`이다. Response에는 raw Collection name/description,
organization ID, lifecycle/source/system-managed field, member KB ID, exact child count,
permission row/capability, hidden/unavailable total을 포함하지 않는다. `read`, `manage`,
`sync` 또는 Knowledge domain action만 있고 `route`가 없는 Collection은 반환하지 않는다.
다른 organization, inactive/archived/deleted 또는 `source_deleted` Collection은 존재
여부를 구분하지 않고 생략한다. Schema/DB failure는 raw SQL/exception 없이 fixed safe
error envelope로 닫는다.

### MBA-233 Editable Graph Reference Authorization

Workflow draft save, Agent Builder apply, optimizer/model-routing graph persistence는
graph structural validation 뒤 current editor와 active organization으로 Knowledge
reference를 다시 authorize한다.

| Reference | Save-time gate |
| --- | --- |
| Direct KB | same organization, active, `sync_state != source_deleted`, retrieval-selectable, effective KB `use`, applicable materialized source authorization |
| Selected Collection | same organization, active, `sync_state != source_deleted`, effective Collection `route` |

Collection child membership/KB/source authorization은 save-time에 열거하지 않는다.
Graph에 direct KB와 Collection reference가 모두 없으면 구조 검증 뒤 authorization context와
DB permission query를 생략하여 organization이 없는 legacy non-RAG draft 저장을 유지한다.
Malformed Knowledge field는 이 short-circuit 전에 거부한다.
Reference 하나라도 실패하면 전체 write와 success audit을 commit하지 않는다. Hidden,
cross-organization, missing, inactive, revoked와 denied 상태는 외부에서 구분하지 않는
`knowledge_reference_unavailable` 계열 fixed code와 safe field path만 반환하며 UUID,
label, raw graph와 permission reason을 echo하지 않는다. Permission query/DB failure는
retryable safe infrastructure error이고 partial graph를 만들지 않는다.

Save authorization result, picker item과 preflight 결과는 capability/token이 아니다.
Direct execute/stream graph는 같은 structural contract를 통과하고 invocation-time
MBA-232 resolver로 current audience를 authorize한다.

### KB Permission Endpoints

MBA-176의 Knowledge 직접 권한 API는 Organization resource permission surface와 같은 응답 envelope를 사용한다. KB 권한은 organization membership의 대체물이 아니며, active organization member에게만 effective permission으로 적용된다.

List response는 `ResourcePermissionListResponse`를 사용하고 `resource_type`은 `"knowledge_base"`다.

```json
{
  "resource_type": "knowledge_base",
  "resource_id": "00000000-0000-0000-0000-000000000000",
  "organization_id": "00000000-0000-0000-0000-000000000000",
  "team_permissions": [],
  "user_permissions": [
    {
      "id": "00000000-0000-0000-0000-000000000000",
      "grantee_type": "user",
      "grantee_id": "00000000-0000-0000-0000-000000000000",
      "grantee_name": "User",
      "auth_state": "operator",
      "assigned_at": "2026-07-04T00:00:00Z"
    }
  ]
}
```

Grant request:

```json
{
  "auth_state": "operator"
}
```

- 허용 값은 `viewer`, `operator`, `builder`, `manager`다. `none`은 직접 grant request에서 거부하고, 권한 회수는 DELETE endpoint를 사용한다.
- Team grant는 기존 `team_knowledge_permissions`를 생성/갱신한다. User grant는 `user_knowledge_permissions`를 생성/갱신한다.
- 요청자는 organization manager 또는 해당 KB `manage` 권한을 가져야 한다.
- `X-Organization-Id`는 KB의 organization과 일치해야 한다. 다른 organization KB, hidden/deleted/archived KB, 존재를 드러내면 안 되는 대상은 safe 404/resource-hidden 계약을 따른다.
- User grant 대상은 같은 active organization member여야 한다. invited/suspended/removed/non-member 사용자에게는 grant를 생성하지 않는다.
- Grant/revoke 성공은 permission row 변경과 같은 DB transaction 안에 `team_knowledge_permission.*` 또는 `user_knowledge_permission.*` data-change audit row를 정확히 한 번 기록해야 한다. Core upsert와 bulk delete 경로는 ORM listener에만 의존하지 않는다.
- Effective KB permission은 organization manager override와 team/user direct grant 중 가장 강한 additive allow다. 직접 grant는 team grant를 낮추거나 deny할 수 없다.
- Source-managed KB retrieval에서는 KB `use` grant가 있어도 source ACL/requester authorization gate와 final evidence policy를 다시 통과해야 한다.

MBA-231부터 list/grant/revoke는 Organization manager, 해당 KB `manage`, 또는
domain `permission_delegate`를 허용한다. Domain delegator가 자신 또는 자신이
active member인 Team에 `viewer/operator/builder/manager` grant를 만드는 요청은
`409 policy.blocked`와 safe `policy_reason=knowledge.self_escalation`으로 차단한다.
Resource manager는 이미 해당 KB의 content-plane `manager`이므로 자기 grant를
갱신하는 행위가 권한을 상승시키지 않지만, 마지막 관리 경로 제거는 recovery
authority가 남아 있는지 검증한다.

### Knowledge Domain Permission Endpoints

| Method | Path | 목적 | 권한 |
| --- | --- | --- | --- |
| GET | `/api/v1/knowledge/domain-capabilities` | 현재 actor의 effective domain action과 UI capability 조회 | active organization member |
| GET | `/api/v1/knowledge/domain-permissions` | Team/User domain grant 목록 | Organization manager |
| GET | `/api/v1/knowledge/domain-delegation-subjects` | bounded Team/User safe 위임 대상 page | Organization manager |
| PUT | `/api/v1/knowledge/domain-permissions/teams/{team_id}/{permission_action}` | Team domain grant upsert | Organization manager |
| DELETE | `/api/v1/knowledge/domain-permissions/teams/{team_id}/{permission_action}` | Team domain grant revoke | Organization manager |
| PUT | `/api/v1/knowledge/domain-permissions/users/{user_id}/{permission_action}` | User domain grant upsert | Organization manager |
| DELETE | `/api/v1/knowledge/domain-permissions/users/{user_id}/{permission_action}` | User domain grant revoke | Organization manager |

`permission_action`은 `catalog_manage`, `permission_delegate`,
`lifecycle_manage`, `sync_manage`만 허용한다. PUT body는 optional `expires_at`만
받고 unknown field를 거부한다. Team은 같은 organization의 active Team, User는
같은 organization의 active member여야 한다. Expired row는 list history에 safe
상태로 표시할 수 있지만 effective capability에는 포함하지 않는다. Domain
grant/revoke와 audit는 한 transaction이며, raw principal, request payload,
resource label이나 source metadata를 audit에 저장하지 않는다.

Active subject 조건은 PUT grant에만 적용한다. DELETE revoke는 inactive Team,
deactivated/removed User를 다시 활성화하거나 membership을 복원하도록 요구하지
않고, active organization 안에서 `organization_id + subject_type/id + action`에
해당하는 기존 permission row를 `FOR UPDATE` 또는 동등한 row lock으로 고정한 뒤
삭제한다. 기존 row가 없으면 idempotent `204`이며 audit를 만들지 않는다. Row가
있으면 permission delete와 canonical audit를 같은 transaction에서 commit하고,
둘 중 하나라도 실패하면 모두 rollback한다.

Domain subject 응답은 active Team/User의 opaque id와 safe label만 반환하며 email,
raw principal, source identity를 포함하지 않는다. UI는 Team을 기본 선택으로 두고
User direct domain grant는 예외 경로로 제공한다.

Collection 관리 Client는 domain-derived control의 canonical source로
`GET /api/v1/knowledge/domain-capabilities`를 사용한다. 특히 private Manual
Collection 생성은 `can_create_collection`, public visibility control은
`can_change_public_visibility`를 각각 사용하고 Organization role이나 `actions` 배열을
Client에서 다시 조합하지 않는다. Collection list의 같은 이름 capability는 기존
관리 projection 호환을 위해 유지하고 정상 상태에서는 domain capability와 일치해야
하지만, 두 응답이 일시적으로 불일치하면 Client는 domain capability를 따르고 최종
인가 판단은 POST/visibility API가 다시 수행한다. Capability refresh가 실패하면
Client는 이전 허용 상태를 유지하지 않고 fail-closed한다.

### MBA-231 KB Object/Property Authorization Inventory

| Surface/path group | Gate | Scope/hidden response | Response boundary | Audit |
| --- | --- | --- | --- | --- |
| `POST /knowledge` | active organization member; creator `manager` bootstrap | active organization required | created KB safe metadata only | KB + creator grant + canonical audit in one transaction |
| `GET /knowledge`, `GET /knowledge/{kb_id}`, `GET /knowledge/{kb_id}/documents/{document_id}`, document safe status, RAG document progress SSE | `read` | active organization; list omits denied rows, direct hidden is 404, visible action denial is 403 | safe KB/document status와 allowlisted operational metadata만 반환. Encrypted config, connection/source identifier, raw/unknown nested metadata와 hidden count는 제외 | read/status polling has no mutation audit |
| `GET /knowledge/llm-selectable`, search-test, standalone Agent answer/stream | `use` + source authorization where applicable | active organization; hidden/source denial does not reveal KB/source identity | retrieval-visible evidence and redaction-safe citation/summary only | retrieval/answer canonical audit; no raw query/evidence payload |
| `POST /knowledge/candidates/resolve`, RAG recommendation, Agent Builder internal safe-reference consumption | caller-specific `read/use/route` composition | active organization and server-resolved candidate set | safe handles/labels/reason codes; hidden IDs, names, counts excluded | decision/audit summary uses safe reason codes only |
| KB settings PATCH, RAG upload to existing KB, document analyze/confirm/delete/process/preview | `write` | active organization; document must belong to authorized KB | mutation result and safe processing metadata only | settings uses KB update audit; upload/confirm/delete/process use document action audit; analyze/preview are non-mutating and emit no mutation audit; payload/content excluded |
| Document sync | `write` or bounded domain `sync_manage` | active organization; source-owned policy remains authoritative | safe queued/status response | document process action audit without credential/source payload |
| Manual original content | `content_read` | `X-Organization-Id` active organization; document must belong to authorized manual KB | validated content response; supported PDF is inline and every original file response uses `X-Content-Type-Options: nosniff`. Browser preview는 organization-scoped API client로 bytes를 받은 뒤 ephemeral Blob URL로 렌더링하며 native navigation으로 이 endpoint를 직접 열지 않는다 | access path must not place content in audit/trace |
| Source-managed original content | `content_read` + requester source authorization + approved display/raw policy | missing primitive/policy is fail-closed | no raw response in MBA-231 baseline | denied/safe decision only; no raw source metadata |
| KB permission list/grant/revoke | Organization manager, KB `manage`, or bounded domain `permission_delegate` | active organization; self/own-Team escalation is 409 policy block | safe Team/User permission projection | permission row and canonical audit in one transaction |
| KB safe catalog metadata | `manage` | active organization | allowlisted `safe_label`, description, topics only | metadata change audit in the mutation transaction |
| KB/Collection archive/restore | resource `manage` or matching domain `lifecycle_manage` | active organization; source-managed lifecycle mutation denied | 204/safe lifecycle projection | lifecycle row and canonical audit in one transaction |
| KB hard delete | Organization manager + `acknowledged_hard_delete=true` + approved retention/legal-hold gate | active organization; source-managed/retention policy fail-closed. Gate 미구성 baseline은 403 | allow된 경우 204; deleted resource is subsequently hidden | allow된 경우 permission cleanup + canonical audit + DB delete in one transaction; default deny는 mutation/audit 없음 |
| Private Collection link/unlink/reorder of KB membership | Collection/KB resource manage combination or domain `catalog_manage` | active organization; public Collection uses stronger exposure gate | safe Collection item projection; linking grants no KB content action | membership mutation and canonical audit in one transaction |
| Public Collection membership/visibility | Organization manager + explicit acknowledgement + source public approval | active organization; absent approval fails closed | safe visibility/membership state only | exposure mutation and canonical audit in one transaction |

Knowledge 최초 등록용 presigned upload은 대상 `knowledgeBaseId`와 active organization을
받아 KB `write` 및 initial document slot을 fast precheck한다. Workflow 입력 파일용 generic
presigned upload은 KB 식별자를 요구하지 않는다. 이 precheck는 concurrent request를 직렬화하지
않으므로 subsequent `/rag/upload`의 canonical row-lock check를 대체하지 않는다. 이미
업로드된 presigned object는 registration conflict에서 ownership이 명확하지 않으면 임의로
삭제하지 않는다. URL/proxy preview처럼 KB identifier가 없는 표면은 authenticated storage
ownership, filename/key validation, egress guard, size/content-type cap과 safe error contract를
계속 적용한다. Backend-owned artifact도 canonical conflict 또는 DB flush 이전 실패처럼
commit이 시작되지 않았음이 확실할 때만 보상 삭제한다. Commit 호출 이후 결과가
불명확하면 이미 커밋된 Document reference를 깨뜨릴 수 있으므로 자동 삭제하지 않는다.
Request-bound presigned upload intent와 만료·orphan reconciler는 `MBA-295`의 target이며,
그 계약이 없는 현재 baseline은 caller prefix만으로 direct object ownership을 확정하지 않는다.

DB source UI가 이번 요청에서 새 Connection을 먼저 생성한 뒤 canonical registration에서
`document_slot_occupied`, source policy, resource/permission rejection을 받으면 owner-scoped
`DELETE /api/v1/connectors/{connection_id}`로 보상 정리한다. 이 endpoint는 Connection row를
잠그고 어떤 Document의 allowlisted top-level 또는 `db_config.connection_id` metadata에도 참조되지 않은 경우에만
`204`로 삭제하며, 참조 중이면 `409 connection.in_use`, unknown/other-owner resource는
`404 resource.hidden`, persistence failure는 `503 connection.delete_unavailable`로 닫는다.
DB source registration은 같은 Connection row lock을 commit까지 유지해 reference 생성과
보상 삭제의 경합을 직렬화한다. Commit 결과가 불명확한 registration 오류에서는 Client가
Connection을 자동 삭제하지 않는다. 기존 DB Document의 process 설정에서 새
`db_config.connection_id`를 저장할 때도 같은 owner-scoped Connection row lock을 metadata
commit까지 유지한다. 따라서 delete가 먼저 commit되면 설정 저장은 `404 resource.hidden`,
설정 저장이 먼저 commit되면 delete는 `409 connection.in_use`로 닫힌다. 설정 화면의 최초
조회 뒤 다른 요청이 같은 Document를 먼저 갱신하면 Connection 다음 Document를 잠근 writer가
`updated_at`을 재검증하고 stale 요청을 `409 connection.reference_conflict`로 전체 rollback한다.
Reference metadata commit에서 발생한 PostgreSQL `40001`, `40P01`, `55P03`, `57014`도 lock 획득 실패와 같은 `503 connection.reference_busy`로 정규화하고, 기타 SQLAlchemy commit 오류는 `503 connection.reference_unavailable`로 닫는다. 두 경우 모두 background ingestion을 등록하지 않고 전체 transaction을 rollback한다.

Direct resource는 active organization으로 먼저 scope를 고정한다. Unknown,
cross-organization, deleted 또는 invisible resource는 `404 resource.hidden`,
same-scope visible resource의 action 부족은 `403 permission.denied`다. 목록은
unauthorized row와 hidden count를 반환하지 않는다.

Builder와 deployment preflight가 사용할 Gateway MBA-105 candidate resolver contract는 다음 shape를 지켜야 한다. 이 contract의 missing Collection scope fallback과 safe metadata response는 위 MBA-232 Workflow runtime resolver에 적용하지 않는다.

| 필드 | 규칙 |
| --- | --- |
| `actor` | Builder 또는 deployer subject. Candidate metadata 표시 권한의 기준 |
| `intended_execution_subject_id` / `audience` | Runtime availability 계산 기준. 없으면 availability를 `unknown` 또는 `unavailable`로 낮춘다. Phase 7 baseline은 요청 필드를 받되 runtime에서는 execution_subject 기준으로 다시 판정한다 |
| `mode` | `auto_collection` 또는 `explicit_kb` |
| `collection_ids` | Auto collection mode에서 서버가 해석한 route scope 후보. 누락 시 actor가 route할 수 있는 safe subset만 사용 |
| `knowledge_base_ids` | Explicit KB mode에서 서버가 safe handle, authorized picker, 또는 trusted backend context로 해석한 KB 후보. Collection route는 생략할 수 있지만 KB visibility/use/source ACL/final evidence preflight는 수행 |
| `purpose` | `builder_suggestion`, `deployment_preflight`, `runtime_preview` 같은 bounded enum |
| `max_collections` / `max_candidate_kbs` | 서버 cap. Baseline은 `max_collections <= 100`, `max_candidate_kbs <= 5000`을 강제한다. Cap은 route/use/source ACL helper를 통과한 authorized subset에 적용하며, 임의 row를 먼저 자른 뒤 authorization하지 않는다 |

Response는 safe candidate list와 summary만 포함한다. 각 candidate는 `candidate_id`, `candidate_type`, safe label, route availability, runtime availability(`available`, `warning`, `unavailable`, `unknown`), safe reason code, required action을 반환할 수 있다. Hidden KB id/name, exact denied count, raw source path/title/url, hidden source distribution은 반환하지 않는다.

### Workflow Builder RAG Recommendation

`POST /api/v1/knowledge/rag-recommendations`는 Workflow Builder/Agent Builder가 `StructuredRequest`에서 파생한 safe intent summary, 지식 요구사항, pending resolution을 기준으로 현재 LLM node schema에 맞는 RAG option 후보를 받기 위한 Builder 단계 API다. Agent Builder client가 직접 호출하는 public client endpoint가 아니라, Agent Builder backend가 인증 사용자, active organization, workflow/app scope를 server-resolved context로 확정한 뒤 호출하는 Knowledge domain boundary로 취급한다. HTTP request는 `KnowledgeCandidateResolver`가 만든 server-issued safe candidate set reference 또는 server-resolved scope hint만 전달하며, full safe candidate set 객체는 같은 backend 내부 service call에서만 소비할 수 있다. Request의 collection/KB scope 값은 candidate resolver hint일 뿐이며, ranking 단계가 raw KB id나 raw source metadata를 직접 해석해서 권한 후보를 만들면 안 된다.

Request body는 raw user input 전체가 아니라 Agent Builder가 구조화한 safe summary로 간주한다. Raw natural language 전체, raw prompt, hidden source 정보는 이 endpoint 입력이 아니다.

Public HTTP boundary에서는 client가 raw KB id를 보내 `explicit_kb` mode로 recommendation scope를 여는 요청을 허용하지 않는다. `explicit_kb`는 Agent Builder backend 또는 Knowledge domain 내부 service call처럼 safe handle, authorized picker, server-resolved context를 이미 통과한 trusted boundary에서만 사용할 수 있다. Public HTTP request에서 `mode=explicit_kb`가 오면 safe validation error로 닫고, `mode=auto`에 raw KB/collection id가 섞여 있으면 권한 판단에 사용하지 않고 무시한다.

| 필드 | 규칙 |
| --- | --- |
| `intent_summary` | 필수. `StructuredRequest`에서 만든 redaction-safe intent summary. 길이 cap과 control character normalization을 적용한다 |
| `target_step_ref` | KB 추천이 필요한 planned step reference |
| `node_purpose_summary` | LLM node 목적 safe 요약. Raw text는 durable metadata에 저장하지 않는다 |
| `safe_workflow_context_summary` | 현재 workflow 목적, 기존 KB 참조, 관련 노드 역할을 요약한 safe context. Raw graph payload, hidden source 정보, raw KB content를 포함하지 않는다 |
| `knowledge_requirement` | `requirement_id`, `query_topics`, `expected_evidence_type`, `required` 같은 지식 요구사항 |
| `safe_query_topics` | Agent Builder 구조화 단계에서 생성한 KB 추천용 safe topics. Adapter는 이 값을 1차 relevance 입력으로 사용하고 raw workflow/action term은 점수 입력에서 제외한다 |
| `pending_resolution_ref` | `resolution_id`, `slot_type=knowledge_base`, `slot_key`, `blocking` 같은 unresolved slot reference |
| `authorized_safe_candidate_set_ref` | 선택. KnowledgeCandidateResolver가 만든 safe candidate set의 server-issued reference. 없으면 Knowledge domain이 아래 scope hint를 기준으로 candidate resolver를 먼저 수행하고, recommendation ranking은 그 결과만 사용한다 |
| `mode` | `auto`, `auto_collection`, `explicit_kb`. `auto`는 adapter 내부 편의값이며 resolver 호출 전 bounded mode로 변환한다. Public HTTP boundary에서 `explicit_kb`는 허용하지 않으며 trusted backend/internal service boundary에서만 사용할 수 있다 |
| `collection_ids` | 선택. 서버가 active organization과 actor 권한 기준으로 해석한 route scope hint. Agent Builder client가 HTTP body로 보낸 raw collection id는 권한/scope 판단에 사용하지 않고 무시한다. Field 생략은 trusted backend/service boundary에서 actor가 route할 수 있는 서버 정책상 collection subset을 뜻하며, 같은 trusted boundary에서 명시적으로 `[]`를 전달한 경우에만 빈 scope로 해석해 recommendation을 만들지 않는다. Collection은 recommendation item으로 반환하지 않고 safe summary로만 제공한다 |
| `knowledge_base_ids` | 선택. 서버가 safe handle, authorized picker, 또는 trusted backend context에서 해석한 explicit KB 후보. Public HTTP `explicit_kb` 요청은 거부하고, Agent Builder client가 HTTP body로 보낸 raw KB id는 그대로 전달하거나 권한 판단에 사용하지 않고 무시한다 |
| `intended_execution_subject_id` | 선택. Runtime availability warning 계산용. 실행 권한 보장이 아니며 runtime은 다시 검증한다 |
| `max_recommendations` | 서버 cap. 초기 기본값은 5, 최대 20 |
| `max_collections` | Auto collection 후보 탐색 cap. 서버 기본값 20, 최대 100 |
| `max_candidate_kbs` | Auto collection에서 resolver가 만들 수 있는 KB 후보 cap. 서버 기본값과 최대값은 5000이며, 실제 response recommendation 수는 `max_recommendations`가 다시 제한한다 |
| `high_risk_domain` | Builder hint. `strict_citation` 같은 option recommendation에만 사용하며 권한, policy block, compliance decision에 사용하지 않는다 |
| `allow_query_rewrite` | `high_risk_domain`이 있는 경우 safe template 기반 `queryRewriteMode=template` 추천을 허용할지 결정한다. 이 값은 권한 후보를 넓히거나 LLM-assisted rewrite를 승인하지 않는다 |

HTTP request body는 full `authorized_safe_candidate_set` 객체를 받지 않는다. 같은 backend 내부 service call에서는 full safe candidate set 객체를 넘길 수 있지만, HTTP 또는 serialized boundary에서는 `authorized_safe_candidate_set_ref` 또는 server-resolved scope hint만 사용한다.

Response는 Agent Builder 내부 adapter 계약과 같은 top-level envelope를 반환한다. Agent Builder backend가 내부 service call이 아니라 HTTP boundary를 사용하더라도 같은 envelope를 소비해야 하며, recommendation item list만 단독으로 반환하지 않는다.

| 필드 | 규칙 |
| --- | --- |
| `status` | `recommended`, `clarification_required`, `no_candidate`, `unavailable` |
| `resolution_id` | 해결 대상 pending resolution id |
| `requirement_id` | 해결 대상 knowledge requirement id |
| `recommendations` | safe KB recommendation item 목록. `status=recommended`일 때 포함하며 각 item은 아래 허용 response field를 따른다 |
| `clarification_options` | 권한 확인된 추천 후보가 있는 경우, 또는 adapter unavailable fallback에서 사용자에게 표시할 safe option 목록. Agent Builder는 후보가 1개여도 이 목록을 사용자 선택 UI로 표시한다 |
| `user_safe_warning` | partial access, runtime availability, unavailable fallback 같은 사용자 표시 경고 |
| `fallback_reason` | `adapter_unavailable`, `no_candidate` 같은 safe reason code. Hidden resource identity나 exact count를 포함하지 않는다 |

Adapter가 unavailable이지만 권한 확인된 safe 후보 선택지를 제공할 수 있으면 `status=clarification_required`, `fallback_reason=adapter_unavailable`, `clarification_options`를 반환한다. Safe 후보 선택지도 제공할 수 없으면 `status=unavailable`, `fallback_reason=adapter_unavailable` 또는 동등한 safe reason code를 반환한다.

Recommendation item은 초기 구현에서 `candidate_type="knowledge_base"`만 반환한다. Collection label과 linked KB count는 `source_collection_summary` safe metadata로만 제공한다. 현재 Workflow LLM node는 `knowledgeBases`를 실행 입력으로 사용하므로 Agent Builder backend 내부 service call은 recommendation result를 runtime KB reference로 materialize할 수 있다. 단, HTTP 또는 serialized boundary의 response는 safe handle과 safe metadata만 반환하며 raw runtime KB id를 담은 materialized reference를 노출하지 않는다.

Apply/save 직전 materialization은 recommendation list의 현재 top-N 결과를 다시 소비하는 방식이 아니라, 이전에 발급한 safe candidate handle을 KnowledgeCandidateResolver의 권한 확인 candidate set 안에서 직접 재검증하고 runtime KB reference로 해석하는 backend/internal service boundary여야 한다. Ranking 변화 때문에 여전히 권한상 유효한 handle이 top-N 밖으로 밀렸다는 이유만으로 저장을 차단하지 않는다.

허용 response field:

| 필드 | 규칙 |
| --- | --- |
| `recommendation_id` | Opaque id. Hidden resource identity를 인코딩하지 않는다 |
| `recommendation_mode` | `auto_collection` 또는 `explicit_kb` |
| `candidate_type` | 초기 구현은 `knowledge_base`만 허용 |
| `candidate_id` | Agent Builder-facing server-issued safe candidate handle. Raw source id/path/url/title 또는 client-stable raw KB id를 직접 노출하지 않는다 |
| `safe_label` | Display-policy-approved label. 없으면 raw KB name fallback 금지, `null` 또는 generic label만 허용 |
| `materialized_knowledge_bases` | HTTP response에서는 empty/suppressed여야 한다. 같은 backend 내부 service call에서만 LLM node `knowledgeBases`로 변환 가능한 권한 확인 runtime KB ref list를 포함할 수 있으며, `MAX_RAG_RETRIEVAL_KBS=20` 이하로 제한한다 |
| `score` | Recommendation ranking에 사용한 normalized score. Raw retrieval/provider score를 직접 노출하지 않는다 |
| `confidence` | `high`, `medium`, `low` 중 하나. 추천 강도를 표시하며 Agent Builder는 이 값만으로 KB를 자동 선택하지 않는다 |
| `reason_category` | 추천 근거의 safe category. 예: topic keyword match, metadata match, collection context match |
| `threshold_result` | `high_confidence`, `close_score`, `below_threshold` 등 추천 강도, warning, failure 분기를 설명하는 safe 결과 |
| `recommended_options` | `queryRewriteMode`, `queryRewriteTemplate`, `evidenceSufficiencyPolicy`, `ragFailurePolicy`, `sourceTierPolicy`, `scoreThreshold`, `topK` allowlist만 허용 |
| `source_collection_summary` | Safe collection id/label, route scope type, bucketed linked KB count 정도만 허용 |
| `provenance` | `recommendation_strategy`, `safe_reason_code`, `used_signals`, `matched_safe_terms`, bucketed counts 같은 redaction-safe summary |
| `runtime_availability` | `available`, `warning`, `unavailable`, `unknown`. Intended subject가 없으면 private 후보를 `available`로 올리지 않는다 |
| `warnings` | Safe warning code/message만 허용 |
| `summary` | Candidate/recommendation/warning/hidden-or-unavailable count는 bucketed 값만 포함한다 |
| `reason_code` | Recommendation이 없을 때만 safe reason code를 반환한다. Hidden resource identity나 exact count는 포함하지 않는다 |

`score`는 DB 저장값이 아니라 추천 요청 시점에 계산한 KB 단위 ranking 값이다. Ranking은 `safe_query_topics`와 KB safe metadata의 `kb_relevance`를 0.70 비중으로 두고, `source_tier`, `runtime_availability`, `sync_freshness`를 각각 0.10 비중으로 더한다. Relevance 입력은 KB candidate의 `safe_label`, `kb_safe_description`, `kb_safe_topics` 같은 allowlisted safe comparison text로 제한한다. `collection_safe_label`, `collection_safe_topics`, Collection name/description, collection id/count는 route/permission boundary와 `source_collection_summary`에만 사용하며 KB relevance score 계산에는 사용하지 않는다. Manual KB의 `name`/`description`은 sanitizer, length cap, secret/url/path 제거를 통과한 뒤 safe label/topics comparison text로 자동 생성할 수 있다. Source-managed KB는 display-policy-approved source safe metadata만 이 경로에 사용할 수 있다.

Manual KB는 `KnowledgeBaseResponse.safe_metadata`로 allowlisted safe metadata를 반환할 수 있다. Safe metadata 조회·수정은 `GET/PATCH /api/v1/knowledge/{kb_id}/safe-metadata`를 사용하며 `safe_label`, `kb_safe_description`, `kb_safe_topics`만 저장 대상으로 허용하고 secret/url/path/raw source key는 sanitizer 또는 allowlist에서 제거한다. 일반 `PATCH /api/v1/knowledge/{kb_id}`는 KB `write` 이름·설명·embedding model 경로이며 `safe_metadata` payload를 422로 거부한다. Detail 응답은 `can_edit_settings`와 `can_manage_safe_metadata`를 분리하고 각각 effective KB `write`와 `manage` action으로 계산한다. Resource manager는 additive RBAC에 따라 두 capability를 모두 가지며 creator 여부는 권한을 높이거나 낮추지 않는다. Safe metadata 변경의 action/data-change audit은 KB target id와 마스킹된 변경 필드를 남기고 metadata 원문 값은 저장하지 않는다. Source-managed KB recommendation은 저장된 manual override가 아니라 display-policy-approved source safe metadata만 사용한다.

KnowledgeCandidateResolver와 recommendation ranking은 retrieval-visible active version 경계를 지켜야 한다. `sync_state=source_deleted`인 KB, active ready document version과 legacy unversioned retrieval-visible chunk가 모두 없는 KB는 recommendation candidate에서 제외한다. Active document version이 있으나 `ready`가 아니고 legacy retrieval-visible artifact도 없는 KB는 selectable ready candidate가 아니며, response는 이를 권한 없음이나 hidden resource로 표현하지 않고 safe `candidate_not_ready` 또는 `indexing_in_progress` warning/fallback reason으로 표시할 수 있어야 한다. 기존 active ready version은 유지되지만 최신 sync 상태가 `stale` 또는 `failed`인 KB는 후보로 남길 수 있으나, safe warning과 score penalty 또는 낮은 confidence를 함께 제공해야 한다. 이 경고는 raw source path/title/url, raw source error, hidden document count를 포함하지 않는다.

Auto recommendation에서 route-allowed collection link 후보가 없고 client가 collection scope를 명시하지 않은 경우, resolver는 같은 active organization 안의 직접 권한 확인된 retrieval-visible KB를 safe candidate set fallback으로 평가할 수 있다. 명시적으로 빈 collection scope는 후보 없음으로 유지하며 direct KB fallback을 적용하지 않는다.

금지: raw workflow intent, raw node purpose, raw natural language 전체, raw source id/url/path/title, raw ACL fact, raw principal, raw skill body, hidden KB id/name, exact denied/hidden count, raw prompt/completion/provider response.

Validation 실패 응답도 같은 금지선을 따른다. Safe summary 입력이라도 Pydantic/FastAPI validation detail의 `input` 값으로 echo하지 않고, field path/type/message 수준의 sanitized error만 반환한다.

## Document Processing Status

Document processing status endpoints, including `GET /api/v1/knowledge/{kb_id}/documents/{document_id}`, `GET .../ingestion` and `GET /api/v1/rag/document/{document_id}/progress`, use the durable job when present. `pending`, due-policy 안의 `retry_scheduled`, valid running lease와 recent heartbeat를 legacy enqueue timeout만으로 `failed`로 바꾸지 않는다. Expired lease는 recovery task가 retry 또는 dead-letter로 전환하고 fixed safe message를 Document projection에 반영한다.

Redis progress and Redis lock availability are not part of the public contract. The API must not require Redis to avoid infinite `processing`; Redis unavailable paths either continue through local processing fallback or become a safe terminal failure.

새 ingestion table을 읽거나 쓰는 endpoint는 resource authorization 뒤 schema readiness를 검사한다. Missing/incomplete schema는 `503 knowledge.ingestion_schema_not_ready`와 allowlisted `details.reason`만 반환하며 DB exception, missing SQL, source config를 반사하지 않는다.

## Request Model

### Explicit KB Answer

Explicit KB mode는 알려진 `knowledge_base_id`를 입력받는다. 이 직접 모드에서는 collection route permission을 요구하지 않을 수 있지만, KB helper, source ACL/requester authorization, metadata filter, hierarchy mode, final evidence policy는 항상 적용한다.

MBA-105 standalone `/api/v1/rag/agent/answer`와 `/api/v1/rag/agent/answer/stream`은 `evidence_sufficiency_policy`를 `minimum_evidence` 기본값으로 평가한다. Evidence가 없으면 LLM을 호출하지 않고 safe no-result로 닫으며, evidence score 또는 strict citation 기준이 부족하면 safe insufficient-evidence 응답으로 닫는다. 이 응답은 hidden KB id/name, 권한 없는 문서명, exact denied count를 포함하지 않는다.

필수 목표 field:

| 필드 | 규칙 |
| --- | --- |
| `knowledge_base_id` | 필수. Active organization scope 안에서만 평가하고, scope 밖이거나 사용할 수 없으면 resource-hiding matrix를 따른다 |
| `generation_model_id` / `credential_id` | 필수. Preset/default credential selection은 별도 ADR이 승인되기 전까지 허용하지 않는다 |
| `query` | 필수. Raw query는 기본적으로 durable 저장하지 않는다 |
| `metadata_filter` | Permission/source ACL gate 이후 허용된 candidate 안에서만 적용 |
| `hierarchy_mode` | 현재 metadata-aware/hierarchical RAG 계약을 따른다 |
| `query_rewrite_mode` | 선택 목표 옵션. 기본값 `off`; deterministic/template rewrite는 opt-in. Rewrite는 접근 범위를 넓히지 않는다 |
| `evidence_sufficiency_policy` | MBA-105 standalone Agent answer에서 기본값 `minimum_evidence`로 적용한다. `strict_citation`은 더 엄격한 citation 개수 검증 후보이며, `off`는 운영 runtime에서 허용하지 않는다 |
| `source_tier_policy` | 선택 목표 옵션. Source-of-Truth Tier를 authorized evidence 안에서 ranking/tie-break/conflict hint로만 사용한다 |

### Auto Collection Answer

Auto mode는 arbitrary KB id를 permission bypass로 받지 않는다. 먼저 safe candidate set을 구성한다.

| 필드 | 규칙 |
| --- | --- |
| `collection_ids` | 선택. 있으면 먼저 collection `route` 권한을 확인한다 |
| `skill_ids` | 빌더 단계 선택 후보. 있으면 skill visibility, freshness/eval, display policy를 확인한다. Skill만으로 KB permission/source ACL gate를 충족할 수 없다 |
| `generation_model_id` / `credential_id` | 필수. Auto mode는 preset/default credential selection을 의미하지 않는다 |
| `max_collections` / `max_candidate_kbs` / `max_retrieval_kbs` | 서버가 강제하는 cap. 초기 baseline은 `max_route_collections=20`, `max_candidate_kbs=5000`, `max_retrieval_kbs=20`, `max_chunks_per_kb=8`, `max_total_chunks=50`이며 운영 설정으로 조정 가능하다. 제품의 영구 고정 계약이 아니다 |
| `metadata_filter` | Permission/source ACL candidate filtering 이후 적용 |
| `query_rewrite_mode` | 선택 목표 옵션. 기본값 `off`; rewrite는 접근 범위를 넓히지 않고 raw rewritten query는 durable metadata에 저장하지 않는다 |
| `evidence_sufficiency_policy` | 선택 목표 옵션. 기본값 `minimum_evidence`; 근거 부족 시 safe no-result 또는 insufficient-evidence 응답 |
| `source_tier_policy` | 선택 목표 옵션. 공통 LLM node의 RAG 옵션이며 ADR-0017의 source tier baseline을 따른다 |
| `query` | Candidate routing과 retrieval에 사용한다. Permission decision에는 사용하지 않는다 |

Router는 authorized safe candidate와 safe metadata만 받는다. Raw source ACL fact, hidden KB id, raw source title/path/url, exact hidden count, raw content는 router input에 포함하지 않는다. `collection_ids`가 없을 때 candidate source는 조직 전체 collection이 아니라 서버 정책상 actor가 route할 수 있는 collection subset이다.

Router candidate metadata는 safe identifier와 coarse summary로 제한한다. 예시는 `knowledge_base_id`, optional `collection_id`, safe redacted display label, coarse source type, safe classification/category/tag, coarse sync/source ACL state, request-scoped ranking hint다. Raw source id/url/path/title, raw principal, raw ACL row, exact hidden/denied count, credential value, prompt/completion, raw content는 router input이 아니다.

Skill candidate metadata도 같은 boundary를 따른다. Workflow Builder가 받을 수 있는 skill field는 safe skill id, skill version, safe display label, source-of-truth tier, freshness state, eval status, validation checklist id, redaction-safe routing hint 정도로 제한한다. Raw skill body, hidden source reference, raw source title/path/url, restricted document list, raw content, prompt/completion, provider raw response는 Builder input이 아니다.

## Manual Collection Management

Manual Collection 관리 API는 Knowledge 관리 영역에서 사용한다. Workflow Builder가 Collection을 생성/삭제하거나 권한을 관리하는 surface가 아니다.

### Collection CRUD

| Method | Path | 목적 | 권한 |
| --- | --- | --- | --- |
| GET | `/api/v1/knowledge/collections` | Collection 목록. content 권한이 없는 domain 관리자는 safe 관리 projection만 조회 | `collection.read`, Knowledge domain 관리 action, 또는 organization manager override |
| POST | `/api/v1/knowledge/collections` | private Manual Collection 생성 | organization manager 또는 domain `catalog_manage` |
| GET | `/api/v1/knowledge/collections/{collection_id}` | Collection 상세 | `collection.read`, Knowledge domain 관리 action, 또는 organization manager override |
| PATCH | `/api/v1/knowledge/collections/{collection_id}` | safe name/description/metadata 수정 | `collection.manage`, private manual Collection의 domain `catalog_manage`, 또는 organization manager override |
| DELETE | `/api/v1/knowledge/collections/{collection_id}` | physical delete가 아니라 archive 전이 | `collection.manage`, domain `lifecycle_manage`, 또는 organization manager override |
| POST | `/api/v1/knowledge/collections/{collection_id}/restore` | archived manual Collection을 active로 복구 | `collection.manage`, domain `lifecycle_manage`, 또는 organization manager override |

List response는 `collections`, `can_create_collection`, `can_change_public_visibility`를 포함한다. 각 Collection row는 `id`, `name`, `description`, `is_system_managed`, `sync_state`, `lifecycle_state`, `visibility`, bucketed linked/active KB count, caller action flags, `safe_metadata`, timestamps만 포함한다. Raw source title/path/url/principal, hidden KB name/id, exact denied count는 반환하지 않는다.

Create request는 `name`, optional `description`, optional allowlisted `safe_metadata`만 받는다. Manual Collection 관리 UI는 새 Collection에 관리용 `name`과 별도 nonblank `safe_metadata.safe_label`을 함께 보내지만, 기존 API/internal caller 호환성을 위해 request schema에서 label 자체는 optional이다. 제공된 `safe_label`은 string이어야 하며 Gateway가 공통 safe-text sanitizer, 255자 cap, control character·secret-like text·URL·email·path 제거를 적용한다. 정제 후 안전한 텍스트가 남지 않거나 타입이 잘못되면 입력값을 echo하지 않는 `400 validation.failed`로 거부한다. Client는 `is_system_managed=true`, source identity, raw source URL/path/title, permission row를 create body에 넣을 수 없다. Duplicate safe name은 safe `409 conflict`로 반환한다.

Update request는 visibility를 바꾸지 않는다. Public/private 전환은 별도 visibility endpoint만 사용한다. Manual Collection 관리 UI는 현재 `safe_metadata`를 보존하면서 `safe_label`을 교체해 label 수정이 다른 허용 metadata를 제거하지 않게 한다. Label이 없는 기존 Manual Collection은 raw `name` 자동 복사나 일괄 backfill 없이 edit surface에서 명시적으로 보완한다. System-managed Collection은 connector/sync가 소유하므로 manual update는 safe override가 승인된 field로 제한한다.

`safe_metadata.safe_label`은 표시용 metadata일 뿐 권한이나 runtime capability가 아니다. Collection picker는 저장된 manual safe label을 다시 정제해 반환하고 값이 없으면 `null`을 반환한다. Raw Collection `name`/`description`을 fallback으로 반환하지 않으며 Client는 `null`에 generic `지식 Collection` label만 사용할 수 있다.

List의 `lifecycle_state` query는 `active`, `archived`, `deleted` 중 하나이며 관리 UI는 active와 archived를 별도 page로 조회한다. Archive와 restore는 Collection row를 잠근 뒤 상태와 권한을 다시 평가한다. Restore는 manual archived Collection만 `active`로 전이하며 active Collection에는 새 mutation/audit 없이 idempotent `204`를 반환한다. `deleted` 또는 organization 밖 대상은 hidden 처리하고 system-managed Collection은 source owner 경계로 거부하며 `sync_state=source_deleted`는 safe `409`로 차단한다. Restore는 기존 permission과 membership을 보존하지만 새 permission, child KB `use`, Workflow `route`를 만들지 않는다.

### Collection Item Management

| Method | Path | 목적 | 권한 |
| --- | --- | --- | --- |
| GET | `/api/v1/knowledge/collections/{collection_id}/items` | linked KB item 목록 | `collection.read` |
| POST | `/api/v1/knowledge/collections/{collection_id}/items` | KB link | private: `collection.manage` + KB `manage` 또는 `catalog_manage`; public: Organization manager + acknowledgement |
| DELETE | `/api/v1/knowledge/collections/{collection_id}/items/{item_id}` | KB unlink | private: `collection.manage` + KB `manage` 또는 `catalog_manage`; public: Organization manager + acknowledgement |
| PATCH | `/api/v1/knowledge/collections/{collection_id}/items/reorder` | deterministic rank 변경 | private: `collection.manage` 또는 `catalog_manage`; public: Organization manager + acknowledgement |
| GET | `/api/v1/knowledge/collections/{collection_id}/link-candidates` | link 가능한 KB 후보 | 해당 membership mutation 권한의 safe 후보만 반환 |

`GET /items`, link와 reorder 성공 response는 `items`, opaque `order_revision`, `reorder_supported`, optional fixed `safe_reason_code`를 포함하고 항상 최신 전체 ordered item projection을 반환한다. 각 item은 `item_id`, `knowledge_base_id`, safe label, lifecycle/sync state, rank, caller action flags만 포함한다. Safe label은 유효한 `KnowledgeBase.safe_metadata.safe_label`, display-policy-approved source safe label, caller가 독립 KB `read`를 통과한 manual KB `name` 순으로 선택하고, 모두 사용할 수 없으면 generic `Knowledge Base`를 반환한다. Domain `catalog_manage`만으로 raw manual KB `name`을 fallback하지 않으며 link-candidate response도 같은 projection을 사용한다. `can_use_kb=false`인 item이 보일 수 있지만, 이는 runtime retrieval 가능성을 의미하지 않는다. Standalone GET은 `collection.read`를 요구하지만 link/reorder 성공 응답은 완료한 mutation authority를 다시 확인한 safe management projection이므로 별도 `read` grant를 만들지 않는다. Link/unlink는 같은 organization KB만 허용하며 archived/deleted KB는 link 대상에서 제외한다. Private Collection membership은 `collection.manage` + KB `manage`, 또는 domain `catalog_manage`로 관리할 수 있다. Public Collection의 link/unlink/reorder는 visibility 변경과 같은 public exposure mutation이므로 Organization manager와 `acknowledged_public_runtime_exposure=true`를 요구한다. Source identity/connector Collection 또는 source-managed child가 연관된 public link/reorder는 approval primitive 부재 상태에서 `source_public_exposure_required`로 차단한다. Duplicate link는 MVP에서 idempotent success로 처리할 수 있다. Link request의 optional `rank`는 legacy caller 호환용 deprecated field이며 서버는 값을 무시하고 Collection lock 아래 끝에 append한 뒤 전체 rank를 연속값으로 정규화한다.

Reorder request는 empty Collection을 포함한 현재 전체 item을 `{item_id, rank}`로 보내고 `expected_order_revision`을 반드시 포함한다. Item id와 rank는 각각 unique이고 rank는 정확히 `0..N-1`이어야 한다. 서버는 Collection과 membership row를 잠근 뒤 current revision, 현재 전체 item set과 request를 비교한다. Stale revision, 누락·추가 item 또는 concurrent link/unlink는 어떤 rank도 바꾸지 않는 safe `409`다. 같은 순서의 no-op은 새 audit를 만들지 않는다. 초기 관리 surface는 item 500개 이하만 reorder하며 초과 response는 `reorder_supported=false`, `safe_reason_code=item_reorder_limit_exceeded`로 고정한다. `order_revision`은 권한이나 조회 capability가 아니다.

### Collection Sync Jobs (MBA-265)

MBA-265는 KC `sync` action과 domain `sync_manage`를 durable asynchronous job에 연결한다.
초기 실행 대상은 active Manual Collection에 연결된 active/non-source-managed KB 중 legacy
`documents` row가 정확히 한 개이고 그 문서가 DB type인 document-level KB다. DB 문서와 FILE
또는 다른 DB 문서가 한 KB에 함께 있는 legacy multi-document KB, API child, source-managed
child는 실행하지 않는다. 신규 connector protocol이나 source-managed sync를 포함하지 않는다.

Collection management response의 `can_sync`는 caller 권한이고 `sync_supported`는 현재 adapter가
해당 Collection의 현재 child source 구성을 실행할 수 있는지 나타내는 safe boolean이다.
Projection과 POST는 같은 canonical eligibility scan을 사용하고 UI는 두 값이 모두 참일 때만
실행 버튼을 활성화한다. 이 boolean은 source/connection identity나 unsupported target count를
공개하지 않는다.

| Method | Path | 목적 | 권한 |
| --- | --- | --- | --- |
| POST | `/api/v1/knowledge/collections/{collection_id}/sync-jobs` | KC sync job 생성 또는 기존 single-flight job 재사용 | Organization manager, Collection `sync`, domain `sync_manage` |
| GET | `/api/v1/knowledge/collections/{collection_id}/sync-jobs/latest` | 현재 caller에게 허용된 최신 job safe projection | 요청 endpoint와 같은 current authority |
| GET | `/api/v1/knowledge/collections/{collection_id}/sync-jobs/{job_id}` | 특정 job safe projection | 요청 endpoint와 같은 current authority |

POST는 canonical UUID 형식의 `Idempotency-Key` header를 필수로 받는다. 서버는 원문을
response/audit에 반사하지 않고 SHA-256 hash로만 저장한다. 같은 organization, Collection,
key의 요청은 기존 job을 반환하고, 다른 key라도 queued/running job이 있으면 active job을
재사용한다. Accepted/reused job은 `202`와 다음 safe envelope를 반환한다.

```json
{
  "job": {
    "job_id": "00000000-0000-0000-0000-000000000000",
    "collection_id": "00000000-0000-0000-0000-000000000000",
    "status": "queued",
    "progress": "none",
    "safe_reason_code": null,
    "retryable": true,
    "requested_at": "2026-01-01T00:00:00Z",
    "started_at": null,
    "completed_at": null
  },
  "reused": false,
  "dispatch_deferred": false
}
```

`status`는 `queued`, `running`, `succeeded`, `partially_failed`, `failed`, `cancelled`로
제한한다. `progress`는 `none`, `started`, `progressing`, `most`, `complete` 중 하나다.
Response에는 job item, KB/document/source identity, exact total/success/failure count, raw
processor/connector error, connection/config/SQL/credential field를 추가하지 않는다. 알 수 없는
내부 reason은 `sync.internal_error`로 일반화한다.

Resource hiding은 active organization 밖 Collection/job 또는 Collection/job mismatch를
`404 resource.hidden`으로 처리한다. Same-scope visible Collection의 sync authority 부족은
`403 permission.denied`다. Archived/deleted/source-managed/system-managed/unsupported source는
mutation 전에 safe `409 policy.blocked` 또는 `sync.not_supported`로 닫는다. Sync 가능한 DB
target이 없으면 `409 sync.no_eligible_targets`, target cap 초과는 `409 sync.target_limit_exceeded`
를 사용하며 child identity와 exact count를 반환하지 않는다. 이 세 sync policy code만 error
code로 승격하고 알 수 없는 reason은 `409 policy.blocked`와 `sync.internal_error` projection으로
일반화한다.

Gateway는 job/audit/Collection pending commit 뒤 `workflow.knowledge_collection_sync.execute`
task를 발행한다. Publish 실패는 raw broker 오류를 반환하지 않고 `dispatch_deferred=true`인
queued job을 유지한다. Recovery task가 due/stale job을 다시 발행하므로 API caller가 새 key로
반복 요청할 필요가 없다.

Legacy DB connection은 organization column이 없으므로 worker의 organization authority gate와
별도로 Connection Use Resolver가 `connection.user_id == execution subject user_id`와 지원 DB
type을 검증한다. 문서당 source row limit은 1,000으로 상한 처리한다. Connection identifier,
selection/SQL, credential과 processor 원문 오류는 job response·task result·audit·log에 포함하지
않는다.

DB processor 결과에는 문서에 저장된 flat `selection_mode`, `chunk_range`, `keyword_filter`를 기존
ingestion과 같은 selection helper로 적용한다. 선택 결과가 비거나 malformed이면 새 active
version으로 전환하지 않고 safe configuration failure로 닫아 기존 active ready version을 유지한다.

### Collection Permission Management

| Method | Path | 목적 | 권한 |
| --- | --- | --- | --- |
| GET | `/api/v1/knowledge/collections/{collection_id}/permissions` | permission grant 목록 | `collection.manage`, domain `permission_delegate`, 또는 organization manager |
| GET | `/api/v1/knowledge/collections/{collection_id}/delegation-subjects` | bounded active Team/User safe 대상 page | permission 변경과 동일 |
| POST | `/api/v1/knowledge/collections/{collection_id}/permissions` | team/user 단일 action grant | permission 변경과 동일 |
| POST | `/api/v1/knowledge/collections/{collection_id}/permissions/bundles` | role bundle을 explicit action row로 원자 적용 | permission 변경과 동일 |
| POST | `/api/v1/knowledge/collections/{collection_id}/permissions/bundles/revoke` | bundle action 집합의 explicit row를 원자 회수 | permission 변경과 동일 |
| DELETE | `/api/v1/knowledge/collections/{collection_id}/permissions/{permission_id}` | grant revoke | permission 변경과 동일 |
| POST | `/api/v1/knowledge/collection-permissions/bulk-bundles` | 같은 subject/bundle을 1~50개 Collection에 원자 grant/revoke | 모든 target에 permission 변경 authority |

단일 grant request는 `subject_type=team|user`, `subject_id`, `permission_action=read|route|manage|sync`만 허용한다. Bundle request의 `role_bundle`은 `viewer`, `workflow_router`, `maintainer`, `sync_operator`이며 각각 ADR-0034의 explicit action 집합을 한 transaction에서 upsert한다. 별도 role row나 inheritance를 만들지 않는다. Bundle revoke는 저장된 role을 찾지 않고 현재 존재하는 매핑 action row만 삭제한다. 따라서 Maintainer(`read+manage`)를 부여한 뒤 Viewer(`read`)를 회수하면 `manage` row는 유지되며 UI도 이를 다시 Maintainer role로 추론하지 않는다. 없는 row의 회수는 idempotent unchanged다. Domain delegator의 self/own-Team grant는 `409 policy.blocked`로 차단하고, 마지막 manage 경로 회수는 safe denial 또는 Organization manager recovery를 요구한다.

Delegation subject query는 `subject_type=team|user`를 필수로 받고 optional `query`(정규화된 safe prefix, 최대 100자), opaque `cursor`, `limit`(기본 25, 최대 50)를 사용한다. Response는 `subjects[{subject_type, subject_id, subject_safe_label}]`와 optional `next_cursor`만 반환한다. 서버는 endpoint별 authority를 먼저 검증한 뒤 current organization의 active Team 또는 active member User를 UUID keyset으로 `limit + 1` 조회한다. Team/User name만 검색하고 email, login principal, raw source identity와 total count는 검색하거나 반환하지 않는다. 같은 page 계약을 Organization manager 전용 `/api/v1/knowledge/domain-delegation-subjects`에도 적용하며 cursor는 subject type과 정규화된 query가 바뀌면 거부한다.

Bulk bundle request는 `collection_ids`(unique, 1~50), `operation=grant|revoke`, `subject_type`, `subject_id`, `role_bundle`을 받는다. 서버는 UUID 정렬 순서로 Collection을 잠그고 모든 target의 organization scope, permission authority, self/own-Team grant 차단과 last-manage revoke 조건을 mutation 전에 검증한다. Actor가 모든 target의 effective `manage`를 가진 경우 resource authority를 domain `permission_delegate`보다 우선하고, 일부 target만 `manage` 가능한 경우 domain-delegate self/own-Team 차단을 유지한다. 하나라도 실패하면 permission과 audit 전체를 rollback한다. Grant는 active subject만 허용하고 revoke는 inactive Team 또는 removed/deactivated User의 기존 row 정리를 허용한다. Response는 `operation`, `subject_type`, `role_bundle`, `target_count_bucket`, `changed_count_bucket`, `unchanged_count_bucket`만 반환하고 Collection/subject id, label 또는 실패 target index를 반복하지 않는다.

### Public Visibility

```text
POST /api/v1/knowledge/collections/{collection_id}/visibility
```

Request:

```json
{
  "visibility": "public",
  "acknowledged_public_runtime_exposure": true
}
```

MVP에서 public/private visibility 전환은 organization manager만 허용한다. Public 전환에는 explicit acknowledgement가 필요하다. 전환 전 summary는 linked KB count bucket, active KB count bucket, safe sensitive-content warning, anonymous public-only runtime 영향 요약만 포함한다. Raw KB title/path/url, hidden KB id/name, exact denied count는 포함하지 않는다.

`safe_metadata["visibility"] == "public"`은 anonymous public-only runtime의 collection candidate inclusion flag다. 인증 사용자 KB `use`, source ACL requester authorization, final evidence policy를 대체하지 않는다.

Source-managed Collection 또는 source-managed KB가 anonymous public-only 후보가 되려면 collection public visibility와 별도 source/connector public exposure approval을 모두 통과해야 한다. Approval row는 `approval_scope`, scope별 target id, `approved_by`, `approved_at`, `expires_at`, `source_identity_id` 또는 connector/source target, `revocation_behavior`, reverification cadence, explicit acknowledgement를 저장해야 한다. `approval_scope`와 target field가 일치하지 않거나 expiry/reverification/revocation 조건이 빠진 broad connector-wide approval은 public-only 후보에서 제외한다.

MBA-176에서 source/connector public exposure approval primitive가 아직 구현되지 않은 경우, source-managed Collection은 manual child KB만 포함해도 anonymous candidate stream을 만들지 않고 source-managed KB도 public collection에 연결되어 있어도 anonymous public-only 후보로 승격하지 않는다. Deployment preflight와 runtime availability preview는 이를 warning이 아니라 `source_public_exposure_required` blocked reason으로 반환한다.

### Workflow Runtime RAG Execution Subject

Workflow runtime에서 RAG를 호출하는 API나 내부 service call은 server-resolved execution audience를 명시한다. MBA-232 contract는 interactive/current user를 `AuthenticatedAudience`로, subject 부재를 synthetic identity 없는 `AnonymousPublicAudience`로 표현한다. 승인된 service account/operator audience는 별도 lifecycle/approval 계약 전까지 MBA-232 closed union에 포함하지 않는다. Subject가 없으면 retrieval은 실패가 아니라 anonymous public-only로 낮아진다.

`/api/v1/deployments/{deployment_id}/run`의 `internal_chatbot`은 current user를 user execution subject로 주입하고 Runtime은 해당 user의 KB permission/source ACL을 다시 검사한다. `/api/v1/run-public/{url_slug}`의 공개 `chatbot`은 subject를 주입하지 않으며 `internal_chatbot`은 public surface에서 허용하지 않는다.

필수 계약:

| 항목 | 규칙 |
| --- | --- |
| `execution_subject` | Workflow run context에서 명시적으로 resolve한 current user. 있으면 `AuthenticatedAudience`의 KB permission과 materialized source authorization 평가 기준 |
| `subject_resolution_reason` | interactive user 또는 anonymous public-only 같은 sanitized reason. Service account/assigned operator는 별도 승인 전 MBA-232에 입력할 수 없다 |
| `workflow_owner_id` | 감사/소유권 표시에는 사용할 수 있지만, 명시 설정 없이 retrieval 권한 fallback으로 사용하지 않는다 |
| missing subject | Anonymous public-only retrieval. Active public collection에 연결된 active KB만 후보로 남기며 silent owner/user_id fallback은 금지 |
| ambiguous or unsupported subject | Private retrieval fail-closed. Anonymous downgrade가 안전하게 판정되지 않으면 safe no-result 또는 failure policy를 따른다 |

모든 운영 RAG mode는 `execution_subject` 기준의 KB permission/source ACL/final evidence gate 또는 anonymous public-only gate를 통과해야 한다. `general RAG`는 authorized/public resource 안에서 넓게 검색하는 mode이고, `task-aware` 또는 `permission-scoped RAG`는 authorized/public resource 안에서 후보를 더 정밀하게 줄이는 mode다.

### LLM node RAG 품질 옵션

Workflow Builder가 LLM node의 RAG 옵션을 구성할 때 다음 목표 옵션을 제안할 수 있다. 이 옵션은 전역 에이전트 기능이나 독립형 RAG 실행 노드 기능이 아니라 생성된 LLM node의 retrieval/generation 정책이다.

| 필드 | 의미 |
| --- | --- |
| `query_rewrite_mode` | `off`, `template`, `llm_assisted` 후보. MBA-105 runtime은 `off` 기본값과 `template` opt-in만 구현한다. Rewrite는 user query와 safe skill/template만 입력으로 사용하고, permission/source ACL candidate scope를 넓히지 않는다 |
| `evidence_sufficiency_policy` | `minimum_evidence`, `strict_citation` 후보. 운영 runtime에서는 `off`를 허용하지 않는다. 근거가 부족하면 safe no-result 또는 insufficient-evidence 응답으로 닫는다 |
| `rag_failure_policy` | 근거 부족 또는 실행 시점 availability 실패를 처리하는 정책. MBA-105 runtime의 구현 기본값은 `safe_no_result`이며, `fail_node`는 node 실패로 닫는다. Permission/source ACL failure는 hidden-safe reason만 허용한다 |
| `source_tier_policy` | Source-of-Truth Tier를 authorized evidence 안에서 ranking, tie-break, conflict resolution hint로 사용할지 나타내는 목표 옵션. Baseline candidate enum은 `legal_regulation`, `contract`, `company_policy`, `adr_decision`, `official_documentation`, `semantic_definition`, `operational_runbook`, `curated_query_corpus`, `conversation_or_thread`이며 최종 enum은 Legal/Compliance review에서 확정한다 |

현재 workflow graph의 LLM node data는 기존 camelCase convention을 유지하므로 구현 필드는 `queryRewriteMode`, `queryRewriteTemplate`, `evidenceSufficiencyPolicy`, `ragFailurePolicy`, `sourceTierPolicy`다. 공식 계약에서 snake_case로 설명한 값과 의미는 같으며, 공개 API shape를 새로 만들 때는 별도 API review에서 casing을 고정한다.

`query_rewrite_mode`가 켜져도 raw rewritten query는 raw prompt와 유사한 민감 입력으로 취급한다. Durable audit/trace/usage metadata에는 rewrite 적용 여부, 전략, safe template id 같은 summary만 저장한다.

`llm_assisted` query rewrite는 LLM 호출이므로 별도 승인 전까지 구현하지 않는다. 승인 시 execution subject, generation model/credential, credential `use` 권한, usage/cost 기록, timeout, token/cost budget, 실패 시 fallback을 확정해야 한다. Workflow runtime에서 실행되면 rewrite LLM call도 workflow 실행 주체 기준의 권한과 비용 기록을 따라야 한다.

## Response Model

### Knowledge Base Detail

`GET /api/v1/knowledge/{kb_id}`의 `documents[].chunk_count`는 물리적으로 저장된 모든 chunk row 수가 아니라, LLM RAG 후보 판단에 사용할 수 있는 retrieval-visible chunk 수다. Document-level KB에서 active ready document version이 있으면 해당 version에 연결된 chunk만 센다. Active version pointer가 아직 없는 전환기 legacy KB는 `document_chunks.document_version_id IS NULL`인 legacy unversioned chunk만 fallback으로 셀 수 있다. `documents.status`가 `completed`가 아니거나 active version이 `ready`가 아닌 pre-finalized/indexing/failed/superseded artifact는 `chunk_count`와 selectable-ready 판단의 근거가 아니다.

이 값은 KB 상세 화면과 LLM node Knowledge Base picker가 같은 ready/not-ready 경계를 쓰도록 제공하는 safe availability signal이다. Raw source title/path/url, hidden document count, 권한 없는 document 존재 여부, non-allowlisted metadata는 포함하지 않는다.

`documents[].meta_info`와 `GET /api/v1/knowledge/{kb_id}/documents/{document_id}`의
`meta_info`는 동일한 fail-closed projection을 사용한다. 허용 후보는 bounded
`progress`/`processing_progress`, safe processing timestamp,
`processing_recovered_from_timeout`, bounded `chunking_mode`/`strategy`/
`upload_method`와 non-negative finite numeric `cost_estimate`다. 각 field는 기대
type, 범위, 길이 또는 enum 검증을 통과해야 한다. `api_config` 전체와
`url_encrypted`, `headers_encrypted`, `body_encrypted`, `connection_id`,
`source_identity_id`, connector/source ref, `db_config`, connection label/config,
unknown key/nested object는 반환하지 않는다. 내부 저장값이 encrypted ciphertext여도
API-safe metadata가 아니며, 새 field는 allowlist와 negative test가 함께 추가되기
전까지 응답에서 생략한다.

### Citation Identity

목표 citation field:

| 필드 | 의미 |
| --- | --- |
| `citation_id` | 이 응답 안에서 사용하는 opaque citation identity |
| `knowledge_base_id` | Document-level KB identity |
| `document_version_id` | Evidence로 사용한 active version 또는 historical version identity |
| `chunk_id` | Evidence chunk |
| `collection_id` | Collection을 통해 선택됐을 때의 선택적 attribution |
| `safe_source_ref` | 선택적 protected/HMAC source reference. Raw source id/url/path/principal을 대체하며 display policy와 protected source identity boundary를 따른다 |
| `rank` / `score` | Retrieval ranking summary |
| `metadata_summary` | Redaction-safe allowlist만 허용 |
| `content_preview` | 선택적 user-facing redacted/capped preview. Durable audit/trace/usage summary에는 기본 저장하지 않는다 |

### Skill provenance

Skill을 사용한 workflow draft, LLM node의 RAG 옵션, workflow test run은 다음 redaction-safe provenance를 선택적으로 반환할 수 있다.

| 필드 | 의미 |
| --- | --- |
| `skill_id` | Provider-neutral Knowledge Skill identity |
| `skill_version` | 사용한 skill version |
| `skill_freshness_state` | `fresh`, `stale`, `review_required`, `deprecated` 같은 freshness state |
| `skill_eval_status` | 평가 통과/주의/미실행 같은 safe eval 상태 |
| `source_tier` | 정책 문서, ADR/decision record, semantic definition, curated query corpus 등 safe source-of-truth tier |
| `provenance_summary` | raw source name/path/url 없이 source tier, validation checklist, safe source/version ref만 포함한 요약 |

Skill provenance는 source of truth를 대체하지 않는다. 실행 시점 citation은 계속 KB/document version/chunk/decision record 같은 근거 resource를 가리켜야 한다.

### Partial Result

Operational partial failure는 반환되는 모든 evidence가 KB permission, source ACL, final policy gate를 통과한 경우에만 safe partial result로 반환할 수 있다.

허용되는 safe marker:

- `partial_result=true`
- bucketed failed candidate count
- `some_sources_unavailable` 같은 safe reason summary
- retryability flag

기본 금지 항목:

- exact failed KB id
- exact hidden/denied count
- unavailable document를 추론하게 하는 source distribution
- raw exception message

### RAG Strategy Summary

A/B 테스트, 비용 최적화, trace side panel은 다음 redaction-safe summary만 사용할 수 있다.

| 필드 | 의미 |
| --- | --- |
| `retrieval_strategy` | `general`, `permission_scoped`, `task_aware`, `metadata_aware`, `hierarchical` 같은 실행 전략 |
| `rag_mode` | UI/실행 설정에 표시되는 RAG mode |
| `selected_collection_count` / `selected_kb_count` | authorized subset 기준 count. hidden/denied resource를 추론할 수 있으면 bucket 처리 |
| `retrieved_chunk_count` / `citation_count` | 실제 evidence로 사용된 chunk/citation 수 |
| `context_token_estimate` | RAG context token 추정치 |
| `retrieval_latency_ms` | Retrieval latency |
| `permission_filter_applied` | KB permission/source ACL gate 적용 여부. 운영 실행에서는 항상 true여야 한다 |
| `policy_result` | Final evidence policy 결과 |
| `partial_result` | Safe partial result 여부 |
| `safe_exclusion_summary` | 정확한 문서명/ID 없이 bucketed reason만 제공 |
| `evidence_sufficient` | Evidence sufficiency 결과. 권한 없는 resource 존재를 암시하지 않는 boolean 또는 safe status만 허용 |
| `insufficiency_reason` | `no_evidence`, `low_score`, `insufficient_citation`, `policy_filtered`, `operational_partial` 같은 safe reason class |
| `query_rewrite_applied` | Query rewrite 적용 여부 |
| `query_rewrite_strategy` | `template`, `llm_assisted` 같은 safe strategy summary. Raw rewritten query는 포함하지 않는다 |

Collection-derived candidate가 하나라도 있는 실행은 `authorized_kb_count`와
`selected_kb_count` exact 값을 생략하고 각각의 `_bucket` field만 저장한다. Candidate
수에서 유도되는 actual `fanout_concurrency`도 생략한다. Collection-derived evidence는
child KB별 결과 경계를 재구성할 수 있는 per-KB `rank`도 생략한다. 대신 최종 전역
정렬·dedupe·top-k 이후 1부터 부여한 `evidence_rank`는 result와 품질 trace에 저장할 수
있다. 이 값은 해당 invocation의 최종 evidence 순서이며 child KB 경계를 뜻하지 않는다.
Direct-only 실행은 current user가
명시적으로 선택하고 authorization된 KB의 기존 exact operational summary를 유지할 수 있다.
| `source_tier_used` | Authorized evidence 안에서 사용한 safe source tier summary |
| `evidence_count` / `min_score_bucket` | 실제 evidence 기준 count와 bucketed score summary. Hidden/denied count는 포함하지 않는다 |
| `skill_id` / `skill_version` | 사용한 Knowledge Skill 식별자와 version. 표시 가능 여부는 skill display policy를 따른다 |
| `skill_freshness_state` / `skill_eval_status` | Skill freshness/eval summary. Raw eval fixture나 hidden source ref는 포함하지 않는다 |

이 summary에는 raw chunk content, raw source title/path/url, raw ACL row, 권한 없는 KB/document id, exact denied count, raw rewritten query, raw prompt/completion/provider response를 포함하지 않는다.

## Permission And Error Contract

| Mode | 필수 gate |
| --- | --- |
| Auto collection mode | active organization, generation model/credential visibility, credential `use`, verified credential-model relation, listing surface의 collection `read`, router scope의 collection `route`, KB use helper, source-managed KB의 source ACL/requester authorization, final evidence policy |
| Explicit KB mode | active organization, generation model/credential visibility, credential `use`, verified credential-model relation, KB visibility/resource hiding, KB use helper, source-managed KB의 source ACL/requester authorization, final evidence policy |
| 빌더 단계 Knowledge Skill mode | active organization, skill visibility, skill safe metadata display, skill freshness/eval gate. Skill visibility는 collection route, KB permission, source ACL gate를 대체하지 않는다 |
| 실행 시점 LLM node의 RAG 옵션 | execution subject가 있으면 해당 subject 기준 KB permission/source ACL gate와 final evidence policy. execution subject가 없으면 anonymous public-only gate와 final evidence policy. Explicit KB mode는 collection route를 생략할 수 있지만 KB visibility/use/source ACL/final evidence gate 또는 anonymous public-only gate를 생략하지 않는다. 빌더 단계 skill selection이나 workflow 작성자 권한을 실행 시점 data access로 전파하지 않는다 |
| MBA-232 runtime selected Collection | explicit authenticated/anonymous audience, 명시 selected active Collection, authenticated `route` + child KB `use` + materialized source provenance 또는 anonymous public membership, active/ready KB, deterministic budget. Missing/empty Collection IDs는 fallback 없음 |
| Anonymous public-only Workflow RAG | active organization, active Knowledge Collection with `safe_metadata.visibility == "public"`, active linked manual KB, final evidence policy. Public exposure approval primitive가 없는 MBA-232에서는 source-managed 후보를 모두 제외한다. Workflow owner/deployment owner/app creator/`user_id` fallback 금지 |
| Collection management | `collection.manage`; 기존 KB linking에는 `kb.manage`도 필요 |
| Collection sync/remediation | `collection.sync` 또는 organization/admin operation policy. Raw content access를 의미하지 않는다 |
| Raw content/export | Dedicated raw/compliance endpoint only. Raw/compliance permission, source-managed KB의 fresh source ACL, retention/legal-hold/purge check, response 전 raw access audit이 필요하다. 최종 enum 이름은 RBAC ADR에서 확정한다 |

Response summary와 citation은 허용된 KB/document version/chunk identity, citation id, direct KB-local `rank`, 최종 `evidence_rank`, score, hierarchy path, safe filename/display label, safe metadata summary, policy result, partial marker, bucketed count, retryability, opaque correlation/request id 같은 redaction-safe field만 포함할 수 있다. Collection-derived evidence에는 child identity, optional collection id, KB-local `rank`를 포함하지 않는다.

Raw source id/url/path/title, raw source ACL, raw principal, raw source exception, raw query, raw rewritten query, raw answer, raw prompt/completion, raw provider response, raw skill body, hidden skill source reference, content preview, credential value는 durable audit/trace/usage metadata에 저장하지 않는다. `content_preview`는 user-facing response 전용이며 redacted/capped 상태로만 반환하고 durable summary에서 제외한다. Raw artifact를 활성화하더라도 dedicated raw/compliance flow에서만 노출하며 Agent answer, retrieval context, prompt construction, SSE stream에는 사용하지 않는다. Raw/compliance access audit은 safe reference, decision, reason code, retention/legal-hold summary, request/correlation identifier만 저장한다.

### Resource Hiding / No-result / Evidence Insufficiency Matrix

Resource hiding/no-result/evidence insufficiency API matrix는 [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)의 safe hidden/no-result/partial-result baseline과 [implementation_baseline.md](implementation_baseline.md)의 matrix를 따른다. MBA-105 구현은 아래 safe envelope를 testable contract로 사용한다.

- Active organization scope 밖, organization mismatch, deleted/archived hidden resource, requester source authorization denied 또는 source ACL stale/unmapped/ambiguous/unverified/revoked 상태가 존재를 드러낼 수 있는 경우.
- Scope 안에서 이미 보이는 resource의 KB `use` 또는 credential `use` 권한 부족.
- 허용된 evidence candidate resolution 이후 policy block.
- Permission/source ACL gate를 통과한 뒤 발생한 source/connector operational failure.
- Auto mode에서 권한 있는 candidate가 없는 경우.
- Anonymous public-only mode에서 public candidate가 없는 경우.
- MBA-232 snapshot/repository/authorization infrastructure failure. 이 경우 candidate partial result를 만들지 않고 retrieval/provider 전에 fixed safe retryable error로 종료한다.
- 권한 gate 이후 evidence가 없는 경우.
- Evidence score, citation coverage, source tier policy 기준으로 근거가 부족한 경우.
- Evidence sufficiency policy가 `policy_filtered` 또는 `operational_partial` reason을 반환하는 경우.

기준은 hidden KB/version/chunk identity를 드러내는 answer run, `rag.retrieve` success audit, citation id, trace metadata, durable summary를 만들지 않는 것이다. Scope 밖, organization mismatch, hidden deleted/archived resource, existence inference가 가능한 requester source authorization denied 또는 source ACL stale/unmapped/ambiguous/unverified/revoked 상태는 resource-hidden/404 또는 safe no-result로 닫는다. MBA-232 candidate resolver의 DB/snapshot/authorization infrastructure failure에는 partial result를 허용하지 않는다. Partial result는 complete candidate authorization 이후 downstream retrieval에서 발생한 operational failure에만 허용한다.

JSON/pre-stream error envelope는 `error.code`, `error.reason_code`, `error.message`, optional `correlation_id`, optional `retryable`만 포함한다. Hidden/resource-hidden path의 `message`는 generic text를 사용하고 target KB id/name/source path/count를 포함하지 않는다. Hidden/resource-hidden path의 external `reason_code`는 `resource.hidden`으로 일반화하며, `source_authorization.denied` 또는 `source_acl.stale/unmapped/ambiguous/unverified/revoked` 같은 세부 reason은 이미 존재가 authorized context에서 보이는 resource, admin/remediation context, 또는 내부 safe audit/trace allowlist에서만 사용할 수 있다. Stream 시작 후에는 HTTP status를 바꾸지 않고 `event: error` terminal event에 같은 semantic `code`/`reason_code`/`correlation_id`/`retryable` allowlist를 넣는다.

Safe no-result/insufficient-evidence response는 `status`, `evidence_sufficient=false`, `insufficiency_reason`, optional `partial_result`, optional bucketed failed candidate count, safe retryability만 포함한다. Hidden candidate id/name/count/source distribution은 포함하지 않는다.

현재 구현된 standalone single-KB `/api/v1/rag/agent/answer`와 `/api/v1/rag/agent/answer/stream` lifecycle, same-scope permission preflight blocked status, trace/usage correlation 경계는 [ADR-0013](../../decisions/ADR-0013-rag-answer-trace-usage-correlation-boundary.md)을 따른다. Source-managed KB, auto collection, multi-KB mode의 target resource hiding 확장은 [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)의 provisional baseline을 따른다. 이 기준은 ADR-0013의 현재 단일 KB 계약을 재정의하지 않는다.

## Workflow User Citation Sidecar

Workflow/Chatbot 최종 응답은 사용자 표시용 Citation이 있을 때만 아래의 additive reserved sidecar를 포함할 수 있다. 이 계약은 privileged lineage Citation과 별개이며 내부 resource identity를 제공하지 않는다.

```json
{
  "__nodease_citations": {
    "version": 1,
    "items": [
      {
        "citation_id": "evidence-1",
        "evidence_rank": 1,
        "label": "공통 휴가 정책",
        "page_number": 3,
        "section": "연차 신청",
        "content_preview": null
      }
    ]
  }
}
```

- item은 최대 8개이며 `citation_id`는 응답 내 전역 `evidence_rank`와 일치한다.
- `content_preview`는 `detailed` mode에서만 최대 300자의 정제된 prompt evidence를 담는다. 공통 fail-closed redaction을 먼저 적용하므로 secret/PII 검출 또는 redaction 실패 시 preview를 생략한다.
- `knowledge_base_id`, `collection_id`, `document_id`, `document_version_id`, `chunk_id`, raw filename/path/URL, score와 child-local rank는 금지한다.
- sidecar는 서버가 만든 projection만 추가한다. legacy final output 또는 stream node-result map에 같은 key가 이미 있으면 기존 output을 덮어쓰거나 제거하지 않고 Citation sidecar만 생략한다.
- Citation이 없거나 설정이 `hidden`이면 sidecar를 생략한다. sidecar 생성 실패는 답변 자체를 실패시키지 않는다.
- 이 sidecar는 사용자 응답용이며 durable run output과 일반 audit/trace payload에는 저장하지 않는다.

## Trace And Audit

- Multi-KB 또는 collection-routed answer는 `trace_payloads.rag_answer_run_id`나 `llm_usage_logs.rag_answer_run_id`를 추가하지 않는다.
- Standalone Agent answer lifecycle은 [ADR-0013](../../decisions/ADR-0013-rag-answer-trace-usage-correlation-boundary.md)에 따라 `rag.answer.*`와 `rag_answer_runs`를 사용한다.
- Workflow runtime RAG evidence는 계속 `trace_payloads.payload_kind='rag.retrieval'`를 사용할 수 있다. Standalone answer는 summary/citation을 RAG-owned record에 저장한다.
- Trace side panel에는 RAG strategy summary, citation id, 허용된 KB/document version/chunk identity, direct KB-local rank, 최종 evidence rank/score, safe metadata summary, token/cost/latency summary만 표시한다. Collection-derived evidence에는 child identity와 KB-local rank를 표시하지 않는다. 권한 없는 문서명/ID, raw source metadata, raw content, raw prompt/completion은 표시하지 않는다.
- Skill usage summary는 workflow draft, LLM node의 RAG 옵션, workflow test run, RAG strategy comparison에서 skill id, skill version, freshness state, eval status, safe source tier, safe provenance refs만 포함할 수 있다. Raw skill body, raw source title/path/url, hidden source refs는 표시하지 않는다.
