# Deployment Test Cases

Status: Draft
Verified Against: `feature/mba-234 @ 647913b9`

## Unit Tests

- Deployment application package는 FastAPI, SQLAlchemy, DB model, concrete adapter/service/composition module을 import하지 않는다.
- Pure preflight use case는 repository port snapshot만으로 결과를 만들고 active blocker는 HTTPException이 아닌 typed `DeploymentPreflightBlocked`를 반환한다. Compatibility facade만 이를 기존 409 envelope으로 mapping한다.
- Preflight graph scanner는 shared strict parser로 root/embedded LLM node의 direct KB와 Collection 목록을 검사한다. Malformed shape와 20개 초과는 active/inactive 여부와 무관한 fixed non-downgradable blocker다.
- Embedded `subGraph` 순회는 반복 방식이며 호출 스택보다 깊은 입력에서도 같은 Collection audience policy를 적용한다.
- Selected Collection repository projection은 selected IDs, active organization, active lifecycle, `sync_state != source_deleted`로 제한하고 same-organization active/retrieval-visible KB aggregate만 계산한다. Direct KB preflight도 retrieval-visible completed chunk가 없는 KB를 generic unavailable로 처리한다. Child ID를 application result로 반환하거나 Collection별 N+1 query를 만들지 않는다.
- Anonymous-public preflight는 private Collection과 source-managed Collection/member를 fail-closed하고, public manual Collection은 통과시킨다. Missing/inactive/cross-org는 하나의 generic unavailable code로 처리한다.
- Candidate budget 가능성은 bucket/boolean warning으로만 반환되고 active create를 차단하지 않는다. Client success step은 warning을 text status로 표시한다.
- MBA-219 node configuration evaluator는 FastAPI, SQLAlchemy, concrete service와 catalog loader를 import하지 않고 composition이 주입한 immutable node side-effect mapping과 resource snapshot port만 사용한다.
- Mail/Gmail Draft/Mail Acknowledge/Slack은 managed validator, LLM/HTTP/GitHub는 runtime-authoritative로 명시된다. External node가 registry에 없거나 `implemented=false`이면 실행 표면에서 `node_configuration_validator_unavailable`로 차단한다.
- 최상위 graph와 다단계 Loop `subGraph`, WorkflowNode target graph의 managed node를 같은 audience/principal로 검사한다. Malformed nested graph와 nesting 한도 초과는 `workflow_graph_invalid`로 차단한다.
- Runtime audience resolver는 `api`, `webapp`, `widget`, `chatbot`, `mcp`, `schedule`, `webhook`를 anonymous public-only로 판정한다.
- `internal_chatbot`은 authenticated run/run-info surface에서만 허용하고 public info와 public app run surface에서는 fail-closed로 거부한다.
- `internal_chatbot` preflight는 server-derived audience를 `authenticated_user`로 판정하며 private KB 참조만으로 활성 배포를 차단하지 않는다. 다만 repository를 조회해 direct KB와 Collection의 organization/lifecycle/sync/retrieval readiness를 검증하고 unavailable reference는 차단한다.
- `internal_chatbot` authenticated run은 current user를 `execution_subject`로 Runtime에 전달하고, 챗봇 `memory_mode`와 deployment/user 기준 conversation namespace를 적용한다.
- `workflow_node` direct public/API/webhook/authenticated run execution is rejected. Subworkflow audience resolver는 parent execution subject를 상속하고, subject가 없으면 anonymous public-only로 판정한다.
- Workflow-node target resolver는 `workflowNode.data.appId`를 사용하고 `workflowId`로 target app을 찾지 않는다.
- Workflow-node target app이 존재하고 `active_deployment_id`가 있어도 active deployment의 `type`이 `workflow_node`가 아니면 `workflow_node_target_unavailable`로 처리한다.
- Workflow-node target이 pending active candidate graph를 가리킬 때도 candidate deployment type이 `workflow_node`가 아니면 `workflow_node_target_unavailable`로 처리한다.
- Workflow-node target unavailable, cycle, depth cap 초과는 `workflow_node_inherited` audience나 inactive preview에서도 warning으로 낮추지 않고 blocked로 유지한다.
- Scheduler service는 active `type=schedule` deployment만 로드/실행하고, non-schedule deployment id로 job이 호출되면 dispatch하지 않는다.
- Preflight response sanitizer는 hidden KB id/name/path, exact denied count, raw source metadata, raw exception을 제거한다.
- Preflight response/409/public graph projection은 Collection/child ID, label, membership, exact count와 두 Knowledge reference 배열을 노출하지 않는다.
- Central deployment runtime policy matrix는 public info, authenticated run/run-info, API secret run, webhook run, schedule run, workflow-node child run surface별 허용 deployment type을 고정하고 unknown surface/type을 fail-closed로 거부한다. 기본 policy는 불변 객체이며 composition dependency로 교체 주입할 수 있지만 환경변수나 전역 mutation으로 확장할 수 없다.
- Schedule occurrence key/state/reason/settings helper는 DB/framework 없이 테스트하고 naive datetime, unknown state/reason, mutable settings input을 fail-closed한다.
- Schedule application use case는 access-management command/model/port/recorder와 FastAPI/Celery/SQLAlchemy query를 import하지 않는다. Schedule 전용 audit port를 사용하고 concrete Gateway UnitOfWork만 composition에서 주입한다.
- Schedule audit recorder는 system actor, canonical action/target과 strict metadata allowlist만 현재 UoW에 추가하며 commit/rollback하지 않는다.
- System tick의 `Schedule.next_run_at`/`last_run_at`만 바뀌면 generic `schedule.updated`가 생성되지 않고 cron/timezone/lifecycle 또는 unrelated tracked mutation audit은 유지된다.

## API Tests

- `POST /api/v1/deployments/preflight`는 blocked 결과도 `200 OK`와 `status="blocked"`로 반환한다.
- `POST /api/v1/deployments/preflight` with `is_active=false`는 null unresolved blocker만 `status="warning"`으로 반환하되 required action은 유지한다. Non-null unavailable credential과 structural blocker는 `status="blocked"`다.
- `POST /api/v1/deployments` with `is_active=true`는 private KB가 anonymous/public 실행 surface에 포함되면 `409 deployment.preflight.blocked`를 반환한다.
- `POST /api/v1/deployments` with `is_active=false`는 같은 graph를 저장할 수 있지만 active deployment 교체, public URL 활성화, schedule job 생성을 하지 않는다.
- Inactive deployment activation/toggle은 private KB preflight 실패 시 `409 deployment.preflight.blocked`를 반환한다.
- Active create/toggle은 unresolved/invalid Mail 또는 Slack, unavailable Mail credential, subject 없는 Mail surface를 기존 `409 deployment.preflight.blocked` envelope으로 차단하며 task/schedule/active-pointer side effect를 만들지 않는다.
- `is_active=false` preview/create는 null unresolved configuration만 warning으로 보존한다. Invalid Mail/Slack 조합, 임의 non-null UUID, revoked/cross-organization/permission-denied credential, malformed graph와 validator unavailable은 blocked로 유지한다.
- Missing/revoked/cross-organization/permission-denied Mail credential은 모두 `mail_credential_unavailable`이며 response에 credential ID/name/email과 permission 상세가 없다.
- Dangling edge, cycle, duplicate node ID, 진입점 오류와 고립 실행 node는 최상위와 Loop subgraph에서 `workflow_graph_invalid`로 차단되고 inactive deployment row와 task를 만들지 않는다. 최상위 graph는 명시적 trigger/start 하나를 요구하고 Loop body는 별도 trigger 없이 incoming executable edge가 없는 실행 진입점 하나를 허용한다. 합산 node 1,000개, edge 5,000개와 depth 16 경계는 통과하며 각각 1개 초과하면 같은 reason으로 차단한다.
- Preview permission denial은 audit 0건이며 create/toggle enforcement의 same-organization denial은 resource별 `permission.denied` 정확히 1건이다.
- 여러 Mail credential preflight는 scalar permission과 같은 결과를 내고 organization/user/membership query를 credential마다 반복하지 않는다. Scalar/bulk 모두 revoked credential의 잔존 grant를 운영 권한으로 집계하지 않는다.
- Active deployment delete는 다른 deployment를 자동 active로 승격하지 않는다.
- Public/API run endpoint, webhook endpoint, authenticated deployment run/run-info endpoint는 `workflow_node` active deployment를 직접 실행하거나 실행 정보를 노출하지 않는다.
- Public info와 public/API slug run은 `App.active_deployment_id`가 가리키는 deployment의 `app_id`가 요청 app과 일치할 때만 노출하거나 실행한다. 다른 app 소유 deployment를 가리키는 stale/corrupt pointer는 safe 404로 닫고 task를 dispatch하지 않는다.
- Public info 기본 policy는 `webapp`, `widget`, `chatbot`만 허용하고 API/`internal_chatbot`/MCP/schedule/webhook/workflow-node/unknown/empty type을 safe 404로 닫는다. 명시적으로 주입한 immutable test policy가 기본 policy를 mutation하지 않고 독립적으로 동작하는지 검증한다.
- App status, clone, workflow-node deployment listing은 active deployment id뿐 아니라 deployment `app_id` ownership도 확인한다. Cross-app pointer로 다른 app의 graph/schema/status를 복제하거나 노출하지 않는다.
- Webhook endpoint는 active deployment가 `type=webhook`이 아닌 경우 API/chatbot/schedule/workflow-node 등 모든 non-webhook deployment와 unknown/empty type을 safe 404로 거부하며, budget check와 background task 등록 전에 종료한다.
- Webhook endpoint는 Bearer 또는 `X-Webhook-Secret` 중 정확히 하나의 valid credential source만 허용한다. Scheme case-insensitivity, credential byte 보존, 1/512-byte 경계, non-ASCII/empty/malformed/oversized candidate와 constant-time verifier 경로를 검증한다.
- Query `token` key는 empty/multiple/value 없는 형태와 valid header 동반 여부에 관계없이 static `400 webhook.query_secret_not_supported`로 body read 전에 거부된다. Query 값, raw target, credential header와 parser error가 response/log/audit/trace/metric에 남지 않는다.
- Bearer와 custom header 동시 사용, 같은 credential header duplicate occurrence와 comma-folded ambiguous value는 값이 같아도 `400 webhook.credential_ambiguous`로 거부하고 body/capture/deployment/budget/background publish를 건드리지 않는다.
- Missing/invalid credential과 invalid server-side secret state는 같은 `403 webhook.authentication_failed`를 반환하며 unauthenticated body를 읽지 않는다.
- Missing/duplicate/malformed Content-Type, unsupported type/charset, duplicate/compressed Content-Encoding은 `415 webhook.payload.unsupported_media_type`으로 queue admission 전에 거부된다. Case-insensitive `application/json`, vendor `application/*+json`, UTF-8 charset와 well-formed non-charset parameter는 허용된다.
- Repository Nginx에서 query sentinel을 붙인 1 MiB 초과 Webhook 요청은 413으로 거부되며 sentinel과 request target이 access/error log에 남지 않는다. Nginx config test는 Webhook location의 log 억제, `client_max_body_size 1m`, `client_body_timeout 5s`, `proxy_request_buffering off`를 함께 확인한다.
- Gateway query-redaction middleware는 exact/empty/repeated/percent-encoded `token` field를 downstream scope에서 제거하고 boolean marker만 보존한다. 다른 Webhook query field와 비-Webhook query는 바꾸지 않으며, 실제 Uvicorn access log에 synthetic token value가 남지 않는지 확인한다.
- Content-Length는 missing, exact 1 MiB, over-limit, understated, duplicate, negative, non-decimal 경계를 검증한다. Actual stream은 0/exact/over-limit와 multi-chunk crossing을 검증하고 over-limit은 `413 webhook.payload.too_large`로 즉시 중단된다.
- Body stream stall/disconnect, decode/parse/traversal stage deadline을 검증한다. 5초를 넘긴 성공은 없고 timeout은 `408 webhook.payload.timeout`, disconnect는 `400 webhook.payload.invalid`이며 raw exception은 노출되지 않는다.
- Strict JSON은 object root와 nested standard JSON value를 보존한다. Array/string/finite number/boolean/null root, UTF-8 BOM, invalid UTF-8, trailing data와 `NaN`/`Infinity`는 `400 webhook.payload.invalid`로 downstream 전에 거부한다. Depth 19/20/21과 total node 9,999/10,000/10,001 경계를 iterative traversal로 검증한다.
- Payload의 `app_id`, organization/workflow/deployment/user/trigger/execution-context 유사 key는 일반 workflow input으로만 전달되고 server-derived execution context나 ORM field를 덮어쓰지 않는다.
- App 404, query/header/auth/media/size/JSON 실패 단계별 spy test는 body read, capture mutation, deployment query, budget, BackgroundTasks와 Celery publish가 mandatory order보다 먼저 발생하지 않는지 검증한다.
- 동일한 valid webhook delivery 두 건은 각각 기존 admission을 거친다. MBA-93은 payload hash dedupe나 exactly-once를 약속하지 않으며 MBA-247 미병합 상태에서는 single active secret 회귀만 검증한다.
- Deployment success UI와 Webhook node panel은 query-integrated URL을 표시·복사하지 않고 endpoint와 header instruction을 분리한다. Secret은 URL, browser storage, analytics 또는 Client log에 저장되지 않는다.
- Repository Nginx config/smoke는 webhook location의 query/header safe logging, 1 MiB body guard와 5초 idle timeout을 검증한다. Direct Gateway test가 static detail code를, proxy test가 edge status와 secret 비노출을 검증하며 production ingress 설정은 rollout evidence로 별도 확인한다.
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
- 공개/내부 챗봇 배포 결과는 각각 공개 링크와 인증 내부 링크만 표시하며, 내부 링크의 `401`은 safe `next`를 보존해 이메일/비밀번호 로그인 후 원래 링크로 복귀한다. 상세 assertion은 [chatbot-deployment test cases](../chatbot-deployment/test_cases.md)를 따른다.
- Disposable PostgreSQL에 연결한 dispatcher 두 개가 같은 occurrence를 동시에 처리해도 claim은 하나이고 `next_run_at`은 한 번만 전진한다.
- Duplicate Celery task를 Worker 두 개가 받아도 stable workflow run identity 하나와 engine admission 한 번만 발생한다.
- Schedule dispatch가 managed node blocker를 발견하면 budget과 Celery publisher 호출은 0회이고 claim은 `canceled + configuration_preflight_blocked`, audit은 기존 `schedule_dispatch.canceled`와 safe reason만 가진다.
- Schedule preflight adapter가 infrastructure exception을 내면 UoW가 rollback되고 publish request가 생성되지 않는다.
- Disposable pgvector PostgreSQL CI는 실제 Alembic head에서 두 dispatcher session과 두 Worker admission session을 동시에 실행해 각각 winner가 하나임을 필수 검증한다. Opt-in skip만 존재하고 CI에서 실행되지 않는 상태는 완료 증거로 인정하지 않는다.
- Broker publish 전후 장애와 Worker admission 전 종료는 bounded recovery되고, admission 후 종료는 outcome unknown으로 격리되어 자동 replay되지 않는다.
- Migration-first, disabled rollout, drain, claim activation과 역순 rollback rehearsal에서 legacy direct dispatcher와 claim dispatcher가 동시에 활성화되지 않는다.
- Coordinated rollout이 첫 서비스 적용 뒤 실패하면 같은 commit image와 desired fingerprint를 가진 선행 서비스, 승인된 previous fingerprint를 가진 나머지 서비스 조합만 재개한다. 반대 순서, 다른 image, 임의 third fingerprint, active claim 상태의 direct settings 변경은 fail-closed한다.
- `claim -> disabled` 직접 전환은 evaluator가 거부한다. `disabled`/`drain -> claim` activation과 `drain -> disabled` rollback은 transition preflight가 nonterminal/unreviewed outcome을 하나라도 찾거나 DB 검사를 완료하지 못하면 두 deployment 적용 전에 중단한다.
- Activation preflight는 legacy/new schedule task, rollback preflight는 new schedule task가 active/reserved/scheduled이거나 Redis workflow queue depth가 0이 아니면 중단한다. Redis inspection 실패도 fail-closed하며 payload/body를 파싱하거나 로그에 남기지 않는다.

## Migration And Persistence Tests

- Alembic 기준 merge head에서 upgrade는 single head를 유지하고 claim table/constraint/index와 schedule-only nullable WorkflowRun executor를 정확히 반영한다. Controlled downgrade/re-upgrade는 system WorkflowRun 이력, admitted claim의 durable run correlation, active/unreviewed claim, configuration quarantine이 모두 없는 경우에만 성공하며, 하나라도 있으면 첫 schedule DDL 전에 fail-closed하고 revision을 보존한다.
- Claim `organization_id`는 non-null이고 canonical App과 일치하며 lifecycle FK cascade가 없다. Schedule/Deployment 삭제 뒤에도 outcome review organization provenance를 유지한다.
- Claim 생성, `next_run_at`, budget policy audit은 한 commit이며 audit/claim/next-run 중 하나가 실패하면 모두 rollback한다.
- Claim model은 generic ORM audit listener 대상이 아니며 raw input, graph, prompt/evidence, credential/provider response와 raw exception column이 없다.
- Dead-letter reason/correlation DB constraint는 admission 전 reason에 run/start correlation을 금지하고 admission 후 reason에 task/enqueue/start/run correlation을 모두 요구한다. 기존 모순 row가 있으면 migration은 값을 추측해 보정하지 않고 constraint 교체 전에 fail-closed한다.
- 실제 PostgreSQL은 null safe reason의 canceled/dead-lettered claim, null resolution의 completed outcome review, null task id의 system schedule WorkflowRun을 모두 거부한다.
- MBA-219 migration 이후 실제 PostgreSQL은 canceled claim의 `configuration_preflight_blocked`를 허용하지만 pending/dispatching/enqueued/running/succeeded/dead-lettered 상태의 같은 reason은 거부한다. 해당 reason row가 남아 있으면 downgrade는 constraint DDL 전에 fail-closed한다.
- `pending`/`dispatching`/`enqueued`에 `workflow_run_id`를 직접 기록하면 domain과 실제 PostgreSQL check constraint가 모두 거부한다. 한 claim의 publish 결과 write 실패 뒤에도 같은 prepared batch의 다음 claim은 publish/result 처리를 계속하며, terminal finalization 일시 실패는 engine call 1회를 유지한 채 fresh session write만 bounded 재시도한다.
- Gateway/Worker startup readiness는 같은 shared helper 결과를 사용하고 introspection 실패, stale head, 필수 column 누락을 safe하게 거부한다. Concurrent migration은 advisory lock owner 하나만 진행하며 contender는 bounded wait 안에서 owner가 끝나면 이어서 진행하고 제한 시간을 넘기면 DDL 전에 실패한다.
- 기존 운영 Deployment에 fingerprint annotation이 없는 최초 `disabled` rollout은 bootstrap으로 진행되지만, `drain`/`claim` desired mode에서 annotation 누락은 fail-closed한다.
- Coordinated claim rollout은 동일 commit Logger image를 Gateway/Worker보다 먼저 배포하고 image identity를 검증한다. 이전 Logger가 남아 있거나 Logger rollout이 실패하면 claim admission을 활성화하지 않는다.
- Coordinated rollout 첫 시도에서 일부 image push 또는 Deployment 적용 후 실패한 뒤 같은 commit으로 재실행하면, 이미 존재하는 ECR digest를 재사용하고 immutable image identity로 남은 단계를 수행한다. 최종 성공은 Logger/Gateway/Worker의 observed generation, desired/updated/Ready/available replica와 non-terminating Pod spec image/container imageID/fingerprint/Ready condition이 모두 일치할 때만 허용한다.
- Activation/rollback preflight에서 일부 Worker가 inspect에 응답하지 않거나 task가 queue 확인 사이 active로 이동하면 전환을 차단한다. 기대 Ready Worker 집합과 응답 집합이 일치하고 앞뒤 task/queue 관측이 연속 두 번 0일 때만 통과한다.
- Lock 대기 또는 느린 budget 평가가 transaction 시작 뒤 발생해도 dispatch lease와 execution deadline은 전환 직전 DB wall clock 이후로 설정되고 commit 직후 만료되지 않는다.
- `disabled` mode에서 신규 occurrence/dispatch/admission은 0건이지만 schema-ready DB의 visibility, terminal cleanup, pending/running age 관측은 계속 실행된다. Schema가 없는 최초 bootstrap에서는 maintenance를 시작하지 않는다.
- Dev 일반 배포와 Helm render에서 non-disabled mode를 요청하면 coordinated workflow 안내와 함께 실패한다. Live Gateway/Worker가 claim/drain/mixed이거나 한쪽만 없는 bootstrap 상태, Deployment generation/replica 미수렴, terminating Pod를 제외한 실제 Pod의 Running/Ready/fingerprint 불일치 상태에서도 단독 disabled 전환을 거부한다. 양쪽이 이미 수렴한 disabled 상태이면 Gateway/Worker를 함께 배포할 때만 disabled fingerprint 설정 변경을 허용하고, 단독 service deploy는 live/desired fingerprint가 같아야 한다. Unrelated service만 배포할 때는 schedule component를 조회하거나 변경하지 않는다. Rollout status 실패는 무시되지 않는다.
- 기본 환경에서 schedule schema downgrade를 시도하면 sibling migration DDL 전에 실패하고 Alembic head가 유지된다. 파괴적 opt-in 없는 성공 downgrade/re-upgrade는 안전성 증거로 인정하지 않는다.
- Schedule Celery task의 producer와 task registration은 모두 `ignore_result=True`이고 `task_store_errors_even_if_ignored=False`다. 성공과 실패 실행 뒤 Redis result backend에는 workflow output, RAG evidence, sync 상세 또는 raw exception이 생성되지 않으며 task outcome은 claim/status/finalization summary로 제한된다. 실제 Redis key 부재는 opt-in integration evidence로 별도 실행한다.
- Schedule structured signal capture와 Scheduler/Worker 오류 log capture에는 정의된 event/value/status/reason/mode 또는 operation/attempt/exception type만 존재하고 UUID, idempotency key, raw payload와 raw exception message가 없다.
- 1024회를 넘는 고빈도 missed occurrence도 quarantine 없이 현재 시각 이후 첫 fire time으로 coalesce하고, 미래 cursor를 과거로 되돌리지 않는다.

## Permission Tests

- Preflight preview는 workflow deploy/manage 권한 없이는 호출할 수 없다.
- Organization member이지만 KB `use` 권한이 없는 사용자의 private KB 후보는 authenticated run에서는 denied 또는 unavailable로 표시되고, anonymous deployment에서는 blocked로 표시된다.
- Client-supplied `audience` hint는 create/activation의 server-derived audience 차단을 완화하지 못한다.
- `authenticated_user` application override가 명시된 내부 use-case 테스트 외에는 public deployment service가 authenticated override를 전달하지 않는다.
- System schedule의 LLM credential permission denial은 credential principal을 user audit actor로 사용하지 않고 system actor로 기록한다.
- Terminal cleanup은 retention을 지난 일반 dead-letter와 검토 완료 `execution_outcome_unknown` claim을 정리하지만, `outcome_reviewed_at`이 null인 `execution_outcome_unknown` claim은 보존한다.
- `disabled` mode는 BackgroundScheduler job 또는 legacy direct enqueue를 만들지 않는다. Schedule 실행이 필요한 환경은 drain 검증 없이 fallback하지 않고 `claim` mode activation 절차를 사용한다.

## Edge Cases

- workflow-node target active deployment가 없으면 safe blocked/warning reason을 반환하고 target app hidden identity를 노출하지 않는다.
- workflow-node 순환 또는 depth cap 초과는 safe blocked reason으로 닫는다.
- 1,100단계 embedded subgraph도 recursive stack error 없이 검사하고 최하위 Collection blocker를 반환한다.
- Direct-only, Collection-only, mixed preflight 결과는 기존 KB bucket을 보존하면서 additive Collection bucket/limit flag를 반환한다.
- Warning-only preflight 뒤 create가 정확히 한 번 호출되고 성공 결과에 safe warning이 표시되며, blocked preflight 뒤에는 create가 호출되지 않는다.
- workflow-node target이 현재 활성화 후보 app을 다시 참조하면 기존 active deployment가 아니라 candidate graph 기준으로 순환을 감지한다.
- 일부 authorized KB의 operational failure는 Knowledge partial-result 정책으로만 표시하고 preflight permission denial과 섞지 않는다.
- Conversation-capable activation preflight는 input/output mapping, node Memory policy, immutable deployment version/snapshot hash, contract/storage generation과 Worker capability 누락을 각각 fail-closed 한다.
- Preflight 통과 뒤 active deployment pointer가 바뀌어도 old session task가 새 snapshot으로 자동 rebind되지 않고 pinned version을 실행하거나 side effect 전에 version conflict로 닫힌다.
- Public `chatbot` preflight는 login cookie나 client audience hint가 있어도 anonymous public-only이며 private KB 후보를 차단한다.
- Future authenticated internal Chatbot policy는 public route, public Access Grant, generic workflow execute 권한만으로 우회할 수 없고 별도 access permission/runtime namespace를 요구한다.
- API/webapp/widget/MCP/workflow-node/schedule/webhook와 일반 authenticated deployment run은 explicit future contract 없이 Conversation Session을 생성하지 않는다.
- Missing/null/unlisted Origin, wildcard, client config와 environment fallback은 public browser session activation/create를 허용하지 않는다. Versioned deployment allowlist만 통과한다.
- Runtime principal mapping은 authenticated execution subject, credential principal, billing principal과 audit actor를 구분하며 public actor에 app/deployment creator를 합성하지 않는다.
