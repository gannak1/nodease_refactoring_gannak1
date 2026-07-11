# Deployment Component Spec

Status: Draft
Verified Against: TBD

## Screens

- Deployment flow modal or equivalent deployment settings surface.
- Existing App/workflow deployment list and activation controls.

## Components

- `DeploymentFlowModal` calls `POST /api/v1/deployments/preflight` before active create.
- If preview returns `blocked`, deployment creation is not attempted and the existing error step displays safe reason labels and required actions.
- Existing activation toggle controls surface `deployment.preflight.blocked` responses without showing hidden KB identity.
- Active delete controls do not need preflight display in MBA-176 because delete no longer auto-promotes another deployment.

### Internal Schedule Dispatch Components

- `SchedulerService`는 periodic tick lifecycle만 담당하는 inbound adapter다.
- Deployment application의 occurrence/dispatch use case가 claim, budget decision, next-run advancement, audit와 publish state transition을 조율한다.
- Existing `apps/gateway/composition/deployment.py`가 preflight와 분리된 schedule dispatch builder로 SQLAlchemy repository/UnitOfWork, schedule audit recorder, next-fire calculator와 Celery publisher를 주입한다.
- Workflow Engine Celery task는 claim locator를 application use case로 전달하고 result를 task outcome으로 mapping한다. DB query, runtime policy 조합과 engine 생성은 task 본문이 직접 소유하지 않는다.
- Public claim 조회/redrive UI는 제공하지 않는다. Outcome unknown acknowledgment는 protected operational job/CLI에서만 수행한다.
- 기존 deployment list/modal은 claim status나 idempotency key를 사용자에게 표시하지 않는다.
- Invalid legacy cron/timezone은 원문 대신 `schedule_configuration_invalid`만 Schedule row에 durable하게 기록하고 due/uninitialized 후보에서 제외한다. 유효한 schedule configuration 저장 시 quarantine code와 cursor 상태를 재계산한다.
- Admission correlation의 `WorkflowRun` row가 visibility grace 이후에도 없으면 claim에 one-time reported timestamp와 system audit만 기록한다. 이 signal은 Log System 지연/누락을 관측하기 위한 것이며 workflow 또는 external effect를 replay하거나 raw run identity를 노출하지 않는다.

### Schedule Dispatch Configuration Contract

- Gateway와 Workflow Engine은 동일한 `SCHEDULE_DISPATCH_*` 환경변수 집합을 각 composition에서 검증해 주입받는다. 설정 파싱은 `apps/shared/domain/schedule_dispatch.py`가 소유하며, 두 프로세스가 서로 다른 mode/deadline을 사용하지 않도록 Helm helper, raw Kubernetes manifest, Docker Compose가 같은 기본값을 전달한다.
- Celery Worker process는 task 소비 전 이 공통 설정을 검증한다. startup hook을 우회한 전용 schedule task도 잘못된 설정을 raw error나 자동 retry로 노출하지 않고 safe permanent rejection으로 종료한다.
- `SCHEDULE_DISPATCH_MODE`의 기본값은 `disabled`다. `claim` 활성화는 Alembic migration 적용, disabled rollout, 기존 direct task drain과 pod 설정 일치 확인 이후에만 수행한다. `drain`은 신규 occurrence를 만들지 않고 이미 생성된 claim만 처리한다. `claim -> drain -> disabled`는 application rollout rollback이며, system schedule 실행 이력, active/unreviewed claim 또는 configuration quarantine이 남은 DB의 과거 schema downgrade는 모든 schedule revision에서 safe하게 거부된다.
- Polling, batch size, lease/delivery/execution deadline, retry cap, retention 값은 환경변수로 조정할 수 있지만 domain range validation을 통과해야 한다. 잘못된 mode 또는 범위를 가진 값은 process startup에서 fail-fast한다.
- 이 설정은 secret이 아니지만 pod 환경과 운영 배포 이력에 남을 수 있으므로 raw workflow payload, credential, audit metadata와 섞어 기록하지 않는다.

## States

- `checking`: Preflight/create request in progress.
- `passed`: Preflight 통과 후 create를 계속 진행한다.
- `warning`: 현재 UI는 별도 warning panel을 표시하지 않고 create를 계속 진행한다.
- `blocked`: 활성 배포 생성/전환 불가. Error step 또는 toggle error message로 표시한다.
- `error`: 네트워크 또는 validation error. Hidden resource detail을 표시하지 않는다.

## Interactions

- Preview endpoint의 blocked response는 API 오류가 아니라 검사 결과로 처리하며, active create 요청을 보내지 않는다.
- `is_active=false` 저장은 blocked preview가 있더라도 허용할 수 있지만, 현재 deployment modal은 active create만 제공한다.
- Active create 또는 activation toggle에서 `409 deployment.preflight.blocked`가 오면 error/blocked message로 safe reason과 required actions를 보여준다.
- Workflow-node 대상은 node 설정의 target app 기준으로 검사된다는 점을 내부 상태에서 유지한다. UI copy는 workflow id나 hidden target identity를 노출하지 않는다.

## Accessibility

- Preflight status는 색상만으로 구분하지 않고 text label을 제공한다.
- Required action list는 keyboard focus 순서 안에 있어야 하며, hidden KB id/name/path를 포함하지 않는다.
