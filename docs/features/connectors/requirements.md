# Connectors Requirements

Status: Draft
Verified Against: feature/mba-120 @ 7a7032e
Related Features: workflow, organization, audit-tracing, knowledge

## Purpose

Connectors 기능은 외부 데이터 소스에 접속하기 위한 연결 정보를 관리한다. 현재 구현 범위는 PostgreSQL DB 연결 테스트, 연결 저장, 연결 상세 조회, 스키마 조회 API(`/api/v1/connectors`)와 `connections` 테이블이다. DB 비밀번호와 SSH 비밀번호/개인키는 서버에서 암호화 저장하고, 응답에는 secret 원문을 반환하지 않는다.

이 feature의 책임은 연결 등록과 조회, owner 기반 접근 제한, secret 저장/비노출, DB probe/schema 조회의 보안 경계다. 사용자 인증 생명주기, organization/team RBAC 부여, workflow 실행 권한, Knowledge Base 권한, Knowledge sync scheduler/worker는 connectors 자체의 책임이 아니다.

## User Stories

- 빌더는 외부 DB 연결 정보를 저장하기 전에 접속 가능 여부를 테스트할 수 있다.
- 빌더는 외부 DB 연결 정보를 저장하고, 이후 workflow 또는 Knowledge DB source 설정에서 connection id를 참조할 수 있다.
- 빌더는 저장한 연결의 테이블, 컬럼, FK 정보를 조회해 DB source의 테이블/컬럼 선택에 사용할 수 있다.
- 빌더는 저장한 연결 상세를 다시 열 때 비밀번호나 SSH secret 원문이 노출되지 않은 host/port/database/username/SSH metadata만 볼 수 있다.
- 플랫폼 운영자는 connector가 workflow 권한과 KB 권한의 책임을 대체하지 않는다는 점을 기준으로 운영 위험을 판단할 수 있다.

## Functional Requirements

### Current DB Connection Requirements

- CONN-REQ-001: 시스템은 `/api/v1/connectors` 하위 API로 외부 DB 연결 테스트, 저장, 상세 조회, 스키마 조회를 제공해야 한다.
- CONN-REQ-002: 현재 지원 DB 타입은 Gateway `SupportedDBType` 기준 `postgres`여야 한다.
- CONN-REQ-003: 클라이언트는 PostgreSQL을 활성 선택지로 제공하고, MySQL은 disabled/Coming Soon 선택지로 표시해야 한다.
- CONN-REQ-004: DB 연결 요청은 `connection_name`, `type`, `host`, `port`, `database`, `username`, `password`, 선택적 `ssh` 설정을 받아야 한다.
- CONN-REQ-005: SSH 설정은 `enabled`, `host`, `port`, `username`, `auth_type`, `password`, `private_key`를 포함할 수 있어야 한다.
- CONN-REQ-006: `ssh.enabled`가 false이면 Gateway는 adapter에 전달하는 설정에서 SSH 구성을 비활성화해야 한다.
- CONN-REQ-007: `POST /connectors/test`는 요청 연결 정보로 실제 DB 접속을 확인하고 `success`와 `message`를 반환해야 한다.
- CONN-REQ-008: `POST /connectors/test`는 현재 저장소에 connection row를 만들지 않아야 한다.
- CONN-REQ-009: `POST /connectors/test`에서 지원하지 않는 DB 타입은 `success=false`와 지원하지 않는 타입 메시지로 반환되어야 한다.
- CONN-REQ-010: `POST /connectors`는 인증된 현재 사용자를 요구해야 한다.
- CONN-REQ-011: `POST /connectors`는 저장 전 같은 연결 정보로 DB 접속 테스트를 수행해야 한다.
- CONN-REQ-012: `POST /connectors`는 저장 전 접속 테스트에 10초 timeout을 적용해야 한다.
- CONN-REQ-013: 저장 전 접속 테스트가 실패하면 시스템은 connection row를 만들지 않아야 한다.
- CONN-REQ-014: 저장 성공 시 시스템은 `connections.user_id`를 현재 사용자 ID로 설정해야 한다.
- CONN-REQ-015: 저장 성공 시 시스템은 DB 비밀번호를 `encrypted_password`에 암호화 저장해야 한다.
- CONN-REQ-016: SSH password 인증을 사용하는 저장 성공 시 시스템은 SSH 비밀번호를 `encrypted_ssh_password`에 암호화 저장해야 한다.
- CONN-REQ-017: SSH key 인증을 사용하는 저장 성공 시 시스템은 SSH private key를 `encrypted_ssh_private_key`에 암호화 저장해야 한다.
- CONN-REQ-018: 저장 성공 응답은 생성된 connection id, success flag, 사용자 표시용 message만 반환해야 한다.
- CONN-REQ-019: 저장 성공은 `connection.create` audit action으로 기록되어야 한다.
- CONN-REQ-020: `GET /connectors/{connection_id}`는 인증된 현재 사용자를 요구해야 한다.
- CONN-REQ-021: `GET /connectors/{connection_id}`는 connection owner가 아니면 `403`으로 거부해야 한다.
- CONN-REQ-022: `GET /connectors/{connection_id}`는 비밀번호, SSH 비밀번호, SSH private key, encrypted secret 값을 반환하지 않아야 한다.
- CONN-REQ-023: `GET /connectors/{connection_id}/schema`는 인증된 현재 사용자를 요구해야 한다.
- CONN-REQ-024: `GET /connectors/{connection_id}/schema`는 connection owner가 아니면 `403`으로 거부해야 한다.
- CONN-REQ-025: `GET /connectors/{connection_id}/schema`는 저장된 encrypted secret을 서버에서만 복호화해 adapter 접속 설정을 구성해야 한다.
- CONN-REQ-026: PostgreSQL schema 조회는 table name, column name/type, FK의 column/referenced table/referenced column 정보를 반환해야 한다.
- CONN-REQ-027: DB schema 조회는 secret 원문을 응답 body에 포함하지 않아야 한다.
- CONN-REQ-028: 현재 `connections` 테이블은 user-owned resource이며 `organization_id`를 갖지 않는다.
- CONN-REQ-029: 현재 connection owner 판정은 organization/team permission helper가 아니라 `connections.user_id == current_user.id` 기준이어야 한다.

## Policies And Edge Cases

- 현재 `POST /connectors/test`는 Gateway 코드상 `get_current_user`를 요구하지 않는다.
- 현재 `POST /connectors`는 `get_current_user`를 요구하지만 resource permission table을 사용하지 않는다.
- 현재 `GET /connectors/{connection_id}`와 `GET /connectors/{connection_id}/schema`는 없는 connection에 `404`, owner mismatch에 `403`을 반환한다.
- 현재 create/test/schema 실패 메시지는 일부 raw exception 문자열을 detail/message에 포함할 수 있다.
- 현재 schema 조회는 SQLAlchemy inspector를 사용해 schema metadata를 읽는다.
- 현재 `DbProcessor`는 Knowledge DB source ingestion에서 저장된 `connection_id`를 조회하고 선택된 테이블/컬럼 기반 SQL을 생성한다. 이 ingestion lifecycle은 Knowledge feature 책임이다.
- `connections`에는 `created_at/updated_at`과 `organization_id`가 없다.

## Open Questions

- `connections`를 organization-scoped resource로 전환할지, user-owned resource로 유지할지 결정해야 한다.
