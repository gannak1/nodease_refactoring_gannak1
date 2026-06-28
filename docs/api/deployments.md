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
| Implemented | `GET` | `/api/v1/deployments` | query | `DeploymentResponse[]` | deployment read |
| Implemented | `GET` | `/api/v1/deployments/nodes` | query | `dict[]` | workflow `read` |
| Implemented | `GET` | `/api/v1/deployments/{deployment_id}` | 없음 | `DeploymentResponse` | deployment read |
| Implemented | `GET` | `/api/v1/deployments/public/{url_slug}/info` | 없음 | `DeploymentInfoResponse` | public |
| Implemented | `PATCH` | `/api/v1/deployments/{deployment_id}/toggle` | 없음 | `DeploymentResponse` | workflow `deploy` |
| Implemented | `DELETE` | `/api/v1/deployments/{deployment_id}` | 없음 | message | workflow `manage` |

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
