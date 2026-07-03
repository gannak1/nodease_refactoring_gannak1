# Knowledge Requirements

Status: Draft
Related Features: auth, organization, workflow, agent-builder, connectors, audit-tracing, llm-credentials

## Purpose

흩어진 사내 문서와 데이터 source item을 자동 또는 수동으로 수집하고, 질문한 사용자의 권한 범위 안에서만 검색해 답변하는 통합 RAG를 제공한다. [PRD](../../PRD.md)의 FR-031~FR-033을 담당한다.

현재 구현은 manual Knowledge Base 생성, 문서 업로드/색인, metadata-aware retrieval, hierarchical RAG, standalone RAG Agent answer 기반을 제공한다. 목표 KB 통합 모델은 [ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)에 따라 Knowledge Base를 document/source item 단위 permission/retrieval/sync/lifecycle atom으로 재정의하고, Knowledge Collection을 grouping/routing/UX/ops 단위로 둔다.

## 현재 Baseline

- `knowledge_bases`는 현재 코드에서 여러 `documents`를 포함할 수 있는 RAG data source 상위 단위다.
- Metadata-aware/hierarchical RAG 경계는 [ADR-0012](../../decisions/ADR-0012-metadata-aware-hierarchical-rag-boundary.md)를 따른다.
- Standalone RAG Agent answer와 trace/usage correlation 경계는 [ADR-0013](../../decisions/ADR-0013-rag-answer-trace-usage-correlation-boundary.md)를 따른다.
- 현재 `documents.meta_info`는 current metadata convention의 source of truth다.
- 목표 cutover 전까지 공식 문서는 현재 동작과 목표 모델을 분리해 읽어야 한다.

## 목표 모델

- `KnowledgeBase`: 문서/source item 1개에 대응하는 permission, retrieval, sync, lifecycle atom.
- `KnowledgeCollection`: 여러 document-level KB를 묶는 grouping, routing, UX, operations 단위.
- `DocumentVersion`: document-level KB의 canonical content/index version. 기본 retrieval은 active ready version만 사용한다.
- `Source-managed KB`: 외부 source connector가 생성/관리하는 KB. Retrieval에는 mbased KB `use`와 fresh source ACL/requester authorization이 모두 필요하다.
- `Redacted canonical text`: target chunk content, embedding input, retrieval-visible text artifact의 기본 원천.

## User Stories

- 빌더로서, 수동 업로드 또는 connector sync로 생성된 지식을 collection 단위로 탐색하고 상태를 확인하고 싶다.
- 플랫폼 관리자 또는 KB/collection manager로서, collection grouping/routing 권한과 KB content 권한을 분리해 관리하고 싶다.
- 현업 사용자로서, 질문하면 내가 접근 가능한 collection/KB 후보에서만 검색된 답변과 citation을 받고 싶다.
- 감사자로서, 특정 답변이 어떤 KB, document version, chunk에서 나왔는지 redaction-safe summary로 추적하고 싶다.
- 운영자로서, source sync 실패, source ACL stale, tombstone, 재색인, purge 상태를 raw content 노출 없이 확인하고 싶다.

## Functional Requirements

- FR-031: Knowledge source item을 document-level KB로 수집·색인하고, 여러 KB를 Knowledge Collection으로 묶는다.
- FR-032: Auto collection mode는 collection routing scope와 KB permission helper 결과로 만든 safe candidate set만 router/Agent에 전달한다.
- FR-033: Explicit KB mode는 collection routing 권한을 생략할 수 있지만 KB helper, source ACL gate, final evidence policy gate를 생략할 수 없다.
- FR-034: Source-managed KB retrieval은 mbased KB `use`와 fresh source ACL/requester authorization을 모두 통과해야 한다. Stale, unmapped, ambiguous, unverified, revoked source ACL은 fail-closed다.
- FR-035: Collection permission은 `collection.read`, `collection.route`, `collection.manage`, `collection.sync`처럼 grouping/routing/ops 권한으로 다루며, 하위 KB content retrieval을 자동 부여하지 않는다.
- FR-036: Source ACL facts는 source ACL provenance로 materialize하고, permission helper가 mbased KB permission gate와 source ACL/requester authorization gate를 분리해 effective result를 반환한다. Router/retrieval은 permission row를 직접 조합하지 않는다.
- FR-037: Retrieval과 citation은 citation id, KB id, document version id, chunk id, optional safe source reference, rank, score, safe metadata summary를 반환한다. Raw source content, raw prompt/completion, credential 원문은 audit/trace/usage metadata에 저장하지 않는다.
- FR-038: `document_chunks.content`, embedding input, retrieval-visible text artifact는 redacted canonical text에서 생성한다. Raw source content는 RAG/embedding/prompt에 사용하지 않으며, organization/source policy가 opt-in한 경우에만 protected raw artifact로 분리 저장할 수 있다 ([ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)).
- FR-039: Server-side URL fetch, connector preview/test, crawler/sitemap/API connector, DB/SSH/SaaS/object-storage probe는 중앙 outbound egress boundary와 protocol adapter safety policy를 통과해야 한다.
- FR-040: Partial operational failure는 권한/source ACL failure와 구분한다. 일부 authorized KB retrieval 실패는 safe partial result로 표시할 수 있지만, permission/source ACL/final evidence failure는 evidence 제외 또는 resource-hidden response로 fail-closed한다.
- FR-041: PII/secret redaction은 shared privacy/redaction service가 hard baseline을 제공하고, Knowledge ingestion은 이를 사용해 redacted canonical text를 생성한다. Admin policy는 baseline을 약화할 수 없고 organization/collection/source/KB 단위로 더 엄격하게 조정할 수 있다.
- FR-042: Workflow runtime에서 RAG retrieval을 실행할 때는 workflow run context가 명시적으로 제공한 execution subject 기준으로 KB permission과 source ACL을 평가한다. Execution subject가 없거나 모호하면 workflow owner로 조용히 fallback하지 않고 preflight 실패로 처리한다.
- FR-043: Production RAG mode는 이름이 `general`, `permission_based`, `task_aware`, `metadata_aware`, `hierarchical` 중 무엇이든 KB permission/source ACL/final evidence gate를 우회할 수 없다. `general RAG`는 authorized resource 안에서 넓게 검색하는 broad retrieval이고, `task-aware` 또는 `permission-scoped RAG`는 authorized resource 안에서 더 정밀하게 후보를 줄이는 retrieval이다.
- FR-044: RAG strategy 비교와 비용 최적화를 위해 retrieval summary는 `retrieval_strategy`, `rag_mode`, selected collection/KB count, retrieved chunk count, citation count, context token estimate, retrieval latency, permission filter 여부, policy result, partial result, safe exclusion summary를 redaction-safe 형태로 제공한다.
- FR-045: Source-managed KB에서 KB `use`가 어떤 경로로 충족되는지는 source ACL materialization gate에서 확정한다. Source ACL authorization은 KB `use`를 자동 대체하지 않으며, source-owned KB use grant를 도입하려면 저장 위치, freshness gate, revocation, audit-safe provenance, manual grant와의 결합 방식을 별도 ADR/RBAC 문서로 닫는다.
- FR-046: Knowledge ingestion은 같은 source item 또는 document-level KB에 대해 중복 finalization이 일어나지 않도록 owner-token lock, fencing token, database advisory lock, 또는 동등한 동시성 제어를 사용해야 한다. TTL 만료 뒤 stale worker가 새 worker의 lock이나 active artifact를 삭제/덮어쓰면 안 된다.
- FR-047: `content_hash`, chunking fingerprint, embedding model, active document version pointer, retrieval-visible index state는 실제 chunk/index artifact가 성공적으로 준비되고 finalization transaction이 끝난 뒤에만 committed processed state로 갱신한다. Chunk 저장 전 hash만 먼저 commit해 다음 실행이 stale/empty artifact를 처리 완료로 오판하게 해서는 안 된다.
- FR-048: Document/KB/raw artifact 삭제는 DB row와 object storage, vector index, external artifact cleanup을 outbox/reconciler로 조정해야 한다. DB commit 전에 physical object를 먼저 삭제해 orphan reference를 만들거나, cleanup 실패 때문에 hidden artifact가 retrieval-visible해지면 안 된다.
- FR-049: RAG answer retention purge와 answer lifecycle/audit/usage 기록은 idempotent하고 복구 가능해야 한다. Purge는 terminal status 대상만 처리하고 row lock, marker, `SKIP LOCKED` 계열 또는 동등한 방어로 동시 실행 중복과 running row 삭제를 막아야 한다. Audit/usage 강한 일관성이 필요한 경로는 transactional outbox 또는 reconcile 기준을 가져야 한다.

## Policies And Edge Cases

- Metadata는 permission source가 아니다. Metadata filter는 allowlist 기반 검색 제한이고 KB `use`/source ACL 판정을 대체하지 않는다.
- Collection visibility나 route 권한은 child KB 존재나 content 접근을 증명하지 않는다.
- Source public ACL은 organization-wide read/use로 자동 materialize하지 않는다. Connector policy와 organization policy가 명시적으로 opt-in하고 approver, expiry/reverification, revocation behavior, audit-safe metadata가 확정된 경우에만 source ACL provenance 생성 후보가 된다.
- Source-derived collection name/description/title/path/url은 민감 metadata일 수 있으므로 redacted, capped, display-policy-approved field로만 user-facing 저장/표시한다.
- Raw source content 조회는 Agent answer나 SSE stream과 분리된 raw/compliance flow로만 허용한다. 요청은 active organization, KB visibility, raw/compliance permission, source-managed KB의 fresh source ACL, retention/legal hold/purge policy, raw access audit 선기록을 모두 통과해야 한다.
- PII/secret redaction policy는 output target별로 다르게 적용한다. Chunk/embedding/retrieval-visible text는 redacted canonical text, citation preview는 redacted+capped preview, audit/trace/log는 allowlist summary, raw/compliance view는 별도 권한 flow를 사용한다.
- Collection list/router metadata는 authorized subset 기준으로만 계산한다. Exact child KB count, denied/hidden count, source distribution, unauthorized child에서 유래한 tag/category aggregate는 omit, bucket, 또는 request-scoped safe aggregate로 낮춘다.
- Auto collection router 입력에는 collection route scope와 KB permission/source ACL helper 결과를 통과한 authorized safe candidate와 safe metadata만 전달한다. Missing `collection_ids`는 organization 전체가 아니라 서버 정책상 route-allowed collection subset에서 시작한다. Raw source ACL, raw source id/url, exact hidden document count, exact denied count는 전달하지 않는다.
- Partial result 표시에는 `partial_result=true`, bucketed failed candidate count 또는 safe reason summary, retryability만 허용한다. Exact failed KB id/source distribution은 기본 저장하지 않는다.
- Explicit KB mode는 collection.route를 생략할 수 있지만 KB helper/source ACL/final evidence gate를 생략할 수 없다. Explicit KB id가 scope 밖, organization mismatch, deleted/archived, source ACL denied/stale/unmapped/ambiguous, permission-unverified인 경우의 응답 shape와 answer-run/audit 생성 여부는 resource hiding API matrix gate에서 확정한다.
- Organization manager remediation/admin view는 읽을 수 없는 source-managed KB에 대해 기본적으로 safe metadata와 remediation reason code만 표시한다. Raw title/path/url/content/source principal 표시에는 별도 display/raw-access policy gate가 필요하다.
- Active version finalization은 indexing 성공 전 기존 active version을 비활성화하지 않는다. Crash/recovery/outbox/fencing token 계약은 gate가 닫힌 뒤 구현한다.
- Destructive reset/reindex, legacy multi-document KB split/backfill, existing `team_knowledge_permissions`/RAG answer reference handling은 G1 data-preservation gate 승인 후에만 진행한다.
- A/B 테스트나 비용 최적화 UI에서 `general RAG` baseline을 보여줄 때도 권한 없는 문서가 prompt, citation, trace, audit에 들어가면 안 된다. 보안상 안전하지 않은 baseline은 production 실행이 아니라 historical, simulated, admin-only, 또는 이미 execution subject에게 허용된 resource 안의 비교로 제한한다.
- 일반 사용자와 workflow 작성자 화면에는 권한/정책상 제외된 문서명, KB id, source path/url/title, 정확한 제외 개수를 표시하지 않는다. 필요한 경우 `권한/정책상 제외된 내부 문서 일부`, bucketed count, safe reason summary 같은 낮은 해상도의 표현만 사용한다.
- Trace side panel과 A/B 비교 화면은 RAG mode, retrieval strategy, citation id, KB id, document version id, chunk id, rank/score, safe metadata summary, token/cost/latency summary만 표시한다. Raw chunk content, raw source title/path/url, raw prompt/completion/provider response, 권한 없는 문서명/ID는 표시하지 않는다.
- Knowledge/RAG는 collection permission의 action 의미와 retrieval access pattern을 정의한다. 최종 permission storage model, permission enum integration, inheritance/override behavior, 공통 permission helper 구현은 Auth/RBAC 도메인에서 ADR 또는 RBAC 문서로 확정한다.
- Ingestion lock은 단순 key 존재 여부만으로 release하면 안 된다. Lock release는 owner token을 비교해야 하며, 장기 작업은 TTL renew 또는 fencing token으로 stale worker finalization을 차단해야 한다.
- Content identity와 retrieval artifact identity는 같은 finalization boundary에서 움직인다. `content_hash` 또는 fingerprint가 새 값으로 보이면 해당 값에 대응하는 redacted canonical text, chunks, embeddings, index namespace, active version이 모두 commit된 상태여야 한다.
- Storage object, raw artifact, vector/index cleanup은 retry 가능한 outbox 작업으로 다룬다. Cleanup 실패는 safe audit/metric으로 남기고, DB rollback된 resource를 가리키는 scheduler나 storage side effect가 남지 않도록 idempotency key를 사용한다.

## Gates Before Implementation

다음 항목은 [ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)의 target semantic decision과 별개로 구현 전 gate가 필요하다.

- G1 destructive cutover/reset 승인 조건, legacy multi-document split/backfill, reindex/backup/rollback 계획.
- G2 source ACL materialization, source-managed KB의 KB `use` provisioning model, content cursor와 ACL/permission watermark 분리, ACL-only idempotency, revocation fast path, freshness epoch, candidate cache invalidation.
- G3 central outbound egress guard와 protocol adapter reason code.
- G4 protected source identity, HMAC key version, display metadata policy.
- G5 collection permission storage model과 helper-only evaluation.
- G6 active version finalization, owner-token/fencing 기반 ingestion lock, outbox, recovery scanner, content_hash/fingerprint commit boundary, external artifact cleanup contract.
- G7 resource hiding/API matrix, auto no-authorized-candidate lifecycle, hidden aggregate handling, partial result semantics.
- G8 post-cutover ID vocabulary와 citation identity.
- G9 canonical metadata source and sanitizer after `documents.meta_info` cutover.
- G10 raw artifact storage schema, raw/compliance permission enum, raw access audit action/reason code, retention/legal hold/purge SLA, terminal-status-only purge와 purge row locking/marker contract.
- G11 workflow runtime RAG execution subject resolution, service account 사용 조건, owner fallback 금지, trace/audit subject 표기 방식.
- G12 RAG strategy/A-B summary field, trace side panel 표시 allowlist, hidden/denied resource summary bucket 정책.

## Open Questions

- Collection permission storage를 resource-specific team/user tables로 둘지, 별도 subject table로 둘지.
- Auto/multi-KB request에서 hidden/denied/success 후보가 섞일 때 partial result를 허용할지.
- Load-test 기준 candidate cap, fanout concurrency, permission helper index strategy의 초기 운영값.
- Raw/compliance permission enum, inheritance, retention, export SLA를 어떤 RBAC ADR에서 확정할지.
- Source ACL sync가 source-owned KB `use` grant를 만들지, 아니면 관리자/team/user grant만 KB `use`를 충족시키고 source ACL은 별도 requester authorization gate로만 둘지.
