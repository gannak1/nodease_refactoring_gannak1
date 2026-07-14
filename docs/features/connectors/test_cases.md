# Connectors Test Cases

Status: Draft
Verified Against: feature/mba-246 @ 3ee48d4280daa163e86c7e1a2bd28cef81d6b75a

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
| CONN-TC-U010 | PostgreSQL 직접 연결은 검증된 public IP로 연결 대상을 고정해야 한다. | 사전 DNS 검증 후 SQLAlchemy/driver가 hostname을 다시 해석하도록 둔다. | 테스트 실패. |
| CONN-TC-U011 | PostgreSQL 직접 연결은 private, loopback, link-local, metadata, reserved target을 거부해야 한다. | `127.0.0.1`, `10.0.0.0/8`, metadata IP 중 하나로 연결을 연다. | safe reason code로 실패. |
| CONN-TC-U012 | PostgreSQL schema introspection은 table/column/FK cap을 적용해야 한다. | cap 초과 schema가 truncation marker 없이 전체 반환된다. | 테스트 실패. |
| CONN-TC-U013 | DB row fetch는 SELECT-only guard와 dangerous function blocklist를 적용해야 한다. | `pg_sleep`, `pg_read_file`, `dblink`, `COPY`, 복수 statement 중 하나가 통과한다. | `adapter.sql_not_allowed`. |
| CONN-TC-U014 | DB row fetch는 read-only transaction, statement timeout, batch size cap, total row cap을 적용해야 한다. | 사용자 SELECT가 cap 없이 실행되거나 row cap 초과를 부분 성공으로 반환한다. | safe reason code로 실패. |
| CONN-TC-U015 | `PostgresConnector()` 기본 생성자는 Knowledge-safe 경계로 SSH tunnel을 거부해야 한다. | 기본 생성자가 SSH tunnel을 연다. | `adapter.ssh_tunnel_not_allowed`. |
| CONN-TC-U016 | Workflow connector API는 기존 SSH tunnel compatibility를 명시적으로 선택해야 한다. | workflow connector API가 기본 생성자를 사용해 문서화된 SSH tunnel 설정을 깨뜨리거나, Knowledge ingestion까지 tunnel을 열어 둔다. | 테스트 실패. |

## API Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| CONN-TC-A001 | `POST /connectors/test`는 필수 필드를 요구해야 한다. | `host`, `database`, `username`, `password`, `connection_name`, `type` 중 하나가 없다. | `422` 검증 오류 envelope. |
| CONN-TC-A002 | `POST /connectors/test`는 지원하지 않는 타입을 저장 없이 거부해야 한다. | `type="mysql"`이다. | `422 validation.failed`, 저장 row 없음. |
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
| CONN-TC-A017 | `GET /connectors/{id}/schema`는 복호화 실패를 safe 오류로 반환해야 한다. | encrypted password가 복호화할 수 없는 값이다. | `500`, safe `reason_code` 응답. |
| CONN-TC-A018 | `GET /connectors/{id}/schema`는 지원하지 않는 저장 타입을 거부해야 한다. | row의 `type`이 adapter map에 없다. | `400`, `Unsupported DB type`. |
| CONN-TC-A019 | `GET /connectors/{id}/schema` 성공은 tables 배열을 반환해야 한다. | adapter schema 결과가 있는데 response에 `tables`가 없다. | 테스트 실패. |
| CONN-TC-A020 | `POST /connectors/test` 실패는 raw host/database/secret/driver detail을 노출하지 않아야 한다. | adapter가 secret 포함 예외를 던진다. | `success=false`, safe message와 safe `reason_code`. |
| CONN-TC-A021 | `POST /connectors` 저장 전 connection check 실패는 raw host/database/secret/driver detail을 노출하지 않아야 한다. | adapter가 secret 포함 예외를 던진다. | `400`, safe `reason_code`, 저장 row 없음. |
| CONN-TC-A022 | `GET /connectors/{id}/schema` fetch 실패는 raw host/database/secret/driver detail을 노출하지 않아야 한다. | adapter가 secret 포함 예외를 던진다. | `400`, safe `reason_code`. |
| CONN-TC-A023 | Connector test는 인증과 active organization을 network 전에 요구해야 한다. | auth 없음, header 없음/invalid, scope 밖, invited/suspended/removed membership 중 하나다. | `401/400/422/404`, admission/DNS/probe 0회. |
| CONN-TC-A024 | Connector test actual body는 32 KiB와 total 5초로 제한되어야 한다. | Exact/over, missing/duplicate/invalid/understated length, chunked crossing, slow stream을 보낸다. | Exact는 parse, over는 413, invalid는 400, slow는 408; admission/probe 0회. |
| CONN-TC-A025 | Connector test media/JSON은 strict해야 한다. | Wrong/duplicate content type, compressed body, BOM, invalid UTF-8/JSON, NaN, non-object root다. | `400/415`, raw body 비노출. |
| CONN-TC-A026 | SSH-enabled test는 network 전에 거부되어야 한다. | Valid SSH credential shape와 `enabled=true`다. | `200`, `connector.ssh_probe_not_supported`, DNS/probe 0회. |
| CONN-TC-A027 | Public PostgreSQL strict target만 허용해야 한다. | Non-5432, private/loopback/link-local/metadata/CGNAT/reserved/mapped/mixed DNS target이다. | `422` 또는 `connector.target_not_allowed`, DB connect 0회. |
| CONN-TC-A028 | Connector test timeout 뒤 실제 blocking work가 끝날 때까지 lease를 유지해야 한다. | API 10초를 넘긴 future가 background에서 계속 실행되거나 실행 중 heartbeat가 필요하다. | Safe timeout 반환, owner-safe renewal 지속, completion 전 lease release 0회, completion 후 정확히 1회. |
| CONN-TC-A029 | Admission 장애와 capacity 부족은 fail-closed해야 한다. | Redis timeout/script error, transport peer 없음, distributed/local concurrency full이다. | `429/503`, DNS/DB connect 0회, process-local unlimited fallback 없음. |
| CONN-TC-A030 | Connector test audit는 bounded metadata만 가져야 한다. | Success/target denial/driver failure/timeout이다. | `connection.test`, organization/actor/result/reason/duration만 기록하고 target/credential/network 원문 없음. |

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
| CONN-TC-C008 | `DBConnectionForm`은 `Retry-After` cooldown을 bounded 적용해야 한다. | `429` 뒤 즉시 중복 요청하거나 비정상 header가 무제한 disable을 만든다. | `1..60`초만 재시도 비활성화하고 raw error/header를 표시하지 않는다. |
| CONN-TC-C008 | `DBSchemaSelector`는 connection id로 schema를 조회해야 한다. | `connectionId`가 있는데 `connectorApi.getSchema`가 호출되지 않는다. | 테스트 실패. |
| CONN-TC-C009 | `DBSchemaSelector`는 schema 조회 실패를 toast로 표시해야 한다. | `getSchema`가 reject된다. | `테이블 정보를 불러오는데 실패했습니다.` 표시. |
| CONN-TC-C010 | `DBSchemaSelector`는 최대 2개 테이블 제한을 적용해야 한다. | 2개 테이블이 선택된 상태에서 3번째 테이블을 선택한다. | 선택 차단, 제한 toast. |
| CONN-TC-C011 | `DBSchemaSelector`는 FK 있는 2개 테이블 선택 시 join config를 생성해야 한다. | FK metadata가 있는데 `onJoinConfigChange`에 enabled config가 전달되지 않는다. | 테스트 실패. |

## Permission Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| CONN-TC-P001 | `POST /connectors/test`는 active organization member/manager만 호출해야 한다. | 미인증 또는 active scope 밖 사용자가 probe를 시작한다. | Network 전 차단. |
| CONN-TC-P002 | 저장된 connection 상세/schema는 owner mismatch를 거부해야 한다. | 다른 사용자의 connection id로 상세 또는 schema를 요청한다. | `403`, `Not authorized`. |
| CONN-TC-P003 | 현재 user-owned `connections`는 workflow/KB 권한만으로 자동 공유되지 않아야 한다. | workflow/KB 접근 권한만 있는 사용자가 다른 사용자의 connection을 사용한다. | 테스트 실패 또는 403/404. |

## Edge Cases

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| CONN-TC-X001 | `connectorApi`는 connector create/test 실패 시 raw Axios error 객체를 console에 전달하지 않아야 한다. | Axios error의 request config/data에 DB password, SSH password, private key가 포함된다. | Operation과 status만 safe warning으로 남기고 sentinel은 UI/console에 없음. |
| CONN-TC-X002 | Secret 원문은 문서, fixture, audit metadata에 남지 않아야 한다. | DB password, SSH password, private key 원문이 문서, 테스트 fixture, audit metadata 중 하나에서 관찰된다. | 테스트 실패. |
| CONN-TC-X003 | Redis admission은 multi-replica 경쟁에서도 rate/concurrency 상한을 넘지 않아야 한다. | 마지막 slot을 병렬 acquire하거나 wrong owner release, long-running heartbeat, stale lease, clock skew를 만든다. | Redis time/atomic script 기준 정확한 winner, owner-safe renew/release와 crash-only TTL recovery. |
| CONN-TC-X004 | Admission key/member는 opaque해야 한다. | Redis key/hash/zset에 raw organization/user/network ID, host/database/username/password가 관찰된다. | HMAC identity와 random owner token만 존재. |
| CONN-TC-X005 | Strict probe는 validated IP 한 곳에 TLS `verify-full`로 한 번만 연결해야 한다. | Multiple public DNS, rebinding, first-attempt failure, plaintext/downgrade를 유도한다. | Pinned one-attempt, no fallback/retry, hostname certificate 검증. |

## Knowledge Source Connector Target Tests

이 섹션은 현재 workflow DB connector 테스트를 대체하지 않고, 목표 Knowledge source connector가 따라야 할 보안 경계를 추가로 검증한다. Knowledge source connector target case는 [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)의 egress/adapter baseline과 [ADR-0020](../../decisions/ADR-0020-knowledge-mcp-incremental-sync-boundary.md)의 MCP/API adapter boundary를 따른다.

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| CONN-KNOW-TC-001 | Knowledge source collection의 SSH tunnel, proxy, approved private network segment는 별도 connector/egress ADR 승인 전 기본 거부되어야 한다. | 승인 정책 없이 SSH tunnel 또는 private target을 사용한다. | safe reason code로 거부. |
| CONN-KNOW-TC-002 | DNS rebinding과 redirect chain은 최종 target 기준으로 검증되어야 한다. | 최초 host는 안전하지만 최종 target이 private/link-local/metadata IP이다. | safe reason code로 거부. |
| CONN-KNOW-TC-003 | Source connector의 public ACL은 organization-wide read/use로 자동 materialize되지 않아야 한다. | public ACL 하나만으로 KB `use` grant가 생성된다. | 테스트 실패. |
| CONN-KNOW-TC-004 | Slack/meeting connector는 channel을 collection으로, thread/huddle recap/canvas/bot-generated meeting summary/pinned-message group을 document-level KB로 매핑해야 한다. | huddle recap 또는 canvas가 channel-level KB 하나에 섞인다. | 테스트 실패. |
| CONN-KNOW-TC-005 | Slack/meeting artifact-level ACL이 있으면 artifact ACL과 containing channel/workspace ACL의 교집합만 source authorization provenance를 얻어야 한다. | channel membership만으로 artifact ACL 없는 requester가 통과한다. | fail-closed 또는 remediation. |
| CONN-KNOW-TC-006 | Slack/meeting DM, raw audio, raw transcript는 별도 opt-in policy 없이 수집되지 않아야 한다. | opt-in 없이 raw transcript가 ingestion 대상에 포함된다. | 테스트 실패. |
| CONN-KNOW-TC-007 | Slack/meeting ACL sync 실패나 partial ACL response는 raw channel/source title/path/url, raw principal, raw exception을 UI, audit, trace, log에 남기지 않아야 한다. | 실패 응답 또는 로그에 raw source metadata가 포함된다. | safe reason code만 남김. |
| CONN-KNOW-TC-008 | MCP/API Knowledge source connector는 allowlist operation만 호출해야 한다. | LLM이 임의 MCP tool을 선택하거나 adapter가 allowlist 밖 operation, raw source data direct fetch, prompt/completion 기반 source query를 실행한다. | 요청 거부, safe reason code, raw tool response 비노출. |
| CONN-KNOW-TC-009 | Private source-managed KB retrieval은 runtime authorization primitive가 없으면 fail-closed되어야 한다. | Source connector가 `check_access_batch`와 bounded `check_access` fallback을 모두 제공하지 않는데 retrieval 후보가 된다. | 후보 제외 또는 remediation, raw source metadata 비노출. |
| CONN-KNOW-TC-010 | Runtime authorization fallback은 bounded concurrency와 timeout을 적용해야 한다. | Batch 미지원 source에서 candidate 수만큼 unbounded `check_access` 호출을 실행하거나 aggregate timeout 없이 대기한다. | safe partial/fail-closed, rate-limit-safe retry policy. |
| CONN-KNOW-TC-011 | Conversation Memory authorization result는 principal-neutral stable revision contract를 제공해야 한다. | Batch result에 decision, principal kind, authorization decision/resource/policy revision 또는 evaluated_at이 누락되거나 source ACL revision이 decision revision에 반영되지 않는다. | 해당 private/sensitive dependency를 `unknown`으로 fail-closed. |
| CONN-KNOW-TC-012 | Partial batch result를 allow로 채우지 않아야 한다. | 요청 item 중 일부만 connector 응답에 존재한다. | 누락 item은 unknown, raw source identity 비노출. |
| CONN-KNOW-TC-013 | Bot/webhook/app installation visibility는 requester authorization으로 쓰면 안 된다. | Bot이 볼 수 있는 source item이라는 이유만으로 private retrieval evidence에 포함한다. | source subject mapping/runtime authorization gate를 통과하지 못하면 fail-closed. |
| CONN-KNOW-TC-014 | File/page artifact connector는 content safety gate 전 raw artifact를 trusted normalized content로 취급하면 안 된다. | Macro-enabled document, embedded script/object, executable child file, unsupported content type 중 하나가 redacted canonical text/chunk/embedding으로 진행된다. | fail-closed 또는 remediation, safe reason code만 저장. |
| CONN-KNOW-TC-015 | Archive connector ingestion은 expansion cap과 nested content policy를 적용해야 한다. | Zip bomb, nested archive cap 초과, archive 내부 executable/script/macro-enabled file이 indexing-visible artifact가 된다. | ingestion 제외 또는 quarantine/remediation. |
| CONN-KNOW-TC-016 | Parser/scanner failure는 raw content leakage 없이 닫혀야 한다. | Parser exception, scan timeout, scan unknown/error가 raw bytes, active marker, parser raw stack detail을 response/log/audit/trace/dead-letter에 남긴다. | safe reason code와 retryability/remediation state만 남김. |
| CONN-KNOW-TC-017 | Pre-normalization raw payload는 connector 실패 경로에 남지 않아야 한다. | Normalization 전 예외가 발생했을 때 raw payload가 connector debug/error log, retry/dead-letter payload, audit, trace 중 하나에 남는다. | 테스트 실패, safe reason code만 저장. |
| CONN-KNOW-TC-018 | Live-linked source-side search는 requester-scoped 또는 opaque-ref-only여야 한다. | Broad service-account search가 authorization 전 title, snippet, count, score를 반환한다. | 검색 후보 제외 또는 metadata suppression, side-channel 없음. |
| CONN-KNOW-TC-019 | Connector result는 server-derived RuntimeDataDependencyEnvelope를 제공해야 한다. | Content에 영향을 준 connector/source item version이 누락되거나 client/node가 canonical dependency를 발급한다. | Private/sensitive Memory write fail-closed. |
| CONN-KNOW-TC-020 | Relevant source mutation은 authorization decision revision을 변경해야 한다. | Source ACL/mapping/policy/lifecycle/public exposure 변경 뒤 old revision이 allow로 재사용된다. | Stale lease/cache 거부. |
| CONN-KNOW-TC-021 | Anonymous source authorization은 synthetic subject를 만들지 않아야 한다. | Bot owner/app installation/Conversation grant를 requester subject로 사용한다. | Explicit public exposure만 평가, 그 외 fail-closed. |
