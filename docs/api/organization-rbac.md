# Organization 및 RBAC API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d
Related ADRs: [ADR-202606271559-active-organization](../decisions/ADR-202606271559-active-organization.md), [ADR-202606271559-auth-state-standard](../decisions/ADR-202606271559-auth-state-standard.md), [ADR-202606271559-user-direct-permission](../decisions/ADR-202606271559-user-direct-permission.md)

## 범위

Organization context, team/member 관리, resource permission grant/revoke API 계약을 정의한다.

현재 dev Gateway에는 전용 organization/team 관리 endpoint가 없다. 아래 API는 MVP 1 RBAC foundation 목표 계약이다.

## Active Organization

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Planned | `GET` | `/api/v1/organizations` | authenticated | 사용자가 속한 organization 목록 |
| Planned | `GET` | `/api/v1/organizations/current` | authenticated | 현재 active organization 조회 |
| Proposed | `PATCH` | `/api/v1/organizations/current` | authenticated | active organization 변경 |

`PATCH /organizations/current`는 active organization 방식을 header로 확정하면 만들지 않을 수 있다.

## Team 관리

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Planned | `POST` | `/api/v1/teams` | organization `manager` | team 생성 |
| Planned | `GET` | `/api/v1/teams` | organization `manager` | active organization의 team 목록 |
| Planned | `PATCH` | `/api/v1/teams/{team_id}` | organization `manager` | team 이름/설명/활성 상태 변경 |
| Planned | `POST` | `/api/v1/teams/{team_id}/members` | organization `manager` | user를 team에 추가 |
| Planned | `DELETE` | `/api/v1/teams/{team_id}/members/{user_id}` | organization `manager` | user를 team에서 제거 |

## Resource Permission

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Planned | `PUT` | `/api/v1/permissions/workflows/{workflow_id}/teams/{team_id}` | workflow `manage` 또는 organization `manager` | team workflow 권한 부여/수정 |
| Planned | `DELETE` | `/api/v1/permissions/workflows/{workflow_id}/teams/{team_id}` | workflow `manage` 또는 organization `manager` | team workflow 권한 회수 |
| Planned | `PUT` | `/api/v1/permissions/workflows/{workflow_id}/users/{user_id}` | workflow `manage` 또는 organization `manager` | user direct workflow 권한 부여/수정 |
| Planned | `DELETE` | `/api/v1/permissions/workflows/{workflow_id}/users/{user_id}` | workflow `manage` 또는 organization `manager` | user direct workflow 권한 회수 |
| Planned | `PUT` | `/api/v1/permissions/llm-credentials/{credential_id}/teams/{team_id}` | credential `manage` 또는 organization `manager` | team LLM credential 권한 부여/수정 |
| Planned | `DELETE` | `/api/v1/permissions/llm-credentials/{credential_id}/teams/{team_id}` | credential `manage` 또는 organization `manager` | team LLM credential 권한 회수 |
| Planned | `PUT` | `/api/v1/permissions/llm-credentials/{credential_id}/users/{user_id}` | credential `manage` 또는 organization `manager` | user direct LLM credential 권한 부여/수정 |
| Planned | `DELETE` | `/api/v1/permissions/llm-credentials/{credential_id}/users/{user_id}` | credential `manage` 또는 organization `manager` | user direct LLM credential 권한 회수 |

## Permission Grant 요청

```json
{
  "auth_state": "viewer"
}
```

허용값은 [rbac-permission-policy.md](../data-model/rbac-permission-policy.md)의 resource matrix를 따른다.

## Audit

권한 부여, 회수, 거부는 `audit_logs`에 남긴다.

| Event | `audit_logs.action` |
| --- | --- |
| 권한 부여 | `permission.grant` |
| 권한 회수 | `permission.revoke` |
| 권한 거부 | `permission.denied` |
