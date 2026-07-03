# Knowledge Component Spec

Status: Draft
Verified Against: docs target model, ADR-0012, ADR-0013, ADR-0014

## 도메인 컴포넌트

| Component | 책임 | 경계 |
| --- | --- | --- |
| Knowledge Source Connector | Adapter policy를 통해 source item과 source ACL을 열거하고 가져온다 | mbased permission을 직접 결정하지 않는다 |
| OutboundEgressGuard | Knowledge/RAG source collection server-side outbound access 전에 network policy를 검증한다 | SQL/SSH/SaaS 의미를 구현하지 않으며, 별도 ADR 없이 모든 workflow runtime outbound를 포괄하지 않는다 |
| Protocol Adapter | Read-only probe, SQL/command deny, listing cap 같은 protocol-specific safe behavior를 수행한다 | 승인된 guard/client/dialer를 사용해야 한다 |
| Sync Scheduler / Worker | Lease, cursor, retry/backoff, dead-letter, tombstone, sync run state를 관리한다 | Raw source metadata를 노출하지 않고 safe state/reason summary만 낸다 |
| Source Identity Store | Protected/HMAC source identity reference와 tombstone matching을 관리한다 | User-facing document resource가 아니다 |
| Privacy/Redaction Service | PII/secret hard baseline과 output-target redaction을 위한 shared detector/masking engine을 제공한다 | Trace storage나 Knowledge lifecycle을 소유하지 않는다 |
| Canonical Normalizer | Source content를 추출, redaction, normalization해 canonical text/metadata를 만든다 | Chunk/embedding 생성 전에 Privacy/Redaction Service를 사용한다 |
| Raw Artifact Store | Compliance view용 optional protected raw source content store | RAG, embedding, prompt, router input, Agent answer stream에서 사용하지 않는다 |
| Ingestion Concurrency Guard | Same source item/document-level KB 처리의 owner-token lock, fencing token, advisory lock을 제공한다 | Lock TTL 만료 뒤 stale worker가 새 artifact를 finalize하거나 lock을 해제하지 못하게 한다 |
| Ingestion Pipeline | Document version, chunk, embedding artifact, external index entry를 생성한다 | 성공 전 active version을 바꾸지 않는다 |
| Active Version Finalizer | Transactional active version pointer swap, content_hash/fingerprint commit, outbox cleanup을 수행한다 | Fencing/recovery gate가 필요하며 hash만 먼저 commit하지 않는다 |
| Artifact Cleanup Reconciler | DB state와 object storage/vector index/external artifact cleanup을 outbox 기반으로 맞춘다 | DB commit 전 physical delete를 수행하지 않고 retry 가능한 cleanup만 실행한다 |
| Knowledge Permission Helper | Collection `read`, collection `route`, KB use, source ACL freshness/requester authorization을 bulk 평가한다 | Router와 controller는 permission row가 아니라 helper 결과를 소비해야 한다 |
| Collection Router | Authorized safe candidate에서 collection/KB 후보를 선택한다 | Access control을 수행하지 않고 raw source ACL이나 hidden aggregate data를 받지 않는다 |
| Retrieval Orchestrator | 선택된 KB들에 대해 metadata/hierarchy retrieval을 실행하고 merge/rerank한다 | Authorized redacted evidence만 사용한다 |
| Audit/Trace Summarizer | Redaction-safe audit/trace/answer summary를 만든다 | Raw content/title/path/url은 제외하고, raw/compliance audit은 safe reference, decision, reason만 저장한다 |
| RAG Answer Retention Worker | Terminal answer run의 retention purge를 수행하고 aggregate audit을 남긴다 | requested/running row를 삭제하지 않고 동시 purge를 row lock/marker로 방지한다 |

## UI 화면

| Surface | 목적 |
| --- | --- |
| Knowledge Collections | Collection, safe metadata, sync status, route/manage/sync control을 표시한다 |
| KB Detail | Document-level KB lifecycle, active version, sync state, permission state를 표시한다 |
| Source Connector Setup | Connector config, egress-safe test/preview, ACL mapping status를 관리한다 |
| Sync Remediation Queue | Stale/unmapped/ambiguous ACL, failed sync, tombstone, retry/dead-letter status를 표시한다 |
| Agent Knowledge Settings | Collection routing scope 또는 explicit KB를 선택한다. 허용된 safe candidate만 표시한다 |
| Audit/Citation Detail | Redaction-safe citation과 retrieval summary를 표시한다. Raw content는 별도 raw/compliance surface에서만 사용한다 |
| RAG A/B Compare | LLM node 단위 RAG strategy, token, cost, citation summary를 비교한다 |

## 상태 모델

| Object | States |
| --- | --- |
| KB lifecycle | `active`, `archived`, `deleted` |
| KB sync state | `synced`, `syncing`, `sync_failed`, `sync_disabled`, `source_deleted` |
| DocumentVersion | `staging`, `indexing`, `ready`, `failed`, `superseded` |
| Source ACL freshness | `fresh`, `stale`, `unmapped`, `ambiguous`, `unverified`, `revoked` |
| Sync run | `queued`, `leased`, `running`, `succeeded`, `failed`, `dead_lettered`, `cancelled` |

`source_deleted`는 KB sync/source state이며 document version status가 아니다. Version이 과거 source 삭제 시점의 snapshot임을 표현해야 하면 `source_deleted_snapshot` 같은 historical stale reason을 사용한다.

Purge는 일반 KB lifecycle state가 아니다. Retention/legal-hold purge, raw artifact purge, source tombstone cleanup은 구현 전에 별도 retention policy, audit action/reason code, recovery contract가 필요하다.

## 상호작용 흐름

### 자동 Collection Retrieval

1. 요청과 active organization을 검증한다.
2. Listing surface에는 collection `read`, routing scope에는 collection `route`를 bulk 평가한다.
3. Collection route scope와 KB permission helper/source ACL freshness/requester authorization 결과로 safe KB candidate set을 만든다.
4. Hidden resource를 추론할 수 있는 aggregate count는 bucket 처리하거나 생략한다.
5. Router는 safe metadata만 사용해 collection/KB를 선택한다. Router input에는 raw source id/url/path/title, raw principal, raw ACL fact, exact hidden/denied count, raw content를 넣지 않는다.
6. Retrieval orchestrator는 active ready version을 검색하고 evidence를 merge한다.
7. Final evidence policy는 answer generation 또는 citation preview emission 전에 실행한다.
8. Answer/citation/audit/trace summary는 redaction-safe allowlist만 사용한다.

### 명시 KB Retrieval

1. 요청과 active organization을 검증한다.
2. Explicit KB를 resource-hiding matrix에 따라 resolve한다.
3. Collection route permission은 생략할 수 있다.
4. KB use helper, source ACL/requester authorization, final evidence policy는 항상 적용한다.
5. Retrieval과 citation은 auto mode와 같은 redaction-safe 규칙을 따른다.

### Workflow Runtime RAG

1. Workflow runtime이 run context에서 execution subject를 명시적으로 resolve한다.
2. Execution subject가 없거나 모호하면 RAG preflight를 실패시킨다. Workflow owner를 silent fallback으로 사용하지 않는다.
3. Knowledge Permission Helper가 execution subject 기준으로 KB permission과 source ACL/requester authorization을 평가한다.
4. `general`, `permission_scoped`, `task_aware` 등 모든 production RAG mode는 같은 permission/source ACL/final evidence gate를 통과한다.
5. Retrieval strategy 차이는 gate 이후 authorized evidence를 얼마나 넓게 또는 정밀하게 선택하는지에만 영향을 준다.
6. Trace/A-B summary는 safe citation metadata, token/cost/latency, strategy 정보만 노출한다.

### Source Sync와 Version Activation

1. Scheduler가 connector sync lease를 획득한다.
2. Connector worker가 guard/adapter를 통해 source item과 source ACL을 가져온다.
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

## 성능과 확장성

- Permission helper는 candidate resolution에서 per-KB query를 피하고 bulk evaluation을 지원해야 한다.
- Candidate lookup에는 KB 중심 index와 user-candidate index가 모두 필요하다.
- Candidate cap, fanout concurrency, timeout, partial failure behavior는 operations policy로 조정 가능해야 하며 production rollout 전에 load test를 거쳐야 한다.
- 가능한 경우 KB/version filter를 포함한 단일 vector/keyword query를 우선한다. Backend가 지원하지 못하면 concurrency와 timeout cap이 있는 bounded per-KB fanout을 사용한다.
- Candidate cache key에는 permission/freshness epoch를 포함해 ACL revocation이 stale candidate를 무효화해야 한다.
- DB source sync나 shared vector save path도 같은 document-level KB에 대한 chunk replacement를 직렬화하거나 versioned chunk set + active pointer 방식으로 처리해야 한다.

## 보안과 개인정보

- Raw source id/url/title/path, raw source ACL, raw content, prompt/completion, provider raw response, credential value, secret은 audit/trace/log에서 제외한다. Raw/compliance access log는 safe reference와 decision만 저장한다.
- Source-derived display metadata는 user-facing 저장 전에 redaction, 길이 제한, display-policy approval을 거쳐야 한다.
- `verify=false`, HTTPS downgrade, 승인된 outbound client factory 밖의 custom HTTP client, private/link-local/metadata IP target, redirect 기반 guard 우회는 금지한다.
- DB adapter arbitrary SQL과 SSH adapter arbitrary command execution은 향후 ADR이 좁은 use case를 승인하지 않는 한 connector test/preview/sync path에서 금지한다.
- 일반 사용자와 workflow 작성자 화면에는 권한/정책상 제외된 문서명, raw source title/path/url, exact denied count를 표시하지 않는다. 관리자/감사 화면도 별도 권한과 display policy가 없으면 safe/bucketed summary만 표시한다.
- Production `general RAG`는 권한 없는 문서를 포함하는 mode가 아니다. 모든 RAG mode는 권한 gate를 통과하며, A/B 테스트의 차이는 authorized evidence 안에서 broad retrieval과 task-aware retrieval을 비교하는 것이다.
- Retention purge와 cleanup worker는 terminal state와 legal hold를 확인하고, concurrent worker가 같은 row를 중복 처리하지 못하도록 row lock, marker, idempotency key 중 하나를 사용해야 한다.

## 접근성

- Collection과 KB state badge에는 색상만이 아니라 text label이 있어야 한다.
- Error/remediation state는 hidden name/path를 누출하지 않으면서 permission denied, source ACL stale, sync failed, hidden resource를 구분해야 한다.
