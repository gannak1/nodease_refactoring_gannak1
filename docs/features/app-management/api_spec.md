# App Management API Spec

Status: Draft
Verified Against: TBD

## Endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| GET | `/api/v1/apps` | 현재 사용자가 접근할 수 있는 App 목록 | authenticated organization member |
| GET | `/api/v1/apps/operations` | 내 모듈 운영 현황 목록 | authenticated organization member |

## Request And Response Models

### GET /apps

기존 `AppResponse`는 App 기본 정보, primary `workflow_id`, 활성 배포 요약, owner 표시명을 반환한다.

Budget Management 확장 계약은 [budget-management api_spec](../budget-management/api_spec.md)의 `GET /apps (확장)`을 따른다.

```json
{
  "id": "<uuid>",
  "name": "<string>",
  "workflow_id": "<uuid|null>",
  "budget_status": {
    "usage_ratio": 0.923457,
    "status": "at_risk"
  }
}
```

- `budget_status`는 member 표면용 요약이다. 예산 금액과 당월 비용 원문은 포함하지 않는다.
- 활성 예산이 없거나 `workflow_id`가 null이면 `budget_status`는 null이다.
- 같은 `app_id`에 과거/보조 Workflow row가 남아 있어도 App의 primary workflow(`apps.workflow_id`)가 아니면 `budget_status` 후보로 사용하지 않는다.
- `budget_status` 계산 규칙과 N+1 금지는 [budget-management api_spec](../budget-management/api_spec.md)의 `GET /apps, GET /apps/operations (확장)`을 따른다.
- 당월 비용 합산은 실행 차단과 동일하게 primary workflow id와 KST 월 경계 기준이며, `llm_usage_logs.organization_id`가 NULL인 기존/마이그레이션 usage row도 포함한다.

### GET /apps/operations

`/dashboard/mymodule`의 원천이다. 응답 항목의 `app` summary는 App 기본 정보와 운영 상태를 함께 표시하기 위한 안전 요약이다.

Budget Management 확장 시 `app.budget_status`는 `GET /apps`의 `budget_status`와 동일한 shape를 사용한다.

```json
{
  "app": {
    "id": "<uuid>",
    "name": "<string>",
    "workflow_id": "<uuid|null>",
    "budget_status": {
      "usage_ratio": 0.923457,
      "status": "at_risk"
    }
  },
  "deployment": { "...": "..." },
  "latest_run": { "...": "..." }
}
```

## Errors

- `401`: 미인증
- `403`: organization scope 또는 App 접근 권한 없음
- `404`: 직접 조회 대상이 없거나 scope 밖 리소스

## Permissions

- App 목록과 운영 현황은 active organization context를 기준으로 사용자가 접근 가능한 App/Workflow만 반환한다.
- `budget_status`는 사용률과 상태만 노출하며, 예산 금액/비용 원문은 관리자 API에만 노출한다.
