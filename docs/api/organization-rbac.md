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
| Planned | `GET` | `/api/v1/organizations/current` | authenticated + `X-Organization-Id` | header로 지정한 현재 active organization 조회 |

Active organization은 `X-Organization-Id` header로 요청마다 명시한다. 서버는 active organization을 session/cookie에 저장하지 않으므로 `PATCH /api/v1/organizations/current`는 만들지 않는다.

`GET /api/v1/organizations/current`는 `X-Organization-Id`가 현재 사용자의 active team membership scope 안에 있는지 검증하고, 접근 가능한 organization이면 `OrganizationResponse`를 반환한다. Header가 없거나 scope를 결정할 수 없으면 [errors.md](errors.md)의 `organization.required` 기준을 따른다.

## Organization 관리

| Status | Method | Path | Request | Response | Permission | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| Planned | `PATCH` | `/api/v1/organizations/{organization_id}` | `OrganizationPatchRequest` | `OrganizationResponse` | organization `manager` | organization 이름/설정 변경 |

`PATCH /api/v1/organizations/{organization_id}`는 organization 자체 정보를 수정한다. Active organization 변경 API가 아니다.

요청에는 `X-Organization-Id` header가 필요하며, header 값은 path의 `organization_id`와 같아야 한다. Gateway는 해당 organization이 active 상태이고 현재 사용자가 그 organization의 owner/manager인지 검증한다.

이 endpoint는 partial update다. 요청에는 변경 가능한 field가 하나 이상 있어야 한다.

오류 기준:

- `X-Organization-Id` header가 없으면 `400`을 반환한다.
- `X-Organization-Id` header와 path의 `organization_id`가 다르면 `404`를 반환한다.
- organization이 없거나 현재 사용자의 scope 밖이면 `403`을 반환한다.
- 현재 사용자가 organization member이지만 owner/manager가 아니면 `403`을 반환한다.
- 변경 가능한 field가 없거나 `name`이 빈 문자열이면 `400`을 반환한다.

### `OrganizationPatchRequest`

| Field | Type | Required | 설명 |
| --- | --- | --- | --- |
| `name` | string | No | organization 표시 이름. 빈 문자열은 허용하지 않는다. |
| `options` | object | No | organization 확장 설정. 제공되면 기존 `options` object를 전체 교체한다. |

다음 field는 이 endpoint에서 수정하지 않는다.

- `created_by`
- `managed_by`
- `flags`
- `is_active`
- `deactivated_at`

`managed_by`, `flags`, organization 비활성화/재활성화는 별도 정책과 endpoint가 필요하다.

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

조직 정보 수정, 권한 부여, 회수, 거부는 `audit_logs`에 남긴다.

| Event | `audit_logs.action` |
| --- | --- |
| 조직 정보 수정 | `organization.update` |
| 권한 부여 | `permission.grant` |
| 권한 회수 | `permission.revoke` |
| 권한 거부 | `permission.denied` |
