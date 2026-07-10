# App Management API Spec

Status: Draft
Verified Against: TBD

## Endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| GET | `/api/v1/apps` | 현재 사용자가 접근할 수 있는 App 목록 | authenticated organization member |
| GET | `/api/v1/apps/operations` | 내 모듈 운영 현황 목록 | organization manager or workflow builder/manager |

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

- `budget_status`는 안전 목록 요약이다. 예산 금액과 당월 비용 원문은 포함하지 않는다.
- 활성 예산이 없거나 `workflow_id`가 null이면 `budget_status`는 null이다.
- 같은 `app_id`에 과거/보조 Workflow row가 남아 있어도 App의 primary workflow(`apps.workflow_id`)가 아니면 `budget_status` 후보로 사용하지 않는다.
- `budget_status` 계산 규칙과 N+1 금지는 [budget-management api_spec](../budget-management/api_spec.md)의 `GET /apps, GET /apps/operations (확장)`을 따른다.
- 당월 비용 합산은 실행 차단과 동일하게 primary workflow id와 KST 월 경계 기준이며, `llm_usage_logs.organization_id`가 NULL인 기존/마이그레이션 usage row도 포함한다.

### GET /apps/operations

`/dashboard/mymodule`의 원천이다. 이 화면은 최종 사용자의 workflow 실행 표면이 아니라 작성자/운영자가 배포, 권한, 비용, 최근 실행 상태를 확인하는 운영 표면이다. 응답 항목의 `app` summary는 App 기본 정보와 운영 상태를 함께 표시하기 위한 안전 요약이다.

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
    },
    "operation_metrics": {
      "current_month_cost": 12.34,
      "projected_month_cost": 24.68,
      "previous_month_cost": 10.0,
      "trend_percent": 146.8
    }
  },
  "deployment": { "...": "..." },
  "latest_run": { "...": "..." }
}
```

- `operation_metrics`는 `/dashboard/mymodule` 비용/추세 UI 전용 요약이다.
- `current_month_cost`: 현재 KST 월의 `llm_usage_logs.total_cost` 합계.
- `projected_month_cost`: 현재 월 경과 비율을 기준으로 단순 projection한 월 예상 비용. 계산할 수 없으면 null이다.
- `previous_month_cost`: 직전 KST 월의 `llm_usage_logs.total_cost` 합계.
- `trend_percent`: `projected_month_cost`와 `previous_month_cost`의 증감률. 직전 월 비용이 0이면 null이다.
- `operation_metrics`는 `budget_status`와 별도 필드이며 `GET /apps` 응답에는 포함하지 않는다.

## Errors

- `401`: 미인증
- `403`: organization scope 또는 App 접근 권한 없음
- `404`: 직접 조회 대상이 없거나 scope 밖 리소스

## Permissions

- App 목록은 active organization context를 기준으로 사용자가 읽을 수 있는 App/Workflow만 반환한다.
- 운영 현황은 active organization context를 기준으로 organization manager이거나 workflow `write` 이상 권한을 가진 App/Workflow만 반환한다. Workflow `execute` 전용 사용자는 `/apps/operations` 대상이 아니며, 배포된 챗봇 링크 또는 내부 실행 링크(`/modules/{workflow_id}/run?deploymentId={deployment_id}`)를 사용한다.
- `budget_status`는 사용률과 상태만 노출한다. `/apps/operations`의 `operation_metrics`는 운영 표면에 반환된 workflow row의 비용 요약으로만 사용한다.
