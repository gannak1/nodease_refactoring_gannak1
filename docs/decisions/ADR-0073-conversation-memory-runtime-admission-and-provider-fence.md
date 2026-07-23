# ADR-0073: Conversation Memory runtime admission과 provider 전송 fence

Status: Accepted

Related ADRs: ADR-0030, ADR-0033, ADR-0064, ADR-0066, ADR-0069

## 배경

Conversation Memory foundation은 Session, Access Grant, Turn, durable dispatch,
Context Plan/Lease와 Provider Attempt schema를 제공하지만 실제 공개 Workflow 실행은
연결하지 않았다. Runtime을 연결할 때 다음 경계를 명시하지 않으면 기존 App owner를
public 실행 주체로 합성하거나, raw 입력을 broker/WorkflowRun에 복제하거나,
Memory와 usage ledger의 두 `provider_started` marker가 서로 다른 replay 결정을 내릴 수
있다.

## 결정

1. 첫 runtime surface는 명시적 conversation envelope을 사용하는
   `POST /api/v1/run-public/{url_slug}` 하나다. 동일 deployment의 legacy Memory-OFF
   요청은 기존 계약을 유지하고, 다른 실행 surface의 versioned Memory-enabled graph는
   별도 계약이 승인될 때까지 provider I/O 전에 거부한다.
2. 첫 활성 graph는 root의 `Start -> LLM -> Answer` 세 node와 두 edge로 고정한다.
   Start에는 하나의 required text input, Answer에는 LLM의 단일 text output mapping만
   허용한다. LLM은 fixed model과 bounded generation parameter allowlist만 사용하며
   routing, fallback, tool, Knowledge/RAG, structured output, nested graph와 summary는
   fail-closed한다. Gateway preflight와 Workflow runtime은 같은 pure validator를 쓴다.
3. Gateway는 current Access Grant와 frozen deployment binding을 확인한 뒤 Turn과
   dispatch를 같은 Memory transaction에서 생성한다. Broker에는 organization,
   dispatch와 Turn의 opaque reference 및 contract version만 전달한다. Raw current input,
   grant ID/token, context, provider response와 assistant output을 task argument, Celery result,
   pub/sub event, WorkflowRun 또는 WorkflowNodeRun payload에 넣지 않는다.
4. Workflow domain은 dispatch당 하나의 durable admission과 generation-fenced execution
   lease를 소유한다. Memory는 admission/running/terminal safe projection만 보존하며
   Workflow session이나 row lock을 cross-domain call 또는 provider I/O 동안 유지하지
   않는다. Current generation만 input read, context claim, provider effect, checkpoint와
   completion을 진행할 수 있다.
5. `BuildMemoryContext`는 raw content를 읽지 않고 현재 Turn 이전의 completed
   user/assistant pair reference를 최신순으로 최대 `maxTurns`개 snapshot한다.
   `ClaimMemoryContextLease`가 current authorization과 revision을 재검증하고 raw를
   process-local로 materialize한다. 선택은 newest-first contiguous barrier다. Missing,
   invalid 또는 serialized token budget을 넘는 pair를 만나면 그 pair와 더 오래된 pair를
   사용하지 않는다. 선택한 pair는 다시 시간순으로 provider context에 넣는다. Empty
   candidate는 explicit complete-empty dependency envelope이며 unknown provenance를 empty로
   승격하지 않는다.
6. Prior Memory context는 untrusted history block으로 직렬화해 현재 user message 바로 앞에
   삽입한다. System/developer prompt와 현재 user prompt의 소유권은 Workflow node에 남고
   Memory content를 instruction이나 system message로 승격하지 않는다.
7. Provider 전송 권한의 canonical source는 ADR-0069의
   `provider_usage_operations`다. 순서는 raw context claim과 최초 full-request 검증,
   usage `intent` commit, current binding 최종 재검증, Memory context-attempt marker commit,
   usage `provider_started` commit, provider I/O다. Memory marker는 context lease lifecycle만
   보호하며 독립 send authority 또는 provider 수신 증거가 아니다. Memory marker만 있고
   usage가 exact `intent`이면 current owner가 모든 binding을 다시 검증한 뒤 같은 attempt의
   usage start까지 한 번 진행할 수 있다. Usage가 `provider_started`, `outcome_unknown` 또는
   terminal이면 어떤 retry도 send 권한을 복원하지 않는다. Usage start commit이 실패하면
   provider를 호출하지 않는다.
8. Provider success 뒤 raw assistant output은 current generation의 Memory-owned provisional
   checkpoint에 먼저 한 번 저장한다. `CompleteTurn` retry는 checkpoint를 읽어 final entry를
   idempotent하게 승인하며 provider를 다시 호출하지 않는다. Public 응답과 turn status는
   승인된 mapped display projection만 반환한다.
9. Public 실행 observability는 explicit public principal과 safe correlation을 가진
   content-free WorkflowRun/WorkflowNodeRun projection이다. App creator를 user로 합성하지
   않고 inputs/outputs는 빈 객체로 유지한다. Observer 장애는 canonical admission, usage,
   Memory completion 또는 public response의 권위가 아니며 durable safe journal로
   reconciliation한다.
10. Production activation은 별도 rollout/readiness gate다. Versioned worker routing,
    retention/physical purge와 legacy cutover가 준비되기 전에는 default-off를 유지한다.

## 구현 결정 기록

### Provider 상한의 production source

- Context: production Worker composition은 public provider 요청에 input/output token과 비용
  상한을 반드시 적용해야 하지만, 이 ADR과 배포 문서에는 승인된 운영 숫자가 아직 없다.
- Options considered: 코드에 임시 기본값을 넣는 방식, graph/public request가 상한을
  전달하는 방식, Worker 환경에서 승인된 값을 필수로 받는 방식을 검토했다.
- Final decision: `MEMORY_RUNTIME_PROVIDER_INPUT_TOKEN_CAP`,
  `MEMORY_RUNTIME_PROVIDER_OUTPUT_TOKEN_CAP`,
  `MEMORY_RUNTIME_PROVIDER_COST_CAP_MICROUSD`를 양의 bounded 정수로 모두 요구한다. 누락
  또는 잘못된 값에는 기본값을 적용하지 않고 provider I/O 전에 fail-closed한다.
- Rationale: 임의 기본값은 승인되지 않은 비용 정책을 만들고, client/graph 값은 public
  caller가 server-owned 상한을 확장하는 경로가 된다. 필수 환경값은 runtime default-off를
  유지하면서 운영 승인과 활성화를 같은 rollout gate에 묶는다.
- Affected files: `apps/workflow_engine/composition/conversation_memory.py`,
  `apps/workflow_engine/tests/test_conversation_memory_composition.py`,
  `docs/features/conversation-memory/component_spec.md`,
  `docs/features/conversation-memory/test_cases.md`.
- Follow-up review: 운영자가 모델 routing과 함께 세 상한을 승인하고 versioned Worker
  queue/capability, Memory schema 및 content key readiness를 확인하기 전에는
  `MEMORY_PUBLIC_RUNTIME_WORKER_READY=true`로 전환하지 않는다.

### Delivery 소유권과 bounded checkpoint recovery

- Context: broker duplicate delivery가 같은 owner를 공유하면 두 Worker가 하나의 live
  lease로 인정돼 늦게 도착한 delivery가 정상 provider 호출을 terminal 처리할 수 있다.
  반대로 checkpoint 뒤 DB 오류를 일반 task 실패로 ack하면 no-replay 복구 경로가 실행되지
  않는다.
- Options considered: broker message별 stable owner와 Celery retry 금지, delivery별 owner와
  무제한 retry, delivery별 owner와 bounded retry를 검토했다.
- Final decision: 각 실제 task invocation은 새 delivery owner를 사용하고, 동일 execution의
  provider attempt/checkpoint identity만 stable하게 유지한다. Active lease의 다른 owner는
  provider/Memory mutation 전에 fence하며 task 예외는 최대 3회의 bounded recovery delivery로
  다시 실행한다. Usage terminal 또는 checkpoint가 있으면 provider send 권한을 복원하지 않고
  terminal projection 또는 checkpoint completion만 재생한다. 첫 recovery countdown은
  production execution lease보다 길게 고정해 새 owner가 active lease에 막힌 채 retry
  budget을 모두 소진하지 않게 한다.
- Rationale: delivery owner는 동시 실행 fencing identity이고 provider attempt는 no-replay
  identity이므로 수명이 다르다. Bounded retry는 transient checkpoint/terminal commit 오류를
  복구하면서 무한 poison-message loop를 막는다.
- Affected files: `apps/workflow_engine/tasks.py`,
  `apps/workflow_engine/application/conversation_memory_execution.py`,
  `apps/workflow_engine/tests/test_conversation_memory_task.py`,
  `apps/workflow_engine/tests/application/test_conversation_memory_admission.py`,
  `apps/workflow_engine/tests/application/test_conversation_memory_execution.py`.
- Follow-up review: 운영 관측은 retry 고갈과 checkpoint reconciliation 실패를 safe code로
  alert하고 raw provider 응답이나 credential detail을 포함하지 않는다.

### Dispatch 재시도 고갈의 terminal scope

- Context: dispatch만 `terminal`로 바꾸면 pending Turn과 provisional user entry,
  `session.active_turn_id`가 남아 이후 모든 turn을 막는다.
- Options considered: dispatch row만 종결, 다음 POST retry에서 lazy reconciliation,
  definitive publish failure 시 Memory scope를 즉시 종결하고 exact retry도 같은 상태를
  복구하는 방식을 검토했다.
- Final decision: 최종 publish attempt가 실패하면 generation-fenced dispatch를 먼저
  terminal로 기록하고, 별도 bounded transaction이 session/Turn/user entry/dispatch binding을
  잠가 Turn failed, entry rejected, active turn released를 함께 commit한다. 이 두 번째
  transaction이 중단돼도 exact retry는 같은 terminal projection을 idempotent하게 완성한다.
- Rationale: broker send 결과와 DB transaction은 원자화할 수 없지만, dispatch terminal
  fence를 권위로 사용하면 ACK race를 덮어쓰지 않으면서 session 점유를 복구할 수 있다.
- Affected files: `apps/memory/application/dispatch.py`,
  `apps/memory/application/public_runtime.py`,
  `apps/gateway/adapters/queue/conversation_turn_publisher.py`와 관련 domain/application/Gateway
  테스트.
- Follow-up review: 운영 dispatch reconciler가 추가되면 같은 terminal finalizer를 재사용하고
  session→Turn→entry→dispatch lock 순서와 current generation 검증을 유지한다.

## 결과

- Public conversation의 raw content는 Memory content store와 provider process-local request
  밖으로 복제되지 않는다.
- Duplicate delivery와 crash window가 Turn, Workflow admission, provider usage와 final entry의
  cardinality를 늘리지 않는다.
- 첫 slice 밖 graph를 묵시적으로 지원하지 않으므로 이후 topology/provenance 확장이
  기존 보안 경계를 약화하지 않는다.
- Memory marker와 usage ledger가 충돌할 때 replay 권위는 usage ledger 하나로 수렴한다.
