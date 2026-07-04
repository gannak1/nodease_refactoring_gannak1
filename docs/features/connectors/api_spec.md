# Connectors API Spec

Status: Draft
Verified Against: feature/mba-120 @ 7a7032e

기본 경로: `/api/v1`

## Endpoints

| 메서드 | 경로 | 설명 | 인증 |
| --- | --- | --- | --- |
| POST | `/connectors/test` | DB/SSH 연결 정보를 저장하지 않고 실제 DB 접속 가능 여부를 테스트한다. | 현재 구현상 공개 |
| POST | `/connectors` | DB/SSH 연결을 테스트한 뒤 secret을 암호화해 `connections`에 저장한다. | `auth_token` 쿠키 필요 |
| GET | `/connectors/{connection_id}` | 저장된 connection 상세를 조회한다. Secret은 반환하지 않는다. | `auth_token` 쿠키 및 owner |
| GET | `/connectors/{connection_id}/schema` | 저장된 connection secret을 서버에서 복호화해 DB schema를 조회한다. | `auth_token` 쿠키 및 owner |

## Request And Response Models

### `POST /connectors/test`

요청 본문: `DBConnectionTestRequest`

| 필드 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `connection_name` | `string` | 예 | 연결 식별용 별칭이다. 저장되지 않는다. |
| `type` | `string` | 예 | 현재 Gateway `SupportedDBType` 기준 `postgres`만 지원한다. |
| `host` | `string` | 예 | DB host이다. |
| `port` | `integer` | 아니오 | 기본값은 `5432`이다. |
| `database` | `string` | 예 | DB 이름이다. |
| `username` | `string` | 예 | DB 사용자명이다. |
| `password` | `string` | 예 | DB 비밀번호이다. 테스트 요청에서는 저장하지 않는다. |
| `ssh` | `SSHConfig \| null` | 아니오 | SSH tunnel 설정이다. `enabled=false`이면 Gateway에서 비활성화한다. |

`SSHConfig`:

| 필드 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `enabled` | `boolean` | 아니오 | 기본값은 `false`이다. |
| `host` | `string \| null` | 아니오 | SSH host이다. |
| `port` | `integer` | 아니오 | 기본값은 `22`이다. |
| `username` | `string \| null` | 아니오 | SSH 사용자명이다. |
| `auth_type` | `"password" \| "key"` | 아니오 | 기본값은 `"password"`이다. |
| `password` | `string \| null` | 아니오 | password 인증용 SSH secret이다. |
| `private_key` | `string \| null` | 아니오 | key 인증용 SSH private key 원문이다. |

성공/실패 응답: `200 OK`, `DBConnectionTestResponse`.

| 필드 | 타입 | 비고 |
| --- | --- | --- |
| `success` | `boolean` | 연결 성공 여부이다. |
| `message` | `string` | 사용자 표시용 메시지이다. 현재 구현은 일부 raw exception 문자열을 포함할 수 있다. |

지원하지 않는 DB 타입도 현재 구현에서는 HTTP 오류가 아니라 `200 OK`, `success=false`로 반환한다.

### `POST /connectors`

요청 본문: `DBConnectionTestRequest`.

인증 입력: `auth_token` 쿠키.

동작:

1. `type`이 지원 DB 타입인지 확인한다.
2. `ssh.enabled=false`이면 SSH 설정을 비활성화한다.
3. adapter `check`를 threadpool에서 실행하며 10초 timeout을 적용한다.
4. 접속 테스트가 성공하면 DB password와 SSH password/private key를 암호화한다.
5. `connections` row를 현재 사용자 소유로 저장한다.
6. `connection.create` audit action을 기록한다.

성공 응답: `201 Created`.

| 필드 | 타입 | 비고 |
| --- | --- | --- |
| `id` | `string` | 생성된 connection id이다. |
| `success` | `boolean` | 성공 시 `true`이다. |
| `message` | `string` | 사용자 표시용 메시지이다. |

예시:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "success": true,
  "message": "연결 정보가 안전하게 저장되었습니다."
}
```

### `GET /connectors/{connection_id}`

요청 본문: 없음.

인증 입력: `auth_token` 쿠키.

성공 응답: `200 OK`, `DBConnectionDetailResponse`.

| 필드 | 타입 | 비고 |
| --- | --- | --- |
| `id` | `string` | connection id이다. |
| `connection_name` | `string` | 연결 별칭이다. |
| `type` | `string` | DB 타입이다. |
| `host` | `string` | DB host이다. |
| `port` | `integer` | DB port이다. |
| `database` | `string` | DB 이름이다. |
| `username` | `string` | DB 사용자명이다. |
| `ssh` | `object \| null` | SSH 사용 시 secret을 제외한 SSH metadata이다. |

`ssh` 객체는 `enabled`, `host`, `port`, `username`, `auth_type`만 포함한다. DB password, SSH password, SSH private key, encrypted secret은 반환하지 않는다.

### `GET /connectors/{connection_id}/schema`

요청 본문: 없음.

인증 입력: `auth_token` 쿠키.

동작:

1. connection row를 조회한다.
2. 현재 사용자가 owner인지 확인한다.
3. DB password와 필요한 SSH secret을 서버에서 복호화한다.
4. adapter의 schema introspection을 호출한다.

성공 응답: `200 OK`.

| 필드 | 타입 | 비고 |
| --- | --- | --- |
| `tables` | `SchemaTable[]` | 조회된 테이블 목록이다. |

`SchemaTable`:

| 필드 | 타입 | 비고 |
| --- | --- | --- |
| `table_name` | `string` | 테이블명이다. |
| `columns` | `SchemaColumn[]` | 컬럼 목록이다. |
| `foreign_keys` | `ForeignKey[]` | FK 목록이다. 현재 PostgreSQL connector는 첫 번째 constrained/referred column을 기록한다. |

`SchemaColumn`:

| 필드 | 타입 |
| --- | --- |
| `name` | `string` |
| `type` | `string` |

`ForeignKey`:

| 필드 | 타입 |
| --- | --- |
| `column` | `string` |
| `referenced_table` | `string` |
| `referenced_column` | `string` |

예시:

```json
{
  "tables": [
    {
      "table_name": "users",
      "columns": [
        { "name": "id", "type": "UUID" },
        { "name": "email", "type": "VARCHAR" }
      ],
      "foreign_keys": []
    }
  ]
}
```

## Errors

HTTP 예외는 Gateway 공통 `detail` 응답을 사용하고, 검증 오류는 Gateway 공통 검증 오류 envelope를 따른다.

구현된 connector 오류 사례:

| 상태 | 엔드포인트 | 상세 / 본문 | 조건 |
| --- | --- | --- | --- |
| 200 | `POST /connectors/test` | `{ "success": false, "message": "지원하지 않는 DB 타입입니다: ..." }` | 지원하지 않는 DB 타입이다. |
| 200 | `POST /connectors/test` | `{ "success": false, "message": "..." }` | adapter `check`가 false를 반환하거나 예외를 던진다. |
| 400 | `POST /connectors` | `지원하지 않는 DB타입입니다.` | 지원하지 않는 DB 타입이다. |
| 400 | `POST /connectors` | `DB 연결 테스트 중 오류 발생: ...` | 저장 전 접속 테스트가 실패하거나 timeout/adapter 예외가 발생한다. |
| 500 | `POST /connectors` | `암호화 처리 중 오류 발생: ...` | secret 암호화에 실패한다. |
| 404 | `GET /connectors/{connection_id}`, `GET /connectors/{connection_id}/schema` | `Connection not found` | connection id를 찾을 수 없다. |
| 403 | `GET /connectors/{connection_id}`, `GET /connectors/{connection_id}/schema` | `Not authorized` | connection owner가 아니다. |
| 500 | `GET /connectors/{connection_id}/schema` | `Decryption failed: ...` | 저장된 secret 복호화에 실패한다. |
| 400 | `GET /connectors/{connection_id}/schema` | `Unsupported DB type` | 저장된 connection type에 맞는 adapter가 없다. |
| 400 | `GET /connectors/{connection_id}/schema` | `Failed to fetch schema: ...` | schema introspection이 실패한다. |
| 422 | `POST /connectors/test`, `POST /connectors` | 검증 오류 envelope | 요청 본문이 Pydantic 검증에 실패한다. |

`POST /connectors`, 상세 조회, schema 조회의 인증 실패 응답은 Auth 공통 dependency의 `auth_token` 쿠키 검증 결과를 따른다.

## Permissions

- `POST /connectors/test`는 현재 구현상 `get_current_user`를 요구하지 않는다.
- `POST /connectors`는 `auth_token` 쿠키로 현재 사용자를 식별해야 하며, 생성된 row의 `user_id`는 현재 사용자 ID이다.
- `GET /connectors/{connection_id}`와 `GET /connectors/{connection_id}/schema`는 current user가 `connections.user_id`와 같을 때만 허용한다.
- 현재 connectors API는 organization/team resource permission table을 사용하지 않는다.
- 현재 `connections`에는 `organization_id`가 없으므로 workflow/KB 권한이 connection 사용 권한을 자동으로 대체하지 않는다.
- Connection 생성은 `connection.create` audit action으로 기록된다. 연결 테스트, 상세 조회, schema 조회는 현재 endpoint-level audit action을 기록하지 않는다.
- Knowledge source connector와 KB retrieval 권한은 Knowledge feature 책임이다.
