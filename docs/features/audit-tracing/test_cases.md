# Audit Tracing Test Cases

Status: Draft
이 문서는 Audit/Tracing feature가 Knowledge/RAG, Workflow, Cost Optimizer와 연결될 때 raw 또는 hidden resource 정보를 저장하지 않는지 검증한다.

## Unit Tests

- Audit metadata sanitizer는 raw source id/url/path/title, raw source principal, raw source ACL row, raw chunk content, raw prompt/completion, credential value, `encrypted_config`, raw exception을 제거한다.
- Authorized retrieval summary allowlist는 KB id, document version id, chunk id, citation id, optional collection id, rank/score, safe metadata summary, policy result, latency/cost/token aggregate, retryability, opaque correlation/request id, `retrieval_strategy`, `rag_mode`, authorized/selected/retrieved count summary, `context_token_estimate`, `permission_filter_applied`, `safe_exclusion_summary`, `query_rewrite_applied`, `query_rewrite_strategy`, `evidence_sufficient`, `insufficiency_reason`, `source_tier_policy`, `source_tier_used`, `fanout_concurrency`, `fanout_timeout_seconds`, `failure_policy`만 허용한다.
- Audit/trace metadata sanitizer는 raw rewritten query를 raw prompt와 같은 민감 입력으로 보고 durable metadata와 log에서 제거한다.
- Hidden/denied/resource-hidden summary allowlist는 sanitized reason class, actor/org scope, request/correlation id, coarse retryability만 허용하고 exact hidden/denied count나 hidden KB id를 거부한다.
- Partial result summary는 `partial_result=true`, bucketed reason summary, retryability, request/correlation id만 허용한다.

## API Tests

- Raw/compliance access audit은 content 반환 전에 성공해야 하며, audit metadata에는 raw content, raw source id/url/path/title, raw principal, object storage key를 저장하지 않는다.
- Policy block, permission denied, requester source authorization denied, source ACL stale/unmapped/ambiguous/unverified/revoked, connector/egress failure는 raw exception 없이 sanitized reason code로 기록된다.
- Permission grant/update/revoke endpoint는 manual audit과 ORM listener audit이 중복되어 같은 mutation을 두 번 기록하지 않는다. Core upsert 또는 bulk delete를 쓰는 endpoint 경로도 permission row별 canonical action을 정확히 한 번 남긴다.
- RAG strategy/A-B summary API는 권한 없는 문서명/ID, raw source metadata, raw prompt/completion, content preview를 반환하지 않는다.
- RAG strategy/A-B summary API는 query rewrite 적용 여부, evidence sufficiency 결과, source tier summary를 safe field로 반환할 수 있지만 raw rewritten query와 hidden source reference를 반환하지 않는다.

## E2E Tests

- Workflow runtime RAG trace는 명시 execution subject, workflow/run/node id, safe citation/retrieval summary를 연결하지만 raw prompt, raw answer, raw chunk content를 저장하지 않는다.
- Standalone Agent answer는 `rag_answer_runs`와 opaque `correlation_id`로 audit/usage를 연결하고 trace/usage table에 RAG-specific FK를 만들지 않는다.
- Cost Optimizer의 RAG 포함 비교 화면은 safe retrieval summary와 비용/latency 집계만 표시한다.

## Permission Tests

- Trace/audit 조회 권한이 없는 사용자는 hidden/denied resource summary를 통해 문서명, source path, exact count를 추론할 수 없다.
- Raw/compliance permission이 없는 사용자는 raw content와 raw source metadata access audit detail을 볼 수 없다.
- Organization scope 밖 audit/trace resource는 resource hiding 정책에 따라 숨긴다.

## Edge Cases

- Sanitizer가 모르는 payload field는 기본 deny 또는 drop으로 처리한다.
- Audit/trace retention 정책은 raw artifact retention 정책을 대체하지 않는다.
- Redaction service 장애 시 raw payload를 fallback으로 저장하지 않는다.
