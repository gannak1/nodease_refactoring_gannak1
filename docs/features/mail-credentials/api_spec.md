# Mail Credentials API Spec

Status: Draft

## 공통 계약

- 모든 endpoint는 인증과 `X-Organization-Id` active organization context를 요구한다.
- Organization scope 밖 credential은 `404 resource.not_found`로 숨긴다.
- 같은 organization에서 action 권한이 부족하면 `403 permission.denied`를 반환한다.
- Request schema는 unknown field를 거부한다.
- Response에는 secret, ciphertext, encryption key metadata 또는 provider raw response를 포함하지 않는다.

## Endpoints

| Method | Path | 설명 | 권한 |
| --- | --- | --- | --- |
| POST | `/api/v1/mail/credentials` | Mail credential 등록 | Organization manager |
| GET | `/api/v1/mail/credentials` | 사용 가능한 safe option 목록 | `use` 이상 또는 manager |
| GET | `/api/v1/mail/credentials/{credential_id}` | Safe metadata 조회 | `read` 이상 또는 manager |
| PATCH | `/api/v1/mail/credentials/{credential_id}` | 이름, endpoint 또는 secret 교체 | `manage` 또는 manager |
| DELETE | `/api/v1/mail/credentials/{credential_id}` | Credential revoke | `manage` 또는 manager |
| GET | `/api/v1/mail/credentials/{credential_id}/permissions` | User/team 권한 목록 | `manage` 또는 manager |
| PUT | `/api/v1/mail/credentials/{credential_id}/permissions/users/{user_id}` | User direct 권한 부여·변경 | `manage` 또는 manager |
| DELETE | `/api/v1/mail/credentials/{credential_id}/permissions/users/{user_id}` | User direct 권한 회수 | `manage` 또는 manager |
| PUT | `/api/v1/mail/credentials/{credential_id}/permissions/teams/{team_id}` | Team 권한 부여·변경 | `manage` 또는 manager |
| DELETE | `/api/v1/mail/credentials/{credential_id}/permissions/teams/{team_id}` | Team 권한 회수 | `manage` 또는 manager |

## Create Request

```json
{
  "credential_name": "업무용 메일",
  "provider": "gmail",
  "email_address": "mailbox@example.com",
  "auth_type": "app_password",
  "secret": "request-only-secret",
  "imap_host": "imap.gmail.com",
  "imap_port": 993,
  "use_ssl": true
}
```

`secret`은 request-only field다. 저장 응답과 이후 조회에 반환하지 않는다.

`use_ssl=true`는 `imap_port=993`의 implicit TLS를 의미한다. `use_ssl=false`는 평문 IMAP 허용이 아니라 `imap_port=143`에서 로그인 전에 STARTTLS를 강제한다. 다른 조합은 `mail.egress_target_denied`로 거부한다.

## Safe Response

`GET /credentials` picker option은 최소 공개 계약으로 다음 필드만 반환한다.

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "credential_name": "업무용 메일",
  "provider": "gmail",
  "email_preview": "m***@example.com",
  "status": "active"
}
```

상세 조회와 lifecycle mutation 응답은 다음 safe detail을 반환한다.

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "organization_id": "00000000-0000-0000-0000-000000000000",
  "credential_name": "업무용 메일",
  "provider": "gmail",
  "email_preview": "m***@example.com",
  "auth_type": "app_password",
  "status": "active",
  "imap_host": "imap.gmail.com",
  "imap_port": 993,
  "use_ssl": true
}
```

## PATCH 계약

PATCH는 `credential_name`, `secret`, `imap_host`, `imap_port`, `use_ssl` 중 하나 이상을 요구한다. `email_address`, provider 또는 auth type 변경은 다른 mailbox identity로 간주하므로 새 credential 등록을 사용한다.

## Permission 계약

Permission PUT body는 `auth_state`에 `viewer`, `operator`, `builder`, `manager` 중 하나만 허용한다. 기존 row가 있으면 갱신하고 없으면 생성한다. User는 active organization member, Team은 같은 organization의 active Team이어야 한다. 동시 변경은 credential row lock 안에서 직렬화한다. Revoked credential에는 신규 권한을 부여할 수 없지만 기존 권한 회수는 허용한다.

- `viewer`: safe detail `read`
- `operator`: `read`, runtime `use`
- `builder`: `read`, `use`, 일반 resource write 계층과의 일관성을 위한 상위 상태
- `manager`: `read`, `use`, `manage`

## 오류

- `mail.credential_reference_required`: Legacy inline password graph 또는 credential reference 누락
- `mail.credential_not_available`: Credential 없음 또는 revoked 상태
- `mail.credential_permission_denied`: Execution subject에게 `use` 권한 없음
- `mail.credential_decryption_failed`: Secret 복호화 실패
- `mail.credential_revoked`: Revoked credential 수정 또는 신규 permission 부여 시도
- `mail.credential_persistence_failed`: Credential 또는 canonical audit transaction 저장 실패
- `mail.egress_target_denied`: Private/loopback/metadata target 또는 허용되지 않은 IMAP port
- `validation.failed`: Unknown field, 빈 PATCH, 잘못된 endpoint 또는 port

오류 detail에는 secret, ciphertext, email 원문, IMAP raw exception을 포함하지 않는다.
