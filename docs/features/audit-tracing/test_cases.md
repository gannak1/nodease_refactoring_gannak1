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
- KB permission grant/revoke endpoint는 `team_knowledge_permission.*`/`user_knowledge_permission.*` data-change audit row를 권한 row mutation과 같은 DB transaction에 추가하며, 비동기 audit 발행 실패가 권한 변경 성공 뒤 audit 누락으로 이어지지 않는다.
- MBA-188 access-management mutation은 membership/team/user-direct/App-creation row mutation과 canonical AuditLog row를 같은 DB transaction에 추가한다. Durable outbox로 대체하지 않으며 Audit add/flush/commit 실패 시 mutation도 rollback한다.
- Access-management no-op은 canonical audit을 만들지 않고, applied mutation은 ORM listener/manual recorder 중 하나의 owner를 통해 정확히 한 번 기록한다.
- Manual audit ownership은 listener-tracked object를 dirty/add/delete로 만들기 전에 등록되고, 같은 Session의 unrelated object audit은 유지되며 commit/rollback/soft-rollback 후 suppression state가 비워진다.
- Ownership 등록부터 mutation/UoW flush 사이 query/autoflush가 발생하는 regression을 차단한다.
- Scope 안 self/last-manager/manager-override/member-state/target-user-inactive/stale block은 scoped membership target의 `policy.block` + action category failure audit 한 건을 남기고, caller 권한 부족은 `permission.denied`를 남긴다. Target scope 확인 전 denial metadata에는 target user/resource/team 정보가 없어야 한다.
- Validation 422, hidden 404, desired-state no-op은 actor access audit을 만들지 않는다. Policy-block audit commit 실패는 500이며 mutation은 없다.
- Audit detail `change_summary`는 정확한 target/action 조합의 allowlist field만 반환한다. Target만 맞고 action이 다르거나 unknown target/action이면 null이다.
- Create는 `after`, delete는 `before`, update는 양쪽 complete safe snapshot의 organization provenance가 request organization과 일치할 때만 `change_summary`를 반환한다. 한쪽 provenance가 누락되거나 다르면 null이다.
- Audit detail allowlist metadata는 UUID/scalar/canonical enum/count type까지 검증한다. 기존 sanitized JSON `summary` 외 허용 key가 nested object이거나 malformed UUID, unknown policy/resource type 또는 boolean count면 해당 field를 생략하고 list/detail을 실패시키지 않는다.
- Audit `auditor`/`raw_auditor`는 audit list/detail을 조회할 수 있지만 actor access profile/team-membership/resource/action API는 `403`이다.
- Security Alert evidence API는 실제 연결된 audit만 `AuditLogSchema` 수준으로 반환하고 generic metadata/before/after/change summary를 inline 노출하지 않는다.
- Audit `auditor`/`raw_auditor` only user는 기존 audit list/detail을 조회할 수 있어도 Security Alert list/detail/evidence/lifecycle API는 `403`이어야 한다.
- Security Alert 최초 생성 또는 lifecycle audit insert가 실패하면 대응 alert transaction도 rollback하고, cooldown occurrence 갱신은 lifecycle audit을 추가하지 않아야 한다.
- Schedule budget/outcome recorder는 access-management recorder나 legacy user helper를 재사용하지 않고 `actor_id=null`, `actor_type=system`, canonical organization과 strict metadata만 caller UoW에 추가한다.
- `schedule_dispatch.outcome_reviewed` detail은 exact claim target과 같은 organization에서만 조회되고 allowlisted operation correlation/resolution만 반환한다. 다른 조직은 404이고 malformed correlation/resolution 또는 nested/raw metadata는 생략한다.
- Outcome review audit insert/flush가 실패하면 claim review field도 rollback하고, recorder가 생성하지 않은 audit id를 claim에 연결할 수 없다.
- WorkflowRun visibility grace를 지난 claim은 exact claim target의 `schedule_dispatch.workflow_run_missing` audit과 one-time marker를 같은 transaction으로 남긴다. 중복 scan은 audit을 추가하지 않고, raw run id/input/output/provider response를 저장하거나 engine을 replay하지 않는다.
- Schedule-correlated WorkflowRun Log System write가 재시도되면 raw storage/provider detail은 logger와 retry exception에 없고, static operation label과 error type만 남는다.
- Schedule operational timestamp만 갱신하면 generic `schedule.updated`가 생성되지 않지만 cron/timezone/lifecycle 변경과 같은 transaction의 unrelated tracked mutation audit은 유지된다.
- RAG strategy/A-B summary API는 권한 없는 문서명/ID, raw source metadata, raw prompt/completion, content preview를 반환하지 않는다.
- RAG strategy/A-B summary API는 query rewrite 적용 여부, evidence sufficiency 결과, source tier summary를 safe field로 반환할 수 있지만 raw rewritten query와 hidden source reference를 반환하지 않는다.

## E2E Tests

- Workflow runtime RAG trace는 명시 execution subject, workflow/run/node id, safe citation/retrieval summary를 연결하지만 raw prompt, raw answer, raw chunk content를 저장하지 않는다.
- Standalone Agent answer는 `rag_answer_runs`와 opaque `correlation_id`로 audit/usage를 연결하고 trace/usage table에 RAG-specific FK를 만들지 않는다.
- Cost Optimizer의 RAG 포함 비교 화면은 safe retrieval summary와 비용/latency 집계만 표시한다.
- Organization manager가 audit actor를 정지/재활성화하면 `organization.member.update` audit의 optional reason과 safe membership before/after를 같은 audit tab에서 확인할 수 있다.
- Direct permission revoke 후 team source가 남는 경우 audit은 direct row deletion만 기록하고 UI effective access는 remaining team source를 반영한다.
- Security Alert detail의 evidence에서 audit detail로 이동해도 기존 organization scope와 metadata allowlist를 우회하지 않아야 한다.
- Protected outcome review job은 product audit에 system actor/canonical organization/operation correlation만 남기고 human operator identity는 platform IAM audit에 남긴다. Acknowledgment 뒤에도 workflow redrive가 발생하지 않는다.
- System schedule 실행 중 deployment가 삭제되어 WorkflowRun deployment FK가 null이 되어도 exact task/run claim의 durable organization으로 완료/실패 audit을 기록한다. Live deployment가 남아 있는데 run/claim/deployment/App provenance가 충돌하면 fail-closed한다.

## Permission Tests

- Trace/audit 조회 권한이 없는 사용자는 hidden/denied resource summary를 통해 문서명, source path, exact count를 추론할 수 없다.
- Raw/compliance permission이 없는 사용자는 raw content와 raw source metadata access audit detail을 볼 수 없다.
- Organization scope 밖 audit/trace resource는 resource hiding 정책에 따라 숨긴다.
- Actor id가 존재해도 target membership/team/resource가 current organization scope 밖이면 actor management API는 404로 숨기고 target name/count를 audit metadata나 error detail에 포함하지 않는다.

## Edge Cases

- Sanitizer가 모르는 payload field는 기본 deny 또는 drop으로 처리한다.
- Audit/trace retention 정책은 raw artifact retention 정책을 대체하지 않는다.
- Redaction service 장애 시 raw payload를 fallback으로 저장하지 않는다.
- Generic AuditLog before/after에 allowlist 밖 column 또는 nested secret이 있어도 change summary에 포함하지 않는다.
- Stored organization provenance가 request organization과 다르거나 필요한 snapshot에 없으면 change summary는 null이고, historical same-org target은 opaque id만 반환하며 name/path를 resolve하지 않는다.
- Concurrent last-manager 또는 permission mutation은 applied mutation당 canonical audit 한 건만 남긴다.
- Management reason은 blank를 null로 정규화하고 500자 초과 또는 forbidden control character를 거부한다.
- Management reason의 CRLF/trim/Unicode code-point 경계와 bidi control을 검증하고, common secret/PII는 durable audit 전에 redacted한다.
- Reason redaction/sanitization 실패는 raw fallback 없이 access mutation과 audit을 모두 rollback한다.
- Schedule/Deployment가 삭제된 뒤에도 claim의 durable organization provenance로 outcome review audit을 올바른 조직에 귀속하고 다른 조직에서 조회하지 못한다.
- System schedule WorkflowRun audit은 exact claim task id, workflow run id, deployment id가 모두 일치할 때만 claim organization을 사용한다. Current deployment가 존재하면 App workflow/organization도 일치해야 하며, queue/run/claim 불일치에서는 잘못된 조직 audit을 생성하지 않는다.
