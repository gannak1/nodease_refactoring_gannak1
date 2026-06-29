# App 및 Workflow API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: dev @ c990b54e931b4de8023822f6dff14f43fc1d415f
Related ADRs: [ADR-202606290145-active-organization-header-context](../decisions/ADR-202606290145-active-organization-header-context.md), [ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission](../decisions/ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission.md), [ADR-202606291315-resource-access-403-404-policy](../decisions/ADR-202606291315-resource-access-403-404-policy.md)

## 범위

App/project boundary, workflow CRUD, draft, execute, stream, run detail 계약을 정의한다.

## App 엔드포인트

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/apps` | `AppCreateRequest` | `AppResponse` | authenticated + `X-Organization-Id` active organization scope |
| Implemented | `GET` | `/api/v1/apps` | query | `AppResponse[]` | `X-Organization-Id` active organization scope + app read |
| Implemented | `GET` | `/api/v1/apps/explore` | query | `AppResponse[]` | authenticated explore read |
| Implemented | `GET` | `/api/v1/apps/{app_id}` | 없음 | `AppResponse` | app read |
| Implemented | `PATCH` | `/api/v1/apps/{app_id}` | `AppUpdateRequest` | `AppResponse` | app settings/manage |
| Implemented | `POST` | `/api/v1/apps/{app_id}/clone` | 없음 | `AppResponse` | app read + `X-Organization-Id` active organization scope for target app |
| Implemented | `DELETE` | `/api/v1/apps/{app_id}` | 없음 | message | app manage |

App 전용 permission table은 만들지 않는다. App read/settings 권한은 organization owner/manager 또는 primary workflow 권한으로 판정한다.
App 생성과 clone으로 생성되는 primary workflow에는 생성자 user direct `manager` 권한을 부여한다.

현재 `AppResponse`에는 `url_slug`와 `auth_secret`이 포함된다. `auth_secret` 원문 비노출은 목표 보안 원칙이며, 현재 schema와 서비스가 masking/removal을 적용하기 전까지 app 조회/생성/복제 응답에서 노출될 수 있다.

현재 backend contract에서 `POST /apps`, `GET /apps`, `POST /apps/{app_id}/clone`, `POST /workflows`는 `X-Organization-Id` header를 요구한다. Header가 없으면 `400 organization.required`가 발생한다. 다만 현재 frontend `appApi`/`workflowApi` wrapper는 이 header를 자동으로 붙이지 않으므로, UI 경로는 active organization wiring 보강 전까지 backend contract와 불일치할 수 있다.

## Workflow 엔드포인트

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/workflows` | `WorkflowCreateRequest` | `WorkflowResponse` | `X-Organization-Id` active organization scope + app manage; workflow inherits app organization |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}` | 없음 | `WorkflowResponse` | workflow `read` |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}/permissions/me` | 없음 | effective permission payload | workflow `read` |
| Implemented | `GET` | `/api/v1/workflows/app/{app_id}` | 없음 | `WorkflowResponse[]` | app read |
| Implemented | `POST` | `/api/v1/workflows/{workflow_id}/draft` | `WorkflowDraftRequest` | message | workflow `write` |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}/draft` | 없음 | draft graph | workflow `read` |
| Implemented | `POST` | `/api/v1/workflows/{workflow_id}/compare` | `WorkflowCompareRequest` | A/B variant result | workflow `execute` |
| Implemented | `POST` | `/api/v1/workflows/{workflow_id}/execute` | execution input | run result | workflow `execute` |
| Implemented | `POST` | `/api/v1/workflows/{workflow_id}/stream` | form/input | `text/event-stream` | workflow `execute` |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}/runs` | pagination query | `WorkflowRunListResponse` | workflow `read` |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}/runs/{run_id}` | 없음 | `WorkflowRunSchema` | workflow `read` |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}/runs/{run_id}/llm-traces` | `node_id`, `limit`, `offset` query | `LLMTraceListResponse` | workflow `read` |
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

### `WorkflowCompareRequest`

| Field | Type | Required | 설명 |
| --- | --- | --- | --- |
| `node_id` | string | Yes | 비교 대상 LLM node id |
| `compare_type` | `model` 또는 `prompt` | Yes | `model_id`를 바꿀지 `user_prompt`를 바꿀지 결정 |
| `inputs` | object | No | 실행 입력값 |
| `left` | string | Yes | A variant 값 |
| `right` | string | Yes | B variant 값 |

## 실행 입력 규칙

- `POST /workflows/{workflow_id}/execute`는 저장된 draft graph를 사용하고, JSON body의 `memory_mode` 값은 실행 입력에서 제거한 뒤 execution context에만 전달한다.
- Client는 SSE buffering을 피하기 위해 `/stream-api/workflows/{workflowId}` Next.js route로 요청하고, 이 route가 backend `/api/v1/workflows/{workflow_id}/stream`으로 프록시한다.
- Backend `POST /workflows/{workflow_id}/stream`은 JSON body 또는 `multipart/form-data`를 모두 지원한다.
- stream JSON body는 `{ "inputs": object, "graph_snapshot": object }` 형태를 지원하며, `graph_snapshot`이 있으면 저장된 draft 대신 그 snapshot을 실행한다.
- stream `multipart/form-data`는 `inputs` JSON 문자열, `graph_snapshot` JSON 문자열, `memory_mode`, `file_변수명` 업로드를 받을 수 있다.
- 실행 graph 검증은 없는 node를 참조하는 edge, trigger/source-only node로 들어오는 edge, answer/terminal node에서 나가는 edge, 순환 연결을 `400`으로 거부한다.

## Effective Permission 응답

`GET /api/v1/workflows/{workflow_id}/permissions/me`는 현재 user의 effective workflow `auth_state`와 action별 boolean을 반환한다.

| Field | 설명 |
| --- | --- |
| `workflow_id` | workflow id |
| `organization_id` | workflow organization id. legacy workflow면 `null` 가능 |
| `auth_state` | `none`, `viewer`, `operator`, `builder`, `manager` 중 effective 상태 |
| `can_read` / `can_write` / `can_execute` / `can_deploy` / `can_manage` | 현재 상태가 각 action을 허용하는지 |

## MVP 1 변경 기준

- Backend 기준 `POST /api/v1/apps`, `GET /api/v1/apps`, `POST /api/v1/apps/{app_id}/clone`, `POST /api/v1/workflows`는 `X-Organization-Id` header로 active organization을 명시한다. 현재 frontend wrapper는 아직 이 header를 자동 첨부하지 않는다.
- `X-Organization-Id` scope 안 여부는 organization owner/manager 또는 active team membership으로 판정한다.
- 생성자가 만든 workflow에는 user direct `manager` 권한을 부여해 생성 직후 App/Workflow 관리가 가능해야 한다.
- creator 기반 권한 체크를 workflow permission helper로 교체한다.
- workflow execute/stream은 `execute` 권한이 없으면 거부한다.
- draft 저장은 `write` 권한이 없으면 거부한다.
- run list/detail/stats는 `read` 권한이 없으면 거부한다.
- 권한 차단은 `audit_logs`에 `permission.denied`로 기록한다.
- App/Workflow id가 없거나 요청 user의 organization scope 밖이면 `404 resource.not_found`로 숨긴다.
- 같은 organization scope 안에서 resource action 권한만 부족하면 `403 permission.denied`를 반환한다.
