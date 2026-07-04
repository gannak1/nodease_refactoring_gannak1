# Connectors Test Cases

Status: Draft
Verified Against: dev @ 7a7032e8da3f721a00d93c6fbff02122397456f3

## Minimum Failure Rule

이 문서는 정상 시나리오를 길게 반복하지 않고, 각 connectors 조건을 깨뜨리는 최소 입력, 상태, 또는 관찰값을 기준으로 테스트 케이스를 정의한다.

각 테스트는 해당 최소 조건 하나만으로 실패를 유도하거나, 성공 경로의 필수 관찰값 하나가 빠졌을 때 실패로 판단할 수 있어야 한다.

## Scope Boundary

이 문서는 현재 구현된 workflow DB connector의 연결 테스트, 연결 저장, 상세 조회, schema 조회, client 호출 경계, connection secret 보호만 직접 검증한다.

다음은 connectors test case의 직접 검증 범위가 아니다. 해당 API와 component 계약이 확정되는 feature 문서에서 별도로 검증한다.

- Knowledge source sync/preview/fetch lifecycle
- HTTP/URL/object-storage adapter egress 세부 정책
- `/api/v1/rag/proxy/preview`와 URL 기반 upload/preview 이관
- connector health/remediation 운영 화면
- KB content retrieval, raw access, compliance access 권한

## Unit Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| CONN-TC-U001 | 지원 DB 타입은 Gateway `SupportedDBType` 기준이어야 한다. | `type="mysql"` 하나만 전달한다. | test는 `success=false`, create는 `400`. |
| CONN-TC-U002 | PostgreSQL connector check는 실제 연결 확인 쿼리를 실행해야 한다. | DB 연결은 되지만 `SELECT 1` 실행이 실패한다. | 연결 테스트 실패. |
| CONN-TC-U003 | SSH disabled 설정은 adapter에 전달되지 않아야 한다. | `ssh.enabled=false`인데 adapter config에 SSH tunnel 설정이 남는다. | 테스트 실패. |
| CONN-TC-U004 | SSH key 인증은 private key를 사용해야 한다. | `auth_type="key"`인데 password auth로 tunnel을 만든다. | 테스트 실패. |
| CONN-TC-U005 | SSH password 인증은 password를 사용해야 한다. | `auth_type="password"`인데 private key auth로 tunnel을 만든다. | 테스트 실패. |
| CONN-TC-U006 | 저장되는 DB/SSH secret은 원문과 구분되어야 한다. | `encrypted_password`, `encrypted_ssh_password`, `encrypted_ssh_private_key` 중 하나가 입력 원문과 같다. | 테스트 실패. |
| CONN-TC-U007 | 상세 응답 모델은 secret 필드를 포함하지 않아야 한다. | response model에 `password`, `private_key`, `encrypted_password`, `encrypted_ssh_private_key` 중 하나가 있다. | 테스트 실패. |
| CONN-TC-U008 | PostgreSQL schema introspection은 table, column, FK shape를 보존해야 한다. | 테이블이 있는데 `table_name`, column `name/type`, FK `referenced_table/referenced_column` 중 하나가 빠진다. | 테스트 실패. |
| CONN-TC-U009 | audit listener는 `Connection` 민감 필드를 마스킹 대상으로 등록해야 한다. | host/database/username/encrypted secret 필드 중 하나가 sensitive set에서 빠진다. | 테스트 실패. |

## API Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| CONN-TC-A001 | `POST /connectors/test`는 필수 필드를 요구해야 한다. | `host`, `database`, `username`, `password`, `connection_name`, `type` 중 하나가 없다. | `422` 검증 오류 envelope. |
| CONN-TC-A002 | `POST /connectors/test`는 지원하지 않는 타입을 저장 없이 거부해야 한다. | `type="mysql"`이다. | `200`, `success=false`, 저장 row 없음. |
| CONN-TC-A003 | `POST /connectors/test` 성공은 저장 row를 만들지 않아야 한다. | adapter check가 true인데 `connections` row count가 증가한다. | 테스트 실패. |
| CONN-TC-A004 | `POST /connectors/test` 실패는 `success=false`를 반환해야 한다. | adapter check가 false이거나 예외를 던진다. | `success=false`. |
| CONN-TC-A005 | `POST /connectors`는 인증을 요구해야 한다. | `auth_token` 쿠키 없이 요청한다. | Auth dependency의 401 응답. |
| CONN-TC-A006 | `POST /connectors`는 지원하지 않는 타입을 거부해야 한다. | 인증된 요청에서 `type="mysql"`이다. | `400`, `지원하지 않는 DB타입입니다.` |
| CONN-TC-A007 | `POST /connectors`는 저장 전 connection check 실패를 row 생성 없이 반환해야 한다. | adapter check가 false를 반환하거나 10초를 초과한다. | `400`, 저장 row 없음. |
| CONN-TC-A008 | `POST /connectors` 성공은 current user owner와 암호화 secret을 저장해야 한다. | `user_id`가 current user와 다르거나 저장 secret이 입력 원문과 같다. | 테스트 실패. |
| CONN-TC-A009 | `POST /connectors` 성공은 생성 id를 반환해야 한다. | `201` 응답에 `id`가 없다. | 테스트 실패. |
| CONN-TC-A010 | `GET /connectors/{id}`는 인증을 요구해야 한다. | `auth_token` 쿠키 없이 요청한다. | Auth dependency의 401 응답. |
| CONN-TC-A011 | `GET /connectors/{id}`는 없는 id를 숨기지 않고 404로 반환해야 한다. | DB에 없는 connection id이다. | `404`, `Connection not found`. |
| CONN-TC-A012 | `GET /connectors/{id}`는 non-owner를 거부해야 한다. | 다른 사용자의 connection id를 요청한다. | `403`, `Not authorized`. |
| CONN-TC-A013 | `GET /connectors/{id}` 성공은 secret을 반환하지 않아야 한다. | 성공 body에 password/private key/encrypted secret이 있다. | 테스트 실패. |
| CONN-TC-A014 | `GET /connectors/{id}/schema`는 인증을 요구해야 한다. | `auth_token` 쿠키 없이 요청한다. | Auth dependency의 401 응답. |
| CONN-TC-A015 | `GET /connectors/{id}/schema`는 없는 id를 숨기지 않고 404로 반환해야 한다. | DB에 없는 connection id이다. | `404`, `Connection not found`. |
| CONN-TC-A016 | `GET /connectors/{id}/schema`는 non-owner를 거부해야 한다. | 다른 사용자의 connection id를 요청한다. | `403`, `Not authorized`. |
| CONN-TC-A017 | `GET /connectors/{id}/schema`는 복호화 실패를 오류로 반환해야 한다. | encrypted password가 복호화할 수 없는 값이다. | `500`, `Decryption failed: ...`. |
| CONN-TC-A018 | `GET /connectors/{id}/schema`는 지원하지 않는 저장 타입을 거부해야 한다. | row의 `type`이 adapter map에 없다. | `400`, `Unsupported DB type`. |
| CONN-TC-A019 | `GET /connectors/{id}/schema` 성공은 tables 배열을 반환해야 한다. | adapter schema 결과가 있는데 response에 `tables`가 없다. | 테스트 실패. |

## Component And Hook Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| CONN-TC-C001 | `connectorApi.testConnection`은 `/connectors/test`로 POST해야 한다. | test 호출이 다른 path 또는 GET/PUT으로 나간다. | 테스트 실패. |
| CONN-TC-C002 | `connectorApi.createConnector`는 `/connectors`로 POST해야 한다. | create 호출이 다른 path 또는 GET/PUT으로 나간다. | 테스트 실패. |
| CONN-TC-C003 | `connectorApi.getSchema`는 `/connectors/{id}/schema`로 GET해야 한다. | schema 호출이 다른 path 또는 POST로 나간다. | 테스트 실패. |
| CONN-TC-C004 | `connectorApi.getConnectionDetails`는 `/connectors/{id}`로 GET해야 한다. | detail 호출이 다른 path 또는 POST로 나간다. | 테스트 실패. |
| CONN-TC-C005 | `connectorApi`는 클라이언트 `authType`을 Gateway `auth_type`으로 매핑해야 한다. | `authType="key"`인데 payload `auth_type`이 `"password"`이다. | 테스트 실패. |
| CONN-TC-C006 | `DBConnectionForm` 입력 변경은 부모 `onChange` 호출과 test status 초기화를 해야 한다. | 한 필드 변경 후 `onChange`가 호출되지 않거나 `testStatus`가 `idle`이 아니다. | 테스트 실패. |
| CONN-TC-C007 | `DBConnectionForm` 연결 테스트는 pending/success/error 상태를 표시해야 한다. | 테스트 pending인데 버튼이 활성 상태이거나, 성공/실패 결과 메시지가 표시되지 않는다. | 테스트 실패. |
| CONN-TC-C008 | `DBSchemaSelector`는 connection id로 schema를 조회해야 한다. | `connectionId`가 있는데 `connectorApi.getSchema`가 호출되지 않는다. | 테스트 실패. |
| CONN-TC-C009 | `DBSchemaSelector`는 schema 조회 실패를 toast로 표시해야 한다. | `getSchema`가 reject된다. | `테이블 정보를 불러오는데 실패했습니다.` 표시. |
| CONN-TC-C010 | `DBSchemaSelector`는 최대 2개 테이블 제한을 적용해야 한다. | 2개 테이블이 선택된 상태에서 3번째 테이블을 선택한다. | 선택 차단, 제한 toast. |
| CONN-TC-C011 | `DBSchemaSelector`는 FK 있는 2개 테이블 선택 시 join config를 생성해야 한다. | FK metadata가 있는데 `onJoinConfigChange`에 enabled config가 전달되지 않는다. | 테스트 실패. |

## Permission Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| CONN-TC-P001 | `POST /connectors/test` 현재 동작은 인증 없는 호출 가능 여부를 명시적으로 고정해야 한다. | 문서/테스트 갱신 없이 인증 요구 여부가 바뀐다. | 문서/테스트 업데이트 필요. |
| CONN-TC-P002 | 저장된 connection 상세/schema는 owner mismatch를 거부해야 한다. | 다른 사용자의 connection id로 상세 또는 schema를 요청한다. | `403`, `Not authorized`. |
| CONN-TC-P003 | 현재 user-owned `connections`는 workflow/KB 권한만으로 자동 공유되지 않아야 한다. | workflow/KB 접근 권한만 있는 사용자가 다른 사용자의 connection을 사용한다. | 테스트 실패 또는 403/404. |

## Edge Cases

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| CONN-TC-X001 | Current gap: `connectorApi`는 connector create/test 실패 시 raw Axios error 객체를 `console.error`에 전달한다. | Axios error의 request config/data에 DB password, SSH password, private key가 포함된다. | 현재 구현은 client console log secret 비노출을 보장하지 않으므로 production 전 sanitize 필요. |
| CONN-TC-X002 | Secret 원문은 문서, fixture, audit metadata에 남지 않아야 한다. | DB password, SSH password, private key 원문이 문서, 테스트 fixture, audit metadata 중 하나에서 관찰된다. | 테스트 실패. |
