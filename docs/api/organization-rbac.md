# Organization 및 RBAC API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: working tree (uncommitted)
Related ADRs: [ADR-202606271559-active-organization](../decisions/ADR-202606271559-active-organization.md), [ADR-202606271559-auth-state-standard](../decisions/ADR-202606271559-auth-state-standard.md), [ADR-202606271559-user-direct-permission](../decisions/ADR-202606271559-user-direct-permission.md)

## 범위

Organization context, team/member 관리, resource permission grant/revoke API 계약을 정의한다.

현재 Gateway에는 organization 목록/상세/수정 endpoint와 team 목록 endpoint가 구현되어 있다. 아래 API는 구현 완료된 계약과 MVP 1 RBAC foundation 목표 계약을 함께 정의한다.

## Active Organization

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/organizations/current` | authenticated + `X-Organization-Id` | header로 지정한 현재 active organization 조회 |

Active organization은 `X-Organization-Id` header로 요청마다 명시한다. 서버는 active organization을 session/cookie에 저장하지 않으므로 `PATCH /api/v1/organizations/current`는 만들지 않는다.

`GET /api/v1/organizations/current`는 `X-Organization-Id`가 현재 사용자의 active team membership scope 안에 있는지 검증하고, 접근 가능한 organization이면 `OrganizationResponse`를 반환한다. Header가 없거나 scope를 결정할 수 없으면 [errors.md](errors.md)의 `organization.required` 기준을 따른다.

이 endpoint는 현재 사용자의 active organization context를 확인하는 조회 API다. `organization.created_by` 또는 `organization.managed_by` 기반 manager fallback은 team 관리 API처럼 manager 권한을 요구하는 endpoint에서만 적용하고, `GET /api/v1/organizations/current`에서는 active team membership scope를 기준으로 판정한다.

오류 응답은 [errors.md](errors.md)의 목표 Error Envelope을 따른다.

| 조건 | HTTP | Code |
| --- | --- | --- |
| `X-Organization-Id` header 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 현재 사용자 active team membership scope 밖 | `404` | `resource.not_found` |

## Organization 조회

| Status | Method | Path | Response | Permission | 설명 |
| --- | --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/organizations` | `list[OrganizationResponse]` | authenticated | 사용자가 속한 active organization 목록 |
| Implemented | `GET` | `/api/v1/organizations/{organization_id}` | `OrganizationResponse` | authenticated | 사용자의 active team membership scope 안에 있는 특정 active organization 조회 |

`GET /api/v1/organizations`는 현재 사용자의 active team membership을 기준으로 active organization 목록을 반환한다. 같은 organization에 여러 team membership이 있어도 organization은 중복 반환하지 않는다. 정렬은 `created_at ASC`, `id ASC`다.

`GET /api/v1/organizations/{organization_id}`는 현재 사용자의 active team membership scope 안에 있는 active organization만 반환한다. Organization이 없거나 inactive이거나 현재 사용자 scope 밖이면 존재 여부를 숨기기 위해 `404` + `resource.not_found`를 반환한다.

## Organization 관리

| Status | Method | Path | Request | Response | Permission | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| Implemented | `PATCH` | `/api/v1/organizations/{organization_id}` | `OrganizationPatchRequest` | `OrganizationResponse` | organization `manager` | organization 이름/설정 변경 |

`PATCH /api/v1/organizations/{organization_id}`는 organization 자체 정보를 수정한다. Active organization 변경 API가 아니다.

요청에는 `X-Organization-Id` header가 필요하며, header 값은 path의 `organization_id`와 같아야 한다. Gateway는 해당 organization이 active 상태이고 현재 사용자가 그 organization의 owner/manager인지 검증한다.

이 endpoint는 partial update다. 요청에는 변경 가능한 field가 하나 이상 있어야 한다.

오류 응답은 [errors.md](errors.md)의 목표 Error Envelope을 따른다.

| 조건 | HTTP | Code |
| --- | --- | --- |
| `X-Organization-Id` header 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| `X-Organization-Id` header와 path의 `organization_id`가 다름 | `404` | `resource.not_found` |
| organization이 없거나 inactive 또는 현재 사용자 scope 밖 | `403` | `permission.denied` |
| 현재 사용자가 organization member이지만 owner/manager가 아님 | `403` | `permission.denied` |
| 변경 가능한 field가 없음 | `400` | `validation.failed` |
| `name`이 빈 문자열 | `400` | `validation.failed` |
| `name`이 database column 길이보다 김 | `422` | `validation.failed` |

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

### `OrganizationResponse`

| Field | Type | 설명 |
| --- | --- | --- |
| `id` | UUID | organization id |
| `name` | string | organization 표시 이름 |
| `options` | object | organization 확장 설정 |
| `is_active` | boolean | 활성 여부 |
| `created_at` | datetime | 생성 시각 |
| `updated_at` | datetime | 수정 시각 |

## Team 관리

| Status | Method | Path | Request | Response | Permission | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/teams` | `X-Organization-Id`, `limit` query | `list[TeamResponse]` | organization `manager` | active organization의 team 목록 |
| Implemented (permission gate) | `POST` | `/api/v1/teams` | TBD | TBD | organization `manager` | team 생성 권한 관문. 생성 계약은 TBD |
| Implemented (permission gate) | `PATCH` | `/api/v1/teams/{team_id}` | TBD | TBD | organization `manager` | team 수정 권한 관문. 수정 계약은 TBD |
| Implemented (permission gate) | `POST` | `/api/v1/teams/{team_id}/members` | TBD | TBD | organization `manager` | team member 추가 권한 관문. 추가 계약은 TBD |
| Implemented (permission gate) | `DELETE` | `/api/v1/teams/{team_id}/members/{user_id}` | 없음 | TBD | organization `manager` | team member 제거 권한 관문. 제거 응답 계약은 TBD |

### `GET /api/v1/teams`

관리 화면용 team 목록 API다. 일반 member의 "내 team 목록" 조회와 섞지 않는다.

요청에는 `X-Organization-Id` header가 필요하다. `organization.created_by` 또는 `organization.managed_by`가 현재 user면 active team membership이 없어도 organization `manager`로 접근할 수 있다. 현재 user가 organization manager가 아니고 active team membership scope 안에 있으면 `403`을 반환한다. 현재 user의 scope 밖 organization이면 존재 여부를 숨기기 위해 `404`를 반환한다.

응답은 active team과 inactive team을 모두 포함한다. 정렬은 `name ASC`, `id ASC`다. `limit` query의 기본값은 `10`이고 허용 범위는 `1..100`이다. `teams` table에 `member_count` column이 없으므로 `member_count`는 반환하지 않는다.

오류 응답은 [errors.md](errors.md)의 목표 Error Envelope을 따른다.

| 조건 | HTTP | Code |
| --- | --- | --- |
| 인증 없음 | `401` | `auth.required` |
| `X-Organization-Id` 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| `limit`이 정수가 아니거나 범위 밖 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 사용자 scope 밖 | `404` | `resource.not_found` |
| organization member지만 manager가 아님 | `403` | `permission.denied` |

### `POST /api/v1/teams`

Team 생성 API의 권한 관문이다. Request/Response 상세 계약은 아직 TBD이므로 구현은 임의 request schema, response schema, DB insert를 만들지 않는다.

요청에는 `X-Organization-Id` header가 필요하다. `organization.created_by` 또는 `organization.managed_by`가 현재 user면 active team membership이 없어도 organization `manager`로 접근할 수 있다. 현재 user가 organization manager가 아니고 active team membership scope 안에 있으면 `403`을 반환한다. 현재 user의 scope 밖 organization이면 존재 여부를 숨기기 위해 `404`를 반환한다.

organization manager 권한 검사를 통과하면, 생성 계약이 확정되지 않았으므로 `501` + `operation.not_implemented`를 반환한다. 이 응답은 team 생성 성공 응답이 아니며 team row를 생성하지 않는다.

오류 응답은 [errors.md](errors.md)의 목표 Error Envelope을 따른다.

| 조건 | HTTP | Code |
| --- | --- | --- |
| 인증 없음 | `401` | `auth.required` |
| `X-Organization-Id` 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 사용자 scope 밖 | `404` | `resource.not_found` |
| organization member지만 manager가 아님 | `403` | `permission.denied` |
| organization manager 권한 검사를 통과했지만 생성 계약이 TBD | `501` | `operation.not_implemented` |

### `PATCH /api/v1/teams/{team_id}`

Team 수정 API의 권한 관문이다. Request/Response 상세 계약은 아직 TBD이므로 구현은 임의 request schema, response schema, DB update를 만들지 않는다.

요청에는 `X-Organization-Id` header가 필요하다. `organization.created_by` 또는 `organization.managed_by`가 현재 user면 active team membership이 없어도 organization `manager`로 접근할 수 있다. 현재 user가 organization manager가 아니고 active team membership scope 안에 있으면 `403`을 반환한다. 현재 user의 scope 밖 organization이면 존재 여부를 숨기기 위해 `404`를 반환한다.

organization manager 권한 검사를 통과하면, 수정 계약이 확정되지 않았으므로 `501` + `operation.not_implemented`를 반환한다. 이 응답은 team 수정 성공 응답이 아니며 team row를 수정하지 않는다.

오류 응답은 [errors.md](errors.md)의 목표 Error Envelope을 따른다.

| 조건 | HTTP | Code |
| --- | --- | --- |
| 인증 없음 | `401` | `auth.required` |
| `X-Organization-Id` 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| `team_id`가 UUID가 아님 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 사용자 scope 밖 | `404` | `resource.not_found` |
| organization member지만 manager가 아님 | `403` | `permission.denied` |
| organization manager 권한 검사를 통과했지만 수정 계약이 TBD | `501` | `operation.not_implemented` |

### `POST /api/v1/teams/{team_id}/members`

Team member 추가 API의 권한 관문이다. Request/Response 상세 계약은 아직 TBD이므로 구현은 임의 request schema, response schema, DB insert를 만들지 않는다.

요청에는 `X-Organization-Id` header가 필요하다. `organization.created_by` 또는 `organization.managed_by`가 현재 user면 active team membership이 없어도 organization `manager`로 접근할 수 있다. 현재 user가 organization manager가 아니고 active team membership scope 안에 있으면 `403`을 반환한다. 현재 user의 scope 밖 organization이면 존재 여부를 숨기기 위해 `404`를 반환한다.

organization manager 권한 검사를 통과하면, 추가 계약이 확정되지 않았으므로 `501` + `operation.not_implemented`를 반환한다. 이 응답은 team membership 추가 성공 응답이 아니며 team membership row를 생성하지 않는다.

오류 응답은 [errors.md](errors.md)의 목표 Error Envelope을 따른다.

| 조건 | HTTP | Code |
| --- | --- | --- |
| 인증 없음 | `401` | `auth.required` |
| `X-Organization-Id` 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| `team_id`가 UUID가 아님 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 사용자 scope 밖 | `404` | `resource.not_found` |
| organization member지만 manager가 아님 | `403` | `permission.denied` |
| organization manager 권한 검사를 통과했지만 추가 계약이 TBD | `501` | `operation.not_implemented` |

### `DELETE /api/v1/teams/{team_id}/members/{user_id}`

Team member 제거 API의 권한 관문이다. Request는 없다. Response 상세 계약은 아직 TBD이므로 구현은 임의 response schema, DB delete를 만들지 않는다.

요청에는 `X-Organization-Id` header가 필요하다. `organization.created_by` 또는 `organization.managed_by`가 현재 user면 active team membership이 없어도 organization `manager`로 접근할 수 있다. 현재 user가 organization manager가 아니고 active team membership scope 안에 있으면 `403`을 반환한다. 현재 user의 scope 밖 organization이면 존재 여부를 숨기기 위해 `404`를 반환한다.

organization manager 권한 검사를 통과하면, 제거 응답 계약이 확정되지 않았으므로 `501` + `operation.not_implemented`를 반환한다. 이 응답은 team membership 제거 성공 응답이 아니며 team membership row를 삭제하지 않는다.

오류 응답은 [errors.md](errors.md)의 목표 Error Envelope을 따른다.

| 조건 | HTTP | Code |
| --- | --- | --- |
| 인증 없음 | `401` | `auth.required` |
| `X-Organization-Id` 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| `team_id`가 UUID가 아님 | `422` | `validation.failed` |
| `user_id`가 UUID가 아님 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 사용자 scope 밖 | `404` | `resource.not_found` |
| organization member지만 manager가 아님 | `403` | `permission.denied` |
| organization manager 권한 검사를 통과했지만 제거 응답 계약이 TBD | `501` | `operation.not_implemented` |

### `TeamResponse`

| Field | Type | 설명 |
| --- | --- | --- |
| `id` | UUID | team id |
| `organization_id` | UUID | team이 속한 organization |
| `name` | string | team 이름 |
| `description` | string 또는 null | team 설명 |
| `options` | object | team 확장 설정 |
| `flags` | integer | team flag bitset |
| `created_by` | UUID | team 생성자 |
| `managed_by` | UUID 또는 null | team 관리자 |
| `is_active` | boolean | 활성 여부 |
| `is_auto_add` | boolean | 자동 추가 team 여부 |
| `created_at` | datetime | 생성 시각 |
| `updated_at` | datetime | 수정 시각 |
| `deactivated_at` | datetime 또는 null | 비활성화 시각 |

## Resource Permission

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Implemented | `PUT` | `/api/v1/permissions/workflows/{workflow_id}/teams/{team_id}` | workflow `manage` 또는 organization `manager` | team workflow 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/workflows/{workflow_id}/teams/{team_id}` | workflow `manage` 또는 organization `manager` | team workflow 권한 회수 |
| Implemented | `PUT` | `/api/v1/permissions/workflows/{workflow_id}/users/{user_id}` | workflow `manage` 또는 organization `manager` | user direct workflow 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/workflows/{workflow_id}/users/{user_id}` | workflow `manage` 또는 organization `manager` | user direct workflow 권한 회수 |
| Implemented | `PUT` | `/api/v1/permissions/llm-credentials/{credential_id}/teams/{team_id}` | credential `manage` 또는 organization `manager` | team LLM credential 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/llm-credentials/{credential_id}/teams/{team_id}` | credential `manage` 또는 organization `manager` | team LLM credential 권한 회수 |
| Implemented | `PUT` | `/api/v1/permissions/llm-credentials/{credential_id}/users/{user_id}` | credential `manage` 또는 organization `manager` | user direct LLM credential 권한 부여/수정 |
| Planned | `DELETE` | `/api/v1/permissions/llm-credentials/{credential_id}/users/{user_id}` | credential `manage` 또는 organization `manager` | user direct LLM credential 권한 회수 |

## Permission Grant 요청

```json
{
  "auth_state": "viewer"
}
```

허용값은 [rbac-permission-policy.md](../data-model/rbac-permission-policy.md)의 resource matrix를 따른다.

이 API는 문서상 canonical `auth_state`인 `viewer`, `operator`, `builder`, `manager` 값을 그대로 저장한다. `admin`은 신규 permission 값으로 저장하지 않는다. 기존 tracing/RBAC reader 중 `read`, `write`, `execute`, `admin` legacy vocabulary만 해석하는 코드가 남아 있으면 이 API가 저장한 권한을 `none`처럼 처리할 수 있으므로, 해당 reader는 담당 영역에서 canonical `auth_state`와 legacy alias 호환을 함께 지원하도록 별도 follow-up으로 수정한다.

### `PUT /api/v1/permissions/workflows/{workflow_id}/teams/{team_id}`

Team workflow 권한을 생성하거나 수정하는 upsert API다.

요청에는 `X-Organization-Id` header가 필요하다. 대상 workflow와 team은 모두 header organization scope 안에 있어야 하며, team은 active 상태여야 한다. 현재 user가 `organization.created_by` 또는 `organization.managed_by`이면 organization `manager`로 허용된다. 그렇지 않으면 현재 user가 active team membership scope 안에 있어야 하고, 대상 workflow에 대한 effective `manager` 권한을 가져야 한다.

응답은 생성/수정된 `team_workflow_permissions` row를 반환한다.

| 조건 | HTTP | Code |
| --- | --- | --- |
| 인증 없음 | `401` | `auth.required` |
| `X-Organization-Id` 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| `workflow_id` 또는 `team_id`가 UUID가 아님 | `422` | `validation.failed` |
| `auth_state`가 workflow matrix 허용값이 아님 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 사용자 scope 밖 | `404` | `resource.not_found` |
| workflow가 organization scope 안에 없음 | `404` | `resource.not_found` |
| team이 organization scope 안에 없거나 inactive | `404` | `resource.not_found` |
| workflow `manage` 또는 organization `manager` 권한 없음 | `403` | `permission.denied` |

### `DELETE /api/v1/permissions/workflows/{workflow_id}/teams/{team_id}`

Team workflow 권한을 회수하는 API다.

요청에는 `X-Organization-Id` header가 필요하다. 대상 workflow와 team은 모두 header organization scope 안에 있어야 하며, team은 active 상태여야 한다. 현재 user가 `organization.created_by` 또는 `organization.managed_by`이면 organization `manager`로 허용된다. 그렇지 않으면 현재 user가 active team membership scope 안에 있어야 하고, 대상 workflow에 대한 effective `manager` 권한을 가져야 한다.

응답은 삭제된 permission row id와 message를 반환한다.

```json
{
  "message": "Team workflow permission deleted",
  "id": "00000000-0000-0000-0000-000000000000"
}
```

| 조건 | HTTP | Code |
| --- | --- | --- |
| 인증 없음 | `401` | `auth.required` |
| `X-Organization-Id` 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| `workflow_id` 또는 `team_id`가 UUID가 아님 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 사용자 scope 밖 | `404` | `resource.not_found` |
| workflow가 organization scope 안에 없음 | `404` | `resource.not_found` |
| team이 organization scope 안에 없거나 inactive | `404` | `resource.not_found` |
| workflow `manage` 또는 organization `manager` 권한 없음 | `403` | `permission.denied` |
| 회수할 team workflow permission row가 없음 | `404` | `resource.not_found` |

### `PUT /api/v1/permissions/llm-credentials/{credential_id}/teams/{team_id}`

Team LLM credential 권한을 생성하거나 수정하는 upsert API다.

요청에는 `X-Organization-Id` header가 필요하다. 대상 credential과 team은 모두 header organization scope 안에 있어야 하며, team은 active 상태여야 한다. 현재 user가 `organization.created_by` 또는 `organization.managed_by`이면 organization `manager`로 허용된다. 그렇지 않으면 현재 user가 active team membership scope 안에 있어야 하고, 대상 credential에 대한 effective `manager` 권한을 가져야 한다.

응답은 생성/수정된 `team_llm_permissions` row를 반환한다.

| 조건 | HTTP | Code |
| --- | --- | --- |
| 인증 없음 | `401` | `auth.required` |
| `X-Organization-Id` 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| `credential_id` 또는 `team_id`가 UUID가 아님 | `422` | `validation.failed` |
| `auth_state`가 LLM credential matrix 허용값이 아님 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 사용자 scope 밖 | `404` | `resource.not_found` |
| credential이 organization scope 안에 없음 | `404` | `resource.not_found` |
| team이 organization scope 안에 없거나 inactive | `404` | `resource.not_found` |
| credential `manage` 또는 organization `manager` 권한 없음 | `403` | `permission.denied` |

### `DELETE /api/v1/permissions/llm-credentials/{credential_id}/teams/{team_id}`

Team LLM credential 권한을 회수하는 API다.

요청에는 `X-Organization-Id` header가 필요하다. 대상 credential과 team은 모두 header organization scope 안에 있어야 하며, credential은 유효하고 team은 active 상태여야 한다. 현재 user가 `organization.created_by` 또는 `organization.managed_by`이면 organization `manager`로 허용된다. 그렇지 않으면 현재 user가 active team membership scope 안에 있어야 하고, 대상 credential에 대한 effective `manager` 권한을 가져야 한다.

응답은 삭제된 permission row id와 message를 반환한다.

```json
{
  "message": "Team LLM credential permission deleted",
  "id": "00000000-0000-0000-0000-000000000000"
}
```

| 조건 | HTTP | Code |
| --- | --- | --- |
| 인증 없음 | `401` | `auth.required` |
| `X-Organization-Id` 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| `credential_id` 또는 `team_id`가 UUID가 아님 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 사용자 scope 밖 | `404` | `resource.not_found` |
| credential이 organization scope 안에 없거나 유효하지 않음 | `404` | `resource.not_found` |
| team이 organization scope 안에 없거나 inactive | `404` | `resource.not_found` |
| credential `manage` 또는 organization `manager` 권한 없음 | `403` | `permission.denied` |
| 회수할 team LLM credential permission row가 없음 | `404` | `resource.not_found` |

### `PUT /api/v1/permissions/llm-credentials/{credential_id}/users/{user_id}`

User direct LLM credential 권한을 생성하거나 수정하는 upsert API다.

요청에는 `X-Organization-Id` header가 필요하다. 대상 credential은 header organization scope 안에 있고 유효해야 한다. 대상 user는 존재해야 하며, header organization의 active team membership을 갖거나 `organization.created_by` 또는 `organization.managed_by`여야 한다. 현재 user가 `organization.created_by` 또는 `organization.managed_by`이면 organization `manager`로 허용된다. 그렇지 않으면 현재 user가 active team membership scope 안에 있어야 하고, 대상 credential에 대한 effective `manager` 권한을 가져야 한다.

응답은 생성/수정된 `user_llm_permissions` row를 반환한다.

| 조건 | HTTP | Code |
| --- | --- | --- |
| 인증 없음 | `401` | `auth.required` |
| `X-Organization-Id` 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| `credential_id` 또는 `user_id`가 UUID가 아님 | `422` | `validation.failed` |
| `auth_state`가 LLM credential matrix 허용값이 아님 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 사용자 scope 밖 | `404` | `resource.not_found` |
| credential이 organization scope 안에 없거나 유효하지 않음 | `404` | `resource.not_found` |
| 대상 user가 없거나 organization scope 안에 없음 | `404` | `resource.not_found` |
| credential `manage` 또는 organization `manager` 권한 없음 | `403` | `permission.denied` |

### `PUT /api/v1/permissions/workflows/{workflow_id}/users/{user_id}`

User direct workflow 권한을 생성하거나 수정하는 upsert API다.

요청에는 `X-Organization-Id` header가 필요하다. 대상 workflow는 header organization scope 안에 있어야 한다. 대상 user는 존재해야 하며, header organization의 active team membership을 갖거나 `organization.created_by` 또는 `organization.managed_by`여야 한다. 현재 user가 `organization.created_by` 또는 `organization.managed_by`이면 organization `manager`로 허용된다. 그렇지 않으면 현재 user가 active team membership scope 안에 있어야 하고, 대상 workflow에 대한 effective `manager` 권한을 가져야 한다.

응답은 생성/수정된 `user_workflow_permissions` row를 반환한다.

| 조건 | HTTP | Code |
| --- | --- | --- |
| 인증 없음 | `401` | `auth.required` |
| `X-Organization-Id` 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| `workflow_id` 또는 `user_id`가 UUID가 아님 | `422` | `validation.failed` |
| `auth_state`가 workflow matrix 허용값이 아님 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 사용자 scope 밖 | `404` | `resource.not_found` |
| workflow가 organization scope 안에 없음 | `404` | `resource.not_found` |
| 대상 user가 없거나 organization scope 안에 없음 | `404` | `resource.not_found` |
| workflow `manage` 또는 organization `manager` 권한 없음 | `403` | `permission.denied` |

### `DELETE /api/v1/permissions/workflows/{workflow_id}/users/{user_id}`

User direct workflow 권한을 회수하는 API다.

요청에는 `X-Organization-Id` header가 필요하다. 대상 workflow는 header organization scope 안에 있어야 한다. 대상 user는 존재해야 하며, header organization의 active team membership을 갖거나 `organization.created_by` 또는 `organization.managed_by`여야 한다. 현재 user가 `organization.created_by` 또는 `organization.managed_by`이면 organization `manager`로 허용된다. 그렇지 않으면 현재 user가 active team membership scope 안에 있어야 하고, 대상 workflow에 대한 effective `manager` 권한을 가져야 한다.

응답은 삭제된 permission row id와 message를 반환한다.

```json
{
  "message": "User workflow permission deleted",
  "id": "00000000-0000-0000-0000-000000000000"
}
```

| 조건 | HTTP | Code |
| --- | --- | --- |
| 인증 없음 | `401` | `auth.required` |
| `X-Organization-Id` 없음 | `400` | `organization.required` |
| `X-Organization-Id`가 UUID가 아님 | `422` | `validation.failed` |
| `workflow_id` 또는 `user_id`가 UUID가 아님 | `422` | `validation.failed` |
| organization이 없거나 inactive 또는 사용자 scope 밖 | `404` | `resource.not_found` |
| workflow가 organization scope 안에 없음 | `404` | `resource.not_found` |
| 대상 user가 없거나 organization scope 안에 없음 | `404` | `resource.not_found` |
| workflow `manage` 또는 organization `manager` 권한 없음 | `403` | `permission.denied` |
| 회수할 user workflow permission row가 없음 | `404` | `resource.not_found` |

### `TeamWorkflowPermissionResponse`

| Field | Type | 설명 |
| --- | --- | --- |
| `id` | UUID | permission row id |
| `grantee_organization_id` | UUID | 권한이 부여되는 organization scope |
| `workflow_id` | UUID | 대상 workflow |
| `team_id` | UUID | 권한을 받는 team |
| `auth_state` | string | workflow 권한 상태 |
| `assigned_by` | UUID | 마지막 부여/수정자 |
| `assigned_at` | datetime | 마지막 부여/수정 시각 |
| `options` | object | 확장 설정 |
| `flags` | integer | flag bitset |

### `UserWorkflowPermissionResponse`

| Field | Type | 설명 |
| --- | --- | --- |
| `id` | UUID | permission row id |
| `grantee_organization_id` | UUID | 권한이 부여되는 organization scope |
| `workflow_id` | UUID | 대상 workflow |
| `user_id` | UUID | 권한을 받는 user |
| `auth_state` | string | workflow 권한 상태 |
| `assigned_by` | UUID | 마지막 부여/수정자 |
| `assigned_at` | datetime | 마지막 부여/수정 시각 |
| `options` | object | 확장 설정 |
| `flags` | integer | flag bitset |

## Audit

조직 정보 수정, 권한 부여, 회수, 거부는 `audit_logs`에 남긴다.

| Event | `audit_logs.action` |
| --- | --- |
| 조직 정보 수정 | `organization.update` |
| 권한 부여 | `permission.grant` |
| 권한 회수 | `permission.revoke` |
| 권한 거부 | `permission.denied` |
