# ADR-0049: Connector 연결 테스트 보안 경계

Status: Accepted
Related ADRs: [ADR-0008](ADR-0008-audit-action-naming-standard.md), [ADR-0009](ADR-0009-active-organization-header-context.md), [ADR-0010](ADR-0010-resource-access-403-404-policy.md), [ADR-0022](ADR-0022-incremental-hexagonal-architecture-adoption.md)

## 배경

`POST /api/v1/connectors/test`는 DB/SSH credential을 저장하지 않고 외부 연결을 확인하는 helper다. 기존 구현은 인증·organization scope·분산 admission 없이 workflow compatibility용 PostgreSQL connector를 호출하므로 외부 사용자가 Gateway를 network oracle 또는 자원 고갈 경로로 사용할 수 있다. Direct PostgreSQL adapter에 public-address 검증이 일부 존재하지만 endpoint 인증, multi-replica rate/concurrency, request ingress, TLS, timeout과 오류 비노출을 함께 보장하지 않는다.

현재 `connections`는 `user_id` 소유이고 `organization_id`가 없다. 따라서 urgent test hardening에 connection ownership/RBAC migration까지 섞지 않는다.

## 결정

1. 연결 테스트는 로그인 사용자와 `X-Organization-Id`의 active organization membership을 요구한다. Active member/manager는 테스트할 수 있지만 이 capability는 connection create/use/manage 권한이 아니다.
2. 인증과 organization scope를 통과한 요청만 body를 읽는다. Gateway는 actual JSON body 32 KiB, 전체 receive 5초를 적용하고 repository edge는 exact route에 32 KiB, 5초 idle receive와 request-target log 억제를 적용한다.
3. 구조 검증을 통과한 요청은 Redis의 단일 atomic acquire에서 user/organization/network fixed-window rate와 user/organization/global concurrency lease를 함께 판정한다. Redis 장애 또는 transport peer 부재는 network 전에 fail-closed한다.
4. Admission identity는 dedicated key와 scope domain tag로 HMAC-SHA256 처리한다. Redis에는 digest와 최소 128-bit owner token만 저장한다. 실행 중 owner는 Redis time 기준 heartbeat로 lease를 연장하고, 완료 시 정확한 owner member만 제거한다. Process crash 때만 TTL로 회수한다.
5. V1 strict probe의 기본·production 경로는 public address로만 resolve되는 PostgreSQL host와 deployment-managed port allowlist만 허용한다. Local development는 `NODE_ENV=development`일 때 서버가 설정한 최대 4개의 exact canonical `host:port`만 별도 trusted-local target으로 허용할 수 있다. Wildcard, CIDR, suffix, raw IP target과 request-controlled override는 허용하지 않는다. Exact local target의 모든 DNS 결과는 RFC1918, IPv6 ULA 또는 loopback이어야 하며 public/private mixed result는 거부한다. Host-run `localhost`가 IPv4/IPv6 loopback을 함께 반환할 때는 loopback-only bind와 일치하도록 검증된 IPv4를 결정적으로 우선한다. 모든 성공 경로는 실제 libpq 연결을 검증된 한 IP에 고정하고 다른 주소로 재시도하지 않는다.
6. Public target은 시스템 CA bundle, exact local target은 서버가 설정한 `CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE`을 사용해 TLS `verify-full`을 적용한다. Local target과 CA file은 함께 설정해야 하며 CA file 부재는 startup 또는 DNS 전에 fail-closed한다. 요청자는 CA나 SSL mode를 지정할 수 없다. 요청당 connection attempt는 한 번이고, query는 read-only `SELECT 1`, result는 one-row scalar로 제한한다. Connect 5초, statement 3초, API 10초, lease 30초를 적용한다.
7. SSH-enabled test는 host-key와 approved private-network 정책이 도입되기 전까지 `connector.ssh_probe_not_supported`로 network 전에 거부한다. 기존 persisted connector create/schema compatibility를 이 결정으로 제거하지 않는다.
8. Expected target/connection 실패는 기존 `200 {success:false}` UX를 유지하되 server-owned static message와 allowlist reason code만 반환한다. 인증, ingress, admission과 schema 오류는 표준 HTTP error envelope을 사용한다.
9. Admission 이후 결과는 `connection.test` action으로 best-effort audit한다. Organization, actor, result, reason code와 coarse duration만 기록하며 host/IP/port/database/username/credential, raw network identity와 exception text를 기록하지 않는다. Post-probe audit 실패는 network probe를 재시도하지 않는다.
10. Endpoint는 auth/context, bounded ingress, use-case 호출과 HTTP mapping만 담당한다. Application은 framework-independent command/result/error/port를 소유하고 Redis, PostgreSQL과 audit 구현은 adapter/composition에서 조립한다.
11. Local/Docker 연결 시연은 일반 플랫폼 DB와 분리된 explicit `connector-demo` profile을 사용한다. Init service가 실행 시 CA와 server certificate를 만들고, CA signing key·server key·생성된 demo credential은 private named volume에만 둔다. 공개 CA certificate만 git-ignore된 local bind directory로 내보내 Gateway에 read-only mount한다. Server certificate SAN은 `connector-test-postgres`와 `localhost`로 제한한다. Production은 trusted-local target 또는 local CA 설정이 있으면 시작하지 않는다.

초기 admission 기본값은 다음과 같다.

| Scope | Limit |
| --- | --- |
| User rate | aligned 60초 window당 5 |
| Organization rate | aligned 60초 window당 30 |
| Network rate | aligned 60초 window당 20 |
| User concurrency | 1 |
| Organization concurrency | 4 |
| Global concurrency | 16 |

제한값은 positive bounded environment setting으로 조정할 수 있지만 `0`, non-finite 값, 과도한 상한이나 누락으로 production 경계를 비활성화할 수 없다. Rate window/user/organization/network rate 상한은 각각 `300/100/1000/1000`, concurrency 상한은 `128`, connect/statement/API/lease timeout 상한은 각각 `10/10/30/120`초다. Timeout 간 `connect < API`, `statement < API < lease` 관계도 유지한다. `CONNECTOR_TEST_ALLOWED_PORTS`는 중복 없는 `1..65535` 정수 1~16개만 허용하고 invalid 설정은 Gateway startup을 실패시킨다. Local profile의 각 target port도 이 allowlist에 포함되어야 한다.

Production admission HMAC key가 없거나 32 byte보다 짧으면 Gateway는 시작하지 않는다. Helm 배포는 별도 `secrets.connectorTestAdmissionHmacKey`를 32 byte 이상으로 제공해야 하며 auth/session key를 재사용하지 않는다.

## 검토한 대안

### 로그인만 요구

Organization attribution과 tenant rate scope가 없어 채택하지 않았다.

### Manager 또는 App 생성 권한만 허용

Knowledge DB source 작성 흐름과 다른 capability를 재사용해 권한 의미를 왜곡하므로 채택하지 않았다.

### Process-local limiter 또는 Redis 장애 시 local fallback

Multi-replica 전체 상한을 보장하지 못하고 장애를 우회 조건으로 만들기 때문에 채택하지 않았다.

### 기존 SSH tunnel 유지

Public bastion 뒤 private target, SSH host-key와 remote target 승인이 정의되지 않아 채택하지 않았다.

### 개발·데모에서 모든 포트 허용

환경 이름만으로 outbound network oracle 경계를 제거할 수 있어 채택하지 않았다. 개발·데모도 설치자가 관리하는 정확한 port allowlist를 사용한다.

### Local private network 전체 또는 CIDR 허용

편의를 위해 arbitrary private-network oracle을 다시 열고 DNS 변경 시 승인 범위가 확장되므로 채택하지 않았다. 개발 환경의 exact hostname과 port, 전용 CA를 함께 고정한다.

### 모든 connector outbound path를 한 번에 변경

Connection ownership, create/schema/runtime compatibility와 Knowledge ingestion까지 범위가 확대되므로 unauthenticated test surface를 우선 닫는다.

## 영향

- `/connectors/test` caller는 로그인과 active organization header가 필요하다.
- Deployment allowlist 밖 DB port와 SSH-enabled test는 V1에서 실패한다.
- Redis가 connector test의 필수 security dependency가 된다.
- Helm 배포자는 `secrets.connectorTestAdmissionHmacKey`를 32 byte 이상의 별도 secret으로 provisioning해야 한다.
- Helm 배포자는 `connectorTest.allowedPorts`로 1~16개의 정확한 허용 포트를 정한다. 기본·production은 `5432`다.
- Local demo는 explicit profile에서만 생성되며 일반 `dev`/Docker 기동에는 자동 포함되지 않는다.
- Local exact-target profile은 `NODE_ENV=development`에서만 유효하고 production 설정은 startup fail-fast한다.
- Connection row schema와 create/detail/schema owner 계약은 변경하지 않는다.
- Client는 raw Axios/backend detail 대신 canonical status/reason만 표시한다.
- DB migration은 없다.

## 잔여 위험과 후속 검토

- Authenticated `POST /connectors`의 저장 전 probe와 schema/runtime SSH path는 별도 hardening이 필요하다.
- 운영 private network/SSH를 다시 허용하려면 host-key lifecycle, organization-approved network segment, target pinning과 audit 정책을 새 ADR로 승인해야 한다. Local exact-target profile은 운영 private-network 권한 primitive가 아니다.
- Trusted proxy가 실제 client transport peer를 복원하지 않으면 network limit은 proxy 단위로 보수적으로 적용될 수 있다.
- libpq/TLS parser의 protocol message bounds는 dependency 변경 때 재검토한다. 실질적으로 unbounded process-memory surface가 확인되면 probe를 memory-bounded isolated worker로 이동한다.
