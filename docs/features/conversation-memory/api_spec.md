# Conversation Memory API Specification

Status: Draft

## Contract Status

이 문서는 [ADR-0030](../../decisions/ADR-0030-memory-bounded-context.md)과 [ADR-0033](../../decisions/ADR-0033-conversation-memory-contract-completion.md)의 목표 API와 runtime application contract를 정의한다. 아래 session endpoint와 request envelope은 아직 구현되지 않았다. 현재 Chatbot의 `inputs.memory_mode`와 `inputs.conversation_id`는 legacy contract이며 target API에 포함하지 않는다.

Endpoint path는 목표 contract다. 구현 PR은 additive versioning과 guided migration으로 도입하고 기존 Workflow/Chatbot API 문서를 함께 갱신해야 한다. Authenticated internal Chatbot endpoint는 별도 내부 Chatbot 접근 정책·배포 surface 구현에 의존하며 이 Conversation Memory 설계만으로 현재 제공되는 기능이 아니다. Numeric retention/rate limit은 운영 설정이지만 이 문서의 security/idempotency baseline을 완화할 수 없다.

## Authentication And Scope

| Surface | Principal | Conversation access |
| --- | --- | --- |
| Public chatbot | 사용자 identity 없음 | Server-issued public Conversation Access Grant bearer capability |
| Authenticated internal Chatbot | 로그인 사용자 | Current user + organization + 별도 내부 Chatbot 이용 권한 + internal deployment/session scope. 별도 기능 구현 전 미지원 |
| Workflow editor test | 로그인 사용자 | 초기 Conversation Memory session 미지원. 별도 인증·CSRF·idempotency·retention·snapshot binding API가 승인되기 전 일반 test execution만 사용 |
| Schedule/webhook/API batch와 일반 deployment run | 일반적으로 사용자 없음 | 이 version에서는 session 생성 안 함. 후속 명시적 conversational contract 필요 |
| Subworkflow | Parent runtime | Parent가 전달한 bounded Memory Context/channel만 사용, parent table 직접 조회 금지 |

Public Access Grant는 사용자 authentication이 아니지만 secret이다. URL/query와 authentication cookie를 사용하지 않고 redaction 대상 authorization header로만 전달한다.

Execution subject, credential principal, billing principal과 audit actor는 별도 server-derived principal이다. Public Access Grant는 이 중 어느 것도 대신하지 않는다. Public request/grant lifecycle audit은 `actor_id=null`, `actor_type='public'`, 비동기 physical purge/compliance completion은 `actor_type='system'`을 사용하고 app/deployment owner를 actor로 합성하지 않는다.

```http
Authorization: Conversation <opaque-access-token>
```

Raw token은 기본적으로 탭 단위 `sessionStorage`에 보관하고 persistent `localStorage`, URL, browser history, access log, audit, trace와 metric label에 남길 수 없다. V1은 탭/브라우저 간 token 이동이나 기존 session용 별도 grant 발급을 지원하지 않는다. 새 탭에서는 새 idempotency key로 새 conversation을 명시 생성한다. Public API는 credential-less CORS만 허용하고 `Access-Control-Allow-Credentials`를 반환하지 않는다. 허용 origin은 deployment-owned versioned exact origin/embed allowlist로 제한하며 wildcard와 credential을 함께 사용하지 않는다. 이 설정 계약이 구현되기 전 client 입력이나 환경변수 fallback으로 allowlist를 넓혀서는 안 된다.

Browser-facing public conversation create/run/lifecycle 요청은 allowlist에 있는 `Origin`을 필수로 요구한다. Origin 없는 server-to-server 실행은 이 browser grant surface를 사용하지 않고 별도 API-secret/service contract를 사용하며 Conversation Session은 명시적으로 구성해야 한다.

Cookie 기반 authenticated mutation은 session-bound synchronizer token인 `X-CSRF-Token` header와 exact `Origin` 검증을 모두 요구한다. Token은 authenticated bootstrap/session response로 발급하고 authentication cookie 값에서 파생하거나 URL에 넣지 않는다. `Sec-Fetch-Site`가 제공되면 `same-origin` 또는 명시적으로 허용된 same-site 요청만 허용한다. State-changing endpoint는 simple cross-origin request로 호출할 수 없는 JSON contract를 유지한다.

Public token, transcript, turn status와 lifecycle response는 `Cache-Control: no-store`를 반환한다. 인증 응답은 `Cache-Control: private, no-store`를 사용하며 origin에 따라 응답이 달라지는 surface는 적절한 `Vary: Origin, Authorization, Cookie`를 적용한다.

Public conversation page는 `Referrer-Policy: no-referrer`와 strict Content Security Policy를 사용한다. Third-party script와 frame origin은 deployment embed 정책의 reviewed allowlist만 허용하며 inline/raw token telemetry를 금지한다.

## Proposed HTTP Surface

### Public Conversation

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/run-public/{url_slug}/conversations` | Public session과 Access Grant 생성 |
| POST | `/api/v1/run-public/{url_slug}` | 기존 public run에 target `conversation` envelope 추가 |
| GET | `/api/v1/run-public/{url_slug}/conversation/turns/{turn_id}` | 현재 grant의 turn 상태/완료 결과 조회 |
| GET | `/api/v1/run-public/{url_slug}/conversation/transcript` | 허용 시 redacted public transcript 조회 |
| POST | `/api/v1/run-public/{url_slug}/conversation/close` | 현재 grant session close |
| POST | `/api/v1/run-public/{url_slug}/conversation/reset` | 기존 session close + 새 session/grant 발급 |
| DELETE | `/api/v1/run-public/{url_slug}/conversation` | 현재 grant session 접근 차단과 purge 요청 |
| GET | `/api/v1/run-public/{url_slug}/conversation/purge-status` | Purge receipt capability로 삭제 상태 조회 |

Public lifecycle/transcript endpoint는 `Authorization: Conversation ...` header를 요구한다. Invalid, expired, revoked 또는 다른 slug/deployment에 binding된 grant는 resource-hiding response를 반환한다.

### Authenticated Conversation

아래 `/internal-chatbots` prefix는 별도 `authenticated_internal_chatbot` deployment surface가 활성화된 뒤의 목표 prefix다. 최종 route naming은 내부 Chatbot 기능 문서가 소유한다. Public Chatbot route나 current generic `/deployments/{deployment_id}/run`에 optional login을 붙여 private Knowledge를 허용하는 방식으로 구현하지 않는다. 같은 시각 Chatbot component는 재사용할 수 있지만 API adapter, authentication/CORS/Origin, deployment access policy와 session namespace는 분리한다.

| Method | Path | Purpose | Authorization |
| --- | --- | --- | --- |
| POST | `/api/v1/internal-chatbots/{deployment_id}/conversations` | 내부 Chatbot session 생성 | 로그인 + 별도 내부 Chatbot 이용 권한 |
| POST | `/api/v1/internal-chatbots/{deployment_id}/run` | 내부 Chatbot run에 target `conversation` envelope 추가 | 로그인 + 별도 내부 Chatbot 이용 권한 |
| GET | `/api/v1/internal-chatbots/{deployment_id}/conversations/{session_id}/turns/{turn_id}` | Turn 상태/완료 결과 조회 | 현재 subject/session scope |
| GET | `/api/v1/internal-chatbots/{deployment_id}/conversations/{session_id}/transcript` | Redacted transcript 조회 | 현재 subject/session scope |
| POST | `/api/v1/internal-chatbots/{deployment_id}/conversations/{session_id}/close` | Session close | 현재 subject/session scope |
| POST | `/api/v1/internal-chatbots/{deployment_id}/conversations/{session_id}/reset` | Close + 새 session 생성 | 현재 subject/session scope |
| DELETE | `/api/v1/internal-chatbots/{deployment_id}/conversations/{session_id}` | 접근 차단과 purge 요청 | 현재 subject/session scope |
| GET | `/api/v1/internal-chatbots/{deployment_id}/conversation-purges/{purge_request_id}` | Purge 상태 조회 | 현재 subject/deployment scope |

Authenticated endpoint는 client-supplied subject, organization, workflow와 internal deployment scope를 신뢰하지 않는다. Gateway가 현재 user와 active organization, App/Workflow/Deployment를 canonical하게 구성한다. 내부 Chatbot 접근 권한이 없으면 workflow 편집/관리 권한만으로 실행을 허용하지 않는다.

## HTTP Status And Idempotency

| Operation | Initial success | Same-key replay |
| --- | ---: | --- |
| Create public/authenticated session | `201 Created` | 같은 scope/fingerprint면 동일 safe response. Public raw token은 10분 replay TTL 안에서만 재반환하고 이후 `409 memory.secret_replay_expired` |
| Run accepted, still pending/running | `202 Accepted` | 동일 `turn_id`, state와 status URL 반환 |
| Run completed within request wait budget | `200 OK` | 동일 redacted completion response 반환 |
| Close | `200 OK` | 동일 terminal lifecycle response 반환 |
| Reset | `201 Created` | 동일 새 session/grant response 반환 |
| Delete accepted | `202 Accepted` | 동일 purge receipt/reference 반환 |
| Transcript/turn/purge status | `200 OK` | 조회 요청이므로 idempotency key 불필요 |

모든 create/run/close/reset/delete mutation은 `Idempotency-Key`를 요구한다. Authenticated scope는 canonical principal, deployment, operation과 target session이다. Public create는 deployment와 normalized Origin, 이후 public operation은 grant, deployment, operation과 target session을 scope로 사용한다. Public create key는 최소 128-bit random entropy를 요구하고 hash만 장기 식별자로 저장하며 raw key를 access/audit log에 남기지 않는다. Network source는 abuse limit에는 사용하지만 정상 retry의 idempotency scope를 바꾸지 않는다. 같은 key에 다른 bounded fingerprint가 오면 `409 memory.duplicate_request_conflict`를 반환한다. Secret replay ciphertext가 만료된 same-key request는 새 grant/receipt를 만들지 않고 `409 memory.secret_replay_expired`를 반환한다. 새 public conversation은 새 idempotency key로 명시적으로 생성한다. Pending replay는 새 task를 발행하지 않고 기존 상태를 반환하고, failed replay는 같은 safe terminal error를 반환한다.

Public reset/delete의 `memory.secret_replay_expired`는 stored idempotency scope/fingerprint, request grant verifier relation과 high-entropy key가 모두 정확히 일치할 때만 반환한다. 하나라도 불일치하면 revoked/invalid grant와 동일한 resource-hidden 404로 닫아 session 존재나 token lifecycle을 추론하지 못하게 한다.

## Session Models

### Create Public Conversation Response

```json
{
  "conversation": {
    "access_token": "opaque-secret-returned-once",
    "lifecycle_revision": 1,
    "memory_contract_version": "memory-v1",
    "expires_at": "2026-07-12T00:00:00Z"
  }
}
```

- Raw access token은 create 또는 reset replacement 응답에서만 반환한다.
- Internal session ID, token hash, subject hash와 persistence key는 반환하지 않는다.
- Response/log redaction middleware는 `access_token`을 secret field로 처리한다.
- Access token은 versioned CSPRNG token이며 최소 128-bit entropy를 가져야 한다. Server verifier는 HMAC 같은 keyed one-way verifier 또는 승인된 memory-hard password hash와 constant-time comparison을 사용한다.
- Create/reset의 replay record가 필요하면 application-level encryption과 10분 TTL을 적용한다. Grant table의 hash에서 raw token을 복원하지 않는다. TTL 이후 same-key replay는 `memory.secret_replay_expired`다.
- V1은 standalone grant rotation endpoint, rotated-grant chain과 old/new grant grace window를 제공하지 않는다. Reset은 old grant를 즉시 revoke하고 새 session/grant를 원자 발급하는 replacement다.

### Create Authenticated Conversation Response

```json
{
  "conversation": {
    "session_id": "cvs_opaque_public_id",
    "lifecycle_revision": 1,
    "memory_contract_version": "memory-v1",
    "expires_at": "2026-08-01T00:00:00Z"
  }
}
```

`session_id`는 organization/user/deployment scope 밖에서 사용할 수 없다. UUID 여부나 DB primary key를 API contract로 노출하지 않는다.

## Run Request Envelope

Legacy처럼 runtime metadata를 업무 `inputs` 안에 넣지 않는다.

### Public Run

```json
{
  "inputs": {
    "question": "휴가 신청 절차를 알려주세요"
  },
  "conversation": {
    "expected_lifecycle_revision": 1
  }
}
```

```http
Idempotency-Key: req_client_unique_value
```

Public Access Grant는 authorization header로 전달한다. Client가 `subject`, `organization_id`, `session_id`, `memory_contract_version`, `storage_generation`을 body에 추가해도 canonical scope를 변경할 수 없다.

### Authenticated Run

```json
{
  "inputs": {
    "question": "내부 출장 규정을 알려주세요"
  },
  "conversation": {
    "session_id": "cvs_opaque_public_id",
    "expected_lifecycle_revision": 1
  }
}
```

`Idempotency-Key` header는 public run과 동일하게 필수다. Gateway가 이를 canonical request ID로 정규화하며 body의 임의 request ID는 계약에 포함하지 않는다.

### Success Response

```json
{
  "status": "success",
  "results": {
    "answer": "..."
  },
  "conversation": {
    "session_id": "cvs_opaque_public_id",
    "turn_id": "turn_opaque_id",
    "turn_sequence": 4,
    "lifecycle_revision": 1,
    "content_revision": 4,
    "memory_status": "applied"
  }
}
```

Public response는 `session_id`를 생략하거나 public-safe opaque reference만 반환한다. `memory_status`는 `applied`, `not_requested`, `degraded` 같은 safe enum만 허용하며 denied source identity/count와 provider detail을 포함하지 않는다.

Mapped user/final assistant turn write는 conversational surface에서 required다. CompleteTurn이 실패하면 `success` 또는 `memory_status=applied`를 반환하지 않는다. Provider/execution 결과가 durable하게 남아 있으면 retry/reconciliation은 해당 결과를 재사용해 CompleteTurn만 idempotent하게 수행하고 provider와 arbitrary node side effect를 다시 실행하지 않는다.

### Accepted Turn Response

동기 wait budget 안에 완료되지 않은 정상 접수는 timeout 오류로 위장하지 않고 다음 `202 Accepted`를 반환한다.

```json
{
  "status": "accepted",
  "conversation": {
    "turn_id": "turn_opaque_id",
    "turn_state": "pending_dispatch",
    "status_path": "/api/v1/.../conversation/turns/turn_opaque_id"
  }
}
```

Turn status는 `pending_dispatch | queued | running | completed | failed | cancelled`만 노출한다. Pending/failed detail에는 queue name, Worker identity, broker error와 raw exception을 넣지 않는다.

## Transcript Model

```json
{
  "conversation": {
    "state": "active",
    "lifecycle_revision": 1,
    "content_revision": 4,
    "expires_at": "2026-08-01T00:00:00Z"
  },
  "turns": [
    {
      "turn_id": "turn_opaque_id",
      "sequence": 1,
      "state": "completed",
      "user": {"content": "redacted display content"},
      "assistant": {"content": "redacted display content"},
      "created_at": "2026-07-11T10:00:00Z"
    }
  ],
  "next_cursor": null
}
```

- Transcript는 bounded page size와 opaque cursor를 사용한다.
- Raw prompt, Memory summary, Data Dependency, private source identity와 authorization reason을 반환하지 않는다.
- Public transcript를 지원하면 해당 public session에서 생성된 redacted display turn만 반환한다.
- Failed/cancelled turn은 state, timestamp와 safe failure reason만 표시한다. Authenticated owner에게 redacted user display entry를 반환할 수 있지만 public transcript에는 failed assistant content와 partial output을 반환하지 않는다.
- Transcript가 보인다는 사실이 같은 turn이 현재 LLM Memory Context에 포함된다는 뜻은 아니다.
- Closed session은 retention 기간 동안 authenticated owner 또는 transcript-only로 제한된 public grant에 redacted transcript를 반환할 수 있지만 runtime context와 mutation은 차단한다. Reset/delete는 기존 grant를 revoke한다. Delete-pending/deleted session은 transcript 대신 resource-hiding response를 반환한다.

## Lifecycle Requests

Close/reset/delete는 stale client가 최신 session을 변경하지 못하도록 lifecycle revision을 body와 중복하지 않고 `If-Match` header로만 전달한다. Mutation idempotency는 별도 header를 사용한다.

Create/run/transcript/turn/close/reset response는 현재 session의 `ETag: "lifecycle-revision-N"`을 반환한다. Reset은 새 session ETag를 response header에 두고 old terminal revision은 body의 previous conversation summary에 포함한다.

```http
If-Match: "lifecycle-revision-1"
Idempotency-Key: req_lifecycle_unique_value
```

Reset success는 새 session 또는 새 public access token과 기존 session의 terminal 상태를 함께 반환한다. Delete는 접근 차단이 durable하게 기록된 뒤 성공해야 하며 물리 purge 완료를 거짓으로 동기 응답하지 않는다.

```json
{
  "status": "delete_pending",
  "purge_request_id": "purge_opaque_id",
  "purge_receipt": "opaque-secret-returned-for-public-delete-only"
}
```

Authenticated caller는 `purge_request_id`와 현재 authentication으로 상태를 조회한다. Public delete는 grant를 즉시 revoke하므로 별도 short-lived `Authorization: Purge <receipt>` capability를 사용한다. Receipt source-of-truth는 verifier hash만 저장하고 URL에 넣지 않는다. Delete 응답 유실 뒤 같은 idempotency key에 receipt를 재반환해야 하면 최대 24시간의 encrypted response replay store를 사용한다. 상태 응답은 `pending | running | completed | completed_with_hold | retryable_failure | terminal_failure`와 safe timestamp/reason만 반환한다. Public purge는 발급 후 7일 안에 terminal 상태로 전이하며 receipt는 terminal 후 최소 24시간, 발급 후 최대 8일까지 유효하다. Public response는 legal-hold 내부 사유를 숨기고 retention notice만 표시한다. `completed_with_hold`는 runtime/compliance 격리가 durable하다는 뜻이며 물리 삭제나 `memory.session.purged` 완료를 뜻하지 않는다.

Response/log redaction middleware는 `purge_receipt`도 `access_token`과 동일한 secret field로 처리한다.

## Internal Application Contracts

HTTP/Celery adapter는 다음 framework-independent command/query를 호출한다. 이름은 목표 capability이며 ORM CRUD API가 아니다.

### ResolveConversationSession

입력:

- canonical organization/app/workflow/deployment ID와 immutable version 또는 snapshot hash
- conversation mapping/Memory policy version
- verified execution subject 또는 public audience
- validated Access Grant hash/reference
- runtime surface (`public_chatbot | authenticated_internal_chatbot`). 초기 구현은 `public_chatbot`만 허용하며 `workflow_editor_test`는 별도 계약 전 거부한다.

출력:

- internal session reference
- lifecycle/content revision
- active turn 상태
- retention policy reference
- deployment/mapping/Memory policy binding
- memory contract/storage generation

기존 session binding과 요청 deployment version이 다르면 active deployment pointer로 자동 rebind하지 않는다. Public route는 session 존재를 숨기고 새 conversation을 요구한다. Authenticated internal route는 `memory.deployment_version_changed`와 safe new-session action을 반환한다.

### StartTurn

입력:

- session reference
- canonical request ID와 bounded fingerprint
- expected lifecycle revision
- redacted user display/memory projection
- server-derived RuntimeDataDependencyEnvelope

출력:

- turn ID/sequence/version
- started lifecycle revision
- durable dispatch job ID/state
- idempotent existing result 여부

### Dispatch Commands

`ClaimTurnDispatch`, `MarkTurnDispatchPublished`, `ObserveWorkflowAdmission`, `ObserveTurnExecutionState`, `ReconcileTurnDispatch`는 dispatch ID, expected state/version, fencing generation과 safe outcome을 입력으로 받는다. 각 command는 typed next state와 idempotent existing result를 반환한다.

Workflow `AdmitExecution(dispatch_id)`은 별도 Workflow application contract다. Memory는 Workflow admission lookup port로 acknowledgement 유실을 복구하지만 execution lease/heartbeat를 변경하지 않는다. Persistence/Celery adapter는 command 없이 dispatch/turn state를 직접 변경할 수 없다.

### BuildMemoryContext

입력:

- session/turn/node reference
- canonical execution subject/audience
- versioned node Memory policy
- server-issued `purpose=main_generation` ProviderExecutionCapability reference
- bounded token/turn budget

출력:

- opaque ContextMaterializationPlan handle
- short-lived context lease
- source/content revision
- safe decision metadata
- summary usage result 또는 degraded reason

`BuildMemoryContext`는 summary가 필요하면 provider/usage/projection side effect가 있으므로 순수 query로 간주하지 않는다. Raw context는 이 응답에 포함하지 않는다.

### ClaimMemoryContextLease

Main provider adapter가 provider 호출 직전에 사용하는 internal contract다.

입력:

- context handle과 lease
- session/turn/node invocation
- canonical execution subject/audience
- server-issued provider attempt ID
- server-issued ProviderExecutionCapability

출력:

- idempotent claimed raw bounded context 또는 fail-closed decision
- materialized context와 정확히 대응하는 server-derived RuntimeDataDependencyEnvelope
- authorization decision/resource/policy revision set와 principal kind
- provider attempt state와 claim deadline

Context handle은 raw text가 아니라 ordered entry/summary reference, version과 server-keyed content digest를 가진 short-lived materialization plan이다. Digest는 API/telemetry에 노출하지 않는다. Lease claim, ProviderExecutionCapability 검증, current authorization 재검증과 raw context materialization은 같은 trusted adapter operation이다. 같은 attempt retry는 idempotent하고 다른 attempt의 active claim 탈취, capability/expiry/invalidation/version mismatch는 context를 반환하지 않는다.

### ResolveProviderExecutionCapability

LLM Credentials domain의 authoritative internal port를 호출해 opaque capability identity/revision을 받는다. 상세 입력·출력 schema와 credential principal/permission decision revision 의미는 [LLM Credentials API Spec](../llm-credentials/api_spec.md#target-provider-execution-capability-contract)이 소유한다. Workflow Runtime은 provider effect 전에 server-issued provider attempt reference를 먼저 만들고 capability 발급 입력에 포함한다. Memory는 main-generation capability를 `BuildMemoryContext` 전에 받아 lease에 binding하고 claim에서 같은 identity/revision, session/deployment version, node invocation, purpose와 provider attempt를 다시 검증한다. Client, Access Grant와 Memory adapter는 provider/model/credential을 직접 선택하거나 capability scope를 확장할 수 없다. Credential revoke 또는 permission/relation/egress revision 변경 뒤 stale capability는 새 claim·reservation·provider attempt admission과 outbound call 전에 거부한다.

### MarkMemoryContextProviderStarted

Provider adapter는 outbound call 직전에 provider attempt ID와 expected attempt version을 전달해 `provider_started`를 durable하게 기록한다. Marker commit이 실패하면 provider를 호출하지 않는다. Claim 후 이 marker 전 crash만 claim expiry 뒤 새 lease/attempt로 재승인할 수 있다.

### RecordMemoryContextProviderOutcome

Provider attempt ID, expected version, terminal/unknown state와 normalized usage reference를 기록한다. `provider_started` 이후 timeout/crash/ambiguous outcome은 `outcome_unknown`이며 provider를 자동 재호출하지 않고 reconciliation 또는 safe node failure로 닫는다.

### RuntimeDataDependencyEnvelope

Workflow Runtime 내부 result/task contract이며 business `inputs`, client response와 arbitrary node payload에 넣지 않는다.

| Field | Contract |
| --- | --- |
| `envelope_version` | Server-supported version. Unknown version은 fail-closed |
| `completeness` | `complete` 또는 `unknown`. V1은 `complete`만 Memory write에 허용 |
| `dependencies` | Bounded, deduplicated server-derived dependency list. 값 dependency와 결과를 선택한 활성 control dependency의 필수 합집합. Complete empty list는 값·제어 source 영향이 없음을 producer가 확인한 경우에만 허용 |

각 dependency는 server-issued opaque dependency reference, source kind, organization safe reference, canonical resource/version safe reference, sensitivity, current authorization adapter가 사용할 authorization-safe lookup reference를 포함한다. Raw source title/path/URL/content/ACL, client subject, optional/required flag와 provider credential을 포함하지 않는다. Condition/Switch는 predicate와 선택 route, Loop는 iterable/bound/continue/termination 판단의 dependency를 active control context로 전달한다. 선택된 branch의 상수 output도 control dependency를 상속하고 선택되지 않은 branch의 값 dependency는 제외한다. Missing envelope, `unknown` completeness, unknown source kind, duplicate conflict, organization mismatch와 count/size cap 초과는 `memory.provenance_incomplete` 또는 `memory.provenance_invalid`로 처리하고 private/sensitive Memory write를 거부한다.

### EvaluateSourceAuthorization

Source-owning domain port의 bulk 응답은 각 dependency에 대해 `decision`, `principal_kind`, opaque `authorization_decision_revision`, `resource_revision`, `policy_revision`, `evaluated_at`을 반환한다. Source ACL이 있는 resource는 ACL revision을 decision revision에 반영한다. Public audience는 `anonymous_public_audience` principal kind를 사용하며 subject revision을 합성하지 않는다. 필요한 revision 또는 source result가 없으면 `unknown`으로 취급하고 entry를 제외한다.

### CompleteTurn

입력:

- session/turn/request/execution reference
- expected turn version와 started lifecycle revision
- mapped final assistant display/memory projection
- final RuntimeDataDependencyEnvelope
- execution terminal state

출력:

- terminal turn state
- content revision
- idempotent existing result 여부

Turn terminal state, Session active-turn/content revision, final entry/projection과 required outbox는 같은 UnitOfWork에서 commit/rollback한다.

## Node Memory Configuration

목표 graph schema 초안:

```json
{
  "memory": {
    "enabled": true,
    "channel": "conversation",
    "readSource": "conversation_turns",
    "writeMode": "none",
    "maxTurns": 5,
    "maxContextTokens": 1200,
    "strategy": "window_then_summary",
    "summaryModelPolicy": "inherit_node",
    "failurePolicy": "continue_without_memory"
  }
}
```

초기 제한:

- `enabled`: default false
- `channel`: bounded normalized identifier
- `readSource`: `conversation_turns | selected_nodes`
- `writeMode`: `none | node_output`
- `selectedNodeIds`: 같은 graph 안의 allowlist
- `maxTurns`: bounded positive integer
- `maxContextTokens`: server upper bound 이하
- `strategy`: `window | window_then_summary`
- `summaryModelPolicy`: 초기에는 `inherit_node`만 허용. 별도 organization model/credential preset ADR과 구현 전에는 `organization_default` 미지원
- `failurePolicy`: `continue_without_memory | fail_node`

Arbitrary SQL/filter, free-form provider options와 user-global scope는 허용하지 않는다. Numeric bound는 finite server configuration으로 제공하고 설정 누락 시 안전 기본값을 적용한다. Client 값으로 server upper bound를 완화할 수 없다.

## Error Contract

Application/domain error는 FastAPI `HTTPException`에 의존하지 않는다. Inbound adapter가 기존 resource-hiding 및 API 계약에 맞게 mapping한다.

| Code | Suggested HTTP | Meaning |
| --- | ---: | --- |
| `memory.session_hidden` | 404 | Tenant/resource/audience 또는 Access Grant scope 불일치 |
| `memory.session_closed` | 409 | Authenticated owner의 closed session runtime read/mutation. Retention transcript는 별도 허용 |
| `memory.stale_lifecycle_revision` | 409 | Expected lifecycle revision 불일치 |
| `memory.active_turn_conflict` | 409 | 같은 session에 처리 중인 turn 존재 |
| `memory.stale_turn_version` | 409 | Pending turn version 불일치 |
| `memory.duplicate_request_conflict` | 409 | 같은 request ID에 다른 fingerprint |
| `memory.secret_replay_expired` | 409 | Secret replay ciphertext 만료. Same key로 새 grant/receipt를 만들지 않음 |
| `memory.dispatch_state_conflict` | internal conflict | Dispatch expected state/version/fencing generation 불일치 |
| `memory.provider_attempt_conflict` | internal conflict | 다른 attempt의 active lease claim 또는 stale attempt version |
| `memory.provider_outcome_unknown` | node failure/reconciliation | Provider-start 이후 outcome 불명확. 자동 provider retry 금지 |
| `memory.input_mapping_invalid` | 422 | Conversational input/output mapping 부재 또는 불일치 |
| `memory.authorization_denied` | 응답 비노출 또는 policy mapping | Entry 제외, source 상세 비노출 |
| `memory.authorization_unavailable` | 503 또는 node failure policy | Current authorization 결과 불명확 |
| `memory.provenance_incomplete` | node/turn failure policy | Required server-derived envelope가 없거나 completeness unknown |
| `memory.provenance_invalid` | node/turn failure policy | Unknown kind, conflicting duplicate, tenant mismatch 또는 size/count cap 위반 |
| `memory.budget_denied` | 429 또는 node failure policy | Summary reservation 거부 |
| `budget.price_unavailable` | node failure policy | Summary 예상 가격 불명확. Provider 미호출, window/fail policy 적용 |
| `memory.adapter_unavailable` | 503/504 또는 failure policy | Store/provider adapter 장애 |
| `memory.rate_limited` | 429 | Grant/deployment/network/organization limit 초과. Safe `Retry-After` 제공 |
| `memory.csrf_rejected` | 403 | Authenticated mutation의 CSRF/Origin/Fetch Metadata 검증 실패 |
| `memory.worker_incompatible` | 503 | Worker가 task contract/storage generation을 side effect 전에 거부 |
| `memory.deployment_version_changed` | 409 authenticated only | Session이 고정된 deployment/mapping/policy version과 요청 version이 다름. Public route는 404 hiding |

Public invalid/expired/revoked/wrong-scope grant와 public session lifecycle probe는 모두 `memory.session_hidden` 404로 통일한다. `memory.session_closed` 409는 authenticated owner가 자신의 session lifecycle을 확인한 경우에만 사용한다. Error detail에는 raw token, content, source identity, credential/provider raw error와 exact denied count를 포함하지 않는다.

## Compatibility

- `inputs.memory_mode`와 `inputs.conversation_id`는 target API에서 제거 대상이다.
- Legacy flag를 수용하더라도 provenance 없는 execution log history를 Memory Context로 읽지 않는다.
- Gateway는 deployment snapshot의 Memory contract/storage generation과 Worker capability로 실행 경로 하나만 선택한다.
- Session은 생성 시 deployment ID/version 또는 snapshot hash와 mapping/Memory policy version에 고정하며 active deployment 변경 시 자동 rebind/migration하지 않는다.
- Target Memory task는 rolling migration 동안 versioned queue 또는 capability 전용 worker pool로 전달하고 Worker가 side effect 전에 envelope capability를 재검증한다.
- New Client는 versioned Gateway capability 확인 후 rollout하지만 client check를 보안 경계로 사용하지 않는다.
