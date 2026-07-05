# Knowledge Component Spec

Status: Draft
MBA-105 구현 baseline, 운영 기본값, permission helper output, active version finalization, resource hiding matrix는 [implementation_baseline.md](implementation_baseline.md)를 따른다. Workflow RAG에서 `execution_subject`가 없는 MVP public-only runtime은 [ADR-0018](../../decisions/ADR-0018-workflow-rag-anonymous-public-only-runtime.md)을 따른다.

## Domain Components

| Component | 책임 | 경계 |
| --- | --- | --- |
| Knowledge Source Connector | Adapter policy를 통해 source item과 source ACL을 열거하고 가져온다 | mbased permission을 직접 결정하지 않는다 |
| OutboundEgressGuard | Knowledge/RAG source collection server-side outbound access 전에 network policy를 검증한다 | SQL/SSH/SaaS 의미를 구현하지 않으며, 별도 ADR 없이 모든 workflow runtime outbound를 포괄하지 않는다 |
| Protocol Adapter | Read-only probe, SQL/command deny, listing cap 같은 protocol-specific safe behavior를 수행한다 | 승인된 guard/client/dialer를 사용해야 한다 |
| Sync Scheduler / Worker | Lease, cursor, retry/backoff, dead-letter, tombstone, sync run state를 관리한다 | Raw source metadata를 노출하지 않고 safe state/reason summary만 낸다 |
| Source Identity Store | Protected/HMAC source identity reference와 tombstone matching을 관리한다 | User-facing document resource가 아니다 |
| Source Authorization Provenance Store | Source ACL fact를 requester authorization provenance와 freshness evidence로 materialize한다 | KB `use` grant 자체가 아니며 retrieval permission은 Knowledge Permission Helper가 two-gate로 평가한다 |
| Privacy/Redaction Service | PII/secret hard baseline과 output-target redaction을 위한 shared detector/masking engine을 제공한다 | Trace storage나 Knowledge lifecycle을 소유하지 않는다 |
| Canonical Normalizer | Source content를 추출, redaction, normalization해 canonical text/metadata를 만든다 | Chunk/embedding 생성 전에 Privacy/Redaction Service를 사용한다 |
| Raw Artifact Store | Compliance view용 optional protected raw source content store | RAG, embedding, prompt, router input, Agent answer stream에서 사용하지 않는다 |
| Ingestion Concurrency Guard | Same source item/document-level KB 처리의 owner-token lock, fencing token, advisory lock을 제공한다 | Lock TTL 만료 뒤 stale worker가 새 artifact를 finalize하거나 lock을 해제하지 못하게 한다 |
| Ingestion Pipeline | Document version, chunk, embedding artifact, external index entry를 생성한다 | 성공 전 active version을 바꾸지 않는다 |
| Active Version Finalizer | Transactional active version pointer swap, previous version `superseded` 표시, content_hash/fingerprint commit, outbox insert를 수행한다 | Fencing/recovery gate가 필요하며 hash만 먼저 commit하거나 pointer swap 후 outbox insert 전에 crash window를 만들지 않는다 |
| Artifact Cleanup Reconciler | DB state와 object storage/vector index/external artifact cleanup을 outbox 기반으로 맞춘다 | DB commit 전 physical delete를 수행하지 않고 retry 가능한 cleanup만 실행한다 |
| Knowledge Permission Helper | Collection `read`, collection `route`, KB use, source ACL freshness/requester authorization을 bulk 평가한다 | Router와 controller는 permission row가 아니라 helper 결과를 소비해야 한다 |
| Knowledge Skill Registry | Provider-neutral Knowledge Skill, version, owner/review state, freshness/eval status를 관리한다 | Skill은 빌더 단계 LLM node의 RAG 옵션 후보이며 권한 source나 source of truth가 아니다 |
| Source-of-Truth Catalog | 정책 문서, ADR/decision record, semantic definition, curated query corpus 같은 source tier와 safe reference를 관리한다 | Raw content나 hidden source identity를 router에 노출하지 않는다 |
| Skill Context Loader | 빌더 단계 safe skill metadata와 workflow 생성 요청을 기반으로 필요한 skill body/checklist만 점진적으로 로드한다 | 전역 metadata 선노출과 raw skill resource 로드를 금지한다. 실행 시점 evidence는 별도 authorized retrieval로 가져온다 |
| Skill Evaluation/Regression Set | Golden question, eval result, freshness signal을 관리한다 | Eval fixture도 raw restricted content를 포함하지 않는다 |
| Skill Governance/Publication | Skill publish, review, deprecate, approval workflow의 policy boundary 후보 | 구체적인 authoring UI, Workflow Playground 연결, 승인 UX는 아직 확정하지 않는다. Code-bearing skill은 별도 sandbox/approval gate 전까지 publish할 수 없다 |
| Collection Router | Authorized safe candidate에서 collection/KB 후보를 선택한다 | Access control을 수행하지 않고 raw source ACL이나 hidden aggregate data를 받지 않는다 |
| Retrieval Orchestrator | 선택된 KB들에 대해 metadata/hierarchy retrieval을 실행하고 merge/rerank한다 | Authorized redacted evidence만 사용한다 |
| Audit/Trace Summarizer | Redaction-safe audit/trace/answer summary를 만든다 | Raw content/title/path/url은 제외하고, raw/compliance audit은 safe reference, decision, reason만 저장한다 |
| RAG Answer Retention Worker | Terminal answer run의 retention purge를 수행하고 aggregate audit을 남긴다 | requested/running row를 삭제하지 않고 동시 purge를 row lock/marker로 방지한다 |

## UI Surfaces

| Surface | 목적 |
| --- | --- |
| Knowledge Collections | Collection, safe metadata, sync status, route/manage/sync control을 표시한다 |
| KB Detail | Document-level KB lifecycle, active version, sync state, permission state를 표시한다 |
| Source Connector Setup | Connector config, egress-safe test/preview, ACL mapping status를 관리한다 |
| Sync Remediation Queue | Stale/unmapped/ambiguous ACL, failed sync, tombstone, retry/dead-letter status를 표시한다 |
| Agent Knowledge Settings | Collection routing scope 또는 explicit KB를 선택한다. 허용된 safe candidate만 표시한다 |
| Skill Management / Playground Candidate | 향후 Skill version, freshness, eval status, publication/review 상태를 표시할 수 있는 후보 surface | 실제 작성/테스트/승인 요청 UX와 Workflow Playground 통합 여부는 아직 확정하지 않는다. 표시한다면 safe metadata만 사용한다 |
| Audit/Citation Detail | Redaction-safe citation과 retrieval summary를 표시한다. Raw content는 별도 raw/compliance surface에서만 사용한다 |
| RAG A/B Compare | LLM node 단위 RAG strategy, token, cost, citation summary를 비교한다 |

## State Model

| Object | States |
| --- | --- |
| KB lifecycle | `active`, `archived`, `deleted` |
| KB sync state | `synced`, `syncing`, `sync_failed`, `sync_disabled`, `source_deleted` |
| DocumentVersion | `staging`, `indexing`, `ready`, `failed`, `superseded` |
| Source ACL freshness | `fresh`, `stale`, `unmapped`, `ambiguous`, `unverified`, `revoked` |
| Sync run | `queued`, `leased`, `running`, `succeeded`, `failed`, `dead_lettered`, `cancelled` |
| Skill freshness | `fresh`, `stale`, `review_required`, `deprecated` |

`source_deleted`는 KB sync/source state이며 document version status가 아니다. Version이 과거 source 삭제 시점의 snapshot임을 표현해야 하면 `source_deleted_snapshot` 같은 historical stale reason을 사용한다.

Permission Helper가 source-managed가 아닌 KB를 평가할 때는 source ACL freshness enum 대신 `not_source_managed` 같은 safe sentinel을 반환할 수 있다. 이 값은 fresh source ACL을 의미하지 않고, source ACL gate가 적용되지 않는 KB임을 나타낸다.

Purge는 일반 KB lifecycle state가 아니다. Retention/legal-hold purge, raw artifact purge, source tombstone cleanup은 구현 전에 별도 retention policy, audit action/reason code, recovery contract가 필요하다.

## Interaction Flows

### 빌더 단계 LLM node RAG 옵션 구성

1. Workflow Builder 요청과 active organization을 검증한다.
2. Builder actor가 볼 수 있는 safe skill metadata와 safe collection/KB display metadata만 후보로 만든다.
3. Skill Context Loader는 선택된 skill의 redaction-safe body/checklist만 필요 시점에 로드한다.
4. Builder는 skill procedure, safe metadata, source-of-truth tier를 참고해 LLM node의 RAG 옵션으로 사용할 collection/KB reference 후보, query template, metadata filter, hierarchy mode, citation requirement, `query_rewrite_mode`, `evidence_sufficiency_policy`를 제안한다.
5. Hidden resource를 추론할 수 있는 aggregate count는 bucket 처리하거나 생략한다.
6. Builder output에는 raw source id/url/path/title, raw principal, raw ACL fact, exact hidden/denied count, raw content, raw skill body를 넣지 않는다.
7. 생성된 workflow의 LLM node의 RAG 옵션은 실행 시점에 execution subject 기준으로 collection route, KB permission, source ACL/requester authorization, final evidence policy를 다시 통과해야 한다.

### Runtime Collection Retrieval

1. Workflow runtime이 execution subject 또는 anonymous public-only context와 active organization을 검증한다.
2. Listing surface에는 collection `read`, routing scope에는 collection `route`를 bulk 평가한다.
3. Collection route scope와 KB permission helper/source ACL freshness/requester authorization 결과로 safe KB candidate set을 만든다.
4. `query_rewrite_mode`가 켜져 있으면 user query와 safe skill/template만 사용해 검색용 query를 만든다. Rewrite는 safe candidate set을 넓히지 않는다.
5. Retrieval orchestrator는 active ready version을 검색하고 evidence를 merge한다.
6. Source-of-Truth Tier는 authorized evidence 안에서 ranking, tie-break, conflict resolution hint로만 사용한다.
7. Final evidence policy와 evidence sufficiency check는 LLM prompt, answer generation, citation preview emission 전에 실행한다.
8. 근거가 부족하면 추측 답변을 만들지 않고 safe no-result 또는 insufficient-evidence response로 닫는다.
9. Answer/citation/audit/trace summary는 redaction-safe allowlist만 사용한다.

### Explicit KB Retrieval

1. 요청과 active organization을 검증한다.
2. Explicit KB를 resource-hiding matrix에 따라 resolve한다.
3. Collection route permission은 생략할 수 있다.
4. KB use helper, source ACL/requester authorization, final evidence policy는 항상 적용한다.
5. Retrieval과 citation은 auto mode와 같은 redaction-safe 규칙을 따른다.

### Workflow Runtime RAG

1. Workflow runtime이 run context에서 execution subject를 resolve한다. Interactive run은 request user를 subject로 전달할 수 있다.
2. Execution subject가 있으면 Knowledge Permission Helper가 해당 subject 기준으로 KB permission과 source ACL/requester authorization을 평가한다.
3. Execution subject가 없으면 Workflow owner, deployment owner, builder, `user_id`를 silent fallback으로 쓰지 않는다. Runtime은 anonymous public-only로 낮추고, active public collection에 연결된 active KB만 candidate로 남긴다.
4. Public collection은 `KnowledgeCollection.safe_metadata["visibility"] == "public"`으로 판정한다. 누락 또는 다른 값은 private로 취급한다.
5. Workflow가 Knowledge Skill을 사용할 경우 skill visibility, freshness/eval, safe metadata gate도 execution subject가 있을 때 같은 subject 기준으로 평가한다. Anonymous public-only runtime은 skill 선택만으로 private KB 후보를 넓힐 수 없다.
6. `general`, `permission_scoped`, `task_aware` 등 모든 운영 RAG mode는 subject 기반 gate 또는 anonymous public-only gate와 final evidence gate를 통과한다.
7. Retrieval strategy, query rewrite, source tier, skill 차이는 gate 이후 authorized/public evidence를 얼마나 넓게 또는 정밀하게 선택하는지에만 영향을 준다.
8. Evidence sufficiency policy가 insufficient로 판정하면 workflow node는 근거 부족 응답이나 안전한 분기 결과를 반환해야 하며 문서에 없는 정책 해석을 생성하지 않는다.
9. Trace/A-B summary는 safe citation metadata, token/cost/latency, strategy, query rewrite 적용 여부, evidence sufficiency 결과, skill id/version/freshness/eval status만 노출한다.

### Source Sync And Version Activation

1. Scheduler가 connector sync lease를 획득한다.
2. Connector worker가 guard/adapter를 통해 source item과 source ACL을 가져온다. Slack 계열 초기 baseline은 channel을 collection으로, thread/huddle recap/canvas/bot-generated meeting summary/pinned-message group을 document-level KB로 매핑한다. DM/raw audio/raw transcript는 기본 수집하지 않는다.
3. Normalizer가 shared privacy/redaction policy를 호출해 redacted canonical text와 safe metadata를 만든다.
4. Ingestion concurrency guard가 source item 또는 document-level KB 단위 owner-token/fencing lock을 확보한다.
5. Ingestion이 새 document version, chunk, embedding, external index artifact를 staging 상태로 생성한다.
6. Finalizer는 모든 artifact가 준비된 뒤 짧은 transaction에서 active version, `content_hash`, chunking fingerprint, embedding model을 함께 확정한다.
7. Outbox/recovery scanner가 orphan cleanup, stale worker finalization 차단, crash recovery를 처리한다.

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
- Candidate cache key에는 permission/freshness epoch를 포함해 ACL revocation이 stale candidate를 무효화해야 한다.
- Skill candidate cache key에는 skill version, freshness state, eval state, source version reference를 포함해 stale skill이나 source tier 변경이 즉시 무효화되어야 한다.
- Query rewrite cache를 둘 경우 key에는 rewrite mode, safe template id, skill version, permission/freshness epoch를 포함해야 하며 raw rewritten query를 durable cache key나 trace key로 사용하지 않는다.
- `llm_assisted` query rewrite는 추가 latency와 LLM cost를 만든다. 운영 배포 전 rewrite timeout, token/cost budget, fallback, load shedding, usage logging 기준을 load test에 포함한다.
- DB source sync나 shared vector save path도 같은 document-level KB에 대한 chunk replacement를 직렬화하거나 versioned chunk set + active pointer 방식으로 처리해야 한다.

## Implementation Phases

- Phase 1: egress negative paths, protected source identity, basic sync, redaction, active version swap, transactional outbox insert, fencing token, recovery scanner smoke.
- Phase 2: source ACL freshness, content cursor와 ACL/permission watermark 분리, Knowledge Permission Helper, KB `use` + source ACL two-gate, source-policy grant inactive lifecycle.
- Phase 3: multi-KB caps, final evidence recheck, resource hiding matrix, retry/dead-letter transition, partial result behavior.
- Later: golden questions, source tier tuning, LLM-assisted rewrite, advanced rerank.

## Security And Privacy

- Raw source id/url/title/path, raw source ACL, raw content, prompt/completion, provider raw response, credential value, secret은 audit/trace/log에서 제외한다. Raw/compliance access log는 safe reference와 decision만 저장한다.
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
