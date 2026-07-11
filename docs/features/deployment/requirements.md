# Deployment Requirements

Status: Draft
Related Features: workflow, llm-credentials, audit-tracing, knowledge, chatbot-deployment

## Purpose

Deployment feature는 App의 workflow snapshot을 API, webapp, widget, chatbot, MCP, workflow-node, schedule, webhook 같은 실행 표면으로 게시하고 실행 가능한 상태를 관리한다.

이 feature의 범위에는 배포된 앱의 공개 실행 표면 — 임베드 챗 UI(`app/embed/chat`), public run/webhook endpoint(app secret Bearer 인증) — 을 포함한다.

배포 타입 `chatbot`(공개 채팅 웹페이지, 기억모드 항상 ON, 방문자별 대화 격리)의 상세는 [chatbot-deployment](../chatbot-deployment/requirements.md)를 참조한다.

Webhook capture helper는 public webhook 실행 표면이 아니라 로그인한 배포 권한자의 디버그 도구다. Capture start/status/cancel은 user session과 대상 workflow `deploy` 권한을 요구하며, app secret 인증만으로는 사용할 수 없다. Capture session은 short TTL과 server-issued `capture_id` nonce를 사용하고, status 응답은 raw webhook payload 원문이 아니라 known secret patterns와 sensitive keys가 redacted/capped 처리된 preview만 반환한다. 사용자가 capture를 취소하면 서버 session도 삭제되어 이후 webhook은 normal execution path를 따른다.

## User Stories

- 빌더로서, 배포를 활성화하기 전에 현재 workflow snapshot이 실제 실행 표면에서 사용할 수 없는 private KB를 참조하는지 알고 싶다.
- 운영자로서, public/API/webhook/schedule/chatbot 실행에서 사용자 주체가 없을 때 private KB가 owner 권한으로 조용히 사용되지 않기를 원한다.
- 감사자로서, 배포 실행 표면별로 RAG 접근 경계가 명시되어 있고 실패 시 hidden KB id/name/count가 노출되지 않기를 원한다.

## Functional Requirements

- DEP-REQ-001: 배포 생성과 활성화는 workflow graph snapshot, input/output schema, deployment type, active 상태를 기준으로 실행 가능 surface를 만든다.
- DEP-REQ-002: `DeploymentType`은 `api`, `webapp`, `widget`, `chatbot`, `mcp`, `workflow_node`, `schedule`, `webhook`를 지원한다.
- DEP-REQ-003: LLM node RAG 옵션이 private KB 후보를 참조하고 실행 표면에 authenticated execution subject가 없으면 해당 활성 배포는 preflight에서 차단해야 한다.
- DEP-REQ-004: Preflight preview endpoint는 UI가 결과를 렌더링할 수 있도록 blocked 상태도 `200 OK` 응답으로 반환한다. `is_active=false` preview는 inactive 저장 가능성을 반영해 활성화 blocker를 warning으로 낮출 수 있지만, create(`is_active=true`)와 enable/toggle activation의 blocking preflight는 완화하지 않는다.
- DEP-REQ-005: 실제 배포를 활성 surface에 올리는 create(`is_active=true`), enable/toggle activation은 blocking preflight 실패 시 `409 deployment.preflight.blocked`로 실패해야 한다.
- DEP-REQ-006: `is_active=false` 배포 생성은 저장을 허용할 수 있다. 단, inactive 생성은 active deployment 교체, public URL 활성화, schedule job 생성 같은 실행 부작용을 만들지 않아야 하며, 이후 활성화 시 blocking preflight를 다시 통과해야 한다.
- DEP-REQ-007: Active deployment 삭제 시 다른 deployment를 자동 승격하지 않는다. 자동 승격을 도입하려면 승격 직전 같은 blocking preflight를 통과해야 한다.
- DEP-REQ-008: Preflight는 graph snapshot의 LLM node RAG 옵션을 검사하고, explicit KB mode와 materialized recommendation 결과의 KB 후보를 서버 side resolver/helper로 다시 평가해야 한다. Client-supplied KB id나 audience hint만으로 차단을 완화하지 않는다.
- DEP-REQ-009: Source-managed KB를 anonymous public-only 후보로 포함하려면 collection public visibility와 별도 source/connector public exposure approval이 모두 필요하다. Public exposure approval primitive가 구현되기 전에는 source-managed public 후보를 blocked로 처리한다.
- DEP-REQ-010: Preflight response는 hidden KB id/name/path, exact denied count, raw source metadata, raw exception을 반환하지 않고 safe reason code, bucketed count, required action만 반환한다.
- DEP-REQ-011: Schedule record와 scheduler job은 active `type=schedule` deployment에서만 생성/로드/실행한다. `scheduleTrigger` node가 `workflow_node`, `chatbot`, `api` 등 다른 deployment type graph에 포함되어도 schedule 실행 surface를 만들지 않는다.
- DEP-REQ-012: Webhook 수신 endpoint는 active deployment가 target app 소유이고 active 상태이며 `type=webhook`일 때만 background execution을 예약한다. 같은 slug의 active deployment가 `api`, `chatbot`, `workflow_node`, `schedule` 등 다른 type이면 `accepted`를 반환하지 않고 dispatch 전에 safe 404로 거부한다.
- DEP-REQ-013: Deployment 실행 surface와 `DeploymentType` allowlist는 Gateway endpoint, scheduler, Workflow Engine task의 개별 문자열 분기가 아니라 중앙 runtime policy matrix에서 판정해야 한다. Unknown surface 또는 unknown deployment type은 fail-closed로 거부한다.
- DEP-REQ-014: 인증 없는 public deployment info는 기본 runtime policy에서 `webapp`, `widget`, `chatbot` metadata만 노출한다. API, MCP, schedule, webhook, workflow-node와 unknown type은 safe 404로 닫는다. Allowlist는 endpoint 문자열 분기나 환경변수가 아니라 불변 `DeploymentRuntimePolicy` dependency로 주입하며, 확장은 명시적 composition 변경과 계약 테스트를 요구한다.
- DEP-REQ-015: Scheduler는 Celery dispatch 전에 `Schedule.id`와 `deployment_id`가 일치하는 canonical DB row를 확인해야 한다. Row가 삭제되었거나 불일치하면 stale local job을 제거하고 budget check, queue dispatch, `last_run_at`/`next_run_at` update를 수행하지 않아야 한다.
- DEP-REQ-016: Deployment ID 기반 Worker는 queue 입력의 tenant/resource 식별자를 권한 source of truth로 사용하지 않아야 한다. `workflow_id`, `organization_id`, `app_id`, deployment id/version, runtime credential owner는 DB의 current active Deployment/App에서 재구성하고, queue에서는 검증된 trigger와 제한된 correlation metadata만 전달받아야 한다. Subject 없는 webhook/schedule 실행에 queue 입력으로 `execution_subject`를 주입할 수 없다.
- DEP-REQ-017: Deployment preflight policy/use case는 FastAPI, SQLAlchemy, concrete adapter를 import하지 않아야 한다. SQLAlchemy adapter는 organization/lifecycle/workflow-node owner/type/active 조건을 pure snapshot으로 변환하고, outer composition root가 port implementation을 주입해야 한다. Existing service facade는 typed application block을 기존 `409 deployment.preflight.blocked` HTTP contract로만 mapping해야 한다.
- DEP-REQ-018: 동일 schedule occurrence는 persisted `Schedule.next_run_at`에서 얻은 `schedule_id + scheduled_for`로 식별하고 durable claim을 정확히 하나만 생성해야 한다. 여러 Gateway replica가 동시에 due row를 처리해도 unique constraint와 row lock으로 한 winner만 claim해야 한다.
- DEP-REQ-019: Claim 생성, budget allow/block/unavailable 판단, 필요한 policy audit와 `Schedule.next_run_at` 전진은 application use case가 소유하는 한 DB transaction에서 commit해야 한다. Repository, audit, queue adapter는 독립 commit/rollback을 수행하지 않아야 한다.
- DEP-REQ-020: Claim commit 뒤 broker publish는 at-least-once로 처리한다. Deterministic idempotency/task id, bounded lease/recovery와 attempt cap을 사용하고 broker network call 중 DB row lock을 유지하지 않아야 한다.
- DEP-REQ-021: Worker는 claim을 lock하고 canonical Schedule/Deployment/App/runtime policy와 organization provenance를 재검증한 뒤 허용 상태를 `running`으로 원자 전이한 경우에만 Workflow Engine을 시작해야 한다. Duplicate task delivery는 같은 stable workflow run identity를 재사용하고 engine을 다시 시작하지 않아야 한다.
- DEP-REQ-022: Admission 이후 결과가 불명확하면 `execution_outcome_unknown`으로 격리하고 자동 replay하지 않아야 한다. Outcome acknowledgment는 exact claim별 allowlisted resolution과 system audit을 같은 transaction에 기록하지만 redrive 권한을 부여하지 않는다.
- DEP-REQ-023: Schedule dispatch claim은 canonical App의 non-null `organization_id`를 durable audit provenance로 저장해야 한다. Queue/CLI가 제공한 organization을 신뢰하지 않고, 조직 누락 또는 claim/App 불일치는 dispatch와 execution 전에 fail-closed해야 한다.
- DEP-REQ-024: System schedule의 workflow run executor는 null이고 audit actor는 system이어야 한다. App/deployment creator나 workflow owner를 executor, audit actor, private RAG execution subject로 합성하지 않아야 한다.
- DEP-REQ-025: Schedule dispatch mode 전환은 migration-first, disabled rollout, legacy task drain, claim activation 순서를 따라야 한다. Activation과 rollback 모두 nonterminal/review되지 않은 outcome unknown/active task가 있으면 fail-closed하고, rollback은 claim, drain, disabled 순서를 따라야 한다. 이는 application rollout rollback이며, system schedule `WorkflowRun.user_id=NULL` 이력, admitted claim의 durable run correlation, active/unreviewed claim 또는 configuration quarantine이 남은 DB에서 과거 schema migration downgrade를 시도하면 임의 executor 귀속, 증거 손실 또는 partial DDL 대신 모든 schedule revision에서 fail-closed해야 한다.
- DEP-REQ-026: Schedule claim과 Worker admission의 duplicate suppression은 외부 node 부수효과의 exactly-once를 의미하지 않는다. Provider별 idempotency는 별도 node adapter 계약으로 다뤄야 한다.
- DEP-REQ-027: 신규 Schedule 생성/활성화의 invalid cron expression 또는 timezone은 partial deployment/schedule mutation 없이 safe `422 deployment.schedule_configuration_invalid`로 거부해야 한다. 기존 invalid legacy row는 다른 due schedule을 굶기지 않고 해당 row만 safe하게 격리해야 한다.
- DEP-REQ-028: admission된 system schedule의 stable WorkflowRun correlation이 visibility grace 이후에도 Log System에서 확인되지 않으면 canonical claim에 one-time safe visibility signal과 system audit을 같은 transaction으로 기록해야 한다. 이 signal은 workflow, node, provider side effect를 replay하거나 raw run payload를 저장해서는 안 된다.
- DEP-REQ-029: `attempt_count`는 pending claim을 Gateway dispatcher가 처리한 주기 수다. 한 처리 주기에서 budget 결과와 broker publish 여부에 관계없이 최대 한 번만 증가하고, Worker budget unavailable은 이미 publish된 attempt를 추가 증가시키지 않아야 한다. 최대치에 도달한 pending claim은 publish 없이 safe dead-letter로 격리한다.
- DEP-REQ-030: `execution_outcome_unknown` 검토는 exact claim의 조사 완료 acknowledgment와 rollback gate 해제 표시에 한정한다. 검토는 claim status를 바꾸거나 redrive 권한을 부여하지 않으며, rollback preflight는 nonterminal claim, 미검토 outcome unknown, Celery active/reserved/scheduled 전용 task를 독립적으로 확인하고 inspection 불가 시 fail-closed해야 한다.
- DEP-REQ-031: Dispatch 핵심 복구는 expired `dispatching`/`enqueued`와 running deadline 격리를 먼저 처리해야 한다. WorkflowRun visibility signal과 terminal cleanup은 별도 UnitOfWork의 optional maintenance로 수행하며 실패가 핵심 dispatch/recovery를 차단해서는 안 된다.
- DEP-REQ-032: `claim`/`drain` mode의 Gateway와 Worker는 동일한 shared Alembic/schema readiness를 startup에서 통과해야 한다. Migration은 동일 DB connection의 bounded PostgreSQL advisory lock과 production rollout 공통 concurrency group으로 직렬화한다. 동시 migration 진입은 제한 시간 동안 현재 owner의 완료를 기다린 뒤에만 실패한다. Pod가 로드한 canonical settings fingerprint가 manifest annotation과 다르거나 일반 독립 rollout 시 live Gateway/Worker fingerprint가 desired 값과 다르면 fail-closed한다. 단, desired mode가 `disabled`인 최초 rollout에서는 기존 Deployment의 fingerprint annotation 누락을 bootstrap 상태로 허용한다.
- DEP-REQ-033: Schedule claim을 활성화하는 coordinated production rollout은 Gateway/Worker보다 먼저 동일 commit의 Log System image를 배포하고 실제 Deployment image identity를 검증해야 한다. 그래야 nullable system actor와 canonical schedule trigger를 이해하지 못하는 이전 Logger가 새 schedule run을 소비하는 혼합 버전을 차단할 수 있다.
- DEP-REQ-034: Admission 전 `pending`/`dispatching`/`enqueued` claim은 `workflow_run_id`를 가질 수 없다. Scheduler는 한 claim의 publish 결과 write 실패를 다른 prepared claim으로 전파하지 않고 lease recovery에 맡겨야 한다. Engine 결과 확정 후 terminal state write는 engine을 재실행하지 않는 fresh-session bounded retry만 허용한다.
- DEP-REQ-035: 오래 밀린 valid schedule은 과거 occurrence 수와 무관하게 현재 시각 이후 첫 fire time으로 coalesce해야 한다. Catch-up iteration cap 초과를 configuration error로 분류하거나 schedule을 quarantine해서는 안 된다.
- DEP-REQ-036: `canceled`/`dead_lettered` claim의 safe reason, completed outcome review의 resolution, nullable system schedule WorkflowRun의 claim task id는 DB CHECK에서도 명시적으로 non-null이어야 한다. PostgreSQL `UNKNOWN` 평가가 incomplete terminal/correlation row를 허용해서는 안 된다.
- DEP-REQ-037: `disabled` schedule dispatch mode는 신규 claim과 legacy direct enqueue를 모두 중지하는 명시적 kill switch다. 다중 replica 중복 실행을 다시 허용하는 legacy fallback은 제공하지 않으며, schedule 실행을 재개하려면 coordinated rollout과 drain 검증을 거쳐 `claim` mode를 활성화해야 한다.
- DEP-REQ-038: Terminal claim cleanup은 retention이 지났더라도 검토되지 않은 `execution_outcome_unknown` claim을 삭제하지 않아야 한다. 해당 claim은 allowlisted outcome review가 같은 row에 기록된 뒤에만 dead-letter retention 대상이 될 수 있으며, rollback/downgrade gate가 조사 전 correlation을 잃어서는 안 된다.
- DEP-REQ-039: Coordinated rollout은 같은 commit tag의 기존 ECR digest를 재사용하거나 신규 push 뒤 digest를 확정하고 immutable image identity로 배포해야 한다. 완료 판정은 Deployment spec뿐 아니라 observed generation, desired/updated/Ready/available replica와 non-terminating Pod의 spec image, container imageID, fingerprint, Ready condition의 수렴을 Logger/Gateway/Worker 모두에서 검증해야 한다. 실패 후 재실행에서 mutable tag 또는 desired spec만 남은 unready stage는 완료로 간주하지 않는다.
- DEP-REQ-040: Activation/rollback drain은 durable ledger의 nonterminal claim과 미검토 outcome unknown이 0이고 기대 Ready Worker 집합과 Celery inspect 응답 집합이 일치해야 한다. Queue와 Worker task 상태를 앞뒤로 확인한 연속 두 안정 관측이 모두 0일 때만 통과하며, DB/inspection 실패, 부분 응답과 관측 사이 task 이동은 fail-closed한다.
- DEP-REQ-041: PostgreSQL lease, delivery deadline과 execution deadline은 transaction 시작 시각이 아니라 lock/정책 평가 이후의 DB wall clock으로 계산한다.
- DEP-REQ-042: `disabled` mode는 신규 claim과 admission을 중지하지만 schema-ready 환경의 WorkflowRun visibility, terminal retention cleanup과 claim age 관측은 계속 수행한다.
- DEP-REQ-043: 일반 Dev namespace workflow와 단일 Helm release는 non-disabled schedule mode 전환을 수행하지 않는다. Dev workflow는 live Gateway/Worker의 observed generation, replica 상태와 non-terminating Pod의 Running/Ready/fingerprint 수렴을 먼저 확인하고, claim/drain/mixed/부분 bootstrap 또는 미수렴 상태에서 단독 disabled 전환을 거부한다. Disabled 설정 변경은 Gateway/Worker 동시 배포에서만 허용하고 단독 service 배포는 live/desired fingerprint가 같아야 한다. `claim`/`drain` 전환은 Logger/Gateway/Worker 순서와 drain preflight를 소유한 coordinated workflow에서만 수행하고 rollout 실패를 성공으로 무시하지 않는다.
- DEP-REQ-044: Schedule schema downgrade는 기본 비지원이다. 공통 Alembic graph의 sibling feature data를 함께 제거할 수 있으므로 일반 rollback은 `claim -> drain -> disabled` application rollback만 사용하며 파괴적 schema downgrade는 명시적 opt-in과 백업 절차가 필요하다.
- DEP-REQ-045: Schedule 전용 Celery task는 result backend에 workflow output, RAG evidence, sync 상세를 저장하지 않고 비민감 claim outcome만 반환한다.
- DEP-REQ-046: Schedule 운영 signal은 low-cardinality event name/status/reason/mode/value만 사용하며 claim/organization/user UUID, idempotency key, raw payload와 raw exception을 포함하지 않는다. Scheduler와 Worker의 일반 오류 로그도 operation, bounded attempt와 exception type만 기록하고 claim UUID 또는 raw exception message를 남기지 않는다.

## Runtime Audience Matrix

| DeploymentType | 실행 주체 정책 | RAG 경계 |
| --- | --- | --- |
| `api` | Public/app secret 호출에는 사용자 subject가 없다 | Anonymous public-only. Private KB blocked |
| `webapp` | Public web app surface에는 사용자 subject가 없다 | Anonymous public-only. Private KB blocked |
| `widget` | Embedded widget surface에는 사용자 subject가 없다 | Anonymous public-only. Private KB blocked |
| `chatbot` | `/run-public` 공개 실행에는 사용자 subject가 없다. 인증 내부 실행 endpoint만 로그인 사용자를 subject로 사용한다 | 공개 실행은 anonymous public-only. 인증 내부 실행은 current user 권한 |
| `mcp` | 별도 authenticated operator/service account가 없으면 사용자 subject가 없다 | Anonymous public-only. Private KB blocked |
| `workflow_node` | Public/API/webhook 및 authenticated run/run-info 같은 direct execution surface는 지원하지 않는다. Subworkflow 실행은 parent workflow의 execution context를 상속한다 | Parent subject 기준 KB permission/source ACL. Parent subject가 없으면 anonymous public-only로 평가되어 private KB blocked |
| `schedule` | 예약 실행에는 사용자 subject가 없다 | Anonymous public-only. Private KB blocked |
| `webhook` | Webhook/app secret 호출에는 사용자 subject가 없다 | Anonymous public-only. Private KB blocked |

## Policies And Edge Cases

- Organization membership은 KB 사용 권한이 아니다. Public/automatic deployment surface에서 private KB를 사용하려면 후속 service account 또는 assigned operator 정책이 필요하다.
- Preview endpoint의 `audience` 필드는 UI 검증용 힌트일 뿐이다. Create/enable/toggle 경로는 서버가 실제 deployment type과 실행 경로에서 audience를 파생해야 하며, client-supplied audience가 보안 차단을 완화할 수 없다.
- Workflow-node preflight는 node 설정의 `workflowNode.data.appId`를 target app으로 해석하고, target app의 active deployment snapshot을 검사한다. `workflowId`와 혼동하지 않는다. Target active deployment는 target app 소유이고, active 상태이며, `type=workflow_node`여야 한다. Pending active candidate graph도 pending deployment type이 `workflow_node`일 때만 workflow-node target으로 인정한다.
- `workflow_node` 배포를 단독 reusable module로 활성화할 때는 parent subject가 아직 없으므로 private KB 참조를 warning으로 보고할 수 있다. 단, public/API/webhook/authenticated run 같은 모든 direct execution surface는 거부하며, public/non-interactive parent deployment가 해당 module을 참조하면 parent audience 기준 preflight에서 private KB를 blocked로 처리한다.
- Workflow-node runtime은 parent `execution_context.organization_id`가 있어야 하며, target app organization이 없거나 target app organization과 다르거나 parent organization context가 없으면 실행하지 않는다. Target active deployment도 target app 소유, active 상태, `type=workflow_node`를 만족해야 한다. Runtime은 `workflow_node_depth`와 `workflow_node_visited_app_ids` context guard로 순환 참조와 depth 초과를 fail-closed로 차단한다.
- Workflow-node nesting은 우선 한 단계 active target 검사를 baseline으로 삼는다. 순환 참조, 과도한 depth, target active deployment 부재는 subject 상속 여부와 무관한 구조적 오류이므로 active publish와 inactive preview 모두에서 safe blocked reason으로 유지한다.
- Workflow-node runtime의 순환 참조, depth 초과, target unavailable 같은 복구 불가능한 설정 오류는 Celery retry 대상이 아니다. Runtime은 non-retryable error로 즉시 실패시켜 같은 잘못된 subworkflow 실행을 반복 예약하지 않는다.
- `run.py`/`webhook.py`와 authenticated deployment run/run-info 같은 runtime endpoint는 실행 주체와 direct surface contract verification 대상이다. Preflight의 핵심 차단은 deployment create/toggle service boundary에서 수행하며, delete는 다른 deployment를 자동 승격하지 않아 우회 activation surface를 만들지 않는다.
- Schedule dispatch는 graph snapshot을 queue payload에 직접 넣지 않고 claim locator를 worker에 전달한다. Worker는 실행 직전에 deployment active/type, app ownership, current active pointer와 claim organization provenance를 다시 확인하며, 삭제/비활성/stale/mismatched target은 retry하지 않는 permanent policy failure로 종료한다. Gateway replica 간 동일 예정 실행의 단일 claim과 Worker admission idempotency는 ADR-0028을 따르며, 이를 외부 부수효과 exactly-once 또는 단일 process stale-job 방어와 혼동하지 않는다.
- Preflight 예외는 broad catch에서 일반 `400`으로 감싸지 않고 `409 deployment.preflight.blocked` 또는 문서화된 error envelope을 보존해야 한다.
- Public info, authenticated run/run-info, webhook dispatch, schedule dispatch, workflow-node child dispatch는 같은 불변 runtime policy dependency를 사용해야 한다. Metadata 조회 가능 여부와 실제 execution 허용 여부는 별도 surface로 표현하며, public info 허용이 public execution 허용을 뜻하지 않는다. Production 기본 policy는 composition provider가 주입하고 임의 runtime mutation이나 환경변수 기반 allowlist 확장을 허용하지 않는다.

## Open Questions

- Private KB를 자동 실행에서 사용할 service account 또는 assigned operator 모델은 MBA-176 범위 밖이다.
