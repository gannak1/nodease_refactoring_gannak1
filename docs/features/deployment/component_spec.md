# Deployment Component Spec

Status: Draft
Verified Against: `feature/mba-219 @ 7baedb4d`

## Screens

- Deployment flow modal or equivalent deployment settings surface.
- Existing App/workflow deployment list and activation controls.
- Workflow editor의 게시하기 메뉴와 공개/내부 챗봇 배포 성공 화면.

## Components

- `DeploymentFlowModal` calls `POST /api/v1/deployments/preflight` before active create.
- If preview returns `blocked`, deployment creation is not attempted and the existing error step displays safe reason labels and required actions.
- If preview returns `warning`, deployment creation continues. The successful deployment result carries only the formatted safe warning, and `SuccessStep` displays it in an amber text banner with `role="status"`.
- Collection preflight copy may show affected Collection count bucket and candidate-budget-limited boolean. It never renders selected Collection/child identifiers, labels, membership, or exact hidden counts.
- Existing activation toggle controls surface `deployment.preflight.blocked` responses without showing hidden KB identity.
- `DeploymentFlowModal`과 activation toggle은 기존 preflight response에서 MBA-219의 generic node reason/action을 함께 표시한다. Mail credential identity, Slack token/Webhook URL/channel/payload와 raw configuration은 렌더링하지 않는다.
- Active delete controls do not need preflight display in MBA-176 because delete no longer auto-promotes another deployment.
- 게시하기 메뉴는 공개 `chatbot`과 `internal_chatbot`을 별도 항목으로 제공한다.
- `SuccessStep`은 공개 챗봇에는 `/embed/chat/{url_slug}` 링크만, 내부 챗봇에는 `/modules/{workflow_id}/run?deploymentId={deployment_id}` 인증 링크만 표시한다. 내부 챗봇 결과에는 public REST API secret/test panel을 표시하지 않는다.
- Target Conversation Memory preflight snapshot includes immutable deployment version/snapshot hash, conversation mapping and node Memory policy version, contract/storage generation and required Worker capability. Runtime revalidates the same binding and never resolves an existing session through the latest active deployment pointer.
- Public Chatbot and authenticated internal Chatbot use separate runtime policy/composition dependencies. They may share a visual Client component, but not auth/CORS/Origin, access permission, preflight audience or session namespace.
- Exact public Origin/embed/CSP allowlist is a deployment-owned versioned policy adapter. Memory or Client code must not read environment fallback to widen it.

### Public Webhook Components

- Deployment success UI와 Webhook trigger node panel은 secret을 query에 결합한 URL을 생성·복사하지 않는다. Endpoint URL과 secret을 분리해 표시하고 primary 방식인 `Authorization: Bearer` header 설정을 안내한다. `X-Webhook-Secret`은 기존 caller 호환을 위한 API 계약으로만 유지하며 UI에서 권장하지 않는다.
- Secret을 URL, `localStorage`, `sessionStorage`, analytics, toast 또는 Client log에 넣지 않는다. MBA-247 전까지 기존 response에서 전달되는 secret 표시 동작은 호환 범위로 남지만 query-integrated URL은 제공하지 않는다.
- Gateway endpoint는 ASGI/HTTP inbound adapter로 raw header occurrence와 query key presence를 추출하고 bounded stream을 수신한다. Framework-independent `application/webhook_ingress` policy가 credential/media/JSON limits를 판정하며 endpoint는 typed error를 static HTTP code로 mapping한다.
- Existing capture, active deployment/runtime policy, budget와 background publish orchestration은 ingress validation 뒤의 transitional path로 유지한다. Client validation은 보안 판단이 아니며 Gateway를 우회할 수 없다.
- Gateway의 outermost ASGI middleware는 `/api/v1/hooks` query에서 `token` field를 값 보존 없이 제거하고 boolean marker로 400 rejection을 유지해 Uvicorn access log 노출을 막는다. Repository Nginx는 `/api/v1/hooks/` 전용 location의 access/error log를 억제하고 1 MiB/5초 idle body guard와 request streaming을 적용한다.

### Internal Schedule Dispatch Components

- `SchedulerService`는 periodic tick lifecycle만 담당하는 inbound adapter다.
- Deployment application의 occurrence/dispatch use case가 claim, budget decision, next-run advancement, audit와 publish state transition을 조율한다.
- Existing `apps/gateway/composition/deployment.py`가 preflight와 분리된 schedule dispatch builder로 SQLAlchemy repository/UnitOfWork, schedule audit recorder, next-fire calculator와 Celery publisher를 주입한다.
- MBA-219 schedule dependency builder는 같은 DB session의 configuration preflight port를 추가로 주입한다. Schedule application use case는 deployment preflight concrete class를 import하지 않고 canonical graph snapshot과 organization만 port에 전달한다.
- Workflow Engine Celery task는 claim locator를 application use case로 전달하고 result를 task outcome으로 mapping한다. `apps/workflow_engine/composition/schedule_dispatch.py`가 DB adapter, audit, runtime policy use case와 engine 생성을 조립하며 task 본문은 세션 수명과 단계 호출만 담당한다.
- Public claim 조회/redrive UI는 제공하지 않는다. Outcome unknown acknowledgment는 protected operational job/CLI에서만 수행한다.
- 기존 deployment list/modal은 claim status나 idempotency key를 사용자에게 표시하지 않는다.
- Invalid legacy cron/timezone은 원문 대신 `schedule_configuration_invalid`만 Schedule row에 durable하게 기록하고 due/uninitialized 후보에서 제외한다. 유효한 schedule configuration 저장 시 quarantine code와 cursor 상태를 재계산한다.
- Admission correlation의 `WorkflowRun` row가 visibility grace 이후에도 없으면 claim에 one-time reported timestamp와 system audit만 기록한다. 이 signal은 Log System 지연/누락을 관측하기 위한 것이며 workflow 또는 external effect를 replay하거나 raw run identity를 노출하지 않는다.

### Schedule Dispatch Configuration Contract

- Gateway와 Workflow Engine은 동일한 `SCHEDULE_DISPATCH_*` 환경변수 집합을 각 composition에서 검증해 주입받는다. 설정 파싱은 `apps/shared/domain/schedule_dispatch.py`가 소유하며, 두 프로세스가 서로 다른 mode/deadline을 사용하지 않도록 Helm helper, raw Kubernetes manifest, Docker Compose가 같은 기본값을 전달한다.
- Celery Worker process는 task 소비 전 이 공통 설정을 검증한다. startup hook을 우회한 전용 schedule task도 잘못된 설정을 raw error나 자동 retry로 노출하지 않고 safe permanent rejection으로 종료한다.
- `SCHEDULE_DISPATCH_MODE`의 기본값은 `disabled`다. `claim` 활성화는 Alembic migration 적용, disabled rollout, 기존 direct task drain과 pod 설정 일치 확인 이후에만 수행한다. `drain`은 신규 occurrence를 만들지 않고 이미 생성된 claim만 처리한다. `claim -> drain -> disabled`는 application rollout rollback이며, system schedule 실행 이력, admitted claim의 durable run correlation, active/unreviewed claim 또는 configuration quarantine이 남은 DB의 과거 schema downgrade는 모든 schedule revision에서 safe하게 거부된다.
- 일반 Dev workflow와 단일 Helm release는 `disabled` bootstrap/image rollout만 허용한다. Dev workflow도 live Gateway/Worker Deployment generation, replica와 non-terminating Pod의 Running/Ready/fingerprint 수렴을 fail-closed로 확인한다. Non-disabled mode는 immutable image identity, 실제 Pod 수렴과 안정 drain을 검증하는 coordinated workflow에서만 전환하며 rollout 실패를 성공으로 무시하지 않는다.
- Gateway와 Worker는 공통 schema readiness service를 사용하고 `claim`/`drain` startup에서 Alembic head와 필수 claim column을 모두 확인한다. Alembic online migration은 같은 connection에서 bounded wait advisory lock을 획득해 동시 migration을 직렬화한다.
- Coordinated rollout은 동일 commit의 Log System image를 migration 이후, schedule claim admission 이전에 배포·검증한다. `disabled` 최초 도입에 한해서만 기존 Gateway/Worker Deployment의 fingerprint annotation 누락을 bootstrap으로 취급한다.
- Helm/raw Kubernetes manifest는 mode와 모든 dispatch batch/lease/deadline/retry/retention 값을 포함한 canonical `nodease.io/schedule-dispatch-fingerprint` pod annotation을 기록하고 Downward API로 `SCHEDULE_DISPATCH_MODE_FINGERPRINT`를 주입한다. `claim`/`drain` process는 fingerprint가 없거나 실제 전체 설정과 다르면 fail-fast한다. Docker Compose는 같은 canonical 값을 직접 주입한다.
- Scheduler tick은 critical recovery, occurrence claim, pending dispatch를 먼저 수행한다. WorkflowRun visibility와 terminal cleanup은 각각 독립 UnitOfWork의 optional maintenance로 실행되어 실패가 dispatch를 중단하지 않는다.
- Pending dispatch는 canonical deployment/type/current-pointer 검증 뒤 configuration preflight를 budget보다 먼저 수행한다. Known blocker는 같은 UoW에서 `canceled + configuration_preflight_blocked`와 기존 canceled audit을 기록하고 publish batch에 넣지 않는다. Adapter/infrastructure exception은 UoW를 rollback해 fail-open을 막는다.
- `disabled`에서는 critical dispatch를 실행하지 않지만 schema-ready 환경의 visibility, retention cleanup과 pending/running age signal은 계속 실행한다.
- Coordinated production rollout은 mutable commit tag를 deployment identity로 사용하지 않는다. 기존 tag digest를 재사용하거나 신규 push digest를 확정한 뒤 Logger/Gateway/Worker manifest를 `repository@sha256`로 렌더링하고 실제 container imageID까지 검증한다.
- Schedule Celery publisher/task는 `ignore_result`를 사용하고 workflow output, RAG evidence, sync 상세를 result backend에 저장하지 않는다.
- Schedule signal과 Scheduler/Worker 오류 로그는 UUID, idempotency key, raw payload와 raw exception message를 기록하지 않는다. 개별 claim 역추적은 durable claim과 canonical audit row를 사용한다.
- Outcome review use case는 exact dead-letter claim을 lock하고 allowlisted resolution/correlation과 system audit만 같은 transaction에 기록한다. Rollback preflight는 별도 read use case/CLI이며 review와 redrive를 수행하지 않는다.
- Production Gateway/Worker workflow는 같은 `production-schema-rollout` concurrency group을 사용한다. 일반 image rollout preflight는 desired manifest fingerprint와 live Gateway/Worker fingerprint가 모두 같을 때만 진행한다. Protected `production` environment의 `.github/workflows/deploy-eks-schedule-coordinated.yml`은 승인된 이전 공통 fingerprint를 입력받아 양쪽 desired/current 상태를 판정하고, migration, commit image가 포함된 최종 manifest render, staged apply, 양 rollout 완료와 최종 fingerprint를 한 작업에서 검증한다. `claim` 활성화는 Worker 우선, `drain`/`disabled`는 Gateway 우선이며 active claim 설정을 바꾸려면 먼저 drain으로 전환해야 한다. 첫 단계 후 실패한 재실행은 먼저 적용돼야 할 서비스가 같은 commit image/desired fingerprint이고 다른 서비스가 승인된 이전 fingerprint일 때만 남은 단계부터 재개한다.
- Coordinated workflow는 `claim -> disabled` 직접 전환을 거부한다. `disabled`/`drain -> claim` activation과 `drain -> disabled` rollback은 새 Gateway image의 transition preflight CLI가 nonterminal claim과 미검토 outcome unknown이 모두 0임을 확인한 뒤에만 진행한다.
- Activation은 Legacy `workflow.execute_by_deployment`와 신규 dedicated schedule task, rollback은 신규 task의 active/reserved/scheduled 상태와 Redis workflow priority queue 전체 depth가 0인지 추가 확인한다. DB, worker inspection 또는 broker queue 확인 불가 시 fail-closed하고 Queue payload 원문은 읽거나 출력하지 않는다.
- Polling, batch size, lease/delivery/execution deadline, retry cap, retention 값은 환경변수로 조정할 수 있지만 domain range validation을 통과해야 한다. 잘못된 mode 또는 범위를 가진 값은 process startup에서 fail-fast한다.
- 이 설정은 secret이 아니지만 pod 환경과 운영 배포 이력에 남을 수 있으므로 raw workflow payload, credential, audit metadata와 섞어 기록하지 않는다.

## States

- `checking`: Preflight/create request in progress.
- `passed`: Preflight 통과 후 create를 계속 진행한다.
- `warning`: Create를 계속 진행하고 성공 화면에 non-blocking preflight warning을 표시한다.
- `blocked`: 활성 배포 생성/전환 불가. Error step 또는 toggle error message로 표시한다.
- `error`: 네트워크 또는 validation error. Hidden resource detail을 표시하지 않는다.

## Interactions

- Preview endpoint의 blocked response는 API 오류가 아니라 검사 결과로 처리하며, active create 요청을 보내지 않는다.
- Preview endpoint의 warning response는 active create를 계속하고 성공 결과에 safe warning text를 결합한다. Candidate budget warning을 배포 실패로 바꾸지 않는다.
- `is_active=false` 저장은 허용된 Knowledge activation warning과 null unresolved managed configuration warning을 보존할 수 있다. Non-null unavailable Mail credential, malformed graph, workflow-node structural 오류와 unsupported external validator처럼 inactive에서도 blocked인 결과는 저장하지 않는다. 현재 deployment modal은 active create만 제공한다.
- Active create 또는 activation toggle에서 `409 deployment.preflight.blocked`가 오면 error/blocked message로 safe reason과 required actions를 보여준다.
- Inactive preview는 null unresolved Mail/Slack configuration을 warning으로 표시하고 active create/toggle은 같은 문제를 blocked로 표시한다. Non-null unavailable credential, malformed graph와 unsupported external node는 inactive에서도 blocked로 표시한다.
- Shared graph validator는 endpoint, preflight와 Loop runtime이 최상위의 명시적 trigger/start 및 Loop body의 단일 implicit 진입점을 포함한 같은 structural contract를 사용하게 한다. Mail resource adapter는 bulk permission decision을 사용하며, preview는 무감사이고 enforcing facade는 확인된 same-organization permission denial을 정확히 한 번 감사한다.
- Workflow-node 대상은 node 설정의 target app 기준으로 검사된다는 점을 내부 상태에서 유지한다. UI copy는 workflow id나 hidden target identity를 노출하지 않는다.
- 내부 실행 페이지가 `401`을 받으면 현재 path/query/hash를 safe `next`로 보존해 로그인 화면으로 이동한다. 이메일/비밀번호 로그인만 same-origin `next`로 복귀하며 unsafe URL은 `/dashboard`로 닫는다.

## Accessibility

- Preflight status는 색상만으로 구분하지 않고 text label을 제공한다.
- 성공 화면의 non-blocking warning은 `role="status"`와 text reason/action을 제공한다.
- Required action list는 keyboard focus 순서 안에 있어야 하며, hidden KB id/name/path를 포함하지 않는다.
