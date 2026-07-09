# Deployment Component Spec

Status: Draft
Verified Against: TBD

## Screens

- Deployment flow modal or equivalent deployment settings surface.
- Existing App/workflow deployment list and activation controls.

## Components

- `DeploymentFlowModal` or current deployment creation form calls `POST /api/v1/deployments/preflight` before active create/activation.
- Preflight result panel displays `passed`, `warning`, or `blocked` states with safe reason labels and required actions.
- Existing activation toggle/delete controls must surface `deployment.preflight.blocked` responses without showing hidden KB identity.

## States

- `checking`: Preflight request in progress.
- `passed`: 배포 활성화 가능.
- `warning`: 저장 가능하지만 활성화 전 확인 필요. Inactive create may proceed.
- `blocked`: 활성 배포 생성/전환 불가.
- `error`: 네트워크 또는 validation error. Hidden resource detail을 표시하지 않는다.

## Interactions

- Preview endpoint의 blocked response는 API 오류가 아니라 검사 결과로 표시한다.
- `is_active=false` 저장은 blocked preview가 있더라도 허용할 수 있지만, UI는 이후 활성화 시 같은 이슈가 차단된다는 점을 명확히 표시한다.
- Active create 또는 activation toggle에서 `409 deployment.preflight.blocked`가 오면 form state를 blocked로 전환하고 required actions를 보여준다.
- Workflow-node 대상은 node 설정의 target app 기준으로 검사된다는 점을 내부 상태에서 유지한다. UI copy는 workflow id나 hidden target identity를 노출하지 않는다.

## Accessibility

- Preflight status는 색상만으로 구분하지 않고 text label을 제공한다.
- Required action list는 keyboard focus 순서 안에 있어야 하며, hidden KB id/name/path를 포함하지 않는다.
