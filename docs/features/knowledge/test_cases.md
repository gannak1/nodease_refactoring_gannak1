# Knowledge Test Cases

Status: Draft
Verified Against: docs target model, ADR-0012, ADR-0013, ADR-0014

이 문서는 현재 RAG 동작과 목표 KB 통합 모델에 필요한 테스트 범위를 함께 기록한다. 목표 모델 테스트는 해당 동작에 필요한 [ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md) execution gate가 닫힌 뒤 구현 blocker가 된다.

## 단위 테스트

- Metadata filter는 allowlist된 key/operator만 허용하고 free-form dict, JSONPath, raw SQL fragment, secret/header/prompt/completion/raw response field를 거부한다.
- Classification metadata가 없으면 [ADR-0007](../../decisions/ADR-0007-mvp2-classification-metadata-storage.md)에 따라 `internal`로 처리한다.
- 목표 cutover 전 `document_chunks.metadata`와 현재 `documents.meta_info`가 충돌하면 document metadata를 우선한다.
- 목표 metadata sanitizer는 protected source identity field를 public metadata/filter path에서 거부한다.
- Redaction은 기본적으로 chunk content, embedding input, retrieval-visible artifact에 사용되는 canonical text를 만든다.
- Raw source content를 저장하더라도 protected raw artifact store 또는 encrypted object storage metadata table에만 저장하고 `document_chunks.content`에는 저장하지 않는다.
- Raw artifact storage path는 organization/source opt-in, raw/compliance gate, encryption, retention, legal hold, purge, audit policy가 명시적으로 활성화되지 않으면 비활성 상태다.
- Privacy/Redaction baseline은 admin policy가 비활성화할 수 없고, organization/collection/source/KB policy는 더 엄격하게 조정하거나 승인된 display mode만 선택할 수 있다.
- Source public ACL은 기본적으로 organization-wide KB read/use로 materialize되지 않는다.
- Source ACL provenance storage는 raw source permission, source permission action/provenance, source authorization state, KB permission `auth_state`를 섞어 저장하지 않는다.
- Source-managed KB의 KB `use` provisioning model이 확정되기 전에는 source ACL authorization만으로 KB `use`가 충족됐다고 판정하지 않는다.
- Ingestion lock release는 owner token을 비교한다. TTL 만료 뒤 다른 worker가 lock을 획득한 경우 stale worker는 새 worker의 lock을 삭제하지 못한다.
- Fencing token 또는 동등한 guard가 없는 stale worker는 active version, `content_hash`, chunking fingerprint, external index namespace를 finalize하지 못한다.

## 권한과 RBAC 테스트

- Collection `read`, `route`, `manage`, `sync`만으로는 하위 KB content retrieval 권한이 생기지 않는다.
- Auto collection mode는 collection route permission이 없는 KB를 제외한다.
- Explicit KB mode는 collection route permission을 생략할 수 있지만 KB helper allow, source ACL gate, final evidence policy는 계속 요구한다.
- 현재 retrieval/search-test content access에는 KB `use`가 필요하며 read/listing permission만으로는 content retrieval이 되지 않는다.
- Source-managed KB는 mbased KB `use`와 fresh requester source ACL authorization을 모두 요구한다.
- Manual KB grant는 stale/unmapped/ambiguous/unverified source ACL freshness gate를 우회하지 못한다.
- Source ACL revocation은 이후 retrieval을 막고 freshness epoch/cache invalidation signal을 갱신한다.
- Organization manager는 operations policy에 따라 remediation을 수행할 수 있지만 기본적으로 source ACL retrieval filtering을 우회하지 못한다.
- 다른 organization KB id의 response shape, audit behavior, answer-run 생성 여부는 resource-hiding API matrix gate가 닫힌 뒤 정의한다.
- Visible resource 확인 이후 same-scope KB use denial은 승인된 resource-hiding/API matrix를 따른다. Matrix가 resource visible 상태를 유지한다고 결정한 경우에만 `403 permission.denied`를 허용한다.

## Connector와 Egress 테스트

- Connector preview/test/fetch는 승인된 outbound guard factory 밖의 raw socket, ad hoc HTTP client, custom dialer를 사용할 수 없다.
- `/api/v1/rag/proxy/preview`, URL upload/preview(`s3FileUrl`, `apiUrl`), crawler, sitemap, future web/API connector, DB/SSH/SaaS/object-storage probe는 모두 central guard를 통과한다.
- DNS rebinding, private IP redirect, link-local/metadata IP, private network target, unsupported scheme, HTTPS downgrade, `verify=false`, oversized response, timeout을 거부한다.
- IPv4 obfuscation, IDNA/punycode/CNAME trick, open redirect chain, redirect 시 sensitive header forwarding, compression/zip bomb payload, unapproved proxy/CA configuration, rate-limit bypass를 거부하거나 safe cap으로 제한한다.
- DB adapter는 arbitrary SQL을 거부하고 승인된 read-only probe/schema introspection만 cap 안에서 허용한다.
- SSH adapter는 arbitrary command execution과 승인되지 않은 tunnel/proxy behavior를 거부한다.
- Object storage adapter는 policy가 bounded listing을 명시적으로 허용하지 않는 한 과도한 bucket/listing operation을 거부한다.
- Egress/adapter error는 sanitized reason code를 반환하고 credential이나 raw connection string을 포함하지 않는다.

## Sync와 Ingestion 테스트

- Sync lease는 두 worker가 같은 source item을 동시에 finalize하지 못하게 한다.
- 같은 document-level KB에 대한 concurrent ingestion은 하나의 finalization만 성공한다.
- `content_hash`, chunking fingerprint, embedding model은 chunk/index artifact finalization 성공 전에는 새 processed state로 commit되지 않는다.
- Finalization 실패 뒤 다음 retry는 stale `content_hash` 때문에 skip하지 않고 다시 처리한다.
- Cursor는 source item과 ACL 처리가 durable하게 기록된 뒤에만 commit된다.
- Source content가 바뀌지 않고 ACL만 바뀐 경우에도 source ACL provenance와 permission freshness를 갱신한다.
- Source deletion은 KB sync state를 `source_deleted`로 만들고 retrieval에서 제외하지만 audit/citation history를 기본 삭제하지 않는다.
- Connector access loss는 sync/permission state를 stale 또는 unverified로 표시하고 `source_deleted`로 처리하지 않는다.
- Indexing failure는 기존 active version을 retrieval 가능 상태로 유지한다.
- Successful indexing은 하나의 finalization contract 안에서 active version을 교체하고 이전 version을 superseded로 표시한다.
- Finalization 중 worker crash는 outbox/recovery scanner로 복구하고 pre-finalized artifact를 노출하지 않는다.
- External index success 이후 DB finalize failure가 발생하면 이전 active version을 유지하고 orphan cleanup을 queue에 넣는다.
- DB finalize success 이후 object storage/vector index cleanup failure가 발생하면 새 active version은 유지하고 cleanup을 retry한다.
- DB source sync 또는 shared vector save path가 같은 KB/document chunks를 동시에 교체하려 할 때 advisory lock 또는 versioned chunk set이 lost update를 막는다.
- Document/KB delete는 DB commit 전에 object storage 또는 raw artifact를 먼저 삭제하지 않는다. Physical cleanup은 outbox/reconciler가 idempotent하게 수행한다.

## Retrieval과 Agent 테스트

- Auto mode는 collection route helper와 KB permission/source ACL helper 결과로 candidate set을 만든다.
- Auto mode에서 명시 `collection_ids`가 없으면 organization 전체 collection이 아니라 actor가 route할 수 있는 collection subset에서 시작한다.
- Router는 authorized safe candidate와 safe metadata만 받는다.
- Router는 raw source ACL fact, hidden KB id, raw source title/path/url, exact hidden count, raw content를 받지 않는다.
- Workflow runtime RAG는 명시적으로 resolve된 execution subject 기준으로 KB permission/source ACL을 평가하고, subject가 없거나 모호하면 workflow owner fallback 없이 preflight 실패한다.
- Production `general RAG`도 KB permission/source ACL/final evidence gate를 통과한다. Test fixture에서 권한 없는 문서는 `general`, `permission_scoped`, `task_aware` 모든 mode의 prompt/citation/trace에 들어가지 않는다.
- `general RAG`는 authorized resource 안의 broad retrieval로 동작하고, `task_aware` 또는 `permission_scoped` mode는 같은 authorized resource 안에서 더 작은 evidence set을 선택한다.
- 여러 collection에 같은 KB가 포함되면 `knowledge_base_id` 기준으로 dedupe하고 safe attribution rule을 유지한다.
- Retrieval은 active ready document version만 검색한다.
- Permission/source ACL/final evidence failure는 fail-closed evidence exclusion이며 partial operational success로 처리하지 않는다.
- 일부 authorized KB의 operational failure는 `partial_result=true`, bucketed reason summary, failed-candidate bucket, retryability를 포함한 safe partial result를 반환할 수 있다.
- 모든 KB retrieval failure는 승인된 API matrix에 따라 safe no-result 또는 terminal operational error 중 하나로 반환한다.
- Authorized source에서 evidence가 없는 경우는 성공한 empty evidence response이며 hidden resource를 암시하지 않는다.
- Explicit KB id not found, outside org, archived/deleted, source ACL denied/stale/unmapped/ambiguous, permission-unverified는 matrix가 요구하는 동일한 safe resource-hidden shape를 따른다.
- PII/final evidence policy block은 answer delta나 citation content preview가 emit되기 전에 발생한다.
- 현재 standalone single-KB Agent answer lifecycle과 same-scope blocked 처리 테스트는 [ADR-0013](../../decisions/ADR-0013-rag-answer-trace-usage-correlation-boundary.md)을 기준으로 유지하고, ADR-0014 matrix 테스트는 target cutover/source-managed/auto/multi-KB mode에 추가한다.

## Audit, Trace, Privacy 테스트

- Successful retrieval audit은 redaction-safe KB/document version/chunk id, score summary, correlation id, policy-safe metadata만 저장한다.
- Hidden/denied/resource-hidden path audit/trace metadata에는 raw title/path/url, exact hidden count, denied KB id, raw source ACL, raw exception을 포함하지 않는다.
- Partial result audit/trace는 safe partial marker, bucketed reason/retryability summary, request/correlation id만 저장한다.
- RAG strategy summary는 `retrieval_strategy`, `rag_mode`, selected collection/KB count, retrieved chunk count, citation count, context token estimate, retrieval latency, permission filter flag, policy result, partial result, safe exclusion summary만 포함한다.
- Trace side panel은 raw chunk content, raw source title/path/url, hidden document name/id, exact denied count, raw prompt/completion, provider raw response를 표시하지 않는다.
- Source ACL mapping audit은 safe principal reference만 저장한다.
- Raw content access는 별도 raw/compliance permission을 요구하고 audit을 남긴다.
- Raw content access는 active organization, KB visibility, source-managed KB의 fresh source ACL, retention/legal-hold/purge state를 확인하고, content 반환 전에 access audit을 기록한다.
- Raw content는 Agent answer, SSE stream, retrieval context, embedding input, prompt construction, citation summary, audit metadata, trace metadata, usage metadata, router input, log에 나타나지 않는다.
- Deleted/archived KB metadata에 대한 admin default view는 redacted 상태이며 raw content access를 암시하지 않는다.
- `rag_answer_runs`는 standalone answer anchor로 유지하고 trace/usage table에는 RAG-specific FK column을 추가하지 않는다.
- RAG answer lifecycle 상태 변경, `rag.answer.*` audit, LLM usage row 기록 중 일부가 실패하면 reconcile 또는 transactional outbox 기준에 따라 누락을 감지할 수 있다.
- RAG answer retention purge는 `completed`, `failed`, `cancelled`, `blocked` 같은 terminal status만 대상으로 삼고 `requested`/`running` row를 삭제하지 않는다.
- 동시 retention purge worker는 같은 answer run을 중복 삭제하거나 중복 purge audit count로 기록하지 않는다.
- Retention purge dry-run은 실제 `purged_count`가 아니라 `would_purge_count` 같은 safe preview 의미로만 표시한다.

## API와 UI 테스트

- Collection list는 safe redacted name/description과 non-color text label이 있는 state badge를 표시한다.
- Source metadata에서 유래한 system-managed collection display name/description은 storage/display 전에 redaction, cap, display-policy approval을 거친다.
- KB detail은 hidden source path를 누출하지 않으면서 sync failed, source ACL stale, source deleted, archived, deleted state를 구분한다.
- Remediation queue는 raw connector exception string이 아니라 safe reason code와 retryability를 표시한다.
- Citation은 ID vocabulary/protected source identity gate가 닫힌 뒤 target identity field(`citation_id`, `knowledge_base_id`, `document_version_id`, `chunk_id`, optional `collection_id`, optional `safe_source_ref`)를 사용한다.
- User-facing content preview는 redacted/capped 상태이며 durable audit/trace/usage summary에 복사하지 않는다.
- A/B 비교 UI는 권한 없는 문서명/ID를 표시하지 않고 authorized evidence 기준의 context token, retrieved chunk count, citation count, cost, latency, quality score만 비교한다.
- Demo fixture는 상담원 허용 문서와 제한 문서를 분리하고, 제한 문서가 모든 production RAG mode의 prompt/citation/trace에 포함되지 않는지 검증한다.

## 성능과 부하 테스트

- Bulk permission helper는 per-KB database query 없이 user-candidate lookup과 KB-centric lookup을 처리한다.
- Candidate cap은 stable ordering으로 큰 candidate set을 deterministic하게 잘라낸다.
- Candidate cache key는 permission/freshness epoch를 포함하고 ACL revocation 시 invalidation된다.
- 단일 filtered vector/keyword query를 우선한다. Bounded fanout을 사용하면 concurrency와 timeout cap을 강제한다.
- Load test는 max candidate KB, max retrieval KB, max chunks per KB, max total chunks, fanout timeout, partial operational failure behavior를 포함한다.
- Concurrent ingestion, concurrent DB-source sync, concurrent retention purge, cleanup outbox retry의 race 테스트를 포함한다.
