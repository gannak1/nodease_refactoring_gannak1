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
