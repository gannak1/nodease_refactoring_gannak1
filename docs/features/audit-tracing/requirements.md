# Audit Tracing Requirements

Status: Draft
Related Features: auth, organization, workflow, llm-credentials, deployment, knowledge

## Purpose

Audit와 trace는 workflow 실행, RAG retrieval, LLM 호출, permission/policy 차단, 운영 작업을 추적한다. Canonical action naming은 [ADR-0008](../../decisions/ADR-0008-audit-action-naming-standard.md)을 따르고, RAG trace 저장 경계는 [ADR-0012](../../decisions/ADR-0012-metadata-aware-hierarchical-rag-boundary.md), standalone RAG answer correlation 경계는 [ADR-0013](../../decisions/ADR-0013-rag-answer-trace-usage-correlation-boundary.md)를 따른다.

## User Stories

- 감사자로서, 사용자의 RAG answer가 어떤 redaction-safe retrieval/citation summary를 사용했는지 확인하고 싶다.
- 플랫폼 관리자로서, permission denied, policy block, source ACL stale, connector sync failure를 raw content 없이 추적하고 싶다.
- 운영자로서, retention/purge, retry/dead-letter, partial result 같은 운영 이벤트를 안전한 reason code로 보고 싶다.

## Functional Requirements

- Audit metadata는 raw secret, credential value, raw source content, raw source ACL, raw source id/url/path/title을 저장하지 않는다. Raw/compliance access audit도 safe reference, decision, reason code, retention/legal-hold summary 같은 allowlist만 저장한다.
- RAG retrieval 성공은 `rag.retrieve`, standalone answer lifecycle은 `rag.answer.*`로 구분한다.
- Standalone answer는 `rag_answer_runs`와 `correlation_id`로 trace/usage/audit을 느슨하게 연결하고, trace/usage table에 RAG 전용 FK를 만들지 않는다.
- Knowledge source sync, source ACL mapping, partial result, egress guard failure는 sanitized reason code와 retryability 중심으로 기록한다.
- Trace redaction storage policy는 Audit/Tracing이 소유하되, PII/secret detector와 masking engine은 shared privacy/redaction boundary로 분리해 Knowledge ingestion도 재사용한다 ([ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)).
- Raw Knowledge artifact access audit은 content 반환 전에 성공해야 하며, audit metadata에는 raw content, raw source id/url/path/title, raw principal, object storage key를 저장하지 않는다.
- Skill usage summary는 redaction-safe allowlist만 사용한다. 허용값은 workflow draft/LLM node의 RAG 옵션/test run에서 사용한 skill id, skill version, freshness state, eval status, safe source-of-truth tier, safe provenance ref, request/correlation id다.

## Policies And Edge Cases

- Success/authorized path와 hidden/denied/resource-hidden path의 allowlist를 분리한다.
- Authorized retrieval/answer path는 redaction-safe id와 summary만 저장할 수 있다. 허용되는 값은 KB id, document version id, chunk id, citation id, optional collection id, score/rank summary, safe metadata summary, policy result, latency/cost/token aggregate, retryability, opaque correlation/request id, `query_rewrite_applied`, `query_rewrite_strategy`, `evidence_sufficient`, `insufficiency_reason`, `source_tier_used`다. Raw rewritten query는 저장하지 않는다.
- Hidden/denied/resource-hidden path는 sanitized reason class, request/correlation id, actor/org scope, 필요한 경우 coarse retryability, audit action/status만 저장한다. Raw source id/url/path/title, raw source principal, source distribution, raw ACL fact, exact hidden/denied count, raw query, raw answer, raw prompt/completion, content preview, raw exception은 저장하지 않는다.
- Partial result audit/trace는 `partial_result=true`, bucketed reason summary, retryability, correlation/request id만 저장한다.
- Source ACL mapping audit는 safe principal reference만 저장하고 raw email/path/title/url은 저장하지 않는다.
- Raw/compliance access permission 이름은 RBAC ADR에서 최종 확정한다. 테스트나 구현에서 임시 이름을 영구 enum처럼 사용하지 않는다.
- Raw/compliance access event는 actor, organization, KB/document version safe reference, reason code, decision, retention/legal-hold state summary, request id 정도의 allowlist만 저장한다.
- Skill audit/trace metadata에는 raw skill body, hidden source refs, raw source title/path/url, restricted document list, raw eval fixture, raw prompt/completion/provider response를 저장하지 않는다.

## Open Questions

- Knowledge source sync와 egress guard failure의 canonical audit action/reason code를 어느 ADR에서 확정할지.
- Generic non-workflow trace subject를 도입할지, RAG-owned summary + correlation convention을 유지할지.
- Skill publication/review/deprecation audit action과 skill eval summary action을 별도 ADR로 둘지.
