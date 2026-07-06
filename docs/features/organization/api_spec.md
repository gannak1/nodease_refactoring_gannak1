# Organization API Spec

Status: Draft

기본 경로: `/api/v1`

## Common Contracts

대부분의 organization scope API는 `auth_token` HTTP-only cookie 인증을 사용하며, organization scope가 필요한 요청은 `X-Organization-Id` header로 active organization을 명시한다.

`X-Organization-Id`가 필요한 endpoint에서 header가 없으면 `400 organization.required`, UUID 형식이 아니면 `422 validation.failed`를 반환한다.

오류 envelope:

```json
{
  "error": {
    "code": "permission.denied",
    "message": "Permission denied.",
    "request_id": "...",
    "details": {}
  }
}
```

## Endpoints

### Organization Context

| 메서드 | 경로 | 설명 | 인증 |
| --- | --- | --- | --- |
| GET | `/organizations` | 현재 사용자가 active context로 사용할 수 있는 active organization 목록을 반환한다. | `auth_token` cookie |
| GET | `/organizations/memberships` | 현재 사용자의 active/invited organization membership 요약을 반환한다. | `auth_token` cookie |
| GET | `/organizations/current` | `X-Organization-Id`로 지정한 현재 organization 상세를 반환한다. | `auth_token` cookie, `X-Organization-Id` |
| GET | `/organizations/{organization_id}` | 현재 사용자가 접근 가능한 organization 상세를 반환한다. | `auth_token` cookie |
| PATCH | `/organizations/{organization_id}` | organization 이름/options를 수정한다. | `auth_token` cookie, manager, `X-Organization-Id` |

### Organization Membership

| 메서드 | 경로 | 설명 | 인증 |
| --- | --- | --- | --- |
| GET | `/organizations/{organization_id}/members` | organization member 목록을 반환한다. | `auth_token` cookie, manager, matching `X-Organization-Id` |
| POST | `/organizations/{organization_id}/members/invitations` | 가입된 user id를 organization member로 초대한다. | `auth_token` cookie, manager, matching `X-Organization-Id` |
| POST | `/organizations/{organization_id}/members/me/accept` | 현재 로그인한 사용자가 해당 organization에서 자신에게 온 초대를 수락한다. | `auth_token` cookie |
| POST | `/organizations/{organization_id}/members/me/decline` | 현재 로그인한 사용자가 해당 organization에서 자신에게 온 초대를 거절한다. | `auth_token` cookie |
| PATCH | `/organizations/{organization_id}/members/{user_id}` | member 상태 또는 organization auth state를 변경한다. | `auth_token` cookie, manager, matching `X-Organization-Id` |
| DELETE | `/organizations/{organization_id}/members/{user_id}` | member를 removed 상태로 바꾸고 team/user direct permission 및 App 생성 권한 row를 정리한다. | `auth_token` cookie, manager, matching `X-Organization-Id` |

### Notifications

| 메서드 | 경로 | 설명 | 인증 |
| --- | --- | --- | --- |
| GET | `/notifications` | 현재 사용자의 organization 초대 알림 목록을 반환한다. | `auth_token` cookie |
| GET | `/notifications/stream` | 현재 사용자의 notification SSE stream을 연다. | `auth_token` cookie |

### Permission Requests

| 메서드 | 경로 | 설명 | 인증 |
| --- | --- | --- | --- |
| POST | `/permission-requests` | 현재 사용자가 App 생성 권한(`app.create`)을 신청한다. | `auth_token` cookie, `X-Organization-Id` |

### Teams

| 메서드 | 경로 | 설명 | 인증 |
| --- | --- | --- | --- |
| GET | `/teams` | active organization의 team 목록을 반환한다. | `auth_token` cookie, manager, `X-Organization-Id` |
| POST | `/teams` | active organization에 team을 생성한다. | `auth_token` cookie, manager, `X-Organization-Id` |
| PATCH | `/teams/{team_id}` | active team을 수정한다. | `auth_token` cookie, manager, `X-Organization-Id` |
| DELETE | `/teams/{team_id}` | team을 비활성화한다. | `auth_token` cookie, manager, `X-Organization-Id` |

### Team Membership

| 메서드 | 경로 | 설명 | 인증 |
| --- | --- | --- | --- |
| GET | `/teams/{team_id}/members` | team member 목록을 반환한다. | `auth_token` cookie, manager, `X-Organization-Id` |
| POST | `/teams/{team_id}/members` | active organization member를 team에 추가한다. | `auth_token` cookie, manager, `X-Organization-Id` |
| DELETE | `/teams/{team_id}/members/{user_id}` | user를 team에서 제거한다. | `auth_token` cookie, manager, `X-Organization-Id` |

### Resource Permission Read

| 메서드 | 경로 | 설명 | 인증 |
| --- | --- | --- | --- |
| GET | `/permissions/workflows/{workflow_id}` | workflow에 부여된 team/user direct permission 목록을 반환한다. | `auth_token` cookie, manager 또는 workflow manage, `X-Organization-Id` |
| GET | `/permissions/llm-credentials/{credential_id}` | LLM credential에 부여된 team/user direct permission 목록을 반환한다. | `auth_token` cookie, manager 또는 credential manage, `X-Organization-Id` |

### Resource Permission Grant

| 메서드 | 경로 | 설명 | 인증 |
| --- | --- | --- | --- |
| PUT | `/permissions/workflows/{workflow_id}/teams/{team_id}` | team workflow permission을 생성하거나 갱신한다. | `auth_token` cookie, manager 또는 workflow manage, `X-Organization-Id` |
| PUT | `/permissions/workflows/{workflow_id}/users/{user_id}` | user direct workflow permission을 생성하거나 갱신한다. | `auth_token` cookie, manager 또는 workflow manage, `X-Organization-Id` |
| PUT | `/permissions/llm-credentials/{credential_id}/teams/{team_id}` | team LLM credential permission을 생성하거나 갱신한다. | `auth_token` cookie, manager 또는 credential manage, `X-Organization-Id` |
| PUT | `/permissions/llm-credentials/{credential_id}/users/{user_id}` | user direct LLM credential permission을 생성하거나 갱신한다. | `auth_token` cookie, manager 또는 credential manage, `X-Organization-Id` |

### Resource Permission Revoke

| 메서드 | 경로 | 설명 | 인증 |
| --- | --- | --- | --- |
| DELETE | `/permissions/workflows/{workflow_id}/teams/{team_id}` | team workflow permission을 삭제한다. | `auth_token` cookie, manager 또는 workflow manage, `X-Organization-Id` |
| DELETE | `/permissions/workflows/{workflow_id}/users/{user_id}` | user direct workflow permission을 삭제한다. | `auth_token` cookie, manager 또는 workflow manage, `X-Organization-Id` |
| DELETE | `/permissions/llm-credentials/{credential_id}/teams/{team_id}` | team LLM credential permission을 삭제한다. | `auth_token` cookie, manager 또는 credential manage, `X-Organization-Id` |
| DELETE | `/permissions/llm-credentials/{credential_id}/users/{user_id}` | user direct LLM credential permission을 삭제한다. | `auth_token` cookie, manager 또는 credential manage, `X-Organization-Id` |

## Request And Response Models

### `GET /organizations`

요청 본문: 없음.

성공 응답: `200 OK`, `OrganizationResponse[]`.

반환 대상은 현재 사용자가 active membership으로 접근할 수 있는 active organization만 포함한다. invited organization은 이 endpoint에 포함하지 않는다.

### `GET /organizations/memberships`

요청 본문: 없음.

성공 응답: `200 OK`, `OrganizationSummaryResponse[]`.

이 endpoint는 active와 invited membership을 함께 반환한다. removed/suspended membership은 포함하지 않는다.

### `GET /organizations/current`

요청 header:

| 이름 | 필수 | 비고 |
| --- | --- | --- |
| `X-Organization-Id` | 예 | 현재 작업 organization UUID |

성공 응답: `200 OK`, `OrganizationResponse`.

### `GET /organizations/{organization_id}`

요청 본문: 없음.

성공 응답: `200 OK`, `OrganizationResponse`.

### `POST /permission-requests`

요청 header:

| 이름 | 필수 | 비고 |
| --- | --- | --- |
| `X-Organization-Id` | 예 | 권한을 신청할 organization UUID |

요청 본문:

| 필드 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `requested_permission` | `string` | 아니오 | 생략 시 `app.create`. 다른 값은 거부한다. |
| `reason` | `string` | 예 | blank 값을 거부한다. |

성공 응답: `201 Created`, `PermissionRequestResponse`. 제출 응답의 `user`는 null이다.

거부 조건:

- 이미 App 생성 권한을 보유한 사용자(owner/manager 또는 `user_app_creation_permissions` row 보유)는 `409`, `{"detail": "App creation permission already granted"}`를 반환한다.
- 같은 organization에 pending `app.create` 신청이 있으면 `409`, `{"detail": "Pending permission request already exists"}`를 반환한다.
- blank `reason`과 `app.create`가 아닌 `requested_permission`은 `422 validation.failed`로 거부한다.
- active organization membership이 아니면 active organization context 판정에서 거부한다.

두 `409` 응답은 오류 envelope가 아니라 `{"detail": <string>}` 형태다. 클라이언트는 `detail` 문자열로 이미 권한 보유 상태와 pending 신청 중복을 구분해 안내한다.

### `PATCH /organizations/{organization_id}`

요청 header:

| 이름 | 필수 | 비고 |
| --- | --- | --- |
| `X-Organization-Id` | 예 | path `organization_id`와 같아야 한다. |

요청 본문:

| 필드 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `name` | `string \| null` | 아니오 | 제공되면 blank 값을 거부한다. 최대 255자. |
| `options` | `object \| null` | 아니오 | 제공되면 null 값을 거부한다. |

성공 응답: `200 OK`, `OrganizationResponse`.

### `GET /organizations/{organization_id}/members`

요청 header: matching `X-Organization-Id`.

Query parameter:

| 이름 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `state` | `string` | 아니오 | `active`, `invited`, `suspended`, `removed` 중 하나. 없으면 active/invited/suspended를 반환한다. |

성공 응답: `200 OK`, `OrganizationMemberResponse[]`.

### `POST /organizations/{organization_id}/members/invitations`

요청 header: matching `X-Organization-Id`.

요청 본문:

| 필드 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `user_id` | `UUID` | 예 | 이미 가입된 active user id. |
| `organization_auth_state` | `member \| manager` | 아니오 | 기본값은 `member`. |

성공 응답: `200 OK`, `OrganizationMemberResponse`.

현재 API는 email invitation이 아니라 user UUID 기반 초대다.

### `POST /organizations/{organization_id}/members/me/accept`

요청 본문: 없음.

성공 응답: `200 OK`, `OrganizationMemberResponse`.

이 endpoint는 초대받은 현재 사용자 본인의 수락 경로이며 manager 권한을 요구하지 않는다.

### `POST /organizations/{organization_id}/members/me/decline`

요청 본문: 없음.

성공 응답: `200 OK`, `OrganizationMemberResponse`.

이 endpoint는 초대받은 현재 사용자 본인의 거절 경로이며 manager 권한을 요구하지 않는다. 성공 시 membership은 `removed`가 되고 `organization.member.decline` audit을 기록한다. invitation이 없으면 `404`, 현재 상태가 `invited`가 아니면 `409`를 반환한다.

### `GET /notifications`

요청 본문: 없음.

성공 응답: `200 OK`.

```json
{
  "items": [
    {
      "id": "organization_invitation:<membership_id>",
      "type": "organization.invitation",
      "organization_id": "<uuid>",
      "organization_name": "Acme",
      "organization_auth_state": "member",
      "created_at": "<datetime>"
    }
  ]
}
```

현재 구현은 별도 notification table을 만들지 않고, 현재 user의 `invited` organization membership을 알림으로 파생한다. active/suspended/removed membership은 포함하지 않는다.

### `GET /notifications/stream`

SSE 응답: `text/event-stream`.

응답 header:

| Header | 값 | 비고 |
| --- | --- | --- |
| `Cache-Control` | `no-cache, no-transform` | 중간 프록시가 SSE 응답을 캐싱하거나 변형하지 않도록 한다. |
| `X-Accel-Buffering` | `no` | nginx 응답 버퍼링 비활성화 힌트. |
| `Connection` | `keep-alive` | SSE 연결 유지. |

현재 구현 event:

```text
event: notifications.changed
data: {}
```

초대 생성/수락/거절 이후 현재 사용자 channel에 발행된다. 클라이언트는 event payload를 source of truth로 사용하지 않고 `GET /notifications`를 재조회한다.

### `PATCH /organizations/{organization_id}/members/{user_id}`

요청 header: matching `X-Organization-Id`.

요청 본문:

| 필드 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `membership_state` | `active \| suspended \| null` | 아니오 | invited/removed로 직접 PATCH할 수 없다. |
| `organization_auth_state` | `member \| manager \| null` | 아니오 | organization-level 권한이다. |

성공 응답: `200 OK`, `OrganizationMemberResponse`.

### `DELETE /organizations/{organization_id}/members/{user_id}`

요청 header: matching `X-Organization-Id`.

성공 응답: `200 OK`, `OrganizationMemberRemoveResponse`.

```json
{
  "status": "removed",
  "removed_team_memberships": 2,
  "revoked_user_permissions": {
    "workflow": 1,
    "llm_credential": 1,
    "knowledge_base": 0,
    "audit": 0
  }
}
```

### `GET /teams`

요청 header: `X-Organization-Id`.

Query parameter:

| 이름 | 타입 | 필수 | 기본값 | 비고 |
| --- | --- | --- | --- | --- |
| `limit` | `integer string` | 아니오 | `10` | 1 이상 100 이하. |

성공 응답: `200 OK`, `TeamResponse[]`. active/inactive team을 함께 반환한다.

### `POST /teams`

요청 header: `X-Organization-Id`.

요청 본문:

| 필드 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `name` | `string` | 예 | 1자 이상, 255자 이하. organization 안에서 unique. |
| `description` | `string \| null` | 아니오 | team 설명. |
| `is_auto_add` | `boolean` | 아니오 | 기본값 false. |

성공 응답: `201 Created`, `TeamResponse`.

### `PATCH /teams/{team_id}`

요청 header: `X-Organization-Id`.

요청 본문:

| 필드 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `name` | `string \| null` | 아니오 | 제공되면 blank 값을 거부한다. |
| `description` | `string \| null` | 아니오 | 명시적 null 허용. |
| `managed_by` | `UUID \| null` | 아니오 | 같은 organization scope 안의 active user만 허용한다. |
| `is_auto_add` | `boolean \| null` | 아니오 | 신규 멤버 자동 추가 flag. |

성공 응답: `200 OK`, `TeamResponse`.

### `GET /teams/{team_id}/members`

요청 header: `X-Organization-Id`.

성공 응답: `200 OK`, `TeamMemberResponse[]`.

### `POST /teams/{team_id}/members`

요청 header: `X-Organization-Id`.

요청 본문:

| 필드 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `user_id` | `UUID` | 예 | active organization membership을 가진 active user. |

성공 응답: `200 OK`.

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "status": "added"
}
```

### `DELETE /teams/{team_id}/members/{user_id}`

요청 header: `X-Organization-Id`.

성공 응답: `200 OK`.

```json
{
  "status": "removed"
}
```

### `DELETE /teams/{team_id}`

요청 header: `X-Organization-Id`.

성공 응답: `200 OK`.

```json
{
  "status": "deactivated"
}
```

### Permission List Endpoints

`GET /permissions/workflows/{workflow_id}`와 `GET /permissions/llm-credentials/{credential_id}`는 같은 응답 구조를 사용한다.

성공 응답: `200 OK`, `ResourcePermissionListResponse`.

```json
{
  "resource_type": "workflow",
  "resource_id": "00000000-0000-0000-0000-000000000000",
  "organization_id": "00000000-0000-0000-0000-000000000000",
  "team_permissions": [
    {
      "id": "00000000-0000-0000-0000-000000000000",
      "grantee_type": "team",
      "grantee_id": "00000000-0000-0000-0000-000000000000",
      "grantee_name": "Builders",
      "auth_state": "builder",
      "assigned_at": "2026-07-04T00:00:00Z"
    }
  ],
  "user_permissions": []
}
```

### Permission Grant Endpoints

PUT permission endpoints는 같은 request body를 사용한다.

요청 header: `X-Organization-Id`.

요청 본문:

| 필드 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `auth_state` | `none \| viewer \| operator \| builder \| manager` | 예 | workflow/LLM credential operational matrix 값. |

성공 응답:

- team workflow: `200 OK`, `TeamWorkflowPermissionResponse`
- user workflow: `200 OK`, `UserWorkflowPermissionResponse`
- team LLM credential: `200 OK`, `TeamLLMPermissionResponse`
- user LLM credential: `200 OK`, `UserLLMPermissionResponse`

### Permission Revoke Endpoints

DELETE permission endpoints는 request body를 사용하지 않는다.

성공 응답: `200 OK`.

```json
{
  "message": "Team workflow permission deleted",
  "id": "00000000-0000-0000-0000-000000000000"
}
```

삭제 대상 종류에 따라 `message`는 `Team LLM credential permission deleted`, `User workflow permission deleted`, `User LLM credential permission deleted`가 될 수 있다.

### 공통 응답 모델

`OrganizationResponse`:

| 필드 | 타입 | 비고 |
| --- | --- | --- |
| `id` | `UUID` | organization id |
| `name` | `string` | organization 이름 |
| `options` | `object` | 확장 옵션 |
| `is_active` | `boolean` | active organization 여부 |
| `is_manager` | `boolean` | 현재 사용자가 organization manager인지 여부 |
| `created_at` | `datetime` | 생성 시각 |
| `updated_at` | `datetime` | 수정 시각 |

`OrganizationSummaryResponse`:

| 필드 | 타입 |
| --- | --- |
| `id` | `UUID` |
| `name` | `string` |
| `membership_state` | `invited \| active \| suspended \| removed` |
| `organization_auth_state` | `member \| manager` |
| `is_active` | `boolean` |

`OrganizationMemberResponse`:

| 필드 | 타입 |
| --- | --- |
| `id` | `UUID` |
| `organization_id` | `UUID` |
| `user_id` | `UUID` |
| `user_email` | `string` |
| `user_name` | `string` |
| `membership_state` | `invited \| active \| suspended \| removed` |
| `organization_auth_state` | `member \| manager` |
| `invited_by` | `UUID \| null` |
| `invited_at` | `datetime \| null` |
| `accepted_at` | `datetime \| null` |
| `removed_at` | `datetime \| null` |
| `created_at` | `datetime` |
| `updated_at` | `datetime` |

`PermissionRequestResponse`:

| 필드 | 타입 | 비고 |
| --- | --- | --- |
| `id` | `UUID` | 신청 id |
| `user` | `object \| null` | `{ id, name, email }`. 제출 응답에서는 null이며 admin 목록 조회에서 채워진다. |
| `requested_permission` | `string` | 현재는 `app.create`만 사용한다. |
| `reason` | `string` | 신청 사유 |
| `status` | `pending \| approved \| rejected` | 신청 상태 |
| `created_at` | `datetime` | 신청 시각 |
| `decided_by` | `UUID \| null` | 처리한 manager |
| `decided_at` | `datetime \| null` | 처리 시각 |

`TeamResponse`:

| 필드 | 타입 |
| --- | --- |
| `id` | `UUID` |
| `organization_id` | `UUID` |
| `name` | `string` |
| `description` | `string \| null` |
| `options` | `object` |
| `flags` | `integer` |
| `created_by` | `UUID` |
| `managed_by` | `UUID \| null` |
| `is_active` | `boolean` |
| `is_auto_add` | `boolean` |
| `created_at` | `datetime` |
| `updated_at` | `datetime` |
| `deactivated_at` | `datetime \| null` |

`TeamMemberResponse`:

| 필드 | 타입 |
| --- | --- |
| `id` | `UUID` |
| `user_id` | `UUID` |
| `email` | `string` |
| `name` | `string` |
| `assigned_at` | `datetime` |

## Errors

| 상태 | 코드 / 상세 | 조건 |
| --- | --- | --- |
| 400 | `organization.required` | `X-Organization-Id` header가 필요한 endpoint에서 header가 없다. |
| 400 | `validation.failed` | 빈 organization/team PATCH, blank name, null options, invalid membership state, no update fields, self invite/update/remove 등 business validation 실패. |
| 401 | `auth.required` | `auth_token` cookie가 없다. |
| 401 | `auth.invalid` | `auth_token` cookie가 유효하지 않거나 만료됐다. |
| 403 | `permission.denied` | organization scope 안에 있지만 manager/manage 권한이 부족하다. |
| 404 | `resource.not_found` | organization/resource가 없거나 current user scope 밖이다. |
| 409 | `resource.conflict` | duplicate team name, duplicate membership race, 마지막 manager 제거/강등, removed/invited/suspended 상태 전이 충돌. |
| 409 | `App creation permission already granted` / `Pending permission request already exists` | App 생성 권한 신청 중복. envelope 없이 `{"detail": <string>}`로 반환한다. |
| 422 | `validation.failed` | UUID route/header/query/body 형식, permission grant body의 invalid `auth_state`, 그 외 Pydantic validation 실패. |

## Permissions

- `/organizations`, `/organizations/memberships`, `/organizations/{organization_id}`, `/organizations/{organization_id}/members/me/accept`는 현재 사용자 인증을 요구하지만 organization manager 권한은 요구하지 않는다.
- `/organizations/current`, organization PATCH, member management, team management, permission management는 `X-Organization-Id` 기반 active organization scope를 사용한다.
- organization PATCH와 member/team 관리 API는 organization manager만 허용한다.
- workflow permission 관리 API는 organization manager 또는 대상 workflow `manage` 권한 보유자를 허용한다.
- LLM credential permission 관리 API는 organization manager 또는 대상 credential `manage` 권한 보유자를 허용한다.
- path organization과 header organization이 불일치하면 `404 resource.not_found`로 숨긴다.
- scope 밖 organization/resource/team/user는 `404 resource.not_found`로 숨긴다.
- scope 안 권한 부족은 `403 permission.denied`로 응답한다.
