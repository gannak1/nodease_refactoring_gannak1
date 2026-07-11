# Audit Tracing Requirements

Status: Draft
Related Features: auth, organization, workflow, llm-credentials, deployment, knowledge

## Purpose

Audit와 trace는 workflow 실행, RAG retrieval, LLM 호출, permission/policy 차단, 운영 작업을 추적한다. Canonical action naming은 [ADR-0008](../../decisions/ADR-0008-audit-action-naming-standard.md)을 따르고, Security Alert eligible audit와 lifecycle 경계는 [ADR-0028](../../decisions/ADR-0028-security-alert-detection-and-lifecycle.md), 상세 기능 계약은 [security-alert](../security-alert/requirements.md)을 따른다. RAG trace 저장 경계는 [ADR-0012](../../decisions/ADR-0012-metadata-aware-hierarchical-rag-boundary.md), standalone RAG answer correlation 경계는 [ADR-0013](../../decisions/ADR-0013-rag-answer-trace-usage-correlation-boundary.md), Knowledge 통합 임시 baseline은 [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)을 따른다.

## User Stories

- 감사자로서, 사용자의 RAG answer가 어떤 redaction-safe retrieval/citation summary를 사용했는지 확인하고 싶다.
- 플랫폼 관리자로서, permission denied, policy block, source ACL stale, connector sync failure를 raw content 없이 추적하고 싶다.
- 운영자로서, retention/purge, retry/dead-letter, partial result 같은 운영 이벤트를 안전한 reason code로 보고 싶다.
- Organization manager로서, member access 관리 조치의 수행자, 대상, optional reason과 안전한 변경 전후 상태를 audit detail에서 확인하고 싶다.
- Organization owner/manager로서, Security Alert 근거 audit를 raw metadata 없이 확인하고 alert 대응 lifecycle도 canonical audit로 추적하고 싶다.

## Functional Requirements

- Audit metadata는 raw secret, credential value, raw source content, raw source ACL, raw source id/url/path/title을 저장하지 않는다. Raw/compliance access audit도 safe reference, decision, reason code, retention/legal-hold summary 같은 allowlist만 저장한다.
- RAG retrieval 성공은 `rag.retrieve`, standalone answer lifecycle은 `rag.answer.*`로 구분한다.
- Standalone answer는 `rag_answer_runs`와 `correlation_id`로 trace/usage/audit을 느슨하게 연결하고, trace/usage table에 RAG 전용 FK를 만들지 않는다.
- Knowledge source sync, source ACL mapping, partial result, egress guard failure는 sanitized reason code와 retryability 중심으로 기록한다.
- Auto-ingested KB use provisioning audit은 source ACL fact를 KB `use`로 오해하지 않게 구분한다. Source authorization provenance update, explicit KB `use` grant provisioning, requester source ACL evaluation은 서로 다른 safe action/reason/metadata로 구분해야 한다.
- Trace redaction storage policy는 Audit/Tracing이 소유하되, PII/secret detector와 masking engine은 shared privacy/redaction boundary로 분리해 Knowledge ingestion도 재사용한다 ([ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)).
- Raw Knowledge artifact access audit은 content 반환 전에 성공해야 하며, audit metadata에는 raw content, raw source id/url/path/title, raw principal, object storage key를 저장하지 않는다.
- Skill usage summary는 redaction-safe allowlist만 사용한다. 허용값은 workflow draft/LLM node의 RAG 옵션/test run에서 사용한 skill id, skill version, freshness state, eval status, safe source-of-truth tier, safe provenance ref, request/correlation id다.
- Workflow LLM node prompt trace가 RAG context를 포함한 provider 호출을 기록하더라도, durable trace payload에는 Knowledge context 원문이나 chunk body를 중복 저장하지 않는다. 저장 payload는 redacted marker, safe summary, count/strategy metadata 같은 allowlist만 사용할 수 있다.
- Access-management mutation은 canonical action, actor, current organization, target member/resource, optional reason, safe before/after를 기록해야 한다. MBA-188에서는 mutation과 AuditLog row를 같은 DB transaction에 기록하며 audit 실패 후 mutation만 성공해서는 안 된다. Durable outbox 일반화는 MBA-189 범위다 ([ADR-0023](../../decisions/ADR-0023-audit-actor-access-management-boundary.md)).
- Audit actor visibility는 organization mutation capability를 부여하지 않는다. Audit `auditor`/`raw_auditor`는 audit list/detail만 조회할 수 있고 actor access profile/mutation은 ADR-0009의 organization manager 판정을 별도로 통과해야 한다.
- Audit detail의 change summary는 target/action별 allowlist로 생성한다. Manual recorder는 update에도 organization provenance를 포함한 complete safe snapshot을 저장한다. Create/delete/update에 필요한 snapshot provenance가 request organization과 일치할 때만 summary를 반환한다. Generic `before`/`after` JSON을 그대로 반환하지 않으며 unknown target/action은 summary를 제공하지 않는다.
- Access-management 진입점을 이유로 row-level canonical audit과 별도 aggregate action을 중복 기록하지 않는다. No-op mutation도 audit을 만들지 않는다.
- Listener-tracked access mutation을 manual transaction audit이 소유할 때는 repository adapter가 object를 dirty/add/delete 상태로 만들기 전에 model/object/operation 단위 ownership을 등록하고 해당 listener candidate만 제외해야 한다. Ownership 등록부터 mutation/UoW flush 사이에는 query/autoflush를 허용하지 않으며 commit/rollback 뒤 suppression state를 다음 transaction으로 누출하지 않는다.
- Scope 안 actor access policy block은 scoped organization membership을 target으로 `policy.block` + `action` category의 failure event를 기록하고 `target_user_id`, `requested_action`, machine `policy_reason`, sanitized optional `reason`과 scope가 확인된 opaque resource/team id만 저장한다. Permission 부족은 `permission.denied`를 사용하되 target scope 확인 전에는 target-aware metadata를 남기지 않는다. Validation, hidden resource, no-op은 actor access audit 대상이 아니다.
- Security Alert 탐지 대상 `permission.denied`는 audit 생성 시점에 검증된 `audit_metadata.organization_id`와 safe target을 제공해야 한다. Detector가 resource table을 다시 조회해 organization을 추론하게 해서는 안 된다.
- 모든 `policy.block` producer는 최상위 `audit_metadata.policy_reason`에 `{domain}.{reason}` canonical 값을 기록해야 한다. Legacy reason mapping과 Security Alert allowlist는 ADR-0028을 따른다.
- Security Alert 최초 생성은 `security_alert.detected`, 관리자 확인·재개·해결은 `security_alert.acknowledged/reopened/resolved`로 기록해야 한다. Alert 최초 row/evidence/detected audit과 lifecycle mutation/audit은 각각 같은 transaction에 기록해야 하며 cooldown occurrence 갱신은 별도 action을 만들지 않는다.
- Security Alert evidence는 `audit_logs` row를 연결만 하고 raw metadata/before/after를 복사하지 않아야 한다. Alert evidence API는 기존 audit allowlist를 따르는 safe projection만 반환해야 한다.
- System schedule 실행 audit은 `actor_id=NULL`, `actor_type=system`을 사용하며 App/deployment creator나 workflow owner를 actor로 합성하지 않는다. Schedule WorkflowRun executor도 null이고 private RAG 권한은 ADR-0018의 anonymous public-only 경계를 따른다.
- Schedule outcome unknown acknowledgment는 `schedule_dispatch.outcome_reviewed` action, `schedule_dispatch_claim` target과 exact claim id를 사용한다. Metadata는 durable `organization_id`, allowlisted `operation_correlation_id`, `outcome_resolution_code`만 허용하고 두 operation field는 정확한 action/target 조합에서만 detail에 표시한다. Raw incident note, provider response, workflow input/output를 저장하지 않는다 ([ADR-0029](../../decisions/ADR-0029-distributed-schedule-dispatch-claim.md)).
- System schedule의 WorkflowRun 완료/실패 audit organization은 queue나 nullable run user가 아니라 exact task/run/deployment correlation을 통과한 durable schedule claim에서 가져온다. Claim과 current deployment/App provenance가 충돌하면 다른 조직으로 귀속하지 않고 audit 생성을 fail-closed한다.
- Schedule outcome review claim update와 AuditLog는 같은 UnitOfWork에서 commit한다. Recorder가 생성한 audit id만 claim에 연결하며 CLI가 audit id/actor id를 입력하거나 adapter가 독립 commit해서는 안 된다.
- Schedule WorkflowRun visibility signal은 `schedule_dispatch.workflow_run_missing`, `schedule_dispatch_claim` exact target, `actor_id=NULL`, `actor_type=system`을 사용한다. Metadata는 canonical `organization_id`와 fixed reason만 허용하며 claim marker와 audit을 같은 UnitOfWork에서 한 번만 기록한다. 이는 Log System 지연/누락 관측이며 WorkflowRun 재생성, engine replay, raw run identity 또는 payload 보관을 의미하지 않는다.
- Schedule-correlated WorkflowRun의 Log System create/finish/error 재시도는 raw storage/provider exception을 로그 또는 retry result에 전달하지 않고, static operation label과 exception type만 기록해야 한다.
- `Schedule.next_run_at`/`last_run_at` system operational update는 generic configuration data-change audit에서 field-level 제외한다. Cron/timezone/activation/lifecycle 변경 audit과 unrelated tracked mutation은 유지하며 claim ledger를 generic listener 대상으로 추가하지 않는다.

## Policies And Edge Cases

- Success/authorized path와 hidden/denied/resource-hidden path의 allowlist를 분리한다.
- Authorized retrieval/answer path는 redaction-safe id와 summary만 저장할 수 있다. 허용되는 값은 KB id, document version id, chunk id, citation id, optional collection id, score/rank summary, safe metadata summary, policy result, latency/cost/token aggregate, retryability, opaque correlation/request id, `retrieval_strategy`, `rag_mode`, authorized/selected/retrieved count summary, `context_token_estimate`, `permission_filter_applied`, `safe_exclusion_summary`, `query_rewrite_applied`, `query_rewrite_strategy`, `evidence_sufficient`, `insufficiency_reason`, `source_tier_policy`, `source_tier_used`, `fanout_concurrency`, `fanout_timeout_seconds`, `failure_policy`다. Raw rewritten query는 저장하지 않는다.
- Hidden/denied/resource-hidden path는 sanitized reason class, request/correlation id, actor/org scope, 필요한 경우 coarse retryability, audit action/status만 저장한다. Raw source id/url/path/title, raw source principal, source distribution, raw ACL fact, exact hidden/denied count, raw query, raw answer, raw prompt/completion, content preview, raw exception은 저장하지 않는다.
- Partial result audit/trace는 `partial_result=true`, bucketed reason summary, retryability, correlation/request id만 저장한다.
- Prompt trace와 RAG retrieval trace는 서로 다른 payload kind를 사용할 수 있지만 raw evidence 저장 금지 기준은 동일하게 적용한다. RAG context block, citation preview, chunk body를 디버깅 편의 목적으로 durable trace에 복사하지 않는다.
- Source ACL mapping audit는 safe principal reference만 저장하고 raw email/path/title/url은 저장하지 않는다.
- Raw/compliance access permission 이름은 RBAC ADR에서 최종 확정한다. 테스트나 구현에서 임시 이름을 영구 enum처럼 사용하지 않는다.
- Raw/compliance access event는 actor, organization, KB/document version safe reference, reason code, decision, retention/legal-hold state summary, request id 정도의 allowlist만 저장한다.
- Skill audit/trace metadata에는 raw skill body, hidden source refs, raw source title/path/url, restricted document list, raw eval fixture, raw prompt/completion/provider response를 저장하지 않는다.
- User-entered management reason은 JSON body로 받는다. CRLF/CR을 LF로 정규화하고 trim한 blank는 null로 바꾸며, 정규화 후 500 Unicode code point를 초과하거나 tab/LF 외 C0/C1 및 bidi override/isolate control을 포함하면 거부한다. Durable audit 전 organization 설정으로 약화할 수 없는 shared fail-closed redaction baseline으로 secret/PII pattern을 치환하고 sanitization 실패 시 raw reason이나 mutation을 저장하지 않는다. Query string이나 URL에 reason을 전달하지 않는다.
- Actor snapshot은 historical attribution을 위해 보존할 수 있지만 target user email/name을 mutation metadata에 불필요하게 중복 저장하지 않는다.
- 전체 sync/async/outbox audit producer 이관, retry/dead-letter 일반화, read repository 분리는 MBA-188 범위가 아니며 Linear MBA-189에서 다룬다.
- Security Alert detector/reconciler 실패는 원래 permission/policy 판단이나 audit 저장 결과를 바꾸지 않아야 한다. 기능 활성화 이전 audit은 alert로 backfill하지 않는다.

## Open Questions

- Knowledge source sync와 egress guard failure의 canonical audit action/reason code를 어느 ADR에서 확정할지.
- Generic non-workflow trace subject를 도입할지, RAG-owned summary + correlation convention을 유지할지.
- Skill publication/review/deprecation audit action과 skill eval summary action을 별도 ADR로 둘지.
