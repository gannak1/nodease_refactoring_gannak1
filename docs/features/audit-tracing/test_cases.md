# Audit Tracing Test Cases

Status: Draft
이 문서는 Audit/Tracing feature가 Knowledge/RAG, Workflow, Cost Optimizer와 연결될 때 raw 또는 hidden resource 정보를 저장하지 않는지 검증한다.

## Unit Tests

- `audit_event_outbox` schema는 audit payload JSONB와 고정된 audit event id 기반 idempotency key를 보존하고, pending/leased/succeeded/retry/dead-letter 상태, lease owner/만료, 최대 5회 재시도에 필요한 counter와 retry 시각을 가진다. 이 테이블은 business resource FK 없이 독립적으로 insert 가능하며 status/retry와 status/lease 조회 인덱스를 제공한다.
- Rollout 4의 `record_audit()`은 audit payload를 한 번만 직렬화해 고정 audit event id를 Outbox idempotency key에 사용한다. Caller session이 있으면 commit하지 않고 같은 transaction에 row를 추가하며, session이 없으면 짧은 독립 transaction으로 Outbox를 commit한다.
- Outbox 저장 성공 시 고정 audit event id를 반환하고 실패 시 `None`을 반환한다. 실패 로그에는 payload, raw exception detail, secret이 없어야 하며 Redis/broker fallback을 시도하지 않는다.
- Rollout 3의 Audit Outbox worker는 due row를 `FOR UPDATE SKIP LOCKED`로 lease하고 lease/attempt 증가를 먼저 commit한 뒤 처리한다. AuditLog insert, Outbox `succeeded` 전환, 성공 payload의 `{}` 교체는 같은 transaction에서 commit하며 기존 `audit_logs.id`가 있으면 멱등 성공으로 처리한다. 성공 row는 idempotency tombstone을 유지하고 retry/dead-letter row는 payload를 유지한다.
- Audit Outbox worker는 owner token이 일치하는 lease만 완료/재시도할 수 있다. 만료 lease는 복구하고 저장 실패는 safe reason code로 최대 5회 재시도한 뒤 `dead_lettered`로 전환하며 raw payload나 exception detail을 reason/log에 남기지 않는다.
- Audit Outbox 처리 성공 뒤 Security Alert 탐지 task를 commit 이후에 발행한다. 이 후속 발행 실패는 이미 저장한 AuditLog/Outbox 성공 transaction을 되돌리지 않으며 Security Alert reconciliation이 누락 탐지를 복구할 수 있다.
- `audit.event_outbox.process`는 Log queue에 등록되고 Celery Beat가 30초마다 실행한다. Rollout 4의 `record_audit()`은 `celery_app.send_task("audit.record")`를 호출하지 않는다.
- 배포 직전에 broker에 들어간 legacy 메시지를 소진할 수 있도록 `audit.record` consumer는 호환성 task로 유지하되 신규 producer에서는 더 이상 사용하지 않는다.
- `audit_logs.workflow_run_id`와 `workflow_node_run_id`는 nullable UUID FK와 개별 조회 인덱스를 가진다. 참조 실행이 삭제돼도 감사 행은 보존되도록 `ON DELETE SET NULL`을 사용한다.
- Correlation migration은 기존 `audit_metadata.workflow_run_id`/`workflow_node_run_id`와 `organization_id`가 정상 UUID이고 실제 대상 row가 존재하며 Run의 Workflow 조직이 audit 조직과 같을 때만 typed 컬럼으로 backfill한다. malformed/orphan/cross-organization 값은 migration을 실패시키지 않고 NULL로 남긴다.
- Outbox worker와 호환 `audit.record` consumer는 top-level correlation을 우선하고 기존 metadata correlation을 호환 입력으로 읽어 같은 typed AuditLog 컬럼에 저장한다.
- Audit list/detail safe projection은 nullable `workflow_run_id`/`workflow_node_run_id`를 additive하게 반환하되 기존 organization 권한·scope 필터를 우회하지 않는다.
- 저장 시 orphan correlation은 NULL로 내리고 NodeRun이 다른 WorkflowRun 소속이거나 Run의 Workflow 조직이 audit 조직과 다르면 잘못된 run/node 연결을 저장하지 않는다. 조직 metadata 누락·malformed을 포함한 optional correlation 문제 때문에 canonical AuditLog 전체가 dead-letter되어서는 안 된다.
- 유효한 `organization_id`와 `workflow_run_id`가 있지만 비동기 `log.create_run`이 아직 WorkflowRun을 저장하지 않은 경우 Outbox worker는 safe reason으로 bounded retry한다. 재시도 중 Run이 보이면 typed correlation을 보존하고, 마지막 시도에도 없으면 correlation만 NULL로 내려 canonical AuditLog 자체는 저장한다.
- 수동/API/Webhook 사용자 WorkflowRun 완료·실패 audit은 Workflow의 canonical `organization_id`와 `workflow_run_id`를 함께 기록해 Outbox 저장 뒤에도 typed run 연결을 유지한다. System schedule은 기존 exact claim provenance 검증을 계속 사용한다.
- Audit metadata sanitizer는 raw source id/url/path/title, raw source principal, raw source ACL row, raw chunk content, raw prompt/completion, credential value, `encrypted_config`, raw exception을 제거한다.
- Authorized retrieval summary allowlist는 KB id, document version id, chunk id, citation id, optional collection id, rank/score, safe metadata summary, policy result, latency/cost/token aggregate, retryability, opaque correlation/request id, `retrieval_strategy`, `rag_mode`, authorized/selected/retrieved count summary, `context_token_estimate`, `permission_filter_applied`, `safe_exclusion_summary`, `query_rewrite_applied`, `query_rewrite_strategy`, `evidence_sufficient`, `insufficiency_reason`, `source_tier_policy`, `source_tier_used`, `fanout_concurrency`, `fanout_timeout_seconds`, `failure_policy`만 허용한다.
- Audit/trace metadata sanitizer는 raw rewritten query를 raw prompt와 같은 민감 입력으로 보고 durable metadata와 log에서 제거한다.
- 공통 Trace redaction은 숫자 또는 null인 명시적 token limit/usage allowlist(`max_tokens`, prompt/completion/input/output/total token count 등)는 보존하되, 인증 token 문자열과 알 수 없는 `*_token`, 문자열로 들어온 token count, 정책이 지정한 민감 경로는 계속 마스킹한다.
- Conversation Memory sanitizer는 raw transcript/Memory content, Access Grant token/hash, prompt, private source identity와 provider raw error를 제거하고 session/grant lifecycle의 safe opaque reference, audience, status, reason과 bucketed count만 허용한다.
- Hidden/denied/resource-hidden summary allowlist는 sanitized reason class, actor/org scope, request/correlation id, coarse retryability만 허용하고 exact hidden/denied count나 hidden KB id를 거부한다.
- Partial result summary는 `partial_result=true`, bucketed reason summary, retryability, request/correlation id만 허용한다.
- Run trigger pure policy는 `manual`/`test`/`manual_compare`/`cost_optimizer_compare`를 MANUAL, `api`/`app`/`deployed`/`api_secret`을 API, `webhook`을 WEBHOOK, `schedule`/`scheduler`를 SCHEDULER로 정규화한다. String은 trim/lowercase하고, Log System adapter가 이미 받은 `RunTriggerMode` enum은 string alias policy를 거치지 않고 exact 값을 보존한다.
- Trigger 누락 또는 `None`은 legacy compatibility로 deployed면 API, 아니면 MANUAL이지만 blank/unknown/non-string explicit input은 fallback하지 않고 permanent contract error다.
- Workflow Logger는 explicit invalid trigger를 run id 할당과 payload preparation 전에 static `NonRetryableWorkflowError`로 변환한다. 이때 trigger와 workflow input 원문을 예외에 포함하지 않는다.

## API Tests

- Raw/compliance access audit은 content 반환 전에 성공해야 하며, audit metadata에는 raw content, raw source id/url/path/title, raw principal, object storage key를 저장하지 않는다.
- Policy block, permission denied, requester source authorization denied, source ACL stale/unmapped/ambiguous/unverified/revoked, connector/egress failure는 raw exception 없이 sanitized reason code로 기록된다.
- Model Routing Judge trace는 14자 이하의 한글 포함 `reason_short`만 보존하고 영문 전용, 과도한 길이, CR/LF 및 제어문자 값은 제거한다. Raw prompt/input과 Judge 자유형 설명은 durable trace에 남지 않는다.
- Permission grant/update/revoke endpoint는 manual audit과 ORM listener audit이 중복되어 같은 mutation을 두 번 기록하지 않는다. Core upsert 또는 bulk delete를 쓰는 endpoint 경로도 permission row별 canonical action을 정확히 한 번 남긴다.
- Workflow/LLM credential의 team/user permission PUT·DELETE는 permission row와 canonical `team_workflow_permission.*`/`user_workflow_permission.*`/`team_llm_permission.*`/`user_llm_permission.*` AuditLog를 같은 UnitOfWork에서 commit한다. Audit add/flush/commit 실패 시 permission create/update/delete도 rollback하고, 동일 값 PUT과 concurrent retry는 row 및 audit cardinality를 늘리지 않으며 concurrent delete는 applied mutation 한 건만 deleted audit을 남긴다.
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
- Audit list/detail은 canonical actor/target ID를 유지하면서 safe `actor_display`/`target_display`를 additive하게 반환한다. Actor snapshot의 name/email scalar를 우선하고 snapshot이 없을 때만 current same-organization member를 사용한다.
- Organization/user/team/workflow primary App/App/Knowledge Base target은 current organization과 target-type allowlist를 통과할 때만 current safe name을 반환한다. Cross-organization, hidden, deleted, malformed, unsupported target은 display를 생략하고 ID-only fallback을 유지한다.
- 한 page의 target display resolution은 target type별 batch query를 사용하고 audit row 수만큼 query가 증가하지 않는다. Resolver 오류는 list/detail 전체 실패가 아니라 display 생략으로 처리한다.
- Trace 목록은 visibility 조건을 `LIMIT` 전에 SQL에 적용하고 정확한 visible total을 반환한다. App 정책은 organization/global 정책보다 우선하며 목록 row마다 `check_trace_access`를 호출하지 않는다. Run/Workflow/Deployment의 App ID가 충돌하면 상세 조회와 같은 Run > Workflow > Deployment 우선순위를 적용하고 하위 fallback App 권한으로 우회하지 않는다.
- Detail의 allowlisted metadata/change summary UUID는 `resolved_references`에 포함된 same-organization safe reference만 병기할 수 있고, map에 없는 UUID나 hidden resource를 추론하지 않는다.
- Audit `auditor`/`raw_auditor`는 audit list/detail을 조회할 수 있지만 actor access profile/team-membership/resource/action API는 `403`이다.
- Security Alert evidence API는 실제 연결된 audit만 `AuditLogSchema` 수준으로 반환하고 generic metadata/before/after/change summary를 inline 노출하지 않는다.
- Audit `auditor`/`raw_auditor` only user는 기존 audit list/detail을 조회할 수 있어도 Security Alert list/detail/evidence/lifecycle API는 `403`이어야 한다.
- Security Alert 최초 생성 또는 lifecycle audit insert가 실패하면 대응 alert transaction도 rollback하고, cooldown occurrence 갱신은 lifecycle audit을 추가하지 않아야 한다.
- Schedule budget/outcome recorder는 access-management recorder나 legacy user helper를 재사용하지 않고 `actor_id=null`, `actor_type=system`, canonical organization과 strict metadata만 caller UoW에 추가한다.
- `schedule_dispatch.outcome_reviewed` detail은 exact claim target과 같은 organization에서만 조회되고 allowlisted operation correlation/resolution만 반환한다. 다른 조직은 404이고 malformed correlation/resolution 또는 nested/raw metadata는 생략한다.
- Outcome review audit insert/flush가 실패하면 claim review field도 rollback하고, recorder가 생성하지 않은 audit id를 claim에 연결할 수 없다.
- WorkflowRun visibility grace를 지난 claim은 exact claim target의 `schedule_dispatch.workflow_run_missing` audit과 one-time marker를 같은 transaction으로 남긴다. 중복 scan은 audit을 추가하지 않고, raw run id/input/output/provider response를 저장하거나 engine을 replay하지 않는다.
- System schedule과 interactive RAG retrieval이 `rag.retrieve`를 기록하면 metadata의 canonical UUID `organization_id`로 해당 조직 list/detail 조회에 노출되고 다른 조직에서는 조회되지 않는다. Invalid/missing organization context는 unscoped audit row로 저장하지 않으며 Schedule credential principal은 actor로 승격되지 않는다.
- Schedule-correlated WorkflowRun Log System write가 재시도되면 raw storage/provider detail은 logger와 retry exception에 없고, static operation label과 error type만 남는다.
- Gateway webhook dispatch는 execution context에 exact `trigger_mode="webhook"`을 전달하고 Log System은 같은 wire value를 `RunTriggerMode.WEBHOOK`으로 저장한다. Existing manual/API/app/deployed/schedule/scheduler와 compare alias 결과는 회귀하지 않아야 한다.
- Explicit invalid trigger는 Workflow Engine의 start node 조회/실행, `log.create_run`, `log.update_run_finish`, `log.update_run_error` 발행 없이 종료하고 workflow Celery retry를 요청하지 않는다. Log System에 직접 전달된 경우에도 session rollback/close 후 WorkflowRun add/flush/commit 없이 종료하고 storage retry를 요청하지 않는다. Exception과 captured log에는 raw trigger, task payload, workflow input 또는 secret-like fixture value가 없어야 한다.
- Schedule operational timestamp만 갱신하면 generic `schedule.updated`가 생성되지 않지만 cron/timezone/lifecycle 변경과 같은 transaction의 unrelated tracked mutation audit은 유지된다.
- RAG strategy/A-B summary API는 권한 없는 문서명/ID, raw source metadata, raw prompt/completion, content preview를 반환하지 않는다.
- RAG strategy/A-B summary API는 query rewrite 적용 여부, evidence sufficiency 결과, source tier summary를 safe field로 반환할 수 있지만 raw rewritten query와 hidden source reference를 반환하지 않는다.
- Organization-scoped `memory.*` event는 safe `organization_id`를 포함해 관리자 audit list/detail에서 조회되고 다른 organization에서는 숨겨진다.
- Memory session/grant lifecycle audit detail은 `change_summary=null`이며 action별 safe metadata allowlist 밖 field를 반환하지 않는다.
- Memory lifecycle mutation과 required audit/outbox가 같은 transaction에서 실패하면 mutation도 rollback한다.
- 정상 turn/summary 상태는 AuditLog row를 만들지 않고 operational trace/metric으로만 기록한다. Permission/policy/provider/workflow 사건은 기존 canonical action을 재사용한다.
- Dispatch/summary reconciliation retry는 같은 logical terminal transition operational event를 중복 기록하지 않는다.
- Authenticated/public create는 각각 session created 1건, session created + grant issued 각 1건을 정확히 기록한다.
- Close는 session closed 1건만 기록하고 transcript-only grant 때문에 issued/rotated/revoked를 만들지 않는다.
- Reset은 old reset + new created를 각 1건 기록하고 public session에서만 old revoke + new issue를 각 1건 추가한다. Authenticated reset은 grant action을 만들지 않고, 어느 경우에도 old closed를 중복 기록하지 않는다. Same-key replay와 outbox retry도 cardinality를 유지한다.
- Delete request는 delete_requested와 active grant revoke를 기록하며 purge pending/retry는 purged를 만들지 않는다.
- `completed_with_hold`와 `terminal_failure`는 `memory.session.purged`를 만들지 않고 hold 해제 후 실제 erasure 완료가 정확히 한 번 purged를 만든다.
- Public create/close/reset/delete request와 grant action은 `actor_id=null`, `actor_type='public'`, async physical purge/compliance completion은 `actor_id=null`, `actor_type='system'`을 사용한다. App/deployment owner, credential/billing principal과 grant reference를 actor로 기록하면 실패한다.
- Audit schema/sanitizer/list/detail/UI는 `actor_type='public'`을 안전한 익명 public actor로 round-trip하고 `System`/user name으로 오표시하지 않는다. User-only alert detector는 이 row를 user actor로 포함하지 않는다.
- ProviderExecutionCapability/lease/reservation의 raw token/scope/credential은 AuditLog/trace/metric에 없고 safe opaque reference/revision/purpose만 operational record에 허용된다.

## E2E Tests

- Workflow runtime RAG trace는 명시 execution subject, workflow/run/node id, safe citation/retrieval summary를 연결하지만 raw prompt, raw answer, raw chunk content를 저장하지 않는다.
- Standalone Agent answer는 `rag_answer_runs`와 opaque `correlation_id`로 audit/usage를 연결하고 trace/usage table에 RAG-specific FK를 만들지 않는다.
- Cost Optimizer의 RAG 포함 비교 화면은 safe retrieval summary와 비용/latency 집계만 표시한다.
- Organization manager가 audit actor를 정지/재활성화하면 `organization.member.update` audit의 optional reason과 safe membership before/after를 같은 audit tab에서 확인할 수 있다.
- Direct permission revoke 후 team source가 남는 경우 audit은 direct row deletion만 기록하고 UI effective access는 remaining team source를 반영한다.
- Security Alert detail의 evidence에서 audit detail로 이동해도 기존 organization scope와 metadata allowlist를 우회하지 않아야 한다.
- Protected outcome review job은 product audit에 system actor/canonical organization/operation correlation만 남기고 human operator identity는 platform IAM audit에 남긴다. Acknowledgment 뒤에도 workflow redrive가 발생하지 않는다.
- System schedule 실행 중 deployment가 삭제되어 WorkflowRun deployment FK가 null이 되어도 exact task/run claim의 durable organization으로 완료/실패 audit을 기록한다. Live deployment가 남아 있는데 run/claim/deployment/App provenance가 충돌하면 fail-closed한다.
- System schedule의 RAG retrieval과 evidence policy block audit은 credential principal을 user actor로 기록하지 않고 `actor_id=null`, `actor_type=system`을 사용한다.
- Trace list/detail schema는 system schedule의 null `user_id`를 response validation 500 없이 반환하고, 기존 interactive trace의 non-null user actor를 유지한다.
- Conversation create/close/reset/delete/physical purge E2E는 canonical action matrix의 target/action/count/status/actor 순서를 검증하고 raw transcript와 grant token을 audit tab/detail에 표시하지 않는다.

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
- Stored organization provenance가 request organization과 다르거나 필요한 snapshot에 없으면 change summary는 null이다. Safe display resolver도 request organization 검증에 실패하면 name/path를 반환하지 않고 opaque ID만 유지한다.
- Concurrent last-manager 또는 permission mutation은 applied mutation당 canonical audit 한 건만 남긴다.
- Memory event에 `organization_id`가 누락되면 organization-scoped 성공 event로 수용하지 않고 mutation 또는 outbox가 fail-closed 한다.
- Management reason은 blank를 null로 정규화하고 500자 초과 또는 forbidden control character를 거부한다.
- Management reason의 CRLF/trim/Unicode code-point 경계와 bidi control을 검증하고, common secret/PII는 durable audit 전에 redacted한다.
- Reason redaction/sanitization 실패는 raw fallback 없이 access mutation과 audit을 모두 rollback한다.
- Schedule/Deployment가 삭제된 뒤에도 claim의 durable organization provenance로 outcome review audit을 올바른 조직에 귀속하고 다른 조직에서 조회하지 못한다.
- System schedule WorkflowRun audit은 exact claim task id, workflow run id, deployment id가 모두 일치할 때만 claim organization을 사용한다. Current deployment가 존재하면 App workflow/organization도 일치해야 하며, queue/run/claim 불일치에서는 잘못된 조직 audit을 생성하지 않는다.
