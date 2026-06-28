# 배포 API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: feature/mba-59 @ b92bc9e0f38588495d228fc0d17b10dfaaed03c1

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

위 permission은 route 구현 상태 기준이다. MVP 3의 배포 범위는 기본 `read/deploy/manage` enforcement가 아니라 deploy checklist, version diff, trigger mode 정합성, operations dashboard 같은 운영 기능 강화를 뜻한다.

## Public Run 및 Webhook

| Status | Method | Path | Request | Response | 인증 |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/run/{url_slug}` | JSON body | run result | app `auth_secret` |
| Implemented | `POST` | `/api/v1/run-public/{url_slug}` | JSON body | run result | public deployment policy |
| Implemented | `POST` | `/api/v1/hooks/{url_slug}` | request body | webhook result | webhook secret/header policy |
| Implemented | `GET` | `/api/v1/hooks/{url_slug}/capture/start` | 없음 | capture state | capture helper endpoint |
| Implemented | `GET` | `/api/v1/hooks/{url_slug}/capture/status` | 없음 | capture state | capture helper endpoint |

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

별도 rollback API는 만들지 않는다. 이전 deployment를 다시 활성화하는 동작은 `PATCH /deployments/{deployment_id}/toggle`로 수행한다.

Audit action은 토글 전 상태에 따라 구분한다.

| 상황 | `audit_logs.action` |
| --- | --- |
| active deployment를 비활성화하거나, active deployment가 없는 상태에서 활성화 | `deployment.toggle` |
| 다른 deployment가 이미 active인 상태에서 inactive였던 이전 deployment를 활성화 | `deployment.activate_previous` |
