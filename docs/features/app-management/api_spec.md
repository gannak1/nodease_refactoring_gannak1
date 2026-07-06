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
- 현재 branch의 클라이언트 타입은 이 필드를 소비하도록 준비되어 있지만, Gateway `AppResponse`/`AppOperationAppSummary`의 backend wiring은 별도 구현이 필요하므로 이 문서의 `Verified Against`는 아직 TBD로 둔다.

### GET /apps/operations

`/dashboard/mymodule`의 원천이다. 응답 항목의 `app` summary는 App 기본 정보와 운영 상태를 함께 표시하기 위한 안전 요약이다.

Budget Management 확장 시 `app.budget_status`는 `GET /apps`의 `budget_status`와 동일한 shape를 사용한다.

## Errors

- `401`: 미인증
- `403`: organization scope 또는 App 접근 권한 없음
- `404`: 직접 조회 대상이 없거나 scope 밖 리소스

## Permissions

- App 목록과 운영 현황은 active organization context를 기준으로 사용자가 접근 가능한 App/Workflow만 반환한다.
- `budget_status`는 사용률과 상태만 노출하며, 예산 금액/비용 원문은 관리자 API에만 노출한다.
