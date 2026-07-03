# Knowledge Requirements

Status: Draft
Related Features: auth, organization, workflow, agent-builder, connectors, audit-tracing, llm-credentials

## Purpose

흩어진 사내 문서와 데이터 source item을 자동 또는 수동으로 수집하고, workflow 생성과 실행에서 권한 범위 안의 근거만 검색할 수 있는 통합 RAG 기반을 제공한다. 현재 제품 방향에서는 전역 에이전트 Q&A보다 Workflow Builder가 LLM node의 RAG 옵션을 구성하고, 생성된 workflow가 실행 시점 execution subject 기준으로 검색하는 흐름을 우선한다. [PRD](../../PRD.md)의 FR-031~FR-033을 담당한다.

Workflow canvas에는 독립형 RAG 실행 노드를 도입하지 않는다. Knowledge retrieval, query rewrite, evidence sufficiency, source tier policy는 LLM node의 RAG 옵션으로 제공한다.

현재 구현은 manual Knowledge Base 생성, 문서 업로드/색인, metadata-aware retrieval, hierarchical RAG, standalone RAG Agent answer 기반을 제공한다. 목표 KB 통합 모델은 [ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)에 따라 Knowledge Base를 document/source item 단위 permission/retrieval/sync/lifecycle atom으로 재정의하고, Knowledge Collection을 grouping/routing/UX/ops 단위로 둔다. Knowledge Skill 경계는 [ADR-0015](../../decisions/ADR-0015-knowledge-skill-context-routing-boundary.md)를 따른다.

## 현재 Baseline

- `knowledge_bases`는 현재 코드에서 여러 `documents`를 포함할 수 있는 RAG data source 상위 단위다.
- Metadata-aware/hierarchical RAG 경계는 [ADR-0012](../../decisions/ADR-0012-metadata-aware-hierarchical-rag-boundary.md)를 따른다.
- Standalone RAG Agent answer와 trace/usage correlation 경계는 [ADR-0013](../../decisions/ADR-0013-rag-answer-trace-usage-correlation-boundary.md)를 따른다.
- Knowledge Skill은 [ADR-0015](../../decisions/ADR-0015-knowledge-skill-context-routing-boundary.md)에 따른 provider-neutral target artifact이며, 현재 구현 완료 상태가 아니다.
- 현재 `documents.meta_info`는 current metadata convention의 source of truth다.
- 목표 cutover 전까지 공식 문서는 현재 동작과 목표 모델을 분리해 읽어야 한다.

## 목표 모델

- `KnowledgeBase`: 문서/source item 1개에 대응하는 permission, retrieval, sync, lifecycle atom.
- `KnowledgeCollection`: 여러 document-level KB를 묶는 grouping, routing, UX, operations 단위.
- `DocumentVersion`: document-level KB의 canonical content/index version. 기본 retrieval은 active ready version만 사용한다.
- `Source-managed KB`: 외부 source connector가 생성/관리하는 KB. Retrieval에는 mbased KB `use`와 fresh source ACL/requester authorization이 모두 필요하다.
- `Redacted canonical text`: target chunk content, embedding input, retrieval-visible text artifact의 기본 원천.
- `Knowledge Skill`: Workflow Builder가 LLM node의 RAG 옵션을 구성할 때 source-of-truth tier 선택, collection/KB routing hint, query template, metadata filter, validation checklist를 제공하는 재사용 artifact. Skill은 권한 source나 최종 근거가 아니다.
- `Source-of-Truth Tier`: 정책 문서, ADR/decision record, semantic definition, curated query corpus 같은 근거 계층. Skill은 이 tier를 선택하는 절차를 제공할 뿐 source of truth가 되지 않는다.

## User Stories

- 빌더로서, 수동 업로드 또는 connector sync로 생성된 지식을 collection 단위로 탐색하고 상태를 확인하고 싶다.
- 플랫폼 관리자 또는 KB/collection manager로서, collection grouping/routing 권한과 KB content 권한을 분리해 관리하고 싶다.
- workflow 생성 권한자로서, 자연어 요청만으로 사내 지식 검색이 필요한 LLM node의 RAG 옵션이 포함된 workflow 초안을 받고 싶다.
- workflow 실행 사용자 또는 실행 주체로서, workflow runtime이 내 execution subject 권한 범위 안의 collection/KB 후보에서만 검색하고 citation을 남기길 원한다.
- 감사자로서, 특정 답변이 어떤 KB, document version, chunk에서 나왔는지 redaction-safe summary로 추적하고 싶다.
- 운영자로서, source sync 실패, source ACL stale, tombstone, 재색인, purge 상태를 raw content 노출 없이 확인하고 싶다.
- 도메인 오너로서, 반복되는 질문 유형에 맞는 Knowledge Skill의 안전한 절차/context/routing 경계를 정의하고 freshness/evaluation 상태를 관리할 수 있는 목표 기능을 원한다. 구체적인 작성 UI와 승인 UX는 아직 확정하지 않는다.

## Functional Requirements

- FR-031: Knowledge source item을 document-level KB로 수집·색인하고, 여러 KB를 Knowledge Collection으로 묶는다.
- FR-032: Auto collection mode는 collection routing scope와 KB permission helper 결과로 만든 safe candidate set만 router, Workflow Builder, 실행 시점 RAG 경로에 전달한다.
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
- FR-043: 운영 RAG mode는 이름이 `general`, `permission_based`, `task_aware`, `metadata_aware`, `hierarchical` 중 무엇이든 KB permission/source ACL/final evidence gate를 우회할 수 없다. `general RAG`는 authorized resource 안에서 넓게 검색하는 broad retrieval이고, `task-aware` 또는 `permission-scoped RAG`는 authorized resource 안에서 더 정밀하게 후보를 줄이는 retrieval이다.
- FR-044: RAG strategy 비교와 비용 최적화를 위해 retrieval summary는 `retrieval_strategy`, `rag_mode`, selected collection/KB count, retrieved chunk count, citation count, context token estimate, retrieval latency, permission filter 여부, policy result, partial result, safe exclusion summary를 redaction-safe 형태로 제공한다.
- FR-045: Source-managed KB에서 KB `use`가 어떤 경로로 충족되는지는 source ACL materialization gate에서 확정한다. Source ACL authorization은 KB `use`를 자동 대체하지 않으며, source-owned KB use grant를 도입하려면 저장 위치, freshness gate, revocation, audit-safe provenance, manual grant와의 결합 방식을 별도 ADR/RBAC 문서로 닫는다.
- FR-046: Knowledge ingestion은 같은 source item 또는 document-level KB에 대해 중복 finalization이 일어나지 않도록 owner-token lock, fencing token, database advisory lock, 또는 동등한 동시성 제어를 사용해야 한다. TTL 만료 뒤 stale worker가 새 worker의 lock이나 active artifact를 삭제/덮어쓰면 안 된다.
- FR-047: `content_hash`, chunking fingerprint, embedding model, active document version pointer, retrieval-visible index state는 실제 chunk/index artifact가 성공적으로 준비되고 finalization transaction이 끝난 뒤에만 committed processed state로 갱신한다. Chunk 저장 전 hash만 먼저 commit해 다음 실행이 stale/empty artifact를 처리 완료로 오판하게 해서는 안 된다.
- FR-048: Document/KB/raw artifact 삭제는 DB row와 object storage, vector index, external artifact cleanup을 outbox/reconciler로 조정해야 한다. DB commit 전에 physical object를 먼저 삭제해 orphan reference를 만들거나, cleanup 실패 때문에 hidden artifact가 retrieval-visible해지면 안 된다.
- FR-049: RAG answer retention purge와 answer lifecycle/audit/usage 기록은 idempotent하고 복구 가능해야 한다. Purge는 terminal status 대상만 처리하고 row lock, marker, `SKIP LOCKED` 계열 또는 동등한 방어로 동시 실행 중복과 running row 삭제를 막아야 한다. Audit/usage 강한 일관성이 필요한 경로는 transactional outbox 또는 reconcile 기준을 가져야 한다.
- FR-050: Knowledge Skill은 provider-neutral Nodease artifact로 정의한다. Skill은 Workflow Builder가 LLM node의 RAG 옵션을 구성할 때 사용할 source-of-truth 선택 절차, collection/KB routing hint, query template, metadata filter 후보, validation checklist, evaluation reference를 담을 수 있지만 권한을 부여하거나 permission decision을 수행하지 않는다.
- FR-051: 빌더 단계에는 organization scope, skill visibility, display policy, freshness/eval gate를 통과한 redaction-safe skill metadata만 workflow 생성 제안에 사용할 수 있다. Skill name/description/tag/source tier도 민감 metadata로 취급한다.
- FR-052: Skill이 제안한 collection/KB reference와 LLM node의 RAG 옵션은 실행 시점 권한을 보장하지 않는다. 생성된 workflow의 LLM node의 RAG 옵션은 실행 시점 `execution_subject` 기준으로 collection route, KB permission, source ACL/requester authorization, final evidence policy를 다시 통과해야 한다.
- FR-053: Skill body/resource에는 raw source content, raw source title/path/url, raw source principal, raw ACL fact, restricted document list, hidden KB id, credential value, raw prompt/completion/provider response를 저장하지 않는다. 실제 근거 content는 항상 workflow 실행 또는 테스트 실행의 authorized retrieval로 가져온다.
- FR-054: Skill freshness와 evaluation은 운영 workflow 생성 자동 후보와 실행 시점 RAG procedure gate다. `freshness_state`, `last_validated_at`, `source_version_refs`, `eval_status`, golden question/regression reference를 관리하고, stale 또는 review-required skill은 fail-closed 또는 remediation surface로 제한한다.
- FR-055: workflow draft, LLM node의 RAG 옵션, workflow test run, RAG strategy comparison은 skill id/version/freshness/eval status와 safe source-of-truth tier를 provenance summary로 남길 수 있다. Raw skill body나 hidden source reference는 durable audit/trace/usage summary에 저장하지 않는다.
- FR-056: Source-of-Truth Tier는 authorized evidence 안에서 ranking, tie-break, conflict resolution hint로만 사용한다. Tier는 KB permission/source ACL/final evidence gate를 대체하지 않으며, Skill이 source of truth로 승격되는 것도 아니다.
- FR-057: LLM node의 RAG 옵션은 목표 옵션으로 `query_rewrite_mode`를 가질 수 있다. 후보 값은 `off`, `template`, `llm_assisted`이며, rewrite는 user query와 safe skill/template만 사용하고 접근 가능한 collection/KB 범위를 넓히지 않는다. `llm_assisted` rewrite는 LLM 호출이므로 execution subject, generation model/credential, credential `use`, usage/cost 기록, timeout, token/cost budget, 실패 시 fallback 정책을 G14에서 닫기 전에는 구현하지 않는다.
- FR-058: LLM node의 RAG 옵션은 목표 옵션으로 `evidence_sufficiency_policy`를 가질 수 있다. 후보 값은 `off`, `minimum_evidence`, `strict_citation`이며, 초기 기본값과 threshold는 별도 gate에서 확정한다. 근거가 부족하면 LLM이 추측 답변을 만들지 않고 safe no-result 또는 insufficient-evidence 응답을 반환해야 한다.

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
- A/B 테스트나 비용 최적화 UI에서 `general RAG` baseline을 보여줄 때도 권한 없는 문서가 prompt, citation, trace, audit에 들어가면 안 된다. 보안상 안전하지 않은 baseline은 운영 실행이 아니라 historical, simulated, admin-only, 또는 이미 execution subject에게 허용된 resource 안의 비교로 제한한다.
- 일반 사용자와 workflow 작성자 화면에는 권한/정책상 제외된 문서명, KB id, source path/url/title, 정확한 제외 개수를 표시하지 않는다. 필요한 경우 `권한/정책상 제외된 내부 문서 일부`, bucketed count, safe reason summary 같은 낮은 해상도의 표현만 사용한다.
- Trace side panel과 A/B 비교 화면은 RAG mode, retrieval strategy, citation id, KB id, document version id, chunk id, rank/score, safe metadata summary, token/cost/latency summary만 표시한다. Raw chunk content, raw source title/path/url, raw prompt/completion/provider response, 권한 없는 문서명/ID는 표시하지 않는다.
- Knowledge/RAG는 collection permission의 action 의미와 retrieval access pattern을 정의한다. 최종 permission storage model, permission enum integration, inheritance/override behavior, 공통 permission helper 구현은 Auth/RBAC 도메인에서 ADR 또는 RBAC 문서로 확정한다.
- Skill은 source of truth가 아니라 source-of-truth 선택 절차다. 최종 citation/evidence는 KB/document version/chunk/ADR/decision record 같은 source-of-truth resource를 가리켜야 한다.
- Skill metadata가 먼저 로드되는 Builder UX/API를 만들더라도 전역 metadata 선노출은 금지한다. Builder에는 authorization-scoped safe skill metadata만 전달하고, skill hint는 실행 시점 permission helper 결과와 교집합 처리한다.
- Query rewrite 결과 원문은 raw prompt와 유사한 민감 입력으로 취급한다. Durable audit/trace/usage metadata에는 raw rewritten query를 저장하지 않고, rewrite 적용 여부와 전략 같은 safe summary만 저장한다.
- Evidence sufficiency 판정은 권한/정책상 제외된 문서의 존재를 암시하면 안 된다. 부족 사유는 `no_evidence`, `low_score`, `insufficient_citation`, `policy_filtered`, `operational_partial` 같은 safe reason class로 낮춘다.
- Skill authoring, test, review, publish UI는 아직 확정하지 않는다. Workflow Playground가 별도 실험 공간인지, canvas와 통합되는지, skill binding을 어떤 화면에서 조작하는지는 Workflow/Agent Builder/Knowledge 공동 UX gate에서 결정한다.
- Published 전 draft skill을 workflow 실험에서 허용할지 여부도 아직 제품 UX/API 결정 대상이다. 허용하더라도 운영 실행 시점 자동 후보가 될 수 없고, actor의 KB permission/source ACL/redaction/freshness/eval gate를 우회할 수 없다.
- 임의 코드 실행 skill은 이 feature 범위에서 승인하지 않는다. Code-bearing skill은 sandbox, approval workflow, egress guard, dependency policy, timeout/resource cap, audit gate가 닫힌 뒤 별도 ADR로만 도입한다.
- Ingestion lock은 단순 key 존재 여부만으로 release하면 안 된다. Lock release는 owner token을 비교해야 하며, 장기 작업은 TTL renew 또는 fencing token으로 stale worker finalization을 차단해야 한다.
- Content identity와 retrieval artifact identity는 같은 finalization boundary에서 움직인다. `content_hash` 또는 fingerprint가 새 값으로 보이면 해당 값에 대응하는 redacted canonical text, chunks, embeddings, index namespace, active version이 모두 commit된 상태여야 한다.
- Storage object, raw artifact, vector/index cleanup은 retry 가능한 outbox 작업으로 다룬다. Cleanup 실패는 safe audit/metric으로 남기고, DB rollback된 resource를 가리키는 scheduler나 storage side effect가 남지 않도록 idempotency key를 사용한다.

## Gates Before Implementation

다음 항목은 [ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)의 target semantic decision과 별개로 구현 전 gate가 필요하다.

- G1 destructive cutover/reset 승인 조건, legacy multi-document split/backfill, reindex/backup/rollback 계획.
- G2 source ACL materialization, source-managed KB의 KB `use` provisioning model, source-owned KB `use` grant 저장 방식, Auth/RBAC와 Knowledge helper 결합 방식, content cursor와 ACL/permission watermark 분리, ACL-only idempotency, revocation fast path, freshness epoch, candidate cache invalidation.
- G3 central outbound egress guard와 protocol adapter reason code.
- G4 protected source identity, HMAC key version, display metadata policy.
- G5 collection permission storage model과 helper-only evaluation.
- G6 active version finalization, owner-token/fencing 기반 ingestion lock, pre-finalized artifact visibility 차단, outbox retry/dead-letter, recovery scanner, content_hash/fingerprint commit boundary, external index success 후 DB finalize failure 복구, DB finalize success 후 cleanup failure retry, external artifact cleanup contract.
- G7 resource hiding/no-result/evidence insufficiency API matrix, auto no-authorized-candidate lifecycle, hidden aggregate handling, partial result semantics, `no_evidence`/`low_score`/`insufficient_citation`/`policy_filtered`/`operational_partial` response shape와 answer-run/audit/trace 생성 여부.
- G8 post-cutover ID vocabulary와 citation identity.
- G9 canonical metadata source and sanitizer after `documents.meta_info` cutover. `source_tier`, approval state, source freshness, version provenance를 KB/document version/chunk/canonical metadata 중 어디에 저장하고 어떤 값을 ranking과 citation summary의 canonical source로 삼을지 포함한다.
- G10 raw artifact storage schema, raw/compliance permission enum, raw access audit action/reason code, retention/legal hold/purge SLA, terminal-status-only purge와 purge row locking/marker contract.
- G11 workflow 실행 시점 RAG execution subject resolution, service account 사용 조건, owner fallback 금지, trace/audit subject 표기 방식.
- G12 RAG strategy/A-B summary field, trace side panel 표시 allowlist, hidden/denied resource summary bucket 정책.
- G13 Knowledge Skill registry/versioning, skill visibility permission, skill metadata display policy, freshness/eval gate, code-bearing skill sandbox policy, authoring/review/publish UX/API, Workflow Playground/canvas integration, deployment approval skill-binding policy.
- G14 Query rewrite mode, evidence sufficiency policy, source tier policy의 기본값, threshold, safe reason code, LLM node의 RAG 옵션 UI/UX, raw rewritten query retention 금지 범위. `llm_assisted` rewrite의 execution subject, model/credential 선택, credential `use` 권한, `llm_usage_logs` operation category, timeout, token/cost budget, 실패 fallback, load-test 기준을 포함한다.

## Open Questions

- Collection permission storage를 resource-specific team/user tables로 둘지, 별도 subject table로 둘지.
- Auto/multi-KB request에서 hidden/denied/success 후보가 섞일 때 partial result를 허용할지.
- Load-test 기준 candidate cap, fanout concurrency, permission helper index strategy의 초기 운영값.
- Raw/compliance permission enum, inheritance, retention, export SLA를 어떤 RBAC ADR에서 확정할지.
- Source ACL sync가 source-owned KB `use` grant를 만들지, 아니면 관리자/team/user grant만 KB `use`를 충족시키고 source ACL은 별도 requester authorization gate로만 둘지.
- Skill visibility와 collection/KB permission을 어떤 helper contract로 결합할지.
- Skill eval/golden question dataset을 Knowledge가 소유할지, Evaluation/Experiment feature가 소유할지.
- Workflow 생성자가 skill을 어떤 UI에서 작성하거나 선택할지, Workflow Playground에서 draft/unpublished skill 실험을 허용할지, 배포 승인 요청에 skill binding과 eval summary를 어떻게 포함할지.
