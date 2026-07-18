# External Action Credentials API Spec

Status: Draft

## Common Contract

- 모든 endpoint는 인증과 `X-Organization-Id` active organization context를 요구한다.
- Unknown request field, 빈 update, 잘못된 UUID/provider/revision 같은 Pydantic request validation은 `422 validation.failed`로 거부한다. provider별 secret 형식 검증 실패는 `400 external_action_credential.invalid`다.
- Same-organization credential의 권한 없는 상세 접근은 `404 external_action_credential.not_found`로 숨긴다. manager-only registration처럼 resource 식별자가 없는 action의 부족 권한은 `403 external_action_credential.permission_denied`다.
- Response와 error detail에는 secret, ciphertext, encryption key metadata, raw Slack Webhook URL, GitHub token 또는 provider raw response를 포함하지 않는다.

## Endpoints

| Method | Path | 설명 | 권한 |
| --- | --- | --- | --- |
| POST | `/api/v1/external-action-credentials/credentials` | Credential 등록 | Organization manager |
| GET | `/api/v1/external-action-credentials/credentials` | 사용 가능한 safe picker option 목록 | `use` 이상 또는 manager |
| GET | `/api/v1/external-action-credentials/credentials/management-options` | active/revoked safe 관리 option 목록 | `manage` 또는 manager |
| GET | `/api/v1/external-action-credentials/credentials/{credential_id}` | Safe metadata 조회 | `read` 이상 또는 manager |
| PATCH | `/api/v1/external-action-credentials/credentials/{credential_id}` | 이름 또는 secret 교체 | `manage` 또는 manager |
| POST | `/api/v1/external-action-credentials/credentials/{credential_id}/revoke` | Credential revoke | `manage` 또는 manager |
| GET | `/api/v1/external-action-credentials/credentials/{credential_id}/permissions` | User/team permission 목록 | `manage` 또는 manager |
| PUT/DELETE | `/credentials/{credential_id}/permissions/users/{user_id}` | User direct grant/revoke | `manage` 또는 manager |
| PUT/DELETE | `/credentials/{credential_id}/permissions/teams/{team_id}` | Team grant/revoke | `manage` 또는 manager |

## Create Request

```json
{
  "credential_name": "운영 Slack 알림",
  "provider": "slack_api",
  "secret": "request-only-secret"
}
```

`secret`은 request-only field다. Slack Webhook은 `https://hooks.slack.com/services/...`의 canonical commercial URL만 `slack_webhook` secret으로 허용한다. provider endpoint, method, repository, channel은 credential resource가 아니라 node configuration이다.

## Safe Response

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "organization_id": "00000000-0000-0000-0000-000000000000",
  "credential_name": "운영 Slack 알림",
  "provider": "slack_api",
  "status": "active",
  "revision": 1,
  "created_at": "2026-07-18T00:00:00Z",
  "updated_at": "2026-07-18T00:00:00Z",
  "revoked_at": null
}
```

Picker와 관리 option은 `id`, `credential_name`, `provider`, `revision`, `status`만 반환한다. Picker는 active이고 `use` 가능한 항목만 반환한다. 관리 option은 active 또는 revoked 중 `manage` 가능한 항목을 반환하되, revoked 항목은 기존 permission 조회·회수에만 사용한다.

## Update, Revoke And Permission

- PATCH body는 `expected_revision`과 `credential_name` 또는 `secret` 중 하나 이상을 요구한다.
- Revoke body는 `expected_revision`을 요구한다. hard delete 대신 active credential을 revoked로 전이한다.
- Permission grant body의 `auth_state`는 `viewer`, `operator`, `builder`, `manager` 중 하나다. `operator` 이상이 runtime `use`를 가진다.
- User grant 대상은 active organization membership과 active user여야 하며, Team은 동일 organization의 active Team이어야 한다.
- Revoked credential은 관리 option과 기존 permission 목록에는 남지만 PUT 신규 grant는 `external_action_credential.revoked`로 거부하고 DELETE 회수만 허용한다.

## Management Error Contract

| Status | Code | 조건 |
| --- | --- | --- |
| 400 | `external_action_credential.invalid` | provider별 secret 형식 또는 keyring 검증 실패 |
| 403 | `external_action_credential.permission_denied` | resource 식별자 없는 organization manager-only 등록 권한 부족 |
| 404 | `external_action_credential.not_found` | credential이 없거나 same-organization actor에게 resource 권한이 없음 |
| 404 | `external_action_credential.permission_target_not_found` | user/team grant 대상이 active organization 범위에 없거나 inactive 상태 |
| 409 | `external_action_credential.revision_conflict` | PATCH/revoke의 `expected_revision`이 최신 revision과 다름 |
| 409 | `external_action_credential.revoked` | revoke된 credential의 수정 또는 신규 grant 시도 |
| 422 | `validation.failed` | route/header/body 형식, unknown field, 빈 PATCH, provider/revision enum 또는 길이 검증 실패 |
| 503 | `external_action_credential.persistence_failed` | mutation과 canonical audit를 함께 durable하게 저장하지 못해 rollback됨 |

## Safe Runtime And Preflight Reasons

- `external_action_credential.unavailable`: missing, revoked, cross-organization, provider mismatch, `use` 거부, revision mismatch 또는 decrypt failure를 runtime에서 숨기는 공통 reason이다.
- `external_action_credential.reference_required`: `credential_id` 누락 또는 malformed reference다.
- `external_action_credential.legacy_secret_requires_migration`, `slack.legacy_credential_requires_migration`: direct secret graph가 발견된 저장/graph validation reason이다.
- Deployment preflight 외부 projection은 `external_action_credential_unavailable`만 반환하며 credential detail을 포함하지 않는다.
