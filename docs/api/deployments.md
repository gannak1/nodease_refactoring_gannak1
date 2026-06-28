# 배포 API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d

## 범위

Deployment 생성, 조회, 활성화, public deployment info, run/webhook 계약을 정의한다.

## Deployment 엔드포인트

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/deployments` | `DeploymentCreate` | `DeploymentResponse` | workflow `deploy` |
| Implemented | `GET` | `/api/v1/deployments` | query | `DeploymentResponse[]` | workflow `read` |
| Implemented | `GET` | `/api/v1/deployments/nodes` | query | `dict[]` | workflow `read` |
| Implemented | `GET` | `/api/v1/deployments/{deployment_id}` | 없음 | `DeploymentResponse` | workflow `read` |
| Implemented | `GET` | `/api/v1/deployments/public/{url_slug}/info` | 없음 | `DeploymentInfoResponse` | public |
| Implemented | `PATCH` | `/api/v1/deployments/{deployment_id}/toggle` | 없음 | `DeploymentResponse` | workflow `deploy` |
| Implemented | `DELETE` | `/api/v1/deployments/{deployment_id}` | 없음 | message | workflow `manage` |
| Planned | `GET` | `/api/v1/deployments/{deployment_id}/diff` | `base_deployment_id` query | diff summary | workflow `read` |
| Planned | `POST` | `/api/v1/deployments/check` | draft/deployment reference | checklist result | workflow `deploy` |

`POST /api/v1/deployments/check` 결과는 별도 `deployment_check_runs` table 없이 `audit_logs.action='deployment.check'`와 `audit_logs.audit_metadata`에 저장한다.

## MVP 3 운영 엔드포인트

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Planned | `GET` | `/api/v1/operations/dashboard` | dashboard filter query | metrics summary | audit `read` 또는 workflow `read` scope |
| Planned | `GET` | `/api/v1/operations/recommendations` | recommendation filter query | recommendation summary | workflow `read` |
| Planned | `POST` | `/api/v1/operations/recommendations/{audit_log_id}/apply` | 없음 | apply result | workflow `write` |
| Planned | `POST` | `/api/v1/operations/recommendations/{audit_log_id}/ignore` | 없음 | ignore result | workflow `write` |

Recommendation lifecycle은 별도 `recommendation_events` table 없이 `audit_logs.action='recommendation.created'`, `recommendation.applied`, `recommendation.ignored`와 `audit_logs.audit_metadata`에 저장한다. Operations dashboard는 별도 aggregate table 없이 organization membership, run, trace, usage, audit table raw query로 시작한다.

`GET /api/v1/operations/dashboard`는 MVP 2-0 이후 active organization membership을 먼저 확인한다. 조직 전체 audit/policy block 집계는 audit `read` 권한이 필요하고, workflow 단위 비용/실패/latency 집계는 해당 workflow `read` scope 안에서만 반환한다.

Dashboard membership 필터 기준:

| Filter | 기준 |
| --- | --- |
| `organization_id` | active organization 또는 audit visibility가 허용된 target organization |
| `membership_state` | 현재 `organization_memberships.membership_state` |
| `include_inactive_members` | audit `read` 권한이 있을 때만 suspended/removed member의 과거 실행량 포함 |
| `team_id` | 현재 `team_memberships` 기준. 제거된 member의 과거 team membership 재구성은 MVP 3 기본 범위가 아님 |

Removed member의 team/direct permission row는 MVP 2-0 cleanup에서 hard delete되므로 dashboard는 과거 permission row에 의존하지 않는다. 과거 실행량은 `workflow_runs`, `workflow_node_runs`, `llm_usage_logs`, `audit_logs`와 soft-removed `organization_memberships` row를 기준으로 구분한다.

## Public Run 및 Webhook

| Status | Method | Path | Request | Response | 인증 |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/run/{url_slug}` | JSON body | run result | app `auth_secret` |
| Implemented | `POST` | `/api/v1/run-public/{url_slug}` | JSON body | run result | public deployment policy |
| Implemented | `POST` | `/api/v1/hooks/{url_slug}` | request body | webhook result | webhook secret/header policy |
| Implemented | `GET` | `/api/v1/hooks/{url_slug}/capture/start` | 없음 | capture state | dev/helper endpoint |
| Implemented | `GET` | `/api/v1/hooks/{url_slug}/capture/status` | 없음 | capture state | dev/helper endpoint |

## 스키마

### `DeploymentCreate`

| Field | Type | Required | 설명 |
| --- | --- | --- | --- |
| `app_id` | UUID | Yes | 배포할 app |
| `type` | enum | No | 기본값 `API` |
| `url_slug` | string | No | 소문자, 숫자, 하이픈 |
| `description` | string | No | 설명 |
| `config` | object | No | 배포 설정 |
| `is_active` | boolean | No | 생성 후 활성 여부 |
| `graph_snapshot` | object | No | workflow graph snapshot |
| `auth_secret` | string | No | 생성 시 입력 가능한 public/webhook secret |

`auth_secret`은 응답에 원문으로 노출하지 않는 방향이 원칙이다. 현재 schema에는 field가 있으므로 구현 시 masking 또는 제거를 검토한다.

## Rollback 표현

별도 rollback API는 만들지 않는다. 이전 deployment를 다시 활성화하는 동작은 `PATCH /deployments/{deployment_id}/toggle`과 `audit_logs.action='deployment.activate_previous'`로 표현한다.
