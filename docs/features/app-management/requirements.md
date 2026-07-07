# App Management Requirements

Status: Draft
Related Features: auth, organization, workflow, deployment, budget-management

## Purpose

TBD

이 feature의 범위에는 앱 탐색/마켓플레이스(`dashboard/explore` 화면, `apps.is_market`)와 앱 복제(`apps.forked_from`)를 포함한다. 마켓플레이스 공개 정책 고도화는 PRD 제외 범위이며, 여기서는 이미 구현된 탐색·복제 동작을 다룬다.

## User Stories

- TBD

## Functional Requirements

- APP-REQ-010: `GET /apps`는 active organization context 기준으로 현재 사용자가 읽을 수 있는 App 목록을 반환한다. 각 App은 기본 정보, primary `workflow_id`, 활성 배포 요약, owner 표시명을 포함한다.
- APP-REQ-020: `GET /apps/operations`는 `/dashboard/mymodule`의 원천으로, 현재 사용자가 운영 현황을 볼 수 있는 App/Workflow row를 반환한다. 각 row는 App summary, workflow permission summary, deployment state, latest run state를 포함한다.
- APP-REQ-030: Budget Management 확장 시 `GET /apps`의 `AppResponse.budget_status`와 `GET /apps/operations`의 `row.app.budget_status`는 같은 member 표면 shape를 사용한다. 계산 규칙, null 조건, 노출 금지 필드는 [budget-management requirements](../budget-management/requirements.md)의 BGT-REQ-022~023을 따른다. App의 primary workflow(`apps.workflow_id`)만 기준으로 하며, 같은 `app_id`의 과거/보조 Workflow row는 예산 상태 후보가 아니다.

## Policies And Edge Cases

- `budget_status`는 사용률과 상태만 포함한다. 예산 금액, 당월 비용 원문, credential, raw payload, secret 값은 App Management 응답에 포함하지 않는다.
- `budget_status`가 null이어도 App 접근 권한, 배포 상태, 실행 상태의 기존 응답 의미는 바뀌지 않는다.
- App의 `workflow_id`가 null이거나 primary workflow에 활성 예산이 없으면 `budget_status`는 null이다. 같은 `app_id`의 다른 Workflow row에 활성 예산이 있어도 이를 대체값으로 사용하지 않는다.
- App/operations 목록 조회와 예산 수정·비활성화·삭제가 경합해도 목록 API는 5xx 없이 완료되어야 한다. 예산 상태는 같은 조회 스냅샷 기준으로 일관되게 계산하고, 경합 결과 활성 예산을 찾을 수 없으면 null로 반환한다.

## Open Questions

- TBD
