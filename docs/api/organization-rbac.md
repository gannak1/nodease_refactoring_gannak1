# Organization 및 RBAC API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: dev @ c990b54e931b4de8023822f6dff14f43fc1d415f
Related ADRs: [ADR-202606290145-active-organization-header-context](../decisions/ADR-202606290145-active-organization-header-context.md), [ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission](../decisions/ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission.md), [ADR-202606291451-team-router-rbac-service-boundary](../decisions/ADR-202606291451-team-router-rbac-service-boundary.md)
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

Organization 조회/수정 API는 공통으로 `OrganizationResponse`를 반환한다.

`PATCH /api/v1/organizations/{organization_id}`는 path organization과 `X-Organization-Id`가 일치해야 한다. Organization이 없거나 inactive이거나 요청 user의 scope 밖이면 `404 resource.not_found`로 숨기고, 같은 scope 안이지만 manager가 아니면 `403 permission.denied`를 반환한다.

```json
{
  "id": "uuid",
  "name": "Acme",
  "options": {},
  "is_active": true,
  "is_manager": true,
  "created_at": "2026-06-29T00:00:00Z",
  "updated_at": "2026-06-29T00:00:00Z"
}
```

`is_manager`는 현재 요청 user 기준 파생 필드다.

- active `organization_memberships` row가 있고 `organization_auth_state == "manager"`이면 `true`
- membership row 자체가 없고 legacy fallback으로 `organization.created_by == current_user.id` 또는 `organization.managed_by == current_user.id`이면 `true`
- 그 외에는 `false`

MBA-67 이후 manager 판정은 organization membership helper를 기준으로 한다. Legacy `created_by` / `managed_by` fallback은 MBA-66 이전 데이터 호환용이며, membership row 자체가 없는 경우에만 적용한다. Invited/suspended/removed row가 있으면 fallback을 적용하지 않고 `false`로 닫는다.

## User Directory

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/users` | organization `manager` | organization 안의 active organization member user 목록 |
| Implemented | `GET` | `/api/v1/users/me/audit-logs` | authenticated | 현재 user 자신의 audit log 목록 |

`GET /api/v1/users` 현재 구현 세부사항:

- `organization_id` query가 있으면 해당 organization을 사용하고, 없으면 현재 user의 첫 active organization membership organization을 fallback으로 사용한다.
- `organization_id` query가 없고 primary organization도 없으면 `404 Organization not found`를 반환한다. 조회 API는 default organization이나 membership을 생성하지 않는다.
- 지정하거나 fallback으로 결정한 organization이 없거나 inactive이거나 요청 user의 scope 밖이면 `404 Organization not found`를 반환한다.
- 같은 organization scope 안이지만 요청 user가 organization owner/manager가 아니면 `403 Forbidden`을 반환한다.
- `q` query는 user `name` 또는 `email`에 대한 부분 검색이다.
- `limit` 기본값은 `50`이고 허용 범위는 `1..200`이다.
- 응답은 active organization membership을 기준으로 distinct user를 반환하며, 비활성 user는 제외한다.

## Team 관리

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/teams` | organization `manager` + `X-Organization-Id` | active organization의 team 목록 |
| Implemented | `POST` | `/api/v1/teams` | organization `manager` + `X-Organization-Id` | active organization에 team 생성 |
| Implemented | `PATCH` | `/api/v1/teams/{team_id}` | organization `manager` + `X-Organization-Id` | active organization 안의 team 수정 |
| Implemented | `DELETE` | `/api/v1/teams/{team_id}` | organization `manager` + `X-Organization-Id` | active organization 안의 team 비활성화 |
| Implemented | `GET` | `/api/v1/teams/{team_id}/members` | organization `manager` + `X-Organization-Id` | active organization 안의 team member 목록 |
| Implemented | `POST` | `/api/v1/teams/{team_id}/members` | organization `manager` + `X-Organization-Id` | active organization 안의 active user를 team member로 추가 |
| Implemented | `DELETE` | `/api/v1/teams/{team_id}/members/{user_id}` | organization `manager` + `X-Organization-Id` | active organization 안의 team member 제거 |

Team 관리 API의 현재 구현 세부사항:

- `GET /api/v1/teams`는 `limit` query를 문자열로 받은 뒤 정수 변환을 수행하며 허용 범위는 `1..100`이다. 기본값은 `10`이다.
- `GET /api/v1/teams`는 organization scope 안의 team을 `name`, `id` 오름차순으로 반환하며, inactive team도 `is_active`, `deactivated_at` 상태 필드와 함께 포함한다.
- Team API는 `auth_token` cookie를 직접 읽어 인증한다. 인증 실패, validation 실패, scope 실패는 [errors.md](errors.md)의 `{ "error": ... }` 구조로 반환한다.
- organization owner/manager가 아니지만 해당 organization의 active membership은 있으면 `403 permission.denied`, scope 밖이면 `404 resource.not_found`로 숨긴다.
- Team 관리 권한 판정, team 목록 조회, team member 목록 조회는 `TeamService`가 소유한다. 등록 router `team.py`는 인증, header/body parsing, response envelope 변환을 담당한다.
- `PATCH /api/v1/teams/{team_id}`의 `managed_by`는 active user이면서 같은 organization scope 안에 있는 user만 허용한다.
- `POST /api/v1/teams/{team_id}/members`는 대상 user가 active organization membership을 가진 경우에만 team member로 추가한다. Team membership은 organization membership을 새로 만들지 않는다.
- `DELETE /api/v1/teams/{team_id}`는 `X-Organization-Id`와 team organization이 일치할 때 team을 inactive로 바꾸고 `{"status": "deactivated"}`를 반환한다. 같은 organization scope 안에서 이미 inactive인 team을 다시 비활성화하면 같은 응답을 idempotent success로 반환한다. 존재하지 않거나 요청 organization 밖의 team은 `404 resource.not_found`로 숨긴다.
- `GET /api/v1/teams/{team_id}/members` 응답은 `id`, `user_id`, `email`, `name`, `assigned_at`을 반환하며 비활성 user는 제외한다.

## Resource Permission

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/permissions/workflows/{workflow_id}` | workflow `manage` 또는 organization `manager` + `X-Organization-Id` | workflow에 부여된 team/user 권한 목록 |
| Implemented | `PUT` | `/api/v1/permissions/workflows/{workflow_id}/teams/{team_id}` | workflow `manage` 또는 organization `manager` + `X-Organization-Id` | team workflow 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/workflows/{workflow_id}/teams/{team_id}` | workflow `manage` 또는 organization `manager` + `X-Organization-Id` | team workflow 권한 회수 |
| Implemented | `PUT` | `/api/v1/permissions/workflows/{workflow_id}/users/{user_id}` | workflow `manage` 또는 organization `manager` + `X-Organization-Id` | user direct workflow 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/workflows/{workflow_id}/users/{user_id}` | workflow `manage` 또는 organization `manager` + `X-Organization-Id` | user direct workflow 권한 회수 |
| Implemented | `GET` | `/api/v1/permissions/llm-credentials/{credential_id}` | credential `manage` 또는 organization `manager` + `X-Organization-Id` | LLM credential에 부여된 team/user 권한 목록 |
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

Permission API의 organization scope 판정은 active organization membership 또는 organization manager helper를 기준으로 한다. User direct permission을 새로 부여하거나 수정할 때 대상 user는 active organization membership을 가져야 한다. Direct permission 회수는 과거 row 정리를 위해 대상 user의 현재 active membership을 요구하지 않는다.

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
