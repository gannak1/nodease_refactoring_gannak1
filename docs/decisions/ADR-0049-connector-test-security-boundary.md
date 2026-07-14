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
5. V1 strict probe는 public address로만 resolve되는 PostgreSQL host와 port `5432`만 허용한다. 모든 DNS 결과를 검증하고 실제 libpq 연결은 검증된 한 IP에 고정한다.
6. Public credential 전송은 시스템 CA bundle의 실제 파일 경로를 명시한 TLS `verify-full`을 사용한다. CA bundle이 없으면 DNS 전에 fail-closed한다. 요청당 connection attempt는 한 번이고, query는 read-only `SELECT 1`, result는 one-row scalar로 제한한다. Connect 5초, statement 3초, API 10초, lease 30초를 적용한다.
7. SSH-enabled test는 host-key와 approved private-network 정책이 도입되기 전까지 `connector.ssh_probe_not_supported`로 network 전에 거부한다. 기존 persisted connector create/schema compatibility를 이 결정으로 제거하지 않는다.
8. Expected target/connection 실패는 기존 `200 {success:false}` UX를 유지하되 server-owned static message와 allowlist reason code만 반환한다. 인증, ingress, admission과 schema 오류는 표준 HTTP error envelope을 사용한다.
9. Admission 이후 결과는 `connection.test` action으로 best-effort audit한다. Organization, actor, result, reason code와 coarse duration만 기록하며 host/IP/port/database/username/credential, raw network identity와 exception text를 기록하지 않는다. Post-probe audit 실패는 network probe를 재시도하지 않는다.
10. Endpoint는 auth/context, bounded ingress, use-case 호출과 HTTP mapping만 담당한다. Application은 framework-independent command/result/error/port를 소유하고 Redis, PostgreSQL과 audit 구현은 adapter/composition에서 조립한다.

초기 admission 기본값은 다음과 같다.

| Scope | Limit |
| --- | --- |
| User rate | aligned 60초 window당 5 |
| Organization rate | aligned 60초 window당 30 |
| Network rate | aligned 60초 window당 20 |
| User concurrency | 1 |
| Organization concurrency | 4 |
| Global concurrency | 16 |

제한값은 positive bounded environment setting으로 조정할 수 있지만 `0`, non-finite 값, 과도한 상한이나 누락으로 production 경계를 비활성화할 수 없다. Rate window/user/organization/network rate 상한은 각각 `300/100/1000/1000`, concurrency 상한은 `128`, connect/statement/API/lease timeout 상한은 각각 `10/10/30/120`초다. Timeout 간 `connect < API`, `statement < API < lease` 관계도 유지한다.

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

### 모든 connector outbound path를 한 번에 변경

Connection ownership, create/schema/runtime compatibility와 Knowledge ingestion까지 범위가 확대되므로 unauthenticated test surface를 우선 닫는다.

## 영향

- `/connectors/test` caller는 로그인과 active organization header가 필요하다.
- Custom DB port와 SSH-enabled test는 V1에서 실패한다.
- Redis가 connector test의 필수 security dependency가 된다.
- Helm 배포자는 `secrets.connectorTestAdmissionHmacKey`를 32 byte 이상의 별도 secret으로 provisioning해야 한다.
- Connection row schema와 create/detail/schema owner 계약은 변경하지 않는다.
- Client는 raw Axios/backend detail 대신 canonical status/reason만 표시한다.
- DB migration은 없다.

## 잔여 위험과 후속 검토

- Authenticated `POST /connectors`의 저장 전 probe와 schema/runtime SSH path는 별도 hardening이 필요하다.
- Private network/SSH를 다시 허용하려면 host-key lifecycle, approved network segment, target pinning과 audit 정책을 새 ADR로 승인해야 한다.
- Trusted proxy가 실제 client transport peer를 복원하지 않으면 network limit은 proxy 단위로 보수적으로 적용될 수 있다.
- libpq/TLS parser의 protocol message bounds는 dependency 변경 때 재검토한다. 실질적으로 unbounded process-memory surface가 확인되면 probe를 memory-bounded isolated worker로 이동한다.
