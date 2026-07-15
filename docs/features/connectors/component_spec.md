# Connectors Component Spec

Status: Draft
Verified Against: feature/mba-246 @ b299e2fa2eecbc8320d38440ff08d34963f5fba6

## Screens

- 독립 Connectors 관리 화면: 현재 없음.
- DB source 추가 흐름: `apps/client/app/features/knowledge/components/create-knowledge-modal/index.tsx`
- Knowledge document DB source 설정 화면: `apps/client/app/dashboard/knowledge/[id]/document/[documentId]/page.tsx`

Connectors UI는 현재 Knowledge 화면 내부의 DB source 설정 부분으로 제공된다. Organization-wide connector inventory, connection 공유/권한 관리, connector health/remediation 전용 화면은 아직 구현되지 않았다.

## Target Knowledge Source Connector Boundary

목표 Knowledge Source Connector는 현재 workflow DB connector UI/API를 그대로 확장한 것이 아니라 [ADR-0020](../../decisions/ADR-0020-knowledge-mcp-incremental-sync-boundary.md)의 server-side allowlist adapter 경계를 따른다. MCP/API source도 LLM 자유 tool-use surface가 아니며, source listing, changed item listing, content fetch, ACL/tombstone listing, capture event normalization, runtime authorization primitive처럼 승인된 operation만 호출할 수 있다.

Private source-managed retrieval에 쓰이는 connector는 `check_access_batch(subject_ref, source_item_refs[])`를 우선 제공해야 한다. Batch 미지원 source는 bounded single `check_access(subject_ref, source_item_ref)` fallback을 제공할 수 있지만, runtime authorization primitive가 없으면 Knowledge retrieval 후보가 아니라 remediation 대상이다. Connector component와 UI는 raw source payload, raw principal, raw source URL/path/title, raw tool error를 표시하거나 durable log/audit/trace에 남기지 않고 safe reason code와 remediation state만 전달한다.

File/page artifact connector는 egress guard 이후에도 artifact content를 trusted로 취급하지 않는다. Target component는 content safety gate와 parser isolation worker를 거쳐 macro/script/embedded object/executable, archive bomb, unsupported type, scan timeout/unknown을 fail-closed 또는 remediation으로 전달해야 한다.

## Components

### `connectorApi`

- 출처: `apps/client/app/features/knowledge/api/connectorApi.ts`
- 책임: `/connectors` API 호출 payload를 클라이언트 `DBConfig`에서 Gateway schema로 변환한다.
- 제공 호출:
  - `createConnector(config)`: `POST /connectors`
  - `testConnection(config)`: `POST /connectors/test`
  - `getSchema(connectionId)`: `GET /connectors/{connection_id}/schema`
  - `getConnectionDetails(connectionId)`: `GET /connectors/{connection_id}`
- 경계:
  - React 상태를 소유하지 않는다.
  - Secret redaction을 직접 수행하지 않는다. Secret 비노출은 Gateway 응답 계약에 의존한다.
  - API 오류는 status와 allowlist reason code만 `{ success: false, message, status?, reasonCode? }`로 정규화한다. Raw Axios error, request config와 backend diagnostic은 console/UI에 전달하지 않는다.

### `DBConnectionForm`

- 출처: `apps/client/app/features/knowledge/components/create-knowledge-modal/DBConnectionForm.tsx`
- 책임: PostgreSQL DB 연결 정보와 선택적 SSH tunnel 정보를 입력하고 연결 테스트를 실행한다.
- Strict test는 기본적으로 public PostgreSQL과 deployment-managed port allowlist만 지원한다. Development demo는 서버가 설정한 exact local hostname+port와 전용 CA에 한해 동일 UI를 사용한다. UI 기본값은 `5432`이고 allowlist 밖 port는 safe target-policy 실패로 표시한다. SSH 입력은 create/schema compatibility를 위해 유지하지만 `ssh.enabled=true` test는 safe 미지원 결과를 표시한다.
- 소비자:
  - `CreateKnowledgeModal`
  - Knowledge document DB source 설정 화면의 connection edit flow
- 렌더링: 연결 이름, DB 타입, DB host/port/database/username/password, 선택적 SSH tunnel 설정, SSH 인증 방식(`password`, `key`), private key file input, `연결 테스트` 버튼, 성공/실패 상태 메시지를 표시한다.
- 현재 기본값: `initialConfig`가 없으면 입력은 비어 있고 DB type은 `postgres`, port는 `5432`, SSH는 비활성이다. Host placeholder는 public hostname 예시이며 local target을 기본 허용으로 오해하게 하는 loopback IP를 제시하지 않는다.
- 경계:
  - 실제 저장은 직접 하지 않고 부모가 전달한 `onTestConnection`과 `onChange`에 위임한다.
  - private key file은 브라우저에서 text로 읽어 local state에 넣는다.
  - 입력값 secret은 화면 state에 존재하므로 로그/토스트/문서에 원문을 남기면 안 된다.

### `CreateKnowledgeModal` DB Source Flow

- 출처: `apps/client/app/features/knowledge/components/create-knowledge-modal/index.tsx`
- 책임: Knowledge Base에 DB source를 추가하는 과정에서 DB 연결 테스트와 connection 생성 요청을 조율한다.
- 동작:
  - source type이 `DB`이면 `DBConnectionForm`을 렌더링한다.
  - `handleTestDBConnection`은 `connectorApi.testConnection(config)`를 호출한다.
  - 테스트 성공 시 Gateway message 또는 `DB 연결 테스트 성공!` toast를 표시한다.
  - 테스트 실패 시 Gateway message 또는 `DB 연결에 실패했습니다.` toast를 표시한다.
  - DB source 제출 시 필수 DB 입력이 없으면 alert로 중단한다.
  - DB source 제출 시 `connectorApi.createConnector(dbConfig)`를 호출한다.
  - connection 생성 성공 시 반환된 `id`를 Knowledge source 생성 payload의 connection id로 사용한다.
  - connection 생성 실패 시 toast를 표시하고 Knowledge source 생성 흐름을 중단한다.
- 경계:
  - Knowledge Base 생성, 문서/source lifecycle, ingestion 실행은 Knowledge feature 책임이다.
  - Connector form이 성공했다고 해서 KB use permission이 승인된 것은 아니다.

### `DBSchemaSelector`

- 출처: `apps/client/app/features/knowledge/components/document-settings/DBSchemaSelector.tsx`
- 책임: 저장된 connection id로 DB schema를 불러오고, ingestion에 사용할 테이블/컬럼/민감 컬럼/alias/JOIN 구성을 선택한다.
- 렌더링: loading/empty 상태, 테이블 검색, 자동 청킹 checkbox, 선택적 `DB 연결 수정` 버튼, 테이블/컬럼 선택, 민감 컬럼 표시, alias 입력, FK 기반 JOIN 안내 또는 경고를 표시한다.
- 제한:
  - 한 번에 최대 2개 테이블 선택을 허용한다.
  - 2개 테이블 선택 시 FK 관계가 없으면 연결 불가 안내를 표시한다.
  - schema 조회 실패 시 `테이블 정보를 불러오는데 실패했습니다.` toast를 표시한다.
- 경계:
  - 실제 schema 조회 permission은 Gateway owner check에 의존한다.
  - 민감 컬럼 선택은 ingestion metadata/처리 정책에 넘길 UI 입력이며, connector API의 secret redaction을 대체하지 않는다.

### `DbSourceViewer`

- 출처: `apps/client/app/features/knowledge/components/ingestion-views/DbSourceViewer.tsx`
- 책임: Knowledge DB source 설정에서 DB schema selector를 표시하고 connection edit 진입점을 연결한다.
- 경계:
  - DB source 문서 처리와 chunk 생성은 Knowledge ingestion processor 책임이다.

## States

### `DBConnectionForm`

- `config`, `loading`, `testStatus`를 로컬 state로 관리한다.
- `initialConfig`가 있으면 클라이언트 `DBConfig`와 필드명이 일치하는 값만 편집 시작값으로 사용한다. 현재 detail 응답의 `connection_name`과 `ssh.auth_type`은 `connectionName`/`ssh.authType`으로 변환되지 않으므로 form fallback이 사용될 수 있다.
- DB/SSH 입력 변경 시 `config`를 갱신하고 부모 `onChange(newConfig)`를 호출하며 `testStatus`를 `idle`로 되돌린다.
- `ssh.enabled`와 `ssh.authType`에 따라 SSH password input 또는 private key file input을 표시한다.
- `handleTest`는 부모 `onTestConnection(config)` 결과에 따라 `연결 성공!` 또는 `연결 실패` 상태를 표시하고, pending 중 버튼을 disabled 처리한다.

### `CreateKnowledgeModal` DB Flow

- 연결 테스트는 `connectorApi.testConnection`의 safe result에 따라 success/error toast를 표시하고 `success`, optional `retryAfter` 결과를 폼에 반환한다.
- `401/404`는 인증/organization context 오류, `429`는 잠시 후 재시도, `503`은 test service 일시 불가의 고정 메시지로 표시한다. Backend raw message는 표시하지 않는다.
- DB source 제출 전 `host`, `port`, `database`, `username`, `password`를 검증하고 누락 시 alert로 중단한다.
- `connectorApi.createConnector`가 success와 id를 반환하면 Knowledge source payload에 connection id를 포함한다.
- connection 생성이 실패하거나 예외가 발생하면 toast를 표시하고 Knowledge source 제출을 중단한다.

### `DBSchemaSelector`

- `connectionId`가 있으면 mount 또는 id 변경 시 schema를 조회하고 loading/empty/error 상태를 표시한다.
- 조회 성공 시 `tables = res.tables || []`로 설정하고 검색어로 table list를 필터링한다.
- table/column 선택은 alias 기본값을 함께 관리하며, 민감 컬럼 toggle은 부모 state로 전달한다.
- 선택 테이블이 2개이면 FK 관계를 검사해 join config를 부모에 전달하거나 FK 없음 경고를 표시한다.

## Interactions

### Connection Test

1. 사용자가 `DBConnectionForm`에서 연결 정보를 입력한다.
2. 사용자가 `연결 테스트`를 클릭한다.
3. `DBConnectionForm`은 부모 `onTestConnection(config)`를 호출한다.
4. `CreateKnowledgeModal`은 `connectorApi.testConnection(config)`를 호출한다.
5. `connectorApi`는 클라이언트 `DBConfig`를 Gateway strict `ConnectorTestRequest`로 매핑해 `POST /connectors/test`를 호출한다.
6. 성공하면 success toast와 `연결 성공!` 상태가 표시된다.
7. 실패하면 error toast와 `연결 실패` 상태가 표시된다.
8. Pending 중 중복 클릭을 막고, `429 Retry-After`가 있으면 bounded cooldown 동안 재시도를 비활성화한다.

### Local/Docker TLS Demo

Local demo는 일반 stack과 분리된 `connector-demo` Compose profile을 명시적으로 시작한 경우에만 사용한다.

1. Host-run은 `docker compose -f dev/docker-compose.yml --profile connector-demo up -d --build --wait connector-test-redis connector-test-tls-init connector-test-postgres`로 격리된 Redis와 TLS PostgreSQL을 시작하고 health 완료를 기다린다.
2. Docker 통합 모드는 `docker compose -f docker/docker-compose.yml -f docker/docker-compose.connector-demo.yml --profile connector-demo up -d --build --wait`를 사용한다.
3. `scripts/copy_connector_demo_password.ps1 -Mode dev` 또는 `-Mode docker`를 실행해 생성 credential을 stdout 없이 clipboard에 복사한다.
4. Host-run Gateway에서는 `localhost`, port `55432`; Docker Gateway에서는 `connector-test-postgres`, port `5432`를 입력한다. Database는 `connector_demo`, username은 `connector_demo_user`를 사용한다.
5. Gateway가 사용하는 exact-target/CA 환경 설정은 profile 또는 `dev/.env.example`을 따른다. Production 설정으로 복사하지 않는다.

Runtime-generated 공개 CA는 git-ignore된 `local/connector-test-tls/<mode>/ca.crt`에 export되지만 CA signing key, server key와 credential은 private named volume을 벗어나지 않는다. 공개 CA 파일도 source artifact로 커밋하지 않는다.

### Connection Create During DB Source Submit

1. 사용자가 DB source 정보를 입력하고 Knowledge source 추가를 제출한다.
2. `CreateKnowledgeModal`은 DB 필수 입력을 확인한다.
3. `connectorApi.createConnector(dbConfig)`를 호출한다.
4. Gateway는 연결을 재테스트하고 secret을 암호화 저장한다.
5. 성공하면 반환된 connection id가 Knowledge source 생성 payload에 포함된다.
6. 실패하면 toast를 표시하고 Knowledge source 생성이 중단된다.

### Schema Selection

1. `DBSchemaSelector`는 `connectionId`를 받으면 `connectorApi.getSchema(connectionId)`를 호출한다.
2. Gateway는 owner check 후 저장된 secret을 복호화해 schema를 조회한다.
3. UI는 table/column/FK 정보를 표시한다.
4. 사용자는 최대 2개 테이블과 필요한 컬럼을 선택한다.
5. 선택한 컬럼 alias, 민감 컬럼, 자동 청킹, JOIN config는 부모 Knowledge 설정 state로 전달된다.

### Connection Edit

1. document settings 화면에서 사용자가 `DB 연결 수정`을 클릭한다.
2. 화면은 `connectorApi.getConnectionDetails(connectionId)`로 secret 없는 connection detail을 조회한다.
3. `DBConnectionForm`이 detail 응답을 `initialConfig`로 직접 받아 열린다. 별도 normalization이 없으므로 `type`, `host`, `port`, `database`, `username`, `ssh.enabled`, `ssh.host`, `ssh.port`, `ssh.username`처럼 필드명이 맞는 값만 복원된다.
4. detail 응답에는 DB password, SSH password, SSH private key가 없고, form은 secret 입력값에 현재 fallback을 사용한다. 재연결 시 필요한 secret은 사용자가 다시 입력해야 한다.
5. document settings 화면의 `연결 테스트`는 `handleConnectionRequest`를 통해 새 connection 생성을 수행하고, 반환된 id로 상위 DB config를 재연결한다.
6. 현재 구현에는 별도 update endpoint가 없으므로 기존 connection row의 in-place update로 해석하지 않는다.

## Accessibility

### `DBConnectionForm`

- 기본 `input`, `select`, `button` 요소를 사용하고, `연결 테스트` 버튼은 loading 중 disabled 상태를 사용한다.
- 현재 label 요소는 보이는 텍스트를 제공하지만 `htmlFor`와 input `id`가 연결되어 있지 않다.
- 현재 성공/실패 상태 메시지는 보이는 텍스트와 icon으로 표시되지만 `role="status"`, `role="alert"`, `aria-live`를 설정하지 않는다.
- private key file input은 숨겨진 input과 label 클릭 영역으로 동작한다.

### `DBSchemaSelector`

- 검색 input, 자동 청킹 checkbox, DB 연결 수정 button은 기본 form/button 요소를 사용한다.
- icon-only에 가까운 control 일부는 `title` 또는 보이는 텍스트를 제공하지만, 모든 icon control이 명시적 accessible name을 보장한다고 보기는 어렵다.
- FK/JOIN 상태는 텍스트 안내를 함께 표시한다.
- schema 조회 실패는 toast로만 표시되며, selector 내부의 접근 가능한 오류 영역은 없다.
