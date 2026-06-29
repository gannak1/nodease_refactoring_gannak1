# Organization 및 RBAC API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: feature/mba-59 @ b92bc9e0f38588495d228fc0d17b10dfaaed03c1
Related ADRs: [ADR-202606290145-active-organization-header-context](../decisions/ADR-202606290145-active-organization-header-context.md), [ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission](../decisions/ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission.md)
Background ADRs: [ADR-202606271559-active-organization](../decisions/ADR-202606271559-active-organization.md)

## 범위

Organization context, team/member 관리, resource permission grant/revoke API 계약을 정의한다.

Organization context, team/member 관리, permission grant/revoke API는 `X-Organization-Id` header를 active organization scope로 사용한다.

## Active Organization

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/organizations` | authenticated | 사용자가 속한 active organization 목록 |
| Implemented | `GET` | `/api/v1/organizations/current` | authenticated + `X-Organization-Id` | header로 전달한 active organization 조회 |
| Implemented | `GET` | `/api/v1/organizations/{organization_id}` | authenticated | 접근 가능한 organization 상세 조회 |
| Implemented | `PATCH` | `/api/v1/organizations/{organization_id}` | organization `manager` + matching `X-Organization-Id` | organization 이름/options 수정 |

서버는 active organization을 session/cookie에 저장하지 않는다. `PATCH /organizations/current`는 만들지 않고, header와 path가 일치하는 `PATCH /organizations/{organization_id}`를 사용한다.

## Team 관리

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/teams` | organization `manager` + `X-Organization-Id` | active organization의 team 목록 |
| Implemented | `POST` | `/api/v1/teams` | organization `manager` + `X-Organization-Id` | active organization에 team 생성 |
| Implemented | `PATCH` | `/api/v1/teams/{team_id}` | organization `manager` + `X-Organization-Id` | active organization 안의 team 수정 |
| Implemented | `POST` | `/api/v1/teams/{team_id}/members` | organization `manager` + `X-Organization-Id` | active organization 안의 active user를 team member로 추가 |
| Implemented | `DELETE` | `/api/v1/teams/{team_id}/members/{user_id}` | organization `manager` + `X-Organization-Id` | active organization 안의 team member 제거 |

## Resource Permission

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Implemented | `PUT` | `/api/v1/permissions/workflows/{workflow_id}/teams/{team_id}` | workflow `manage` 또는 organization `manager` + `X-Organization-Id` | team workflow 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/workflows/{workflow_id}/teams/{team_id}` | workflow `manage` 또는 organization `manager` + `X-Organization-Id` | team workflow 권한 회수 |
| Implemented | `PUT` | `/api/v1/permissions/workflows/{workflow_id}/users/{user_id}` | workflow `manage` 또는 organization `manager` + `X-Organization-Id` | user direct workflow 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/workflows/{workflow_id}/users/{user_id}` | workflow `manage` 또는 organization `manager` + `X-Organization-Id` | user direct workflow 권한 회수 |
| Implemented | `PUT` | `/api/v1/permissions/llm-credentials/{credential_id}/teams/{team_id}` | credential `manage` 또는 organization `manager` + `X-Organization-Id` | team LLM credential 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/llm-credentials/{credential_id}/teams/{team_id}` | credential `manage` 또는 organization `manager` + `X-Organization-Id` | team LLM credential 권한 회수 |
| Implemented | `PUT` | `/api/v1/permissions/llm-credentials/{credential_id}/users/{user_id}` | credential `manage` 또는 organization `manager` + `X-Organization-Id` | user direct LLM credential 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/llm-credentials/{credential_id}/users/{user_id}` | credential `manage` 또는 organization `manager` + `X-Organization-Id` | user direct LLM credential 권한 회수 |

## Permission Grant 요청

```json
{
  "auth_state": "viewer"
}
```

허용값은 [rbac-permission-policy.md](../data-model/rbac-permission-policy.md)의 resource matrix를 따른다.

## Audit

권한 변경과 거부는 `audit_logs`에 남긴다. 현재 등록된 `/api/v1/permissions/*` router는 grant/revoke를 `permission.grant`/`permission.revoke`가 아니라 permission row별 data-change action으로 기록한다.

| Event | `audit_logs.action` |
| --- | --- |
| team workflow 권한 생성/수정 | `team_workflow_permission.created` 또는 `team_workflow_permission.updated` |
| team workflow 권한 회수 | `team_workflow_permission.deleted` |
| user workflow 권한 생성/수정 | `user_workflow_permission.created` 또는 `user_workflow_permission.updated` |
| user workflow 권한 회수 | `user_workflow_permission.deleted` |
| team LLM credential 권한 생성/수정 | `team_llm_permission.created` 또는 `team_llm_permission.updated` |
| team LLM credential 권한 회수 | `team_llm_permission.deleted` |
| user LLM credential 권한 생성/수정 | `user_llm_permission.created` 또는 `user_llm_permission.updated` |
| user LLM credential 권한 회수 | `user_llm_permission.deleted` |
| 권한 거부 | `permission.denied` |
