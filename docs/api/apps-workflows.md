# App 및 Workflow API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d
Related ADRs: [ADR-202606271559-active-organization](../decisions/ADR-202606271559-active-organization.md), [ADR-202606271559-user-direct-permission](../decisions/ADR-202606271559-user-direct-permission.md)

## 범위

App/project boundary, workflow CRUD, draft, execute, stream, run detail 계약을 정의한다.

## App 엔드포인트

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/apps` | `AppCreateRequest` | `AppResponse` | authenticated, target organization scope |
| Implemented | `GET` | `/api/v1/apps` | query | `AppResponse[]` | app read |
| Implemented | `GET` | `/api/v1/apps/explore` | query | `AppResponse[]` | public/explore read |
| Implemented | `GET` | `/api/v1/apps/{app_id}` | 없음 | `AppResponse` | app read |
| Implemented | `PATCH` | `/api/v1/apps/{app_id}` | `AppUpdateRequest` | `AppResponse` | app settings/manage |
| Implemented | `POST` | `/api/v1/apps/{app_id}/clone` | 없음 | `AppResponse` | app read, create target app |
| Implemented | `DELETE` | `/api/v1/apps/{app_id}` | 없음 | message | app manage |

App 전용 permission table은 만들지 않는다. App read/settings 권한은 organization owner/manager 또는 primary workflow 권한으로 판정한다.

## Workflow 엔드포인트

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/workflows` | `WorkflowCreateRequest` | `WorkflowResponse` | app/workflow create scope |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}` | 없음 | `WorkflowResponse` | workflow `read` |
| Implemented | `GET` | `/api/v1/workflows/app/{app_id}` | 없음 | `WorkflowResponse[]` | app read |
| Implemented | `POST` | `/api/v1/workflows/{workflow_id}/draft` | `WorkflowDraftRequest` | message | workflow `write` |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}/draft` | 없음 | draft graph | workflow `read` |
| Implemented | `POST` | `/api/v1/workflows/{workflow_id}/execute` | execution input | run result | workflow `execute` |
| Implemented | `POST` | `/api/v1/workflows/{workflow_id}/stream` | form/input | `text/event-stream` | workflow `execute` |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}/runs` | pagination query | `WorkflowRunListResponse` | workflow `read` |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}/runs/{run_id}` | 없음 | `WorkflowRunSchema` | workflow `read` |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}/stats` | query | `DashboardStatsResponse` | workflow `read` |

## 주요 스키마

### `AppCreateRequest`

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | Yes |
| `description` | string | No |
| `icon` | `AppIcon` | Yes |
| `is_market` | boolean | No |

### `WorkflowDraftRequest`

| Field | Type | Required | 설명 |
| --- | --- | --- | --- |
| `nodes` | `NodeSchema[]` | No | canvas node 목록 |
| `edges` | `EdgeSchema[]` | No | canvas edge 목록 |
| `viewport` | `ViewportSchema` | No | canvas viewport |
| `features` | object | No | workflow feature flags |
| `envVariables` | array | No | 환경 변수 |
| `runtimeVariables` | array | No | 실행 시 입력 변수 |

## MVP 1 변경 기준

- creator 기반 권한 체크를 workflow permission helper로 교체한다.
- workflow execute/stream은 `execute` 권한이 없으면 거부한다.
- draft 저장은 `write` 권한이 없으면 거부한다.
- run list/detail/stats는 `read` 권한이 없으면 거부한다.
- 권한 차단은 `audit_logs`에 `permission.denied`로 기록한다.
