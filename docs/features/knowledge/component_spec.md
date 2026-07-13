# Knowledge Component Spec

Status: Draft
MBA-105 구현 baseline, 운영 기본값, permission helper output, active version finalization, resource hiding matrix는 [implementation_baseline.md](implementation_baseline.md)를 따른다. Workflow RAG에서 `execution_subject`가 없는 MVP public-only runtime은 [ADR-0018](../../decisions/ADR-0018-workflow-rag-anonymous-public-only-runtime.md)을 따른다. MCP/API source connector와 incremental sync 경계는 [ADR-0020](../../decisions/ADR-0020-knowledge-mcp-incremental-sync-boundary.md)을 따른다. Direct KB와 명시 selected Collection의 Workflow runtime candidate 해석은 [ADR-0036](../../decisions/ADR-0036-knowledge-runtime-candidate-resolution.md)을 따른다.

## Domain Components

| Component | 책임 | 경계 |
| --- | --- | --- |
| Knowledge Source Connector | Adapter policy를 통해 source item과 source ACL을 열거하고 가져온다. MCP/API source는 server-side allowlist operation으로만 호출한다 | mbased permission을 직접 결정하지 않고, LLM 임의 tool-use나 raw source direct fetch surface가 아니다 |
| OutboundEgressGuard | Knowledge/RAG source collection server-side outbound access 전에 network policy를 검증한다 | SQL/SSH/SaaS 의미를 구현하지 않으며, 별도 ADR 없이 모든 workflow runtime outbound를 포괄하지 않는다 |
| Protocol Adapter | Read-only probe, SQL/command deny, listing cap 같은 protocol-specific safe behavior를 수행한다 | 승인된 guard/client/dialer를 사용해야 한다 |
| Sync Scheduler / Worker | Lease, cursor, retry/backoff, dead-letter, tombstone, sync run state를 관리한다 | Raw source metadata를 노출하지 않고 safe state/reason summary만 낸다 |
| Source Identity Store | Protected/HMAC source identity reference와 tombstone matching을 관리한다 | User-facing document resource가 아니다 |
| Source Subject Mapping Store | Nodease execution subject와 source subject의 mapping state와 epoch를 관리한다 | `unmapped`, `ambiguous`, `stale`, `revoked` 상태는 private retrieval에서 fail-closed이며 raw principal을 user-facing surface에 노출하지 않는다 |
| Source Authorization Provenance Store | Source ACL fact를 requester authorization provenance와 freshness evidence로 materialize한다 | KB `use` grant 자체가 아니며 retrieval permission은 Knowledge Permission Helper가 two-gate로 평가한다 |
| Runtime Source Authorization Client | `check_access_batch` 또는 bounded `check_access` fallback으로 retrieval 실행 시 source 접근을 재확인한다 | Short-lived cache는 optimization일 뿐 권한 원천이 아니며, item/version별 key 없이 subject-level allow를 재사용하지 않는다 |
| Public Exposure Policy Store | Source-managed KB의 anonymous public-only 노출 승인, 만료, 회수, 재검증 상태를 관리한다 | Collection visibility flag만으로 source-managed KB를 public candidate로 만들지 않는다 |
| Content Safety Scanner | Source artifact의 file type allowlist, active content, archive cap, malware/content scan 결과를 평가한다 | Scan pass는 source ACL, KB permission, redaction, prompt-injection guard를 대체하지 않는다 |
| Parser Isolation Worker | PDF/Office/HTML/archive 같은 rich content를 least-privilege 또는 sandboxed 환경에서 text로 추출한다 | Macro, script, embedded object, executable payload, external reference를 실행하지 않는다 |
| Privacy/Redaction Service | PII/secret hard baseline과 output-target redaction을 위한 shared detector/masking engine을 제공한다 | Trace storage나 Knowledge lifecycle을 소유하지 않는다 |
| Canonical Normalizer | Source content를 추출, redaction, normalization해 canonical text/metadata를 만든다 | Chunk/embedding 생성 전에 Privacy/Redaction Service를 사용한다 |
| Raw Artifact Store | Compliance view용 optional protected raw source content store | RAG, embedding, prompt, router input, Agent answer stream에서 사용하지 않는다 |
| Ingestion Concurrency Guard | Same source item/document-level KB 처리의 owner-token lock, fencing token, advisory lock을 제공한다 | Lock TTL 만료 뒤 stale worker가 새 artifact를 finalize하거나 lock을 해제하지 못하게 한다 |
| Ingestion Pipeline | Document version, chunk, embedding artifact, external index entry를 생성한다 | 성공 전 active version을 바꾸지 않는다 |
| Active Version Finalizer | Transactional active version pointer swap, previous version `superseded` 표시, content_hash/fingerprint commit, outbox insert를 수행한다 | Fencing/recovery gate가 필요하며 hash만 먼저 commit하거나 pointer swap 후 outbox insert 전에 crash window를 만들지 않는다 |
| Artifact Cleanup Reconciler | DB state와 object storage/vector index/external artifact cleanup을 outbox 기반으로 맞춘다 | DB commit 전 physical delete를 수행하지 않고 retry 가능한 cleanup만 실행한다 |
| Knowledge Permission Helper | Collection `read`, collection `route`, KB use, source ACL freshness/requester authorization을 bulk 평가한다 | Router와 controller는 permission row가 아니라 helper 결과를 소비해야 한다 |
| Knowledge Administration Application | Organization manager의 domain grant/revoke, active subject grant validation, stale grant permission-row revoke와 transaction-bound audit를 조율한다 | Grant subject lock과 revoke permission-row lock을 분리하고 controller가 subject 활성 상태를 추정하지 않는다 |
| Workflow Runtime Knowledge Candidate Resolver | Direct KB와 명시 selected Collection을 current authenticated/anonymous audience, lifecycle/readiness, route/use/source gate로 해석하고 direct-first/Collection-round-robin 20-KB set을 만든다 | Shared pure policy + Workflow Engine application/port + PostgreSQL snapshot adapter다. Gateway Builder resolver를 import하지 않고 retrieval/provider를 호출하지 않는다 |
| Knowledge Collection Management Service | Manual Collection CRUD, item link/unlink/reorder, permission grant/revoke, visibility transition을 조율한다 | Controller에 business logic을 두지 않고, Collection 권한과 KB content 권한을 분리해서 검증한다 |
| Knowledge Document Response Projector | 내부 `documents.meta_info`에서 safe operational field만 allowlist projection한다 | Encrypted config, connection/source identifier, DB/source config와 unknown nested field를 API response로 전달하지 않는다 |
| Knowledge RAG Recommendation Adapter | `StructuredRequest` 기반 safe intent summary, node purpose summary, knowledge requirement, pending resolution reference를 받아 safe KB recommendation과 LLM node RAG option 후보를 만든다 | Raw natural language 전체를 받지 않고 권한 판단을 직접 하지 않는다. HTTP/serialized boundary에서는 `KnowledgeCandidateResolver`가 만든 server-issued reference만 사용하고, full safe candidate set 객체는 같은 backend 내부 service call에서만 ranking input으로 사용할 수 있다. 초기 구현은 `candidate_type=knowledge_base`만 반환하고 Collection은 safe summary metadata로만 제공한다 |
| Knowledge Skill Registry | Provider-neutral Knowledge Skill, version, owner/review state, freshness/eval status를 관리한다 | Skill은 빌더 단계 LLM node의 RAG 옵션 후보이며 권한 source나 source of truth가 아니다 |
| Source-of-Truth Catalog | 정책 문서, ADR/decision record, semantic definition, curated query corpus 같은 source tier와 safe reference를 관리한다 | Raw content나 hidden source identity를 router에 노출하지 않는다 |
| Skill Context Loader | 후속 target component로, 선택된 skill의 safe metadata와 workflow 생성 요청을 기반으로 필요한 skill body/checklist를 gate 통과 후 점진적으로 로드한다 | MBA-145 Agent Builder MVP에서는 Knowledge Skill body/checklist를 prompt context로 직접 로드하지 않는다. 전역 metadata 선노출과 raw skill resource 로드를 금지한다. 실행 시점 evidence는 별도 authorized retrieval로 가져온다 |
| Skill Evaluation/Regression Set | Golden question, eval result, freshness signal을 관리한다 | Eval fixture도 raw restricted content를 포함하지 않는다 |
| Skill Governance/Publication | Skill publish, review, deprecate, approval workflow의 policy boundary 후보 | 구체적인 authoring UI, Workflow Playground 연결, 승인 UX는 아직 확정하지 않는다. Code-bearing skill은 별도 sandbox/approval gate 전까지 publish할 수 없다 |
| Collection Router | Authorized safe candidate에서 collection/KB 후보를 선택한다 | Access control을 수행하지 않고 raw source ACL이나 hidden aggregate data를 받지 않는다 |
| Retrieval Orchestrator | 선택된 KB들에 대해 metadata/hierarchy retrieval을 실행하고 merge/rerank한다 | Authorized redacted evidence만 사용한다 |
| Audit/Trace Summarizer | Redaction-safe audit/trace/answer summary를 만든다 | Raw content/title/path/url은 제외하고, raw/compliance audit은 safe reference, decision, reason만 저장한다 |
| RAG Answer Retention Worker | Terminal answer run의 retention purge를 수행하고 aggregate audit을 남긴다 | requested/running row를 삭제하지 않고 동시 purge를 row lock/marker로 방지한다 |

### MBA-232 Runtime Candidate Resolver Boundary

구성요소는 다음으로 분리한다.

| Layer | 책임 | 금지 |
| --- | --- | --- |
| Shared pure contract/policy | explicit audience/request/snapshot/result, direct-first/round-robin/dedupe/budget, safe bucket | SQLAlchemy, FastAPI, Celery, Gateway/Workflow concrete import |
| Workflow Engine application use case/port | request validation, snapshot port 1회 호출, pure policy 적용, whole-resolution failure mapping | SQL query, Gateway response schema, provider/retrieval side effect |
| PostgreSQL outbound adapter | fresh `REPEATABLE READ, READ ONLY` transaction, selected Collection별 pre-window LATERAL cap, fixed transaction evaluation time, membership/readiness/permission/materialized provenance bulk projection | organization-wide discovery, live connector/source call, cross-invocation cache |
| Workflow Engine composition | session factory, adapter와 use case 조립 | LLM node business policy와 graph parsing |

Gateway의 기존 `KnowledgeCandidateResolver`는 Builder recommendation/deployment
preview 경계다. Missing Collection scope에서 route-safe subset 또는 direct-KB fallback을
사용할 수 있으나 MBA-232 runtime resolver에는 적용하지 않는다. Runtime
missing/empty Collection IDs는 Collection stream 0개다. Builder/preflight adapter,
Workflow graph와 LLM node/retrieval wiring은 MBA-233에서 연결한다.

Runtime audience는 `AuthenticatedAudience(organization_id, user_id)`와
`AnonymousPublicAudience(organization_id)`의 closed union이다. Anonymous audience에
owner/builder/deployment owner/credential principal/service account를 합성하지 않는다.
Source-managed authenticated 후보는 materialized `SourceAuthorizationProvenance`만
사용하고 live `check_access*`/cache를 호출하지 않는다. Public exposure primitive가
없는 동안 source-managed anonymous 후보는 모두 제외한다.

`KnowledgeCollectionItem`은 lifecycle을 갖지 않는다. Present row만 membership이고
Collection/child KB lifecycle과 KB readiness를 별도로 평가한다. Snapshot/repository/
authorization infrastructure failure는 partial candidate를 반환하지 않는 retryable
whole-resolution failure다. Budget cap은 successful safe warning이며 downstream
retrieval timeout과 구분한다.

### MBA-233 Workflow Collection Routing Integration

| Component | 책임 | 금지 |
| --- | --- | --- |
| Shared Workflow Knowledge Reference Parser | 두 graph list의 shape, canonical UUID, display snapshot, per-list 20 cap을 pure validation하고 configured order/deduped ID를 제공한다 | Graph mutation, silent slicing, permission/DB 조회 |
| Route-safe Collection Query Service | active organization/lifecycle, non-source-deleted sync state와 current editor effective `route`를 SQL query scope에 먼저 적용하고, authorized result를 정렬·제한한 뒤 UUID와 optional safe label만 projection한다 | 권한 확인 전 row cap, Management response 재사용, raw name/description/child count, runtime authorization |
| Workflow Knowledge Reference Service | Editable graph write 전에 direct KB active/non-source-deleted/retrieval-visible/effective `use`/source gate와 Collection active/non-source-deleted/`route`를 current editor로 검증하고 whole-write failure를 반환한다. Reference 없는 legacy graph는 구조 검증 뒤 authorization query를 생략한다 | Collection child expansion, saved label/Client capability 신뢰, runtime lease 발급 |
| Deployment Preflight | 두 list의 structure, lifecycle/sync eligibility, direct KB retrieval-visible readiness와 server-derived audience/public gate를 재귀 graph에 적용하고 safe bucket/action을 반환한다 | Child ID/exact hidden count 공개, preflight를 runtime capability로 재사용 |
| Workflow LLM Integration | explicit execution audience와 두 configured ID list로 MBA-232 resolver를 invocation당 한 번 호출하고 ordered KB ID를 Retrieval Orchestrator에 전달한다 | Gateway resolver import, LLM node 내부 permission SQL, owner/credential fallback |
| Public/Observability Projector | public graph에서 두 reference list를 제거한다. Explicit direct KB의 기존 authorized lineage와 KB-local rank는 유지할 수 있다. Collection-derived evidence는 child KB/document/chunk identity와 KB-local rank를 제거하고 최종 병합 evidence rank만 result/quality trace에 남기며, audit은 node-level count bucket으로 집계한다 | Collection identity/provenance, child resource identity/rank, raw graph/query/source/provider payload 저장 |

Builder는 고정 KB와 Knowledge Collection을 별도 selector group으로 표시한다. 각 group은
독립 `n/20` limit을 가지며 Collection membership이 실행 시점에 다시 계산된다는 설명을
표시한다. Picker에서 사라진 saved item은 generic unavailable chip으로 보존하고
사용자가 제거하거나 권한이 복구되기 전 새 저장을 차단한다. Builder 안에서
Collection 생성/삭제/permission/membership을 관리하지 않는다.

Agent Builder와 optimizer는 기존 Collection selection을 보존하지만 자동으로 새
Collection을 추천하거나 선택하지 않는다. Runtime sync는 explicit direct KB만 처리하고
Collection child는 MBA-232 materialized provenance/readiness 결과를 사용한다.

Conversation Memory target adapter는 Knowledge Permission Helper의 bulk 결과를 `decision`, `principal_kind`, opaque `authorization_decision_revision`, `resource_revision`, `policy_revision`, `evaluated_at` contract로 투영한다. Source-managed KB의 source ACL revision은 decision revision에 반영한다. Lifecycle, KB permission, source ACL 중 필요한 revision이 없으면 allow를 추정하지 않고 `unknown`을 반환한다. Anonymous public audience에는 subject ID/revision을 합성하지 않는다.

Retrieval Orchestrator는 최종 evidence와 함께 KB/document version, organization, sensitivity와 authorization-safe reference를 `RuntimeDataDependencyEnvelope`로 발급한다. Raw title/path/URL/content/ACL은 envelope에 포함하지 않는다. Client나 Workflow node가 canonical Knowledge dependency를 발급할 수 없고, V1에서는 answer content에 영향을 준 모든 Knowledge dependency를 필수로 취급한다.

## UI Surfaces

| Surface | 목적 |
| --- | --- |
| Knowledge Collections | Collection 목록, 상세, 생성/수정/archive, item 관리, permission grant/revoke, visibility 상태를 표시한다 |
| KB Detail | Document-level KB lifecycle, active version, sync state, permission state를 표시한다 |
| KB Permission Management | Admin/settings의 권한 UI에서 KB별 team grant와 user direct grant를 표시, 생성, 갱신, 회수한다 |
| Knowledge Delegation | Organization manager가 Team 우선으로 Knowledge domain action을 부여·회수하고 만료 상태를 확인한다. Domain action과 KB content access를 분리해 표시한다 |
| Source Connector Setup | Connector config, egress-safe test/preview, ACL mapping status를 관리한다 |
| Sync Remediation Queue | Stale/unmapped/ambiguous ACL, failed sync, tombstone, retry/dead-letter status를 표시한다 |
| Agent Knowledge Settings | Collection routing scope 또는 explicit KB를 선택한다. 허용된 safe candidate만 표시한다 |
| Skill Management / Playground Candidate | 향후 Skill version, freshness, eval status, publication/review 상태를 표시할 수 있는 후보 surface다. 실제 작성/테스트/승인 요청 UX와 Workflow Playground 통합 여부는 아직 확정하지 않으며, 표시한다면 safe metadata만 사용한다 |
| Audit/Citation Detail | Redaction-safe citation과 retrieval summary를 표시한다. Raw content는 별도 raw/compliance surface에서만 사용한다 |
| RAG A/B Compare | LLM node 단위 RAG strategy, token, cost, citation summary를 비교한다 |

### KB Detail Source Processing UI

`POST /api/v1/rag/upload`로 등록된 source document는 초기 상태가 `pending`일 수 있으며, chunk/embedding 생성이 끝나기 전까지 RAG 검색 대상이 아니다.

- KB 상세의 source 목록은 `pending` document에 `처리 시작` action과 "처리 시작 전에는 RAG 검색에 사용되지 않는다"는 safe 안내를 표시한다.
- `failed` document는 같은 document settings 화면으로 들어가는 `재처리` action을 제공한다.
- 처리 중 document의 progress UI는 active organization UUID를 포함한 authorization-scoped SSE URL만 연다. Active organization이 없으면 stream을 열지 않고 safe 안내를 표시하며, Gateway의 KB `read` 거부 응답 뒤 자동 재연결하지 않는다.
- Source upload 성공 후 UI는 KB 상세 source 목록으로 돌아오며, 방금 등록된 `pending` source를 포함한 목록에서 처리 시작 action을 제공한다. FILE source는 document settings 화면에서 원본 preview를 렌더할 수 있으므로 업로드 직후 자동으로 상세 화면을 열지 않는다. Client는 원본 content를 active organization header가 포함된 API 요청으로 받고 ephemeral Blob URL만 viewer에 전달한다. PDF는 Edge를 포함한 브라우저 기본 PDF viewer를 사용하는 `object`와 `noopener noreferrer` 새 탭 fallback을 제공하며, content 응답은 `nosniff`를 유지한다. Blob URL은 document scope 전환 또는 unmount 때 revoke한다. HTML로 변환되는 Office 문서와 text 계열은 기존 scriptless sandbox iframe(`allow-same-origin allow-downloads`)을 유지하며 `allow-scripts`를 추가하지 않는다. 기존 `completed` document를 열 때는 자동으로 KB 상세로 이동하지 않으며, 현재 document scope에서 active processing 상태를 관찰한 뒤 완료된 경우에만 완료 후 이동한다.
- 지식 테스트 모달은 모델 목록, 일반 검색, AI 답변 요청을 하나의 active organization scope에 묶고 모두 같은 `X-Organization-Id`를 전송한다. Organization, KB 또는 modal open scope가 바뀌면 진행 중인 검색 generation을 무효화하고 이전 scope의 결과를 렌더링하지 않는다. Stored organization과 아직 rerender되지 않은 Client state가 다르면 이전 organization header로 새 검색을 시작하지 않는다. AI 답변은 현재 organization에서 사용 가능한 chat model이 선택된 경우에만 제출할 수 있다.
- KB/document `read` response의 metadata는 safe progress/state projection만 사용한다. UI는 `api_config`, encrypted source config, DB/connector connection identifier나 raw source reference가 detail payload에 존재한다고 가정하지 않는다. Document settings UI는 별도 `GET .../edit-config`를 KB `write` 경계에서 호출하고, 현재 KB/document scope의 `editable=true` configuration hydration이 끝나기 전에는 DB/API preview와 process action을 disabled 처리한다. Route 전환 시 source-specific state와 gate를 즉시 reset하고 cleanup 이후 도착한 이전 scope 응답은 폐기한다. API URL/header/body나 encrypted value를 화면 state, session storage key, toast/log에 복원하지 않는다.
- Document processing UI는 process/approval API가 성공한 뒤에만 local status를 active processing으로 바꾼다. Initial fetch, process/approval, SSE와 polling callback은 자신이 시작된 active organization/KB/document scope를 캡처하고 organization 또는 route 전환, cleanup 뒤 도착한 응답을 폐기한다. Scope ref가 이미 바뀐 이전 render의 handler는 process/analyze/preview/approval 요청 자체를 시작하지 않는다. 완료 후 이동은 같은 scope에서 active processing 상태를 관찰한 경우에만 예약하므로 이미 처리 중인 문서를 지켜보는 흐름은 완료 후 이동할 수 있지만, 비용 승인 취소·요청 실패·초기 `completed` 상태는 이동 intent를 만들지 않는다.
- Document status UI는 Gateway가 반환한 fixed public processing message와 generic failure만 표시한다. Persisted `error_message`, `processing_current_step`, Redis value를 raw UI string으로 간주하지 않으며 Client가 internal exception detail을 fallback으로 표시하지 않는다.
- 이 UI는 hidden document, 권한 없는 source path/title, raw source content를 표시하지 않는다.

### KB Permission Management UI

- MBA-176에서는 기존 admin/settings permission surface를 확장해 KB team permission과 user direct permission을 함께 관리한다. MBA-231은 같은 관리 영역에 Organization manager 전용 Knowledge domain delegation panel을 추가하되 KB resource grant와 시각적으로 분리한다.
- UI는 organization member 목록을 grant 대상 후보로 사용하되, 조직에 속해 있다는 사실만으로 KB `use/read/manage` 권한이 생긴다고 표시하지 않는다.
- User direct grant 생성/수정에서는 `viewer`, `operator`, `builder`, `manager`만 선택할 수 있다. `none`은 선택지로 제공하지 않고, 권한 회수는 삭제 action으로 표현한다.
- Effective permission 표시는 organization manager override와 team/user direct grant 중 가장 강한 additive allow로 계산된 값을 사용한다. User direct grant가 team grant를 낮추거나 deny할 수 있는 것처럼 표시하지 않는다.
- `can_manage_kb`가 없는 사용자에게는 grant action을 숨기거나 disabled 처리하되, 최종 차단은 Gateway API가 수행한다.
- Domain delegation은 Team을 기본 선택으로 제공하고 user direct grant는 예외 경로로 둔다. `catalog_manage`, `permission_delegate`, `lifecycle_manage`, `sync_manage`의 허용 범위와 content-plane 비상속을 각 action 설명에 표시한다.
- Domain `permission_delegate` actor에게는 자신과 자신이 속한 Team이 grant 대상으로 보이더라도 content-plane grant가 차단됨을 safe 안내한다. 최종 self/own-Team 차단은 Gateway가 수행한다.
- `completed` document만 workflow builder/RAG 선택과 runtime retrieval에서 ready evidence 후보가 될 수 있다.

KB detail UI는 manual KB recommendation용 safe metadata 편집 surface를 제공할 수 있다. `safe_label` 자동 생성 버튼과 `kb_safe_topics` 자동 생성 버튼은 각각 KB name/description에서 sanitizer, length cap, secret/url/path removal을 적용한 값을 채우며, 저장 버튼은 전용 `PATCH /api/v1/knowledge/{kb_id}/safe-metadata`로 allowlisted 필드만 전송한다. `can_manage_safe_metadata=true`일 때만 이 surface를 표시하고, `can_edit_settings=false`이면 이름·설명·embedding model·소스 추가/재처리 같은 `write` 동작을 표시하거나 활성화하지 않는다. Archive/restore는 `can_manage` 또는 lifecycle domain capability, hard delete는 별도 Organization manager acknowledgement capability를 사용한다. Source-managed KB의 raw source title/path/url은 이 surface에 표시하거나 recommendation input으로 사용하지 않는다.

### Knowledge Collection Management UI

Knowledge Collection 관리 UI는 Workflow Builder가 아니라 Knowledge 관리 영역에 둔다.

필수 surface:

- Collection 목록: safe name/description, manual/system-managed, lifecycle/sync state, visibility, bucketed linked/active KB count, caller action flags를 표시한다.
- Collection 생성/수정: organization manager 또는 domain `catalog_manage`가 private manual Collection을 생성한다. Delegated create는 client 입력과 무관하게 private다. `is_system_managed`나 public visibility는 일반 create/edit form에서 직접 설정하지 않는다.
- Collection 상세: item, permission, visibility, sync/system state를 분리해서 표시한다.
- Item manager: linked KB safe label, lifecycle/sync state, rank, `can_manage_kb`, `can_use_kb`를 표시한다. 유효한 safe label이 없고 caller가 KB `read`를 통과하지 못하면 generic label을 사용하며, domain `catalog_manage`만으로 manual KB `name`을 표시하지 않는다. Private membership은 `collection.manage` + KB `manage` 또는 domain `catalog_manage`, public membership은 Organization manager acknowledgement 경계를 따른다.
- Permission panel: server가 반환한 safe Team/User 대상 목록을 사용하고 Team을 기본값으로 둔다. `collection.manage` 또는 domain `permission_delegate` actor가 `read`, `route`, `manage`, `sync` additive allow를 grant/revoke할 수 있다.
- Public visibility warning flow: organization manager, explicit acknowledgement, safe exposure summary를 요구한다.
- Public Collection item link/unlink/reorder도 같은 public exposure warning과 acknowledgement를 요구한다.
- Collection role preset은 Viewer, Workflow Router, Maintainer, Sync Operator를 제공하되 저장 시 explicit action row를 transactionally 적용하고 KB `use`가 포함되지 않음을 표시한다.

금지 surface:

- raw source title/path/url/principal 표시.
- hidden KB name/id 또는 exact denied count 표시.
- Collection manage 권한을 KB content use 권한처럼 표시.
- Workflow Builder 화면에서 Collection 생성/삭제/권한관리를 주 기능으로 제공.

## State Model

| Object | States |
| --- | --- |
| KB lifecycle | `active`, `archived`, `deleted` |
| KB sync state | `synced`, `syncing`, `sync_failed`, `sync_disabled`, `source_deleted` |
| DocumentVersion | `staging`, `indexing`, `ready`, `failed`, `superseded` |
| Source ACL freshness / mapping | `fresh`, `stale`, `unmapped`, `ambiguous`, `unverified`, `revoked` |
| Sync run | `queued`, `leased`, `running`, `succeeded`, `failed`, `dead_lettered`, `cancelled` |
| Skill freshness | `fresh`, `stale`, `review_required`, `deprecated` |

`source_deleted`는 KB sync/source state이며 document version status가 아니다. Version이 과거 source 삭제 시점의 snapshot임을 표현해야 하면 `source_deleted_snapshot` 같은 historical stale reason을 사용한다.

Permission Helper가 source-managed가 아닌 KB를 평가할 때는 source ACL freshness enum 대신 `not_source_managed` 같은 safe sentinel을 반환할 수 있다. 이 값은 fresh source ACL을 의미하지 않고, source ACL gate가 적용되지 않는 KB임을 나타낸다.

Purge는 일반 KB lifecycle state가 아니다. Retention/legal-hold purge, raw artifact purge, source tombstone cleanup은 구현 전에 별도 retention policy, audit action/reason code, recovery contract가 필요하다.

## Interaction Flows

### 빌더 단계 LLM node RAG 옵션 구성

1. Workflow Builder 요청과 active organization을 검증한다.
2. `KnowledgeCandidateResolver`가 Builder actor와 server-resolved context 기준으로 authorized safe candidate set 또는 server-issued reference를 만든다. MBA-145 Agent Builder MVP에서는 Knowledge Skill body/checklist를 prompt context로 직접 로드하지 않는다.
3. Skill Context Loader는 후속 target 흐름이다. 후속 기능에서 Skill을 사용할 때만 선택된 skill의 redaction-safe body/checklist를 visibility, display policy, freshness/eval gate 이후 필요 시점에 로드한다.
4. Builder는 Knowledge RAG Recommendation Adapter를 통해 safe KB recommendation과 LLM node RAG option 후보를 받는다. Adapter input은 raw natural language 전체가 아니라 `StructuredRequest` 기반 `intent_summary`, `node_purpose_summary`, `knowledge_requirement`, `pending_resolution_ref`, `safe_workflow_context_summary`, KnowledgeCandidateResolver의 server-issued reference다. 같은 backend 내부 service call에서는 full safe candidate set 객체를 사용할 수 있지만, HTTP/serialized boundary에서는 reference만 사용한다. Adapter는 Collection을 실행 candidate로 반환하지 않고 `source_collection_summary`로만 제공하며, 현재 LLM node schema에 맞게 `knowledgeBases`로 materialize 가능한 KB 목록을 반환한다.
5. Hidden resource를 추론할 수 있는 aggregate count는 bucket 처리하거나 생략한다.
6. Builder output에는 raw source id/url/path/title, raw principal, raw ACL fact, exact hidden/denied count, raw content, raw skill body를 넣지 않는다.
7. 생성된 workflow의 LLM node의 RAG 옵션은 실행 시점에 execution subject 기준으로 collection route, KB permission, source ACL/requester authorization, final evidence policy를 다시 통과해야 한다.

### Runtime Collection Retrieval

1. Workflow runtime이 server-owned canonical organization과 explicit authenticated audience 또는 anonymous public audience를 구성한다. Optional user/owner fallback은 사용하지 않는다.
2. MBA-232 resolver는 configured direct KB와 명시 selected Collection만 받아 fresh PostgreSQL `REPEATABLE READ, READ ONLY` snapshot을 연다. Missing/empty Collection scope는 0개다.
3. Authenticated audience에서는 direct KB `use`, selected Collection `route`와 각 child KB `use`, applicable materialized source provenance를 bulk 평가한다. Anonymous audience에서는 active public Collection membership을 평가하고 source-managed KB를 fail-closed 제외한다.
4. Active lifecycle, `source_deleted` exclusion, active ready version 또는 documented legacy retrieval-visible fallback을 적용한다. Collection item은 row presence만 membership으로 보고 parent/child lifecycle을 별도로 평가한다.
5. Direct configured order를 먼저 유지하고 selected Collection configured order의 round-robin으로 남은 20-KB budget을 채운다. Canonical KB ID로 dedupe하고 first provenance를 보존한다.
6. Candidate 0개는 provider/retrieval 전 `safe_no_result`, budget 제한은 fixed safe warning을 가진 성공이다. Snapshot/repository/authorization infrastructure failure는 partial candidate 없이 retryable whole-resolution failure다.
7. MBA-233에서 연결되는 Retrieval Orchestrator는 resolved active/ready KB만 검색하고 evidence를 merge한다. `query_rewrite_mode`는 safe candidate set을 넓히지 않는다.
8. Source-of-Truth Tier는 authorized evidence 안에서 ranking, tie-break, conflict resolution hint로만 사용한다.
9. Final evidence policy와 evidence sufficiency check는 LLM prompt, answer generation, citation preview emission 전에 실행한다.
10. 근거가 부족하면 추측 답변을 만들지 않고 safe no-result 또는 insufficient-evidence response로 닫는다.
11. Answer/citation/audit/trace summary는 redaction-safe allowlist만 사용한다.

### Explicit KB Retrieval

1. 요청과 active organization을 검증한다.
2. Explicit KB를 resource-hiding matrix에 따라 resolve한다.
3. Collection route permission은 생략할 수 있다.
4. KB use helper, source ACL/requester authorization, final evidence policy는 항상 적용한다.
5. Retrieval과 citation은 auto mode와 같은 redaction-safe 규칙을 따른다.

### Workflow Runtime RAG

1. Workflow runtime이 run context에서 execution subject를 resolve한다. Gateway는 `internal_chatbot` 인증 run에서 current user를 subject로 전달하고 공개 `chatbot` run에는 subject를 전달하지 않는다.
2. Execution subject가 있으면 Knowledge Permission Helper가 해당 subject 기준으로 KB permission과 source ACL/requester authorization을 평가한다.
3. Execution subject가 없으면 Workflow owner, deployment owner, builder, `user_id`를 silent fallback으로 쓰지 않는다. Runtime은 anonymous public-only로 낮추고, active public collection에 연결된 active KB만 candidate로 남긴다.
4. Public collection은 `KnowledgeCollection.safe_metadata["visibility"] == "public"`으로 판정한다. 누락 또는 다른 값은 private로 취급한다. Source-managed Collection과 source-managed KB는 Public Exposure Policy Store의 valid source/connector public exposure approval도 통과해야 candidate로 남는다. Approval primitive가 없는 현재 anonymous runtime은 `source_identity_id`가 있는 Collection을 child KB 유형과 무관하게 fail-closed 제외하며, source-managed public 후보는 warning이 아니라 `source_public_exposure_required` blocked state로 표시한다.
5. Workflow가 Knowledge Skill을 사용할 경우 skill visibility, freshness/eval, safe metadata gate도 execution subject가 있을 때 같은 subject 기준으로 평가한다. Anonymous public-only runtime은 skill 선택만으로 private KB 후보를 넓힐 수 없다.
6. `general`, `permission_scoped`, `task_aware` 등 모든 운영 RAG mode는 subject 기반 gate 또는 anonymous public-only gate와 final evidence gate를 통과한다.
7. Retrieval strategy, query rewrite, source tier, skill 차이는 gate 이후 authorized/public evidence를 얼마나 넓게 또는 정밀하게 선택하는지에만 영향을 준다.
8. Evidence sufficiency policy가 insufficient로 판정하면 workflow node는 근거 부족 응답이나 안전한 분기 결과를 반환해야 하며 문서에 없는 정책 해석을 생성하지 않는다.
9. Trace/A-B summary는 safe citation metadata, token/cost/latency, strategy, query rewrite 적용 여부, evidence sufficiency 결과, skill id/version/freshness/eval status만 노출한다.

### Source Sync And Version Activation

1. Scheduler가 connector sync lease를 획득한다.
2. Connector worker가 guard/adapter를 통해 source item과 source ACL을 가져온다. MCP/API source는 allowlist operation만 사용한다. Slack 계열 초기 baseline은 channel을 collection으로, thread/huddle recap/canvas/bot-generated meeting summary/pinned-message group을 document-level KB로 매핑한다. DM/raw audio/raw transcript는 기본 수집하지 않는다.
3. Content Safety Scanner와 Parser Isolation Worker가 file type allowlist, active content 차단, archive cap, scan timeout/unknown, parser isolation을 적용한다.
4. Normalizer가 content safety gate를 통과한 content에만 shared privacy/redaction policy를 호출해 redacted canonical text와 safe metadata를 만든다.
5. Ingestion concurrency guard가 source item 또는 document-level KB 단위 owner-token/fencing lock을 확보한다.
6. Ingestion이 새 document version, chunk, embedding, external index artifact를 staging 상태로 생성한다.
7. Finalizer는 모든 artifact가 준비된 뒤 짧은 transaction에서 active version, `content_hash`, chunking fingerprint, embedding model을 함께 확정한다.
8. Outbox/recovery scanner가 orphan cleanup, stale worker finalization 차단, crash recovery를 처리한다.

### Live-linked Retrieval

1. Runtime이 execution subject와 source subject mapping state를 확인한다.
2. Source-side search가 requester-scoped이면 해당 subject 기준으로 검색한다.
3. Requester-scoped search가 없고 opaque source ref-only search만 있으면 ref 후보를 받은 뒤 `check_access_batch` 또는 bounded `check_access` fallback으로 재확인한다.
4. Broad service-account search가 authorization 전 title, snippet, count, score를 반환하는 source는 Live-linked 일반 retrieval 후보에서 제외한다.
5. Metadata, citation, audit/trace summary는 runtime authorization과 display policy를 통과한 safe field만 사용한다.

### Raw Content View

1. Active organization과 KB visibility를 검증한다.
2. Raw/compliance permission과 source-managed KB의 fresh source ACL을 검증한다.
3. Retention, legal hold, purge state를 검증한다.
4. Content 반환 전에 raw access audit을 기록한다.
5. Raw content는 dedicated raw/compliance surface에서만 반환한다. Agent answer, retrieval context, prompt construction, SSE stream은 redacted canonical text만 사용한다.

## Performance And Scalability

- Permission helper는 candidate resolution에서 per-KB query를 피하고 bulk evaluation을 지원해야 한다.
- Candidate lookup에는 KB 중심 index와 user-candidate index가 모두 필요하다.
- 초기 candidate cap은 `max_candidate_kbs=5000`, `max_route_collections=20`, `max_retrieval_kbs=20`, `max_chunks_per_kb=8`, `max_total_chunks=50`이다. 이 값은 운영 baseline이며 제품의 고정 계약이 아니다.
- Candidate cap, fanout concurrency, timeout, partial failure behavior는 [implementation_baseline.md](implementation_baseline.md)의 baseline을 시작점으로 삼고, operations policy로 조정 가능해야 하며 운영 배포 전에 load test를 거쳐야 한다.
- 가능한 경우 KB/version filter를 포함한 단일 vector/keyword query를 우선한다. Backend가 지원하지 못하면 concurrency와 timeout cap이 있는 bounded per-KB fanout을 사용한다.
- MBA-232 runtime resolver는 candidate ID/authorization을 invocation 사이에 cache하지 않는다. 향후 candidate cache를 별도 승인할 경우 permission/freshness revision을 포함해 ACL revocation이 stale candidate를 무효화해야 한다.
- Skill candidate cache key에는 skill version, freshness state, eval state, source version reference를 포함해 stale skill이나 source tier 변경이 즉시 무효화되어야 한다.
- Query rewrite cache를 둘 경우 key에는 rewrite mode, safe template id, skill version, permission/freshness epoch를 포함해야 하며 raw rewritten query를 durable cache key나 trace key로 사용하지 않는다.
- `llm_assisted` query rewrite는 추가 latency와 LLM cost를 만든다. 운영 배포 전 rewrite timeout, token/cost budget, fallback, load shedding, usage logging 기준을 load test에 포함한다.
- DB source sync나 shared vector save path도 같은 document-level KB에 대한 chunk replacement를 직렬화하거나 versioned chunk set + active pointer 방식으로 처리해야 한다.

## Implementation Phases

- Phase 1: egress negative paths, protected source identity, basic sync, content safety/parser isolation, redaction, active version swap, transactional outbox insert, fencing token, recovery scanner smoke.
- Phase 2: source ACL freshness, content cursor와 ACL/permission watermark 분리, Knowledge Permission Helper, KB `use` + source ACL two-gate, source-policy grant inactive lifecycle.
- Phase 3: multi-KB caps, final evidence recheck, resource hiding matrix, retry/dead-letter transition, partial result behavior.
- Later: golden questions, source tier tuning, LLM-assisted rewrite, advanced rerank.

## Security And Privacy

- Raw source id/url/title/path, raw source ACL, raw content, prompt/completion, provider raw response, credential value, secret은 audit/trace/log에서 제외한다. Raw/compliance access log는 safe reference와 decision만 저장한다.
- Internal document metadata는 encrypted value도 credential-bearing configuration으로 취급한다. KB/document read response는 allowlist projector를 통과하고 unknown field는 default deny하며, API config와 connection/source identifier는 response, error, audit, trace, log로 복사하지 않는다.
- Domain revoke는 inactive subject 복원을 요구하지 않는다. Existing permission row를 organization scope 안에서 lock/delete하고 audit와 원자 commit해 stale delegated capability를 제거한다.
- Domain revoke repository는 organization/subject/action predicate와 `FOR UPDATE`를 하나의 SQL statement로 유지한다. Compile contract와 opt-in disposable PostgreSQL test가 cross-org isolation, audit rollback, concurrent exactly-one delete/audit를 검증한다.
- Collection membership 관리 capability는 KB label read capability가 아니다. Safe label이 없으면 독립 KB `read`를 통과한 caller만 manual KB `name`을 볼 수 있다.
- Source-derived display metadata는 user-facing 저장 전에 redaction, 길이 제한, display-policy approval을 거쳐야 한다.
- `verify=false`, HTTPS downgrade, 승인된 outbound client factory 밖의 custom HTTP client, private/link-local/metadata IP target, redirect 기반 guard 우회는 금지한다.
- DB adapter arbitrary SQL과 SSH adapter arbitrary command execution은 향후 ADR이 좁은 use case를 승인하지 않는 한 connector test/preview/sync path에서 금지한다.
- 일반 사용자와 workflow 작성자 화면에는 권한/정책상 제외된 문서명, raw source title/path/url, exact denied count를 표시하지 않는다. 관리자/감사 화면도 별도 권한과 display policy가 없으면 safe/bucketed summary만 표시한다.
- 운영 `general RAG`는 권한 없는 문서를 포함하는 mode가 아니다. 모든 RAG mode는 권한 gate를 통과하며, A/B 테스트의 차이는 authorized evidence 안에서 broad retrieval과 task-aware retrieval을 비교하는 것이다.
- Knowledge Skill은 source of truth나 permission decision이 아니다. Skill body/resource에는 raw content, raw source title/path/url, hidden KB id, restricted document list를 저장하지 않는다.
- Query rewrite 결과 원문은 raw prompt처럼 취급한다. Durable audit/trace/log에는 raw rewritten query를 저장하지 않고 safe strategy summary만 저장한다.
- Evidence sufficiency reason은 권한 없는 문서의 존재나 개수를 암시하지 않는 safe reason class로만 표시한다.
- Code-bearing skill은 별도 sandbox/approval/egress/resource-cap gate가 닫히기 전까지 Knowledge 실행 시점 경로에서 실행하지 않는다.
- Retention purge와 cleanup worker는 terminal state와 legal hold를 확인하고, concurrent worker가 같은 row를 중복 처리하지 못하도록 row lock, marker, idempotency key 중 하나를 사용해야 한다.

## Accessibility

- Collection과 KB state badge에는 색상만이 아니라 text label이 있어야 한다.
- Error/remediation state는 admin/preflight 또는 이미 visible로 판정된 resource context에서만 permission denied, source ACL stale, sync failed, hidden resource를 구분한다. 일반 사용자/작성자 context에서는 hidden name/path를 누출하지 않는 safe reason class로 낮춘다.
