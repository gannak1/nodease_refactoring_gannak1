# Deployment Test Cases

Status: Draft
Verified Against: TBD

## Unit Tests

- Deployment application package는 FastAPI, SQLAlchemy, DB model, concrete adapter/service/composition module을 import하지 않는다.
- Pure preflight use case는 repository port snapshot만으로 결과를 만들고 active blocker는 HTTPException이 아닌 typed `DeploymentPreflightBlocked`를 반환한다. Compatibility facade만 이를 기존 409 envelope으로 mapping한다.
- Preflight graph scanner는 LLM node RAG 옵션의 explicit/materialized KB 후보를 찾고 unsupported shape는 safe warning 또는 blocked reason으로 낮춘다.
- Runtime audience resolver는 `api`, `webapp`, `widget`, `chatbot`, `mcp`, `schedule`, `webhook`를 anonymous public-only로 판정한다.
- `workflow_node` direct public/API/webhook/authenticated run execution is rejected. Subworkflow audience resolver는 parent execution subject를 상속하고, subject가 없으면 anonymous public-only로 판정한다.
- Workflow-node target resolver는 `workflowNode.data.appId`를 사용하고 `workflowId`로 target app을 찾지 않는다.
- Workflow-node target app이 존재하고 `active_deployment_id`가 있어도 active deployment의 `type`이 `workflow_node`가 아니면 `workflow_node_target_unavailable`로 처리한다.
- Workflow-node target이 pending active candidate graph를 가리킬 때도 candidate deployment type이 `workflow_node`가 아니면 `workflow_node_target_unavailable`로 처리한다.
- Workflow-node target unavailable, cycle, depth cap 초과는 `workflow_node_inherited` audience나 inactive preview에서도 warning으로 낮추지 않고 blocked로 유지한다.
- Scheduler service는 active `type=schedule` deployment만 로드/실행하고, non-schedule deployment id로 job이 호출되면 dispatch하지 않는다.
- Preflight response sanitizer는 hidden KB id/name/path, exact denied count, raw source metadata, raw exception을 제거한다.
- Central deployment runtime policy matrix는 public info, authenticated run/run-info, API secret run, webhook run, schedule run, workflow-node child run surface별 허용 deployment type을 고정하고 unknown surface/type을 fail-closed로 거부한다. 기본 policy는 불변 객체이며 composition dependency로 교체 주입할 수 있지만 환경변수나 전역 mutation으로 확장할 수 없다.
- Schedule occurrence key/state/reason/settings helper는 DB/framework 없이 테스트하고 naive datetime, unknown state/reason, mutable settings input을 fail-closed한다.
- Schedule application use case는 access-management command/model/port/recorder와 FastAPI/Celery/SQLAlchemy query를 import하지 않는다. Schedule 전용 audit port를 사용하고 concrete Gateway UnitOfWork만 composition에서 주입한다.
- Schedule audit recorder는 system actor, canonical action/target과 strict metadata allowlist만 현재 UoW에 추가하며 commit/rollback하지 않는다.
- System tick의 `Schedule.next_run_at`/`last_run_at`만 바뀌면 generic `schedule.updated`가 생성되지 않고 cron/timezone/lifecycle 또는 unrelated tracked mutation audit은 유지된다.

## API Tests

- `POST /api/v1/deployments/preflight`는 blocked 결과도 `200 OK`와 `status="blocked"`로 반환한다.
- `POST /api/v1/deployments/preflight` with `is_active=false`는 inactive 저장 context를 반영해 활성화 blocker를 `status="warning"`으로 반환하되 required action은 유지한다.
- `POST /api/v1/deployments` with `is_active=true`는 private KB가 anonymous/public 실행 surface에 포함되면 `409 deployment.preflight.blocked`를 반환한다.
- `POST /api/v1/deployments` with `is_active=false`는 같은 graph를 저장할 수 있지만 active deployment 교체, public URL 활성화, schedule job 생성을 하지 않는다.
- Inactive deployment activation/toggle은 private KB preflight 실패 시 `409 deployment.preflight.blocked`를 반환한다.
- Active deployment delete는 다른 deployment를 자동 active로 승격하지 않는다.
- Public/API run endpoint, webhook endpoint, authenticated deployment run/run-info endpoint는 `workflow_node` active deployment를 직접 실행하거나 실행 정보를 노출하지 않는다.
- Public info와 public/API slug run은 `App.active_deployment_id`가 가리키는 deployment의 `app_id`가 요청 app과 일치할 때만 노출하거나 실행한다. 다른 app 소유 deployment를 가리키는 stale/corrupt pointer는 safe 404로 닫고 task를 dispatch하지 않는다.
- Public info 기본 policy는 `webapp`, `widget`, `chatbot`만 허용하고 API/MCP/schedule/webhook/workflow-node/unknown/empty type을 safe 404로 닫는다. 명시적으로 주입한 immutable test policy가 기본 policy를 mutation하지 않고 독립적으로 동작하는지 검증한다.
- App status, clone, workflow-node deployment listing은 active deployment id뿐 아니라 deployment `app_id` ownership도 확인한다. Cross-app pointer로 다른 app의 graph/schema/status를 복제하거나 노출하지 않는다.
- Webhook endpoint는 active deployment가 `type=webhook`이 아닌 경우 API/chatbot/schedule/workflow-node 등 모든 non-webhook deployment와 unknown/empty type을 safe 404로 거부하며, budget check와 background task 등록 전에 종료한다.
- Gateway runtime endpoints, webhook endpoint, scheduler, Workflow Engine task는 같은 central runtime policy 결과를 사용하며 서로 다른 allowlist를 갖지 않는다.
- 직접 생성한 runtime policy에 mutable dict/set을 전달한 뒤 원본을 변경해도 policy 결과가 바뀌지 않아야 하며, direct constructor도 unknown type/surface/trigger를 fail-fast로 거부한다. Gateway webhook/scheduler/DeploymentService와 Workflow Engine provider에 custom immutable policy를 주입했을 때 해당 surface 판정에 실제 적용되어야 한다.
- Workflow-node runtime은 target app이 조직 소속인데 parent `execution_context.organization_id`가 없거나 target app organization과 다르면 fail-closed로 실행하지 않는다.
- Workflow-node runtime은 target app organization이 없으면 legacy/ambiguous target으로 보고 fail-closed로 실행하지 않는다.
- Workflow-node runtime은 target app의 active deployment가 `type=workflow_node`가 아니면 fail-closed로 실행하지 않는다.
- Workflow-node runtime의 active deployment query는 deployment id, target app id, `is_active=true`를 함께 요구하고 설정 오류는 정확한 non-retryable `WorkflowNodeConfigurationError`로 반환한다.
- Workflow-node runtime은 `workflow_node_visited_app_ids`에 target app이 이미 있거나 `workflow_node_depth`가 cap에 도달하면 DB lookup 또는 subworkflow dispatch 전에 fail-closed로 실행하지 않는다.
- Workflow-node runtime의 순환/depth/target 설정 오류는 Celery retry로 재시도하지 않고 non-retryable runtime error로 즉시 실패한다.
- Active `type=workflow_node` deployment graph에 `scheduleTrigger`가 있어도 schedule record나 scheduler job을 생성하지 않는다.
- Scheduler startup query와 dispatch 시점은 모두 schedule deployment가 해당 app의 현재 `active_deployment_id`인지 재확인한다. Queue에는 graph가 아니라 deployment id를 넣고, worker가 실행 직전 active/type/app/current pointer를 다시 확인해 enqueue 후 삭제/비활성/stale/non-current가 된 deployment를 retry 없이 종료한다.
- APScheduler에 job이 남아 있어도 `Schedule.id + deployment_id` row가 없으면 queue와 budget service를 호출하지 않고 local job을 제거한다. Worker queue context에 다른 organization/workflow/app/deployment/version 또는 execution subject를 넣어도 DB의 canonical App/Deployment context로 덮어쓰거나 제거하고 correlation allowlist만 보존한다.
- Invalid cron/timezone 활성화는 safe `422 deployment.schedule_configuration_invalid`로 실패하고 parser 원문을 노출하지 않으며 schedule/deployment partial mutation을 남기지 않는다.
- Public route 목록에는 schedule claim 조회, status mutation, outcome acknowledgment 또는 redrive endpoint가 없어야 한다.
- Blocking preflight 예외는 broad catch에서 generic `400`으로 변환되지 않는다.
- Source-managed KB public 후보는 public exposure approval primitive가 없으면 blocked로 처리한다.
- Webhook capture start/status rejects unauthenticated requests.
- Webhook capture start/status rejects authenticated users without target workflow `deploy` permission.
- Webhook capture status rejects missing, wrong, expired, or different-requester `capture_id`.
- Webhook capture cancel deletes a waiting session, rejects wrong/different-requester `capture_id`, and requires target workflow `deploy` permission.
- Webhook received after capture cancel follows the normal execution path instead of the capture path.
- Webhook capture stores and returns only a redacted/capped payload preview; token, secret, authorization, cookie, password, raw payload/content fields and known token patterns such as JWT, GitHub, Slack, AWS, Google API keys, and PEM private keys are not returned as raw values. Public identifier fields such as `issue.key` and `project.key` are preserved, while secret-bearing names such as `api_key`, `secret_key`, `access_key`, `x-api-key`, `secret-key`, and `api.key` are redacted. Secret-like or oversized JSON field names are sanitized before returning or storing the preview. Large arrays are capped while iterating the preview and are not copied in full before applying the item limit.
- Webhook capture deletes the session after the captured status is read once.

## E2E Tests

- Deployment modal은 preflight preview가 blocked인 경우 safe reason과 required actions를 표시하고 hidden KB identity를 표시하지 않는다.
- Inactive save 후 activation을 시도하면 같은 preflight blocker가 사용자에게 표시된다.
- Disposable PostgreSQL에 연결한 dispatcher 두 개가 같은 occurrence를 동시에 처리해도 claim은 하나이고 `next_run_at`은 한 번만 전진한다.
- Duplicate Celery task를 Worker 두 개가 받아도 stable workflow run identity 하나와 engine admission 한 번만 발생한다.
- Disposable pgvector PostgreSQL CI는 실제 Alembic head에서 두 dispatcher session과 두 Worker admission session을 동시에 실행해 각각 winner가 하나임을 필수 검증한다. Opt-in skip만 존재하고 CI에서 실행되지 않는 상태는 완료 증거로 인정하지 않는다.
- Broker publish 전후 장애와 Worker admission 전 종료는 bounded recovery되고, admission 후 종료는 outcome unknown으로 격리되어 자동 replay되지 않는다.
- Migration-first, disabled rollout, drain, claim activation과 역순 rollback rehearsal에서 legacy direct dispatcher와 claim dispatcher가 동시에 활성화되지 않는다.
- Coordinated rollout이 첫 서비스 적용 뒤 실패하면 같은 commit image와 desired fingerprint를 가진 선행 서비스, 승인된 previous fingerprint를 가진 나머지 서비스 조합만 재개한다. 반대 순서, 다른 image, 임의 third fingerprint, active claim 상태의 direct settings 변경은 fail-closed한다.
- `claim -> disabled` 직접 전환은 evaluator가 거부한다. `drain -> disabled`는 rollback preflight가 nonterminal/unreviewed outcome/active task 중 하나라도 찾거나 Celery inspection을 완료하지 못하면 두 deployment 적용 전에 중단한다.

## Migration And Persistence Tests

- Alembic 기준 merge head에서 upgrade는 single head를 유지하고 claim table/constraint/index와 schedule-only nullable WorkflowRun executor를 정확히 반영한다. Controlled downgrade/re-upgrade는 system WorkflowRun 이력, admitted claim의 durable run correlation, active/unreviewed claim, configuration quarantine이 모두 없는 경우에만 성공하며, 하나라도 있으면 첫 schedule DDL 전에 fail-closed하고 revision을 보존한다.
- Claim `organization_id`는 non-null이고 canonical App과 일치하며 lifecycle FK cascade가 없다. Schedule/Deployment 삭제 뒤에도 outcome review organization provenance를 유지한다.
- Claim 생성, `next_run_at`, budget policy audit은 한 commit이며 audit/claim/next-run 중 하나가 실패하면 모두 rollback한다.
- Claim model은 generic ORM audit listener 대상이 아니며 raw input, graph, prompt/evidence, credential/provider response와 raw exception column이 없다.
- Dead-letter reason/correlation DB constraint는 admission 전 reason에 run/start correlation을 금지하고 admission 후 reason에 task/enqueue/start/run correlation을 모두 요구한다. 기존 모순 row가 있으면 migration은 값을 추측해 보정하지 않고 constraint 교체 전에 fail-closed한다.
- `pending`/`dispatching`/`enqueued`에 `workflow_run_id`를 직접 기록하면 domain과 실제 PostgreSQL check constraint가 모두 거부한다. 한 claim의 publish 결과 write 실패 뒤에도 같은 prepared batch의 다음 claim은 publish/result 처리를 계속하며, terminal finalization 일시 실패는 engine call 1회를 유지한 채 fresh session write만 bounded 재시도한다.
- Gateway/Worker startup readiness는 같은 shared helper 결과를 사용하고 introspection 실패, stale head, 필수 column 누락을 safe하게 거부한다. Concurrent migration은 advisory lock winner 하나만 진행하며 lock을 얻지 못한 실행은 DDL 전에 실패한다.

## Permission Tests

- Preflight preview는 workflow deploy/manage 권한 없이는 호출할 수 없다.
- Organization member이지만 KB `use` 권한이 없는 사용자의 private KB 후보는 authenticated run에서는 denied 또는 unavailable로 표시되고, anonymous deployment에서는 blocked로 표시된다.
- Client-supplied `audience` hint는 create/activation의 server-derived audience 차단을 완화하지 못한다.

## Edge Cases

- workflow-node target active deployment가 없으면 safe blocked/warning reason을 반환하고 target app hidden identity를 노출하지 않는다.
- workflow-node 순환 또는 depth cap 초과는 safe blocked reason으로 닫는다.
- workflow-node target이 현재 활성화 후보 app을 다시 참조하면 기존 active deployment가 아니라 candidate graph 기준으로 순환을 감지한다.
- 일부 authorized KB의 operational failure는 Knowledge partial-result 정책으로만 표시하고 preflight permission denial과 섞지 않는다.
