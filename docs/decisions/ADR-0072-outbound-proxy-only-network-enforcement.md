# ADR-0072: Outbound proxy-only 네트워크 강제 경계

Status: Accepted

## Context

ADR-0067은 LLM, Knowledge와 Workflow 외부 HTTP 호출을 server-owned operation profile과 guarded transport에 연결했다. 이 계층은 URL, method, redirect, 크기, timeout과 목적지 주소를 요청 전에 검증하지만, 같은 workload 안에서 새 HTTP client나 SDK가 직접 socket을 열면 애플리케이션 guard를 우회할 수 있다.

기존 Docker Compose의 Squid는 ambient proxy 환경변수와 외부 연결 가능한 공용 bridge에 의존했다. Provider-neutral Helm에는 Squid workload가 없었고 Workflow Worker NetworkPolicy는 public 80/443 direct egress를 허용했다. 표준 Kubernetes NetworkPolicy는 여러 policy의 allow 규칙이 합쳐지며 CNI가 실제로 집행해야 하므로 YAML 존재만으로 proxy-only를 보장할 수 없다.

이 결정은 애플리케이션 의미 정책을 Squid로 옮기려는 것이 아니다. Application guard와 네트워크 강제를 함께 적용해 하나의 계층이 우회되어도 다른 계층이 외부 HTTP/HTTPS direct dial을 막도록 한다.

## Options considered

### 1. 애플리케이션 guard만 유지한다

- 장점: 배포 변경이 작고 destination IP를 고정하는 현재 transport를 유지한다.
- 단점: ad hoc client와 SDK가 공통 factory를 우회하면 물리적인 차단 경계가 없다.

### 2. Squid와 NetworkPolicy만 사용한다

- 장점: workload의 direct public socket을 제한할 수 있다.
- 단점: SSL bump를 사용하지 않는 Squid는 HTTPS path, header, body, actor와 operation 권한을 판단할 수 없다. NetworkPolicy만으로 DNS rebinding과 provider별 payload 계약도 해결할 수 없다.

### 3. Application guard, explicit proxy transport와 proxy-only network를 결합한다

- 장점: 의미 정책과 물리 경계를 분리하면서 우회와 장애 시 direct fallback을 차단한다.
- 단점: proxy HA, CNI 검증, rollout과 운영 책임이 추가된다.

## Decision

Option 3을 채택한다.

1. Application guard는 operation, method, origin, redirect, timeout, request/response cap과 safe failure의 유일한 의미 정책 권위다. Squid와 NetworkPolicy는 이 판단을 대체하지 않는다.
2. 외부 HTTP/HTTPS transport는 server-owned `proxy_guarded_external` mode와 exact internal proxy endpoint를 사용한다. `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`는 정책 입력으로 사용하지 않으며 HTTP client는 `trust_env=false`와 retry 0을 사용한다.
3. Production Gateway, Workflow Worker와 Knowledge Worker는 proxy mode/revision/endpoint가 없거나 잘못되면 작업 수락 전에 fail-closed한다. Proxy 연결 또는 tunnel 실패 뒤 direct transport로 fallback하지 않는다.
4. Direct-pinned mode는 local/test와 exact internal 또는 별도 non-HTTP adapter에만 남는다. Production public HTTP workload는 direct mode로 시작할 수 없다.
5. Squid는 두 내부 listener를 제공한다.
   - `3128`: Gateway와 Knowledge Worker의 HTTPS CONNECT 443 전용
   - `3129`: Workflow Worker의 HTTPS CONNECT 443과 Generic HTTP 호환 public 80
   Source/listener 분리는 NetworkPolicy와 Squid ACL을 함께 사용한다. 이는 network-authorized source이며 cryptographic workload identity가 아니다.
6. Squid는 SSL bump/MITM을 사용하지 않는다. 원래 hostname SNI와 certificate 검증은 workload와 origin 사이의 CONNECT tunnel에서 유지한다.
7. Squid는 private, loopback, link-local, metadata, reserved와 multicast IPv4/IPv6 destination을 거부한다. Application과 Squid가 각각 DNS를 검증하며 CNAME 또는 A/AAAA 결과 중 하나라도 unsafe이면 전체 hostname을 거부한다.
8. Squid는 response cache와 request access log를 비활성화한다. Raw URL/query/header/body, credential, resolved IP와 provider exception은 proxy, application log, trace, audit와 metric label에 저장하지 않는다. 운영 관측은 readiness, replica, resource와 safe reason bucket으로 제한한다.
9. Docker Compose는 application/internal dependency network를 `internal`로 만들고, Gateway·Knowledge·Workflow는 각각 proxy client network만 추가로 사용한다. Squid만 별도 egress-capable network에 연결하며 host에 proxy port를 publish하지 않는다.
10. Provider-neutral Helm은 immutable Squid image digest, internal ClusterIP Service, 최소 2개 production replica, `maxUnavailable: 0`, PDB, non-root/read-only/capability-drop와 resource bound를 제공한다.
11. Helm의 target workload egress는 DNS, Squid와 필요한 exact internal/dedicated protocol만 허용한다. Logger, Beat와 Frontend는 public proxy 권한 없이 각각 DB/Redis 또는 internal Gateway만 허용한다. Sandbox는 일반 Squid source가 아니며 기존 격리를 완화하지 않는다.
12. PostgreSQL, Redis, Sandbox control, IMAP과 Connector DB/SSH는 Squid 대상이 아니다. 각 protocol의 기존 exact service/port, pinned transport와 Accepted ADR을 유지한다.
13. Rollout은 `nodease.io/egress-mode=proxy-v1` revision label을 사용한다. `canary` phase의 strict workload policy는 이 label이 있는 새 pod만 선택한다. `final` phase는 revision label을 selector에서 제거해 해당 component의 모든 pod를 선택하며, old pod가 모두 drain된 뒤에만 적용한다. Pod annotation에 phase를 기록한다.
14. Kubernetes 완료 판정은 정적 render만으로 하지 않는다. PR CI는 pinned kind/Kubernetes와 Calico IPv4에서 target direct HTTPS 실패, authorized proxy 성공과 unauthorized source 실패를 실행한다. Dual-stack과 실제 배포 CNI는 release 환경에서 같은 positive/negative probe를 통과해야 하며, 통과하지 않은 CNI는 지원 대상으로 간주하지 않는다.
15. Standard NetworkPolicy가 additive라는 사실은 변하지 않는다. Release manifest와 cluster의 다른 allow policy, `hostNetwork`, privileged workload와 CNI enforcement를 배포 전 확인한다. 이 검증을 실패하면 proxy-only activation을 중단한다.
16. Object storage SDK는 ambient 환경이 아니라 explicit proxy configuration을 사용한다. Signed request와 provider business semantics는 storage adapter가 계속 소유한다.
17. 이 결정은 Docker Compose와 provider-neutral Helm만 변경하며 ADR-0068의 EKS 비지원 경계를 확장하지 않는다.

## Security and protected-resource boundaries

| Boundary | Result | Evidence |
| --- | --- | --- |
| 정책·설정 | 완료 | Typed transport mode, exact endpoint/host/port, immutable revision과 production startup validation |
| 관리 API·UI | 해당 없음 | Operator-owned deployment setting이며 사용자 destination 등록 기능을 추가하지 않는다. |
| Runtime/background | 완료 | Gateway lifespan, Workflow worker init/process init, Knowledge worker init/bootstep과 guarded HTTP/S3 composition |
| Authorization | 완료 | 기존 operation/resource authorization을 유지하며 proxy source 권한으로 대체하지 않는다. |
| 외부 I/O 전 fail-closed | 완료 | Invalid/missing config, unsafe DNS와 proxy failure에서 origin direct dial을 수행하지 않는다. |
| Secret·trace·audit | 완료 | Squid access/cache log 비활성, safe application error와 synthetic marker 계약 |
| Lifecycle·HA | 완료 | 최소 replica, rolling bound, PDB, readiness/liveness와 canary/final selector 전환 |
| Network enforcement | 완료(기준 환경) | Compose disposable network test와 pinned kind+Calico IPv4 CI probe |
| Dual-stack·운영 CNI | Release gate | 실제 배포 환경에서 같은 probe를 통과해야 하며 미검증 환경은 활성화하지 않는다. |
| 비-HTTP protocol | 해당 없음 | DB, Redis, IMAP, Sandbox와 Connector의 별도 Accepted 계약을 유지한다. |

## Consequences

- External HTTP/HTTPS 호출은 application guard와 Squid를 모두 통과한다.
- Proxy 장애는 해당 외부 operation의 가용성을 낮추지만 direct path로 보안을 완화하지 않는다.
- HTTPS payload inspection은 제공하지 않는다. Squid만으로 operation authorization이 완료됐다고 판단할 수 없다.
- NetworkPolicy를 집행하지 않거나 additive allow policy가 있는 cluster는 동일 chart를 렌더할 수 있어도 지원 환경이 아니다.
- Local Helm profile은 개발 편의를 위해 direct-pinned mode를 유지할 수 있지만 production readiness 증거로 사용할 수 없다.

## Affected files

- `apps/shared/services/outbound_proxy_policy.py`
- `apps/shared/services/guarded_http_transport.py`
- `apps/gateway/lifespan.py`
- `apps/gateway/knowledge_worker*.py`
- `apps/gateway/services/storage.py`
- `apps/workflow_engine/outbound_proxy_startup.py`
- `docker/docker-compose.yml`
- `docker/proxy/*`
- `infra/helm/moduly/*`
- `.github/workflows/pr-quality-gate.yml`
- `tests/ci/test_egress_proxy_*.py`
- `docs/architecture.md`
- `docs/engineering/outbound-proxy-rollout.md`
- `docs/features/deployment/*`
- `docs/features/workflow/*`

## Follow-up review notes

- 새 public HTTP adapter나 workload를 추가할 때 operation registry, explicit proxy composition, workload inventory와 NetworkPolicy probe를 같은 변경에서 갱신한다.
- Dual-stack 또는 다른 CNI를 공식 지원하려면 실제 positive/negative evidence를 runbook의 지원 matrix에 추가한다.
- mTLS/service mesh workload identity, TLS inspection과 arbitrary organization destination 등록은 본 결정의 확장이 아니며 별도 ADR이 필요하다.
