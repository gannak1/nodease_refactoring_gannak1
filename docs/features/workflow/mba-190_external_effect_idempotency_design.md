# MBA-190 External Effect Node Idempotency Design

Status: Draft

## Scope

이 문서는 Workflow Runtime에서 외부 부수효과를 만드는 node adapter의 멱등성 계약을 정의한다. 대상은 HTTP 요청, Slack/GitHub/Gmail 같은 provider 호출, ticket 생성, 외부 DB mutation처럼 Nodease 밖의 시스템 상태를 바꿀 수 있는 실행이다.

이 설계는 schedule dispatch/admission 멱등성을 재구현하지 않는다. schedule occurrence가 workflow run으로 진입하는 경계는 MBA-187의 책임이고, 여기서는 이미 시작된 workflow run 안에서 node 단위 외부 effect가 중복 생성되지 않도록 adapter와 retry 경계를 정의한다.

## Design Principles

- External effect idempotency is an adapter contract, not a graph scheduler contract.
- Provider가 idempotency key 또는 동등한 deduplication 계약을 제공하지 않으면 exactly-once를 주장하지 않는다.
- Worker retry는 provider capability와 직전 outcome이 안전할 때만 허용한다.
- 내부 idempotency identity는 prompt, 사용자 응답, durable raw trace, metric label에 노출하지 않는다.
- 공통 runtime은 identity 생성, outcome 기록, replay decision만 담당하고 provider별 header/field 선택은 adapter가 담당한다.

## Runtime Boundary

현재 node 생성 경계는 `NodeFactory.create(schema, context=execution_context)`이고, 모든 node는 `Node.execute(inputs)`를 통해 실행된다. `WorkflowEngine`은 `workflow_run_id`, `workflow_id`, `app_id`, `deployment_id`, `organization_id` 같은 context를 보유하며 node log와 trace metadata를 기록한다.

MBA-190에서는 이 경계를 유지한다. `WorkflowEngine`은 node 실행 직전에 effect identity를 계산해 node execution context에 제공하고, adapter는 이 identity를 provider 요청에 반영하거나 replay 불가 판단에 사용한다. 개별 node가 workflow graph scheduling, Celery retry, schedule claim을 직접 알 필요는 없다.

## Domain Contract

### Idempotency Identity

외부 effect identity는 같은 workflow run, 같은 node, 같은 effect operation, 같은 node attempt를 안정적으로 식별해야 한다.

필수 입력:

- `workflow_run_id`
- `node_id`
- `node_type`
- `operation`
- `effect_sequence`
- `workflow_task_id` 또는 upstream schedule idempotency key가 있는 경우 그 값의 안전한 fingerprint

provider로 전달되는 key는 deterministic해야 하지만 raw 내부 식별자를 그대로 노출하지 않는다. 권장 형식은 Nodease namespace prefix와 HMAC 기반 digest를 조합한 짧은 문자열이다. DB에는 raw key가 아니라 fingerprint와 provider-visible key의 hash만 저장한다.

### Capability

adapter는 다음 capability 중 하나를 명시한다.

- `supported`: provider의 공식 idempotency header/field 또는 동등한 deduplication semantics를 사용한다.
- `unsupported`: provider가 중복 방지 계약을 제공하지 않거나 현재 adapter가 안전하게 적용하지 못한다.
- `unknown`: provider 또는 operation별 semantics를 아직 검증하지 않았다.

`unknown`은 `unsupported`처럼 보수적으로 동작한다. 문서와 테스트로 검증되기 전까지 자동 replay를 허용하지 않는다.

### Outcome

node adapter는 외부 요청 실패를 다음 outcome으로 분류한다.

- `succeeded`: provider가 effect를 성공 처리했거나 같은 idempotency key에 대한 replay 결과를 반환했다.
- `failed_before_effect`: DNS 실패, validation 실패, request serialization 실패처럼 provider가 effect를 만들기 전에 실패했다.
- `effect_outcome_unknown`: timeout, disconnect, provider accept 후 응답 유실, response parse 실패처럼 effect 생성 여부를 알 수 없다.

### Replay Decision

공통 runtime은 capability와 outcome으로 자동 retry 가능성을 판단한다.

- `failed_before_effect`: adapter가 다시 요청해도 중복 effect 위험이 없으므로 retry 가능하다.
- `effect_outcome_unknown` + `supported`: 같은 provider idempotency key를 재사용하는 replay만 허용한다.
- `effect_outcome_unknown` + `unsupported` 또는 `unknown`: 자동 replay를 금지하고 non-retryable failure로 분류한다.
- `succeeded`: workflow engine의 중복 delivery에서는 provider replay가 아니라 저장된 outcome 재사용을 우선한다.

## Adapter Responsibilities

### Common Adapter Layer

공통 layer는 `ExternalEffectContext`, `ExternalEffectCapability`, `ExternalEffectOutcome`, `ExternalEffectReplayDecision` 같은 작은 domain object를 제공한다. 이 layer는 `apps/workflow_engine/workflow/nodes`와 `apps/shared` 사이의 shared runtime contract로 유지한다.

책임:

- execution context에서 안전한 effect identity 생성
- provider key 길이와 character constraint 적용
- raw key redaction과 fingerprint 생성
- outcome과 replay decision을 node result metadata로 반환
- trace metadata에는 capability, outcome, replay decision, provider, operation, key fingerprint만 기록

비책임:

- provider별 header 이름 결정
- provider별 response 재사용 semantics 해석
- schedule dispatch claim 생성 또는 workflow admission 제어

### Provider Adapter

각 provider adapter는 operation 단위 capability profile을 선언한다.

- HTTP generic request: 기본값 `unknown`
- Slack post: 공식 중복 방지 계약이 검증되기 전까지 `unknown`
- GitHub mutation: operation별 공식 semantics가 확인된 경우에만 `supported`, 그 외 `unknown`
- Gmail send/draft: message id 또는 provider deduplication 계약이 검증된 operation만 `supported`
- Mail IMAP read: 조회만 수행하면 external effect 대상이 아니다. `mark_as_read=true`는 mailbox mutation이므로 `unsupported` 또는 provider 검증 전 `unknown`

`slackPostNode`가 현재 `HttpRequestNode`에 매핑되어 있으므로, Slack 전용 capability를 적용하려면 generic HTTP adapter 안에 provider profile을 주입하거나 Slack 전용 adapter로 분리해야 한다. 응집도 관점에서는 provider별 멱등성 semantics가 늘어날수록 전용 adapter 분리가 더 적합하다.

## Persistence

Worker가 provider 요청 후 종료될 수 있으므로 outcome은 durable하게 남아야 한다. 권장 모델은 node run log와 별도 `workflow_node_effect_attempts` 테이블이다.

필드:

- `id`
- `workflow_run_id`
- `node_run_id`
- `node_id`
- `node_type`
- `provider`
- `operation`
- `effect_sequence`
- `idempotency_key_fingerprint`
- `capability`
- `outcome`
- `replay_decision`
- `provider_request_id`
- `provider_status_code`
- `error_code`
- `created_at`
- `updated_at`

unique key는 `workflow_run_id + node_id + operation + effect_sequence`를 기준으로 둔다. provider-visible raw idempotency key, credential, request body, response body는 저장하지 않는다.

이미 존재하는 `WorkflowNodeRun`은 node 실행 결과와 tracing의 중심이고, 외부 effect attempt는 provider replay decision의 중심이다. 두 관심사를 분리하면 node log schema가 provider별 세부 상태로 비대해지는 것을 피할 수 있다.

## Error Handling

adapter는 provider 호출을 세 단계로 나눠 실패 지점을 분류한다.

- request 준비 전 실패: `failed_before_effect`
- provider에 request write 전 실패: `failed_before_effect`
- request write 이후 timeout/disconnect/parse failure: `effect_outcome_unknown`

`effect_outcome_unknown`이면서 capability가 `unsupported` 또는 `unknown`이면 `NonRetryableWorkflowError` 계열로 올려 Celery 자동 retry를 막는다. 사용자-facing error는 중복 가능성을 설명하되 raw provider payload나 idempotency key를 포함하지 않는다.

## Trace And Logging

trace metadata에 허용되는 값:

- provider
- operation
- capability
- outcome
- replay_decision
- idempotency key fingerprint
- provider request id
- status code
- latency bucket 또는 latency ms

금지되는 값:

- provider-visible raw idempotency key
- credential 원문
- Authorization header
- API key, token, encrypted config
- prompt, 사용자 응답, raw trace payload 안의 identity
- metric label의 full key 또는 workflow/user raw identifier 조합

HTTP node의 현재 trace payload는 request header와 body를 저장한다. MBA-190 구현에서는 idempotency header를 trace payload 수집 전에 redact하거나 trace payload sanitizer allowlist를 강화해야 한다.

## Implementation Plan

1. `apps/shared` 또는 `apps/workflow_engine`에 external effect domain contract를 추가한다.
2. `WorkflowEngine._submit_node` 또는 `_execute_node_task`에서 node별 `ExternalEffectContext`를 생성해 node execution context에 주입한다.
3. durable effect attempt repository를 추가하고 node 실행 전후 상태를 기록한다.
4. HTTP adapter에 generic `unknown` policy와 provider profile hook을 추가한다.
5. supported provider는 공식 header/field를 적용하고, unsupported/unknown provider는 ambiguous outcome에서 자동 replay를 금지한다.
6. WorkflowLogger trace metadata에는 sanitized effect summary만 남긴다.
7. integration test용 fake provider를 만들어 duplicate delivery, timeout, accept 후 disconnect, malformed response를 검증한다.

## Test Plan

- Domain unit test: 같은 execution context는 같은 fingerprint를 만들고 raw key는 로그gable dict에 포함되지 않는다.
- Domain unit test: capability와 outcome 조합이 올바른 replay decision을 만든다.
- HTTP adapter test: supported profile은 provider idempotency header를 넣고 trace payload에서는 redact한다.
- HTTP adapter test: unsupported/unknown profile은 `effect_outcome_unknown`에서 non-retryable failure를 반환한다.
- Integration test: fake provider가 같은 key의 duplicate request를 하나의 effect로 deduplicate한다.
- Integration test: provider accept 후 response loss가 발생하면 supported adapter만 같은 key replay를 허용한다.
- Regression test: schedule dispatch idempotency key는 workflow admission 경계에 남고 provider raw key로 직접 노출되지 않는다.
- Security test: prompt, answer, raw trace payload, metric label에 raw idempotency identity가 남지 않는다.

## Open Questions

- `workflow_node_effect_attempts`를 새 migration으로 추가할지, 기존 node run log metadata에 최소 필드로 먼저 저장할지 결정이 필요하다.
- provider-visible key의 최대 길이와 허용 문자 정책을 provider profile에 둘지 공통 key builder에 둘지 결정이 필요하다.
- generic HTTP node에서 사용자가 직접 idempotency header를 설정한 경우 Nodease managed key와 충돌할 때 우선순위를 어떻게 둘지 정해야 한다.
- `succeeded` outcome의 duplicate workflow delivery에서 node result를 어디까지 재사용할지 결정해야 한다. response body 재사용은 provider별 semantics가 다르므로 기본은 summary만 재사용하는 것이 안전하다.
