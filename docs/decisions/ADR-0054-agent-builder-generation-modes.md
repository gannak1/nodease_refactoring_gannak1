# ADR-0054: Agent Builder 생성 모드와 전환 경계

Status: Accepted

Related ADRs: [ADR-0019](ADR-0019-agent-builder-preview-apply-save-boundary.md), [ADR-0024](ADR-0024-agent-builder-node-capability-catalog.md), [ADR-0026](ADR-0026-agent-builder-intent-and-connection-validation.md), [ADR-0027](ADR-0027-agent-builder-pre-intent-safe-kb-context.md), [ADR-0040](ADR-0040-agent-builder-unified-model-recommendation.md), [ADR-0045](ADR-0045-agent-builder-direct-edit-parameter-guidance.md), [ADR-0046](ADR-0046-agent-builder-graph-mutation-and-cas-save.md)

## Context

ADR-0045는 Legacy Preview 프로토콜을 폐기하고 typed `GraphMutation`, CAS 저장, acknowledgement와 `ParameterTask`를 사용하는 direct-edit 계약을 채택했다. 현재 제품은 `configure_and_generate`와 `structure_only` 두 값을 제공하지만, 사용자는 다음 두 요구를 모두 가진다.

- 복잡하거나 권한이 필요한 workflow는 구조와 설정을 단계적으로 확인하고 싶다.
- 안전하게 자동 결정할 수 있는 단순 workflow는 전체 결과를 한 번에 검토하고 적용하고 싶다.

Legacy Preview API와 direct-edit를 동시에 유지하면 graph 생성, validation, 권한 검사, stale 검사, 저장, audit와 Undo 계약이 이중화된다. 반대로 모든 생성을 단계별 설정으로만 제한하면 단순 workflow와 시연 흐름의 불필요한 마찰이 커진다. 따라서 UX 모드는 나누되 내부 변경·저장 계약은 하나로 유지해야 한다.

## Decision

### 1. 정식 생성 모드

Agent Builder는 다음 세 모드를 제공한다.

| 값 | 사용자 표시 | 목적 |
| --- | --- | --- |
| `guided_generate` | 단계별 생성 | 구조를 만든 뒤 Knowledge, parameter와 외부 연결 설정을 순서대로 확인한다. 기본값이다. |
| `quick_generate` | 빠른 생성 | 서버가 안전하게 확정할 수 있는 전체 변경안을 한 화면에서 검토한 뒤 명시적으로 적용한다. |
| `structure_only` | 구조만 생성 | graph 구조만 생성하고 미해결 설정은 일반 Editor에서 처리한다. 고급 옵션이다. |

기존 `configure_and_generate`는 `guided_generate`의 입력·조회 호환 별칭이다. Gateway의 내부 domain과 신규 저장 metadata는 canonical `guided_generate`로 정규화한다. 외부 API 응답 표현은 7절의 consumer-first 계약 협상을 따르며, canonical mode를 읽는다고 명시한 Client에만 `guided_generate`를 반환한다. 기존 JSON row를 일괄 backfill하지 않으며 mixed-version read에서만 별칭을 해석한다.

### 2. 모드 선택 권한

- 별도 선택이 없으면 `guided_generate`를 사용한다.
- 사용자는 화면 control 또는 "한 번에 만들어 줘"처럼 명시적인 자연어 요청으로 `quick_generate`를 요청할 수 있다.
- Client는 화면의 초기값과 사용자의 명시적 control 선택을 `generation_mode_source=default|explicit_control`로 구분한다. 명시적 control 선택, 명시적 자연어 mode 의도, 기본 guided 순서로 requested mode를 확정한다.
- `source=default`인 guided 표시는 자연어의 명시적 quick/structure-only 요청을 막지 않는다. `source=explicit_control`인 선택은 자연어 mode 의도보다 우선한다.
- LLM은 자연어에서 모드 의도를 구조화할 수 있지만 빠른 생성 가능 여부를 승인하지 않는다.
- 최종 가능 여부는 Gateway의 결정론적 eligibility policy가 현재 사용자 권한, Catalog, graph와 resource 상태를 기준으로 판정한다.
- 서버는 사용자 동의 없이 빠른 생성을 단계별 생성으로 조용히 전환하지 않는다.

### 3. 빠른 생성 eligibility

다음 조건을 모두 만족하는 경우에만 빠른 생성을 허용한다.

- 모든 node와 edge가 현재 Node Capability Catalog에서 Agent Builder 지원 대상으로 검증된다.
- 필요한 parameter를 사용자 요청, 기존 graph, 결정론적 selector 또는 안전한 catalog default로 하나의 값으로 확정할 수 있다.
- 권한이 필요한 resource reference가 현재 execution subject와 active organization 기준으로 재검증된다.
- 외부 부수효과, credential 사용, network egress 또는 code 실행을 새로 활성화하지 않는다.
- Condition branch처럼 실행 의미를 바꾸는 선택이나 의미 있는 복수 후보가 남지 않는다.
- base graph hash, workflow `updated_at`, Catalog version과 resource revision이 유효하다.

다음 중 하나라도 해당하면 빠른 생성을 완료하지 않는다.

- credential 선택 또는 원문 secret 입력이 필요하다.
- 권한 있는 Knowledge Base 또는 Collection 선택이 필요하다.
- 일반 required parameter에 사용자 요청·기존 graph·selector·안전한 Catalog default 중 확정 가능한 값이 없다.
- 외부 대상, 수신자, 저장 위치처럼 부수효과 범위를 정해야 한다.
- Condition case, HTTP/code/egress 설정 또는 unresolved 외부 action이 있다.
- 후보가 없거나 둘 이상이고 정책만으로 안전하게 하나를 확정할 수 없다.
- resource가 삭제, 비활성, 권한 상실 또는 stale 상태다.

이 경우 서버는 graph를 변경하지 않고 safe reason code와 `mode_transition_required`를 반환한다. 일반 required parameter 값을 확정할 수 없는 경우에는 `configuration_value_required`를 사용한다. UI는 단계별 생성으로 전환할 이유를 민감 정보 없이 설명하고 사용자의 명시적 확인을 받는다. 사용자가 취소하면 기존 graph는 그대로 유지한다.

### 4. 빠른 생성 적용 경계

빠른 생성도 ADR-0045와 ADR-0046의 typed `GraphMutation`과 CAS 저장을 사용한다.

1. 서버는 full typed operations와 민감하지 않은 변경 요약을 한 API 응답으로 반환한다. Request는 `graph_mutation_ready`, 응답 안의 GraphMutation만 `pending_apply`다.
2. Client는 실제 editor graph가 아닌 복제본에 mutation을 dry-run하고 동일한 validator로 결과를 검증한다.
3. UI는 추가·변경·삭제 node와 남은 차단 사항을 요약해 보여준다.
4. 사용자가 `생성 적용`을 명시적으로 선택한 뒤에만 실제 editor history boundary에 mutation을 적용하고 CDS CAS 저장을 수행한다.
5. 서버 acknowledgement가 끝난 뒤에만 요청을 완료한다.

이 검토 화면은 Legacy Preview Mode가 아니다. 별도 preview session, draft graph 저장소, preview 전용 apply API를 만들지 않는다. 저장과 stale 검사, acknowledgement, Undo/Redo는 guided mode와 동일한 GraphMutation/CDS 경계를 사용한다.

Full typed operations는 기존 계약대로 발급 API 응답에서만 전달한다. 적용 전 응답을 잃거나 reload하면 safe envelope에서 operations를 복원하지 않는다. 같은 operation id 재시도는 중복 상태 전이를 만들지 않지만 원래 operations 대신 `operation_payload_unavailable`과 safe canonical 상태를 반환한다. 사용자가 기존 request를 취소하고 같은 의도로 새 request를 명시적으로 제출해야 새 operation id로 재생성하며, 서버는 현재 권한, Catalog와 graph/resource revision을 다시 검증한다. 적용·저장 후 acknowledgement 복구는 ADR-0046을 따른다.

### 5. 단계별 생성 중 빠른 완료

`남은 설정 빠르게 완료`는 네 번째 생성 모드가 아니라 `guided_generate` 내부의 범위 축소 명령이다.

- 이미 acknowledgement된 graph와 완료된 Knowledge/parameter 결정은 보존한다.
- 서버는 아직 완료되지 않은 task만 현재 권한, Catalog와 graph revision으로 다시 평가한다.
- 전체 planner를 다시 호출하거나 workflow 전체를 재생성하지 않는다.
- Canonical graph에 추천값이 이미 materialize돼 있고 recommendation fingerprint와 task version이 변하지 않은 남은 task만 하나의 검토안으로 묶는다.
- credential, 권한 resource, 외부 부수효과, Condition branch 또는 복수 후보가 남은 task는 단계별 확인 상태로 유지한다.
- 사용자가 검토안을 적용하면 parent request row lock 안에서 각 추천 fingerprint와 task version을 다시 검증하고 값 변경 없는 기존 추천만 멱등 batch `confirm`한다. GraphMutation이나 workflow 저장을 만들지 않는다.
- 값이 없거나 새 값 계산·graph 변경이 필요한 task와 미완료 Knowledge/Collection 선택은 단계별 확인 상태로 유지한다. 여러 task를 바꾸는 신규 batch mutation은 별도 결정 전까지 도입하지 않는다.

### 6. 구조만 생성

`structure_only`는 parameter task를 열지 않는다. 생성된 graph에 unresolved 설정이 있으면 저장은 가능하지만 server-side test, run과 deployment preflight가 차단한다. UI는 이를 완성된 실행 가능 workflow로 표시하지 않는다. 실행·배포 readiness는 저장된 graph와 Catalog에서 계산한 missing/deferred/invalid configuration을 기준으로 하며, 값이 이미 유효하게 materialize된 graph의 `pending|active` ParameterTask 자체는 차단 사유가 아니다. Agent Builder의 사용자 확인 완료 상태와 runtime readiness는 별도 상태다.

### 7. 저장·동시성·취소

- 세 모드는 같은 canonical graph hash, workflow `updated_at`, Catalog version과 ADR-0046 CAS 저장 계약을 사용한다.
- mode 전환과 빠른 완료 요청은 client-generated operation id와 expected request/task version을 포함한다.
- Request 상태, GraphMutation 상태와 ParameterTask 상태는 서로 다른 enum과 owner를 가진다. `pending_apply|pending_save|pending_ack|acknowledged`는 GraphMutation lifecycle이며 RequestStatus로 저장하지 않는다.
- stale graph, stale task 또는 중복 operation은 기존 결과를 덮어쓰지 않고 conflict로 닫는다. 다만 full operations를 저장하지 않는 mutation 발급 응답의 재시도는 같은 payload 반환을 보장하지 않고 `operation_payload_unavailable` 복구 계약을 따른다.
- 적용 전 취소는 graph를 변경하지 않는다. 적용 중 취소는 이미 acknowledgement된 변경을 자동 롤백하지 않고 기존 Workflow Undo boundary로 복구한다.
- 한 request에서 Legacy Preview와 direct-edit를 혼용하지 않는다.
- 외부 generation mode 표현은 선택적 `X-Agent-Builder-Mode-Contract` 요청 헤더로 협상한다. 헤더가 없거나 `legacy-v1`이면 Gateway는 legacy `configure_and_generate` 표현을 반환하고, `canonical-v2`이면 canonical 표현을 반환한다.
- Message request 생성 시 정규화한 `mode_contract_version=legacy-v1|canonical-v2`를 기존 `AgentBuilderRequest.response_payload`에 고정한다. Raw header와 session 전체 계약은 저장하지 않으며 contract 값이 없는 기존 request는 `legacy-v1`로 읽는다. Active request를 조회하거나 변경하는 후속 endpoint는 고정된 contract와 같은 요청만 허용하고 불일치하면 request payload를 projection하지 않은 채 `mode_contract_mismatch`로 닫는다.
- Request cancel은 generation mode를 포함하지 않는 contract-neutral 응답으로 제공해 고정 contract를 모르는 복구·운영 경로도 같은 인증·권한 아래 request를 종료할 수 있게 한다.
- Rollout은 Gateway가 두 입력을 수용하되 legacy 응답을 유지하는 단계, Client가 두 응답을 읽는 단계, 모든 Gateway replica와 Client dual-read gate 확인 뒤 `canonical-v2`를 허용하는 단계, Client가 canonical 값을 쓰는 순서로 진행한다. `quick_generate`는 canonical-v2와 Backend·Frontend 통합 gate가 모두 준비된 경우에만 노출한다. Client rollback 전에는 quick/canonical request 생성을 먼저 닫고 active `canonical-v2` request를 완료·취소해 0건임을 확인하며, 이 drain이 끝날 때까지 dual-contract Gateway를 유지한다. Drain count는 `mode_contract_version=canonical-v2`이면서 RequestStatus가 terminal이 아닌 request의 내부 운영 집계이며 request id나 payload를 외부에 노출하지 않는다.

### 8. 데이터와 보안

- canonical mode, requested mode와 source, effective mode, request-scoped `mode_contract_version`, monotonic request/proposal version, 전환 상태와 safe reason code는 기존 `AgentBuilderRequest.response_payload`의 safe metadata에 저장할 수 있다.
- full operations, raw prompt의 민감 부분, credential 원문, token, API key, hidden resource identifier와 외부 payload는 저장·audit·trace하지 않는다.
- mode metadata를 위한 신규 table 또는 전용 column을 추가하지 않는다.
- 빠른 생성 eligibility와 mode 전환은 권한 우회 수단이 아니다. 생성 시점, mutation 발급 시점, CAS 저장 시점과 실행·배포 preflight에서 기존 권한 검사를 유지한다.

## Authority and implementation state

이 ADR은 Agent Builder 생성 모드, 기본값, 빠른 생성 eligibility와 모드 전환의 Accepted authority다. ADR-0045는 direct-edit parameter/Knowledge UX와 history boundary를, ADR-0046은 GraphMutation/CDS CAS 저장을 계속 소유한다. ADR-0019의 Preview 프로토콜은 Superseded 상태이며 빠른 생성 구현에 재사용하지 않는다.

MBA-293 시점의 코드는 `configure_and_generate|structure_only`만 구현한 현재 상태다. 이 ADR과 관련 feature 문서의 세 모드 계약은 후속 구현 목표이며, 기능 구현과 배포 gate가 완료되기 전에는 `quick_generate`가 가용하다고 표시하지 않는다.

## Consequences

- 단순 workflow는 한 화면 검토 후 빠르게 적용할 수 있고 복잡한 workflow는 안전한 단계별 확인을 유지한다.
- 두 UX가 같은 GraphMutation, CAS, validation, audit와 Undo 경계를 공유하므로 Legacy Preview 이중 구현을 피한다.
- 빠른 생성 가능 여부를 서버 정책이 소유하므로 LLM의 임의 판단으로 credential·권한·외부 부수효과가 확정되지 않는다.
- compatibility alias와 target mode가 일정 기간 공존하므로 Gateway, Client, 문서와 테스트의 단계적 전환이 필요하다.

## Non-goals

- Legacy Preview API/UI 또는 별도 preview graph store 복구
- Agent Builder 전용 graph 저장소나 신규 session table 도입
- Knowledge 후보 ranking·Collection 계층 선택 알고리즘 재정의
- credential 원문 수집 또는 외부 부수효과의 자동 승인
- LLM에게 eligibility 또는 권한 판정을 위임
- `structure_only` 결과의 실행·배포 차단 완화
- Guided 진행 중 아직 materialize되지 않은 여러 parameter를 새 값으로 일괄 변경하는 batch GraphMutation
