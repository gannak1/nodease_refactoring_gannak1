# ADR-0065: RAG query embedding provider capability 경계

Status: Accepted

Related ADRs: ADR-0018, ADR-0036, ADR-0057, ADR-0064

## 배경

Workflow LLM node의 RAG 검색은 Knowledge 후보를 권한에 따라 제한한 뒤 후보 Knowledge Base의 embedding model로 질의 vector를 만든다. Legacy 구현은 이 단계에서 실행 사용자 또는 배포 작성자에서 유도한 사용자 ID로 credential을 다시 선택한다. 이 선택은 main generation의 deployment credential policy와 무관하고, public·system 실행에서는 Knowledge execution subject, credential principal, billing principal과 audit actor를 혼동할 수 있다.

ADR-0064는 generation과 Memory summary provider 호출에 short-lived `ProviderExecutionCapability`를 도입했지만 query embedding purpose, embedding model별 credential policy와 호출 lifecycle은 정하지 않았다. 하나의 node가 서로 다른 embedding model을 사용하는 여러 Knowledge Base를 조회할 수 있으므로 node당 generation policy 한 개만으로는 query embedding credential을 결정할 수 없다.

## 결정

1. LLM Credentials domain의 기존 `ProviderExecutionCapability` aggregate에 `purpose=query_embedding`을 추가한다. Main generation 또는 Memory summary capability를 query embedding에 재사용하거나 그 반대로 사용하는 것을 금지한다.
2. Deployment credential policy에는 `purpose`를 저장한다. 기존 row는 `main_generation`으로 해석한다. Main generation은 deployment version/node당 active row를 최대 한 개만 허용하고, query embedding은 deployment version/node/canonical embedding model당 active row를 최대 한 개만 허용한다.
3. 기존 `PUT /deployments/{deployment_id}/llm-credential-policies/{node_id}`는 `purpose`를 생략하면 `main_generation`으로 동작한다. `purpose=query_embedding` 요청은 Knowledge가 설정된 LLM node와 active embedding model UUID를 명시해야 한다. Response와 목록 projection은 purpose를 반환하되 credential principal, secret, capability scope와 provider payload를 반환하지 않는다.
4. Query embedding policy 작성과 runtime admission은 canonical deployment와 organization scope, active embedding model, active credential, provider 일치, verified credential-model relation과 policy 작성자의 current credential `use` 권한을 검증한다. Generation policy credential, execution user, App/deployment owner, 조직 기본값, 이름·최신 row 또는 환경 변수 fallback을 사용하지 않는다.
5. Workflow Engine은 별도 application `QueryEmbeddingExecutionRuntime` port와 single-use lease를 사용한다. `LLMNode`는 Shared capability service, credential ORM/config 또는 provider SDK를 직접 해석하지 않는다. Runtime dependency는 process-local로 주입하고 graph, execution context 또는 task payload에 직렬화하지 않는다.
6. Knowledge execution subject는 후보 해석과 source/evidence 권한에만 사용한다. Credential principal은 policy 작성자 user, billing principal은 organization, audit actor는 실제 user/public/system execution actor로 유지한다. Credential principal을 private Knowledge subject나 public audit actor로 승격하지 않는다.
7. Authorized Knowledge 후보가 없으면 query embedding policy, capability, credential, provider와 usage 경계를 호출하지 않는다. 후보가 있으면 distinct canonical embedding model마다 stable provider attempt와 capability를 하나 만들고, 같은 model을 사용하는 후보는 invocation-local query vector를 공유한다. KB ID는 provider attempt identity나 usage dimension으로 사용하지 않는다.
8. Query embedding capability는 exact canonical embedding model, provider, credential policy/revision, permission/relation/pricing/authoritative egress revision, node invocation, execution admission, provider attempt, query input token·byte 상한, 비용 상한과 expiry에 binding한다. Output token cap과 request는 `0`이어야 한다.
9. Query 원문과 vector는 invocation-local ephemeral data다. Capability, usage ledger, audit, trace, log, API 또는 task payload에 저장하지 않는다. Provider 오류는 allowlisted phase/reason으로 정규화하고 raw payload나 원본 예외 문자열을 저장하지 않는다.
10. Capability issue/admission과 credential materialization은 Workflow shared session과 분리한 짧은 transaction에서 완료하고 provider I/O 전에 commit·close한다. Lease는 첫 provider 전송 시도 전에 소진한다. Credential revoke, 권한 회수, relation/model/provider/policy 또는 egress revision 변경이 admission보다 먼저 commit되면 provider 호출 없이 fail-closed한다.
11. Query embedding outbound는 MBA-178의 authoritative LLM egress authorization과 address-pinned transport를 사용한다. ADR-0064의 provider-routing fingerprint만으로 outbound를 허용하지 않는다. Durable provider intent, `provider_started`, success/failure/outcome-unknown과 중복 reconciliation은 MBA-287의 provider usage ledger를 사용한다. 두 경계가 주입되지 않은 capability runtime은 provider client를 호출하지 않는다.
12. Capability-required LLM node는 authorized Knowledge 후보가 있으면 main generation lease를 resolve하기 전에 query embedding runtime이 위 계약을 소비할 수 있는지 검증한다. 후보가 없으면 안전한 무근거 결과를 반환하고 두 provider lease를 모두 만들지 않는다. Legacy 전체 rollout과 rollback은 MBA-320의 server-owned activation이 소유하며 client 또는 graph field로 capability mode를 선택하지 않는다.
13. Schema downgrade는 `query_embedding` policy 또는 capability row가 하나라도 있으면 중단한다. 이를 main generation으로 변환하거나 삭제해 의미와 비용 추적을 손상시키지 않는다. Query-embedding row를 운영 절차로 정리한 뒤에만 기존 schema로 downgrade할 수 있다.

## 검토한 대안

### Main generation capability와 credential 재사용

구현은 단순하지만 generation model과 embedding model의 provider·credential·가격·egress가 다를 수 있고 purpose isolation이 사라진다. 별도 purpose와 policy slot을 사용한다.

### 별도 EmbeddingExecutionCapability aggregate

호출 형태는 분명해지지만 principal, permission/relation revision, revoke, expiry, ledger와 redaction 규칙이 중복된다. Aggregate는 공유하고 Workflow application port와 request/lease만 분리한다.

### 실행 사용자 또는 organization default credential 선택

Interactive 실행에는 편리하지만 public·schedule에서 principal을 혼동하고 배포 재현성을 깨뜨린다. 명시적 manager policy가 없으면 실행하지 않는다.

### KB마다 provider attempt 생성

같은 model query를 중복 호출하고 비용·usage를 부풀리며 숨겨진 KB identity를 operation dimension에 노출한다. Node invocation과 canonical embedding model을 단위로 사용한다.

## 결과

- RAG query embedding은 main generation과 독립된 명시 정책, capability와 usage operation으로 추적된다.
- Public·system 실행에서도 private Knowledge 권한과 credential 사용 권한이 섞이지 않는다.
- 같은 embedding model을 사용하는 여러 Knowledge Base는 한 번의 승인된 query vector를 재사용한다.
- MBA-178 또는 MBA-287 경계가 준비되지 않은 환경에서는 capability-required RAG가 의도적으로 fail-closed한다. Legacy 활성화 전 운영 준비 상태는 MBA-320에서 검증한다.
