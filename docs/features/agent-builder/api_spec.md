# Agent Builder API Specification

Status: Draft

## 1. Contract Boundary

이 문서는 Accepted ADR-0045/ADR-0046의 direct-edit API와 ADR-0054의 생성 모드·전환 목표 API를 정의한다. ADR-0019는 Superseded Preview 기록이며 기존 결과는 characterization fixture로만 사용하고 direct-edit parity와 필수 검증 뒤 Preview API/UI를 제거한다. MBA-293 시점 코드는 기존 두 mode만 구현했으므로 `quick_generate`와 전환 endpoint는 후속 구현 전까지 제공되는 API로 간주하지 않는다.

모든 endpoint는 인증과 `X-Organization-Id`를 요구한다. Client는 raw workflow graph, credential config, secret value를 Agent Builder API로 보내지 않는다. Backend는 server-loaded workflow graph hash, workflow `updated_at`과 catalog version을 기준으로 판단한다. 신규 direct-edit session의 target contract는 단일 catalog v3다. 기존 Preview protocol session은 cutover 뒤 `stale_protocol`로 복구하며 미적용 draft를 새 protocol로 변환하지 않는다. Generation mode의 외부 표현은 선택적 `X-Agent-Builder-Mode-Contract` 헤더로 협상하고 내부 domain·저장 metadata의 canonical mode와 구분한다.

Base path는 `/api/v1/agent-builder`다.

## 2. Common Types

### 2.1 GenerationMode

```text
guided_generate | quick_generate | structure_only
```

`configure_and_generate`는 입력과 기존 JSON row를 위한 `guided_generate` 호환 별칭이다. Gateway 내부 domain은 canonical 값으로 정규화하며 기존 row를 backfill하지 않는다. 외부 응답은 2.1.4의 negotiated contract를 따른다. Mode가 없으면 내부 기본값은 `guided_generate`다.

### 2.1.1 GenerationModeSource

```text
default | explicit_control
```

Client는 화면 초기값에는 `default`, 사용자가 mode control을 조작한 뒤에는 `explicit_control`을 보낸다. 명시적 control 선택이 자연어 mode intent보다 우선하고, 그 다음 명시적 자연어 intent, 마지막으로 default guided를 적용한다. Legacy client가 mode만 보내고 source를 생략하면 해당 값은 `explicit_control`로 해석해 기존 동작을 보존한다.

### 2.1.2 Request And Proposal Version

`request_version`은 기존 request `response_payload`에 저장하는 1부터 시작하는 단조 증가 정수다. Mode transition, quick-completion proposal 생성·acknowledgement처럼 task version만으로 보호할 수 없는 상태 변경은 parent request row lock 안에서 expected request version을 비교하고 성공 시 증가시킨다. `proposal_version`도 proposal별 1부터 증가하며 둘 다 신규 DB column을 요구하지 않는다.

### 2.1.3 QuickCompletionProposalStatus

```text
pending | acknowledged | canceled | stale
```

### 2.1.4 Generation Mode Contract Negotiation

Client는 Agent Builder endpoint에 다음 선택적 요청 헤더를 보낼 수 있다.

```text
X-Agent-Builder-Mode-Contract: legacy-v1 | canonical-v2
```

- 헤더가 없거나 `legacy-v1`이면 외부 request/response mode 표현은 `configure_and_generate|structure_only`다. `canonical-v2`이면 외부 표현은 `guided_generate|quick_generate|structure_only`다.
- Gateway는 negotiated contract가 허용한 입력 표현을 내부 canonical mode로 정규화하고 같은 이름의 응답 헤더로 실제 적용한 contract를 반환한다. 지원하지 않는 contract 값은 canonical로 추측하지 않고 `400 unsupported_mode_contract`로 거부한다.
- Contract는 planner 호출과 request row 생성 전에 확정한다. `legacy-v1`의 `generation_mode_source=default` 요청에서 planner가 자연어 quick 의도를 감지해도 resolver는 requested mode를 `guided_generate`로 유지하고 legacy `configure_and_generate` 응답만 만든다. `mode_transition_required`와 quick metadata는 생성하지 않는다. Legacy 표현으로 `quick_generate`를 직접 보내면 request row를 만들기 전에 `400 unsupported_generation_mode`로 거부한다.
- Request가 아직 없는 `POST /sessions`는 해당 호출의 header로만 응답 표현을 정하고 session에 contract를 고정하지 않는다.
- `POST /sessions/{session_id}/messages`가 request를 만들 때 정규화한 `mode_contract_version=legacy-v1|canonical-v2`를 기존 request `response_payload`에 고정한다. Raw header는 저장하지 않고 contract 값이 없는 기존 request는 `legacy-v1`로 읽는다.
- Active request를 조회·전환·acknowledge하는 후속 endpoint는 고정된 contract와 같은 header를 요구한다. 헤더 생략은 `legacy-v1`로 해석하며, 불일치하면 request mode나 payload를 다른 표현으로 projection하지 않고 `409 mode_contract_mismatch`와 safe `request_id`, `required_mode_contract`만 반환한다.
- Session timeline의 terminal request는 각 request에 저장된 `mode_contract_version`과 mode 의미를 유지한다. Mixed history는 dual-read Client가 request별 contract로 해석하며 canonical quick을 legacy guided로 축소 projection하지 않는다.
- Request cancel endpoint는 예외적으로 mode-free contract-neutral 응답을 사용해 동일한 인증·권한 아래 contract 불일치 상태에서도 request를 종료할 수 있다.
- 저장된 mode와 audit mode는 항상 canonical이며 request-scoped contract는 외부 representation 선택에만 사용한다.
- `quick_generate`는 `canonical-v2`와 Backend·Frontend integration gate가 모두 활성화된 경우에만 허용한다.

Contract 불일치 응답은 active request 내용을 포함하지 않는다.

```json
{
  "code": "mode_contract_mismatch",
  "request_id": "uuid",
  "required_mode_contract": "canonical-v2"
}
```

### 2.2 RequestStatus

```text
planning | clarification_required | mode_transition_required | graph_mutation_ready | parameter_configuration |
completed | configuration_required | stale | stale_protocol | validation_failed | unsupported | failed | canceled
```

앞의 다섯 값은 비종료 상태이고 뒤의 여덟 값은 종료 상태다. `configuration_required`는 intent model/credential route를 선택한 새 request가 필요한 기존 terminal 상태다. 모든 비종료 상태는 9절의 contract-neutral request cancel로 종료할 수 있어야 하며, 기능별 endpoint가 별도 취소 allowlist를 만들지 않는다.

### 2.3 ParameterInputType

```text
text | textarea | code | json | number | boolean | select |
resource_ref | credential_ref | variable_selector
```

### 2.4 ParameterTaskStatus

```text
pending | active | completed | deferred | skipped | invalid | canceled
```

### 2.5 ParameterGroupStatus

```text
pending_save | pending_ack | active | completed | blocked | canceled
```

`ParameterGroupStatus`는 workflow graph 저장과 acknowledgement 경계를 나타내고,
`ParameterTaskStatus`는 group 내부 개별 입력 항목의 진행 상태를 나타낸다.

### 2.6 GraphMutationKind

```text
initial_graph | graph_edit | replace_workflow | parameter_update | knowledge_binding
```

### 2.7 GraphMutationStatus

```text
pending_apply | pending_save | pending_ack | acknowledged | blocked | reverted
```

### 2.8 GraphMutationOperation

```text
add_node | remove_node | add_edge | remove_edge | replace_node_data
```

모든 operation은 `op` discriminator를 사용한다. 임의 JSON Patch path, raw graph
snapshot과 node type별 optional mutation field는 허용하지 않는다.

### 2.9 MutationSaveAction

```text
apply | revert | redo
```

`apply`는 발급된 GraphMutation 결과를 저장한다. `revert`는 completed Agent Builder history boundary의 시작 전 graph를 복구하고, `redo`는 reload 전 client memory에 남은 final graph를 다시 저장한다.

### 2.10 Catalog And Protocol Version Gate

새로 발급하는 모든 `GraphMutation`의 API 응답에는 full typed operations를 포함하지만,
복구용 `AgentBuilderRequest.response_payload` JSON에는 operations를 제외한 safe operation
envelope와 `catalog_version=3`만 기록한다.
`catalog_version`이 없거나 `2`인 미적용 operation은 legacy로 분류해 `stale`
처리한다. `catalog_version=3`인 operation만 current catalog validation을 통과한
뒤 적용·CDS 저장·acknowledgement할 수 있다. Catalog version, canonical/requested/effective generation mode와 transition 상태는 JSON metadata를 재사용하며 별도 column이나 legacy backfill을 요구하지 않는다.

Session protocol은 additive migration으로 추가하는 nullable
`AgentBuilderSession.protocol_version`에 기록한다. MBA-228 단일 기능 PR의 신규 direct-edit
session은 `direct_edit_v1`을 저장하며 기존 null row는 backfill하거나 자동 변환하지 않는다.
Gateway는 null/`direct_edit_v1`을 함께 읽고 null Preview session을 `stale_protocol`로 복구한다.
`generation_mode`는 request마다 달라질 수 있으므로 request `response_payload`에만 기록한다. 기존 `configure_and_generate`는 조회 시 canonical `guided_generate`로 정규화한다.
Repository는 payload 내부 dict를 제자리 변경하지 않고 새 전체 JSON 객체를 column에 재할당한다.
Frontend와 Gateway의 무중단 전환, 배포 gate와 image artifact 분리는 별도 배포 계약에서 다룬다.

### 2.11 Edit Target Reference

`between` insertion의 target은 다음 중 하나다.

- `selected_edge`: request의 `selected_edge_id`가 server graph에 존재해야 한다.
- `natural_language_edge`: `source_query`와 `destination_query`를 모두 포함한다. Server는 각 query를 저장 graph node로 resolve한 뒤 source에서 destination으로 향하는 직접 edge가 정확히 하나일 때만 target을 확정한다.
- Server는 자연어 node query에서 `data.title`을 먼저 비교하고, 제목 불일치 시에만 예약 구조 node의 `입력`/`시작` 및 `응답`/`출력` 별칭을 각각 `startNode`와 `answerNode`로 해석한다. 별칭 후보가 복수이면 edge 선택 clarification을 반환한다.

`natural_language_edge`의 direct edge가 0개 또는 복수이면 response는 typed edge 선택 clarification을 반환한다. Server는 multi-hop path를 탐색하거나 edge를 임의로 선택하지 않는다.

### 2.12 ParameterSuggestion

Selector suggestion은 backend가 발급하고 client가 임의로 구성하지 않는다.

```json
{
  "suggestion_id": "opaque-id",
  "kind": "variable_selector",
  "label": "Webhook PR 번호",
  "description": "Webhook payload의 pull_request.number 값을 사용합니다.",
  "source_node_id": "node-webhook",
  "output_key": "payload",
  "value_type": "number",
  "value_selector": ["node-webhook", "payload", "pull_request", "number"],
  "json_path": "$.pull_request.number"
}
```

- `value_selector`는 runtime 표준인 `[source_node_id, output_key, ...nested_path]`다.
- `json_path`는 같은 nested path를 표시하기 위한 safe metadata이며 decision의 별도 권위값이 아니다.
- `source_node_id`, `output_key`, nested path와 `value_type`은 current graph와 catalog output contract로 다시 검증한다.
- Resource/credential 후보는 같은 envelope에서 각각 `kind=resource_ref`/`credential_ref`와 권한 검증된 opaque resource id만 제공한다. Credential 후보는 durable credential resource와 use 권한 resolver가 존재하는 provider에만 제공하고 node runtime의 provider/auth compatibility로 추가 필터한다. `gmailDraftNode.credential_id`는 `provider=gmail`, `auth_type=oauth2`인 use-permitted credential만 후보와 `set` 제출에 허용한다. Slack/GitHub credential은 `direct_edit_v1` ParameterTask response에 포함하지 않으며, 해당 node는 기존 Editor 연결 설정에서만 구성한다.

### 2.12 ParameterDecisionValue

`action=set`의 `value`는 `kind` discriminator를 사용하는 union이다.

| kind | Required fields | Rule |
|---|---|---|
| `text` / `textarea` / `code` / `select` | `value: string` | catalog length/pattern/options 검증 |
| `json` | `value: any` | catalog type/schema 검증 |
| `number` | `value: number` | catalog min/max 검증 |
| `boolean` | `value: boolean` | boolean만 허용 |
| `resource_ref` | `resource_id` | active organization과 resource use 권한 검증 |
| `credential_ref` | `credential_id` | safe reference와 credential use 권한만 검증; config/secret 금지 |
| `variable_selector` | `suggestion_id`, `value_selector` | server-issued suggestion과 runtime selector contract 재검증 |

### 2.13 ParameterGuidanceHint

Planner가 최초 자연어 요청 한 번에서 만드는 설명 전용 hint다.

```json
{
  "step_id": "step-slack",
  "parameter_key": "channel",
  "reason": "메시지를 전달할 대상을 정하기 위해 필요합니다.",
  "input_guidance": "권한이 있는 Slack 채널을 선택합니다."
}
```

- Planner prompt에는 capability Catalog가 허용한 parameter key와 safe label만 제공한다.
- `step_id`는 현재 structured plan step이어야 하고 `parameter_key`는 해당 step capability의 Catalog에 있어야 한다.
- Unknown step/key, capability mismatch 또는 secret-like hint는 폐기하며 task description은 Catalog 설명으로 fallback한다.
- Hint는 설명용이며 parameter 존재 여부, 타입, required, validation, default 또는 실제 값을 결정하지 않는다.
- Planner client가 strict JSON Schema response format을 지원하면 `AgentBuilderIntentExtraction` Pydantic schema를 provider 형식에 맞게 전달한다. 지원하지 않는 provider/model은 JSON object mode와 동일한 Pydantic/semantic validation을 유지한다.
- Planner 출력 한도는 schema의 모든 typed field와 reasoning을 포함한 정상 응답이 잘리지 않도록 `max_tokens=4000`을 사용한다. 이 값은 응답 최대치이며 parameter별 추가 Planner 호출을 허용하지 않는다.

### 2.14 KnowledgePlacement

Planner는 KB 선택별 완성 graph 대신 Knowledge가 base topology에 미치는 관계만 반환한다.

```json
{
  "requirement_id": "knowledge-project-docs",
  "timing": "before_graph",
  "target_step_id": "step-llm",
  "effect_kind": "insert_step",
  "knowledge_step_id": "step-knowledge",
  "upstream_step_id": "step-input",
  "downstream_step_id": "step-llm",
  "empty_selection_bridge": "connect_upstream_to_downstream"
}
```

- `timing`은 `before_graph|after_graph`다.
- `effect_kind`는 `binding_only|insert_step`다.
- `binding_only`는 `timing=after_graph`와 `target_step_id`만 사용하고 topology를 바꾸지 않는다.
- `insert_step`은 `timing=before_graph`, Knowledge step과 upstream/downstream step을 모두 요구한다.
- `empty_selection_bridge`는 `insert_step`에서만 필요하며 `connect_upstream_to_downstream`만 허용한다. Bridge가 유효한 graph를 만들 수 없으면 validation failure다.
- 모든 step reference는 같은 structured plan에 존재해야 하고 Knowledge capability와 연결은 Catalog가 검증한다.
- Planner는 node data, edge 원문, 선택별 graph snapshot 또는 KB id를 만들지 않는다.

### 2.15 Request Aggregate Invariants

`AgentBuilderRequest`는 mode transition, safe GraphMutation envelope, ParameterTask, Knowledge resolution, quick-completion proposal와 operation idempotency result의 aggregate root다. API 구현은 다음 순서를 공통으로 적용한다.

| Operation | Preconditions and fencing | Atomic result |
| --- | --- | --- |
| Message submit | Session row lock, 비종료 request 0건 | `planning` request 1건 생성 |
| Pre-save operation loss recovery | Workflow/request lock, 저장 결과 없음 | envelope `blocked`; request cancel 완료 전 신규 message 거부 |
| Quick-completion proposal create | Request lock, expected request version, 대상 task current version | request와 대상 task version 증가, pending proposal이 fenced version 예약 |
| Proposal acknowledge/cancel/stale | Request lock, proposal/fenced task version | proposal terminal; acknowledge만 task completed와 task version 재증가 |
| Session-scoped cancel | Session lock, 같은 operation result 우선 조회 | 과거 결과 반환 또는 유일한 현재 비종료 request 취소 |
| Request cancel | `Workflow -> AgentBuilderRequest`; session-scoped이면 Session 선행 | request와 모든 비종료 child를 같은 transaction에서 terminal 처리 |

공통 lock 순서는 `AgentBuilderSession -> Workflow -> AgentBuilderRequest`이며 operation에 필요하지 않은 앞쪽 row만 생략한다. Terminal request 아래에는 pending proposal, `pending|active|invalid` task, 미완료 Knowledge resolution 또는 저장 전 pending envelope가 남을 수 없다. Pending proposal이 예약한 task는 proposal이 terminal이 되기 전 다른 decision을 받지 않는다. 같은 operation id의 persisted result는 현재 active request나 task를 선택하기 전에 조회한다.

## 3. Model Options

### GET `/model-options`

현재 endpoint를 유지한다. 응답은 provider group과 사용 가능한 credential/model pair만 반환한다.

이 endpoint의 권한 검증과 정렬은 ADR-0040의 통합 추천 계약이다. MBA-228은 정렬 정책을 변경하지 않고 최신 dev 동작의 회귀만 확인한다.

정렬 계약:

1. provider: `openai`, `anthropic`, `google`; `llamaparse`는 disabled group
2. provider 내부: 최신 generation 우선
3. 같은 generation: `general`, `mini`, `nano`, `pro`
4. 같은 tier: suffix 없는 기본형, 날짜 또는 명시 release snapshot, `preview`, `latest`
5. 그 뒤 verified relation priority, safe display name과 안정적인 식별자로 결정적 정렬

후보는 active organization의 valid credential, active chat model, provider 일치, verified relation과 사용자 credential `use` 권한을 모두 통과해야 한다. 같은 model/credential 관계가 중복이면 가장 낮은 relation priority 하나만 사용한다. 정규화한 model ID로 특수 목적이 확정된 모델은 제외하며, 세대나 tier를 해석하지 못한 verified chat model은 해당 provider의 해석 가능한 후보 뒤에 안정적으로 유지한다. Header의 첫 option과 새 generated LLM node 추천은 같은 후보 집합에서 같아야 하지만 사용자가 Header에서 바꾼 선택은 workflow node로 복사하지 않는다. 선택 id는 message마다 재검증하며 session이나 graph에 저장하지 않는다.

## 4. Session

### POST `/sessions`

다음 예시는 `X-Agent-Builder-Mode-Contract: canonical-v2`를 보낸 경우다. 헤더가 없거나 `legacy-v1`이면 `default_generation_mode`는 `configure_and_generate`로 반환한다. Response에도 실제 적용한 contract를 같은 이름의 헤더로 반환한다.

Request:

```json
{
  "workflow_id": "uuid",
  "app_id": "uuid"
}
```

Rules:

- Direct-edit session은 기존 Editor 생성 흐름으로 만들어진 `workflow_id`를 요구한다. Server는 workflow graph hash와 `updated_at`을 읽고 read/write 권한을 확인한다.
- 새 workflow 요청은 저장된 빈 workflow shell에 `initial_graph` mutation을 적용한다. Agent Builder session endpoint가 workflow row를 생성하지 않는다.
- client graph snapshot은 허용하지 않는다.
- current editor에 미저장 변경이 있으면 client는 autosync를 완료한 뒤 session을 시작해야 한다.
- Server는 신규 session의 `protocol_version`을 `direct_edit_v1`로 저장한다. Request가 아직 없는 session도 이 값으로 protocol을 판별하며 기존 null session은 `stale_protocol`로 복구한다.
- Generation mode contract header는 session row나 `protocol_version`에 복제하지 않는다. Message request가 생성되기 전까지만 호출별로 협상하고, 생성 뒤에는 request에 고정된 `mode_contract_version`을 따른다.

Response:

```json
{
  "session_id": "uuid",
  "workflow_id": "uuid",
  "app_id": "uuid",
  "protocol_version": "direct_edit_v1",
  "default_generation_mode": "guided_generate",
  "status": "completed",
  "messages": [],
  "active_request": null,
  "active_graph_mutation": null,
  "parameter_group": null
}
```

### GET `/sessions/{session_id}`

Session의 만료되지 않은 request 전체에서 redaction된 safe conversation을 시간순으로, 최신 request, operations를 제외한 safe operation envelope와 parameter task 상태를 복구한다.

- 최신 request와 관계없는 과거 mutation은 `active_graph_mutation`으로 반환하지 않는다.
- Non-null `active_request`는 고정된 `mode_contract_version`을 포함해 Client가 후속 호출에 같은 header를 재사용할 수 있게 한다.
- Active request가 있으면 요청 header가 해당 request의 `mode_contract_version`과 일치해야 한다. 불일치 시 active request body를 반환하지 않고 `409 mode_contract_mismatch`로 닫으며 Client는 요구된 contract로 GET을 다시 보내거나 mode-free cancel을 호출한다.
- secret-like message span과 parameter value 원문은 반환하지 않는다.
- stale mutation은 safe envelope만 반환하고 client가 자동 적용하지 않는다.
- mutation metadata의 `catalog_version`이 없거나 `2`이면 legacy stale로 반환하고, `3`인 mutation만 active 후보로 복구한다.
- session row의 `protocol_version`이 null인 기존 Preview session은 `status=stale_protocol`로 반환한다. Safe 대화 이력은 표시할 수 있지만 legacy preview/draft를 적용하거나 GraphMutation으로 변환할 수 없다.
- `stale_protocol`, server가 명시한 session not found 또는 invalid session 외의 transport/5xx 오류는 terminal 상태를 의미하지 않는다. Client는 저장된 session pointer를 보존하고 같은 GET만 `1초 -> 2초 -> 4초` 간격으로 최대 세 번 재시도할 수 있다. 세 번 모두 실패하면 UI는 `결과 확인 필요`와 수동 재조회 control을 표시한다.
- `stale_protocol` 응답은 redaction을 통과한 safe conversation을 읽기 전용으로 유지하고 재제출 안내를 포함한다. Client는 legacy Preview graph/draft/apply 정보를 복원하지 않고 신규 요청용 `direct_edit_v1` session을 한 번 생성하며 같은 stale session 전환을 반복하지 않는다.
- CDS 저장 전 full operations 응답이 유실되면 server는 이를 복구·재생하지 않고 기존 envelope를 `blocked`로 닫아 `operation_payload_unavailable` reason을 반환한다. Initial/graph-edit/replace는 request를 재생성하고 parameter decision은 현재 task/version에서 새 operation id로 다시 입력한다.
- Recovery는 최신 request row를 잠근 뒤 safe operation envelope의 GraphMutationStatus가 `pending_apply|pending_save`이고 저장 결과가 없는 경우만 차단한다. `pending_ack|acknowledged|blocked|reverted` operation은 변경하지 않으며 차단 상태, 연결 task/Knowledge 복구와 safe audit는 한 transaction에서 확정한다. 이 값들은 RequestStatus가 아니다.
- `parameter_update` 차단은 pending decision을 제거하고 같은 task/version을 `active`로 다시 연다. Initial/graph-edit/replace parameter group은 `blocked`, Knowledge resolution은 `canceled`로 닫는다.
- CDS 저장 뒤 acknowledgement만 유실된 operation은 persisted graph hash와 envelope의 expected/saved hash, operation id와 workflow `updated_at`으로 acknowledgement를 복구할 수 있다.
- `reverted` history boundary는 active mutation으로 반환하지 않고 모든 연결 ParameterTask/Knowledge resolution을 `canceled`로 복구한다. Parameter/Knowledge operation별 `reverted` 상태는 허용하지 않으며 Redo도 canceled 흐름을 자동 완료하지 않는다.

## 5. Natural Language Request

### POST `/sessions/{session_id}/messages`

Direct-edit session의 workflow graph가 비어 있지 않은데 structured request가 완결된 `new_workflow`이면 `replace_workflow` GraphMutation을 반환한다. 명시적 전체 교체는 `request_type=modify_workflow`, `draft_mode=replace_workflow`로 구조화하며 edit target을 요구하지 않는다. 둘 다 typed remove/add operation과 동일한 CDS/acknowledgement 경계를 사용한다.

아래 request/response 예시는 `X-Agent-Builder-Mode-Contract: canonical-v2` 기준이다. `legacy-v1` Client는 `configure_and_generate|structure_only`만 전송하고 같은 표현으로 응답받으며, Gateway 내부 requested/effective mode와 저장 metadata는 canonical 값이다.

Request:

```json
{
  "message": "웹훅으로 요청을 받아 Slack으로 보내는 워크플로우를 만들어줘",
  "workflow_id": "uuid",
  "app_id": "uuid",
  "selected_node_id": "node-id-or-null",
  "selected_edge_id": "edge-id-or-null",
  "generation_mode": "guided_generate",
  "generation_mode_source": "default",
  "intent_model_selection": {
    "credential_id": "uuid",
    "model_id": "uuid"
  },
  "knowledge_selection": null,
  "conversation_context_id": "opaque-id-or-null"
}
```

Rules:

- `message`는 최대 4,000자다.
- Server는 session row를 잠가 비종료 request가 없음을 확인하고, 정규화된 `mode_contract_version`, `generation_mode_source`, 요청 귀속 metadata와 `status=planning`을 포함한 request row를 commit한 뒤에만 usage attempt 예약과 provider 호출을 시작한다. 명시적 control과 `legacy-v1` default는 canonical requested/effective mode도 이때 저장한다. `canonical-v2` default는 planning 동안 두 mode를 미확정으로 두고 schema-valid planner 결과에서 같은 request lock 안에 정확히 한 번 기록한다. 같은 session에 비종료 request가 있으면 새 row나 usage를 만들지 않고 `409 request_in_progress`를 반환한다.
- `generation_mode`가 없으면 pre-planning fallback은 `guided_generate`다. `canonical-v2`의 default source는 planner가 명시적 mode intent를 반환하지 않을 때 이 fallback을 최종 requested/effective mode로 기록한다. 기존 `configure_and_generate` 입력은 guided mode로 정규화하고 외부 response mode는 negotiated contract 표현을 따른다.
- `generation_mode_source=explicit_control`이면 해당 canonical mode가 자연어 mode intent보다 우선한다. `canonical-v2`의 `source=default`이면 planner가 반환한 명시적 quick/structure-only intent를 requested mode로 사용할 수 있고, 그런 intent가 없으면 guided다. `legacy-v1`은 자연어 quick intent를 활성화하지 않고 guided로 유지한다. Legacy request가 mode를 보내고 source를 생략하면 explicit control로 해석한다.
- `structured_plan.generation_mode_intent`는 `guided_generate|quick_generate|structure_only|null`이고 사용자 문장에 생성 방식이 명시된 경우에만 non-null이다. 이는 requested mode 계산 입력일 뿐 quick eligibility, 권한 또는 GraphMutation 적용 승인이 아니다.
- 화면 control 또는 자연어에서 명시된 `quick_generate` 의도는 요청값이지만 eligibility 승인이 아니다. Planner가 mode intent를 구조화해도 Gateway application policy가 현재 권한, Catalog, graph/resource revision과 미해결 설정으로 최종 판정한다.
- Quick eligibility가 없으면 response는 `mode_transition_required`이며 `graph_mutation=null`이다. Server는 값에 독립적인 structured plan과 재입력이 필요한 safe `step_id`/`parameter_key` descriptor만 보존하고 사용자의 명시적 guided 전환 또는 취소를 기다린다. 실제 parameter 값과 값에 의존하는 graph fragment는 보존하지 않으며 planner를 다시 호출하지 않는다.
- selected ids는 server-loaded graph 안에 있어야 하며 target hint일 뿐 권위 graph가 아니다.
- raw graph key, raw credential config, secret parameter payload를 포함하면 422 또는 safe validation failure로 거부한다.
- 정상 request는 planner provider를 한 번 호출한다. 최초 schema-valid 결과가 semantic invariant만 위반한 경우 safe code repair를 최대 한 번 수행할 수 있다. Provider/JSON/schema 실패에는 repair하지 않는다.
- Usage recorder가 연결된 경우 실제로 시작된 attempt의 token/cost는 validation 결과와 별도로 request id에 기록할 수 있지만 이 기록이 미확정 mode를 추측하거나 repair eligibility를 넓히지 않는다. Schema-invalid 응답은 attempt 1만 기록하고 종료한다. Request가 취소된 뒤 도착한 in-flight 응답의 usage는 완료할 수 있으나 planner 결과를 commit하거나 attempt 2를 예약하지 않는다. Usage 저장 실패는 RequestStatus `failed`와 safe validation issue code로 반환하며 별도 RequestStatus를 추가하지 않는다.
- `parameter_guidance_hints`는 2.13 계약으로 검증하고 잘못된 hint를 graph/task 권위값으로 사용하지 않는다.

Success response:

```json
{
  "request_id": "uuid",
  "request_version": 1,
  "mode_contract_version": "canonical-v2",
  "status": "graph_mutation_ready",
  "requested_generation_mode": "guided_generate",
  "generation_mode_source": "default",
  "effective_generation_mode": "guided_generate",
  "structured_plan": {
    "request_type": "new_workflow",
    "intent_summary": "웹훅 입력을 Slack으로 전달",
    "generation_mode_intent": null,
    "steps": [
      {
        "step_id": "step-webhook",
        "capability": "webhook_trigger",
        "purpose": "외부 요청을 workflow 입력으로 수신",
        "depends_on": []
      },
      {
        "step_id": "step-slack",
        "capability": "slack_send",
        "purpose": "수신한 내용을 Slack으로 전달",
        "depends_on": ["step-webhook"]
      }
    ],
    "parameter_guidance_hints": [
      {
        "step_id": "step-slack",
        "parameter_key": "channel",
        "reason": "메시지를 전달할 대상을 정하기 위해 필요합니다.",
        "input_guidance": "권한이 있는 Slack 채널을 선택합니다."
      }
    ],
    "knowledge_requirements": []
  },
  "knowledge_resolution": {
    "resolution_id": "opaque-id",
    "timing": "after_graph",
    "required": false,
    "candidates": [],
    "selected": []
  },
  "graph_mutation": {
    "operation_id": "uuid",
    "kind": "initial_graph",
    "status": "pending_apply",
    "workflow_id": "uuid",
    "base_graph_hash": "sha256",
    "expected_workflow_updated_at": "ISO-8601",
    "expected_result_graph_hash": "sha256",
    "catalog_version": 3,
    "operations": [],
    "affected_node_ids": [],
    "completion_context": null
  },
  "parameter_group": {
    "group_id": "uuid",
    "status": "pending_save",
    "tasks": []
  },
  "warnings": []
}
```

`generation_mode=structure_only`에서는 `parameter_group`이 `null`이고 unresolved configuration warning만 반환한다. Mutation kind는 빈 workflow의 새 graph면 `initial_graph`, 기존 workflow 부분 변경이면 `graph_edit`, 기존 workflow 전체 교체면 `replace_workflow`다. GraphMutation은 frontend 적용 전 `pending_apply`이며 local transaction 적용 뒤 `pending_save`, CDS workflow draft 저장 뒤 `pending_ack`, acknowledgement 뒤 `acknowledged`가 된다.
`operations`를 포함한 `graph_mutation`은 이 API 응답에서만 전달한다. Server는 같은
operation의 typed operations를 session/request payload에 저장하지 않고, 발급 전에 candidate
graph를 검증해 계산한 `expected_result_graph_hash`를 포함한 safe envelope만 저장한다.

`guided_generate`의 최초 응답은 workflow가 아직 저장되지 않았으므로
`parameter_group.status=pending_save`다. client가 workflow draft 저장을 완료한
뒤 acknowledgement 요청을 보내기 전까지는 local 상태를 `pending_ack`로 표시할 수 있지만,
개별 parameter task를 활성화하거나 입력을 받으면 안 된다.

### 5.1 Quick Generation Response

`quick_generate`가 eligible이면 일반 success response에 다음 `quick_review`가 추가되고 `parameter_group`은 `null`이다.

```json
{
  "request_id": "uuid",
  "request_version": 1,
  "mode_contract_version": "canonical-v2",
  "status": "graph_mutation_ready",
  "requested_generation_mode": "quick_generate",
  "generation_mode_source": "explicit_control",
  "effective_generation_mode": "quick_generate",
  "structured_plan": {
    "request_type": "new_workflow",
    "intent_summary": "입력 값을 그대로 응답",
    "generation_mode_intent": "quick_generate",
    "steps": [
      {
        "step_id": "step-input",
        "capability": "start_input",
        "purpose": "사용자 입력 수신",
        "depends_on": []
      },
      {
        "step_id": "step-answer",
        "capability": "answer",
        "purpose": "입력 값을 응답으로 반환",
        "depends_on": ["step-input"]
      }
    ],
    "parameter_guidance_hints": [],
    "knowledge_requirements": []
  },
  "knowledge_resolution": null,
  "quick_review": {
    "scope": "whole_workflow",
    "summary": {
      "added_node_count": 2,
      "changed_node_count": 0,
      "removed_node_count": 0,
      "has_unresolved_configuration": false
    }
  },
  "graph_mutation": {
    "operation_id": "uuid",
    "kind": "initial_graph",
    "status": "pending_apply",
    "workflow_id": "uuid",
    "base_graph_hash": "sha256",
    "expected_workflow_updated_at": "ISO-8601",
    "expected_result_graph_hash": "sha256",
    "catalog_version": 3,
    "operations": [
      {
        "op": "add_node",
        "node": {
          "id": "start-node",
          "type": "startNode",
          "position": {"x": 0, "y": 0},
          "data": {
            "title": "입력",
            "variables": [{"name": "input", "type": "string", "required": true}],
            "configuration_state": "resolved"
          }
        }
      },
      {
        "op": "add_node",
        "node": {
          "id": "answer-node",
          "type": "answerNode",
          "position": {"x": 320, "y": 0},
          "data": {
            "title": "응답",
            "outputs": [{"variable": "answer", "value_selector": ["start-node", "input"]}],
            "configuration_state": "resolved"
          }
        }
      },
      {
        "op": "add_edge",
        "edge": {
          "id": "edge-start-answer",
          "source": "start-node",
          "target": "answer-node",
          "sourceHandle": null,
          "targetHandle": null
        }
      }
    ],
    "affected_node_ids": ["start-node", "answer-node"],
    "completion_context": null
  },
  "parameter_group": null,
  "warnings": []
}
```

- Summary는 count와 allowlisted 사용자 문구만 포함하고 node data, hidden resource id, credential, URL/path 또는 raw prompt를 복제하지 않는다.
- Client는 actual editor와 분리된 clone에 full operations를 dry-run하고 동일한 graph/Catalog validator를 통과시킨다.
- 사용자가 `생성 적용`을 선택하기 전에는 editor graph, workflow draft와 request 상태를 변경하지 않는다.
- 적용 뒤 6절의 CDS save/acknowledgement를 사용하고 acknowledgement가 끝난 뒤에만 request를 `completed`로 전환한다.
- 적용 전 response 유실 또는 reload는 safe envelope를 `operation_payload_unavailable`로 닫고 operations를 복원하지 않는다. Parent request는 `graph_mutation_ready` 비종료 상태이므로 Client는 먼저 9.2의 contract-neutral cancel을 호출해 terminal `canceled`를 확인한 뒤에만 같은 의도의 새 message request를 생성한다. Cancel 결과가 불명확하면 같은 request cancel을 재시도하거나 canonical session에서 terminal 상태를 확인하며, 그 전에는 재제출하지 않는다.

Quick eligibility가 없으면 다음 형태를 반환한다.

```json
{
  "request_id": "uuid",
  "request_version": 1,
  "mode_contract_version": "canonical-v2",
  "status": "mode_transition_required",
  "requested_generation_mode": "quick_generate",
  "generation_mode_source": "explicit_control",
  "effective_generation_mode": null,
  "mode_transition": {
    "transition_id": "opaque-id",
    "target_mode": "guided_generate",
    "expected_request_version": 1,
    "reason_codes": ["resource_confirmation_required"],
    "reconfirmation_required": [
      {"step_id": "step-slack", "parameter_key": "channel"}
    ]
  },
  "graph_mutation": null
}
```

Reason code는 `credential_confirmation_required`, `resource_confirmation_required`, `configuration_value_required`, `external_effect_confirmation_required`, `branch_confirmation_required`, `network_or_code_confirmation_required`, `multiple_candidates`, `stale_context`의 allowlist다. `configuration_value_required`는 일반 required parameter에 사용자 요청·기존 graph·selector·안전한 Catalog default로 확정할 값이 없을 때 사용하며 UI는 `필수 설정값을 확인해야 합니다`로 표시한다. `reconfirmation_required`에는 Catalog가 검증한 `step_id`/`parameter_key`만 포함하고 실제 값, label, resource id와 hidden candidate 정보는 포함하지 않는다. 정확한 hidden resource, 후보 수, 이름과 식별자는 반환하지 않는다.

### 5.2 Mode Transition

#### POST `/requests/{request_id}/mode-transitions`

Request:

```json
{
  "operation_id": "uuid",
  "transition_id": "opaque-id",
  "action": "continue_guided",
  "expected_request_version": 1
}
```

- `action`은 `continue_guided`만 허용한다. 취소는 기존 `POST /requests/{request_id}/cancel` 경로 하나를 사용한다.
- `continue_guided`는 보존된 값 독립 structured plan으로 guided GraphMutation/Knowledge/Parameter 결과를 만들며 planner를 다시 호출하지 않고 성공 응답의 `request_version`을 증가시킨다. `reconfirmation_required` descriptor에 해당하는 실제 값은 GraphMutation에 materialize하지 않고 `resolution_source=null`, `reconfirmation_required=true`인 ParameterTask로 연다. Server는 원 prompt를 재실행하거나 처리 replica 메모리의 값을 사용하지 않으며, 값에 의존하는 graph fragment는 해당 typed task 입력과 후속 GraphMutation 전까지 만들지 않는다.
- GraphMutation을 포함한 성공 응답의 RequestStatus는 `graph_mutation_ready`이고 nested GraphMutationStatus는 `pending_apply`다. Before-graph Knowledge 선택처럼 mutation을 아직 발급하지 않은 결과는 해당 기존 RequestStatus를 유지한다.
- 같은 operation/payload 재시도는 상태 전이와 mutation 발급을 반복하지 않는다. 최초 응답에 full operations가 없었던 safe transition 결과는 같은 canonical 결과를 반환할 수 있지만, GraphMutation 발급 뒤 응답이 유실된 재시도는 저장되지 않은 operations를 재구성하지 않고 `409 operation_payload_unavailable`과 현재 safe request/envelope 상태를 반환한다. Client는 기존 request의 contract-neutral cancel 결과가 terminal `canceled`임을 확인한 뒤에만 새 operation id의 신규 message request를 명시적으로 제출한다.
- 다른 payload, stale request version 또는 이미 처리된 competing transition은 `409 mode_transition_conflict`다.
- 사용자가 확인하지 않은 transition을 server나 client가 자동 제출하지 않는다.

### 5.3 Remaining Configuration Quick Completion

#### POST `/requests/{request_id}/quick-completion-proposals`

Request:

```json
{
  "operation_id": "uuid",
  "expected_request_version": 7,
  "expected_graph_hash": "sha256",
  "expected_workflow_updated_at": "ISO-8601"
}
```

Server는 canonical `guided_generate` request의 미완료 task만 평가한다. 이미 acknowledged된 graph와 completed/skipped/deferred task를 바꾸지 않고 planner 또는 전체 graph generation을 다시 호출하지 않는다.

Response:

```json
{
  "proposal_id": "opaque-id",
  "proposal_version": 1,
  "status": "pending",
  "scope": "remaining_configuration",
  "request_version": 8,
  "confirmable_tasks": [
    {"task_id": "opaque-task-id", "task_version": 4}
  ],
  "remaining_guided_task_ids": ["opaque-task-id"],
  "summary": {
    "auto_completable_count": 1,
    "guided_count": 1
  }
}
```

- `confirmable_tasks`는 canonical graph 값과 recommendation fingerprint가 변하지 않은 멱등 confirm 대상의 id와 proposal 생성 transaction에서 증가된 fenced `task_version`을 포함한다.
- 값이 없거나 graph 변경이 필요한 task, Credential, 권한 resource, 외부 부수효과, Condition branch와 복수 후보 task는 `remaining_guided_task_ids`에 남긴다.
- Client는 proposal을 별도 검토안으로 표시하고 자동 적용하지 않는다. 이 V1 endpoint는 GraphMutation 또는 workflow save를 반환·호출하지 않는다.
- Proposal 생성은 parent request row lock에서 expected request version과 대상 task current version을 확인한다. 성공 transaction은 request version과 각 confirm 대상 task version을 정확히 한 번 증가시키고 증가된 task id/version, recommendation fingerprint와 canonical graph 값을 pending proposal에 저장한다. 같은 operation/payload 재시도는 같은 proposal/request/task version을 반환하고 다시 증가시키지 않는다.
- Pending proposal은 `confirmable_tasks`를 예약한다. 해당 task의 `confirm|set|defer|skip|previous`는 proposal이 `acknowledged|canceled|stale` 중 하나가 되기 전까지 `409 task_conflict`로 거부한다. `remaining_guided_task_ids`에만 속한 task는 기존 decision 계약으로 계속 진행할 수 있다.

#### POST `/requests/{request_id}/quick-completion-proposals/{proposal_id}/acknowledge`

Request:

```json
{
  "operation_id": "uuid",
  "expected_request_version": 8,
  "proposal_version": 1
}
```

Server는 proposal의 fenced task version, 권한, Catalog, recommendation fingerprint와 canonical graph 값을 다시 확인하고 모든 confirm 대상이 유효할 때만 한 request lock 안에서 완료한다. 성공 시 `request_version`, `proposal_version`과 완료되는 각 task의 `task_version`을 같은 row lock에서 각각 한 번 증가시키고 다음 응답을 반환한다. Stale 또는 일부만 적용 가능한 proposal은 graph/task 값을 변경하지 않은 채 proposal을 terminal `stale`로 전환하고 request/proposal version을 각각 한 번 증가시켜 예약을 해제한 뒤 `409 quick_completion_conflict`와 canonical stale proposal metadata를 반환한다.

```json
{
  "proposal_id": "opaque-id",
  "proposal_version": 2,
  "status": "acknowledged",
  "request_version": 9,
  "completed_tasks": [
    {"task_id": "opaque-task-id", "status": "completed", "task_version": 5}
  ],
  "next_task_id": "opaque-task-id-or-null"
}
```

실제 parameter 값은 반환하지 않는다. 같은 operation/payload 재시도는 새 version을 다시 증가시키지 않고 최초 성공의 `proposal_version=2`, `request_version=9`와 동일한 `completed_tasks` 결과를 반환한다. Proposal 생성 전 task version을 사용한 늦은 `set`과 pending proposal이 예약한 task에 대한 새 decision은 모두 `409 task_conflict`다. 이 endpoint는 GraphMutation, workflow save 또는 planner 호출을 만들지 않는다.

#### POST `/requests/{request_id}/quick-completion-proposals/{proposal_id}/cancel`

```json
{
  "operation_id": "uuid",
  "expected_request_version": 8,
  "proposal_version": 1
}
```

Pending proposal만 `canceled`로 전환하고 request와 proposal version을 같은 row lock에서 각각 증가시켜 target task 예약을 해제한다. Proposal 생성 시 증가한 task version은 되돌리거나 다시 증가시키지 않으며 Client는 반환 뒤 canonical task version을 다시 읽는다.

```json
{
  "proposal_id": "opaque-id",
  "proposal_version": 2,
  "status": "canceled",
  "request_version": 9
}
```

Graph, ParameterTask와 guided 진행 상태는 변경하지 않는다. 같은 operation/payload 재시도는 version을 다시 증가시키지 않고 같은 canceled 결과를 반환하며 stale/acknowledged/competing proposal은 `409 quick_completion_conflict`다.

## 6. GraphMutation And CDS Save

### 6.1 Operation Schema

```json
{
  "op": "add_node",
  "node": {
    "id": "server-generated-id",
    "type": "slackPostNode",
    "position": {"x": 0, "y": 0},
    "data": {"configuration_state": "unresolved"}
  }
}
```

지원 operation:

- `add_node`: server-generated id의 node를 추가한다.
- `remove_node`: 기존 node id를 제거한다.
- `add_edge`: 검증된 source/target/handle의 edge를 추가한다. `conditionNode` source의 edge는 case id 또는 `default`인 `sourceHandle`이 필수이며 handle 없는 edge를 default로 보정하지 않는다. 각 case/default 대상은 typed ParameterTask에서 기존 node 또는 명시적 `연결 안 함`으로 확인하고, 후자는 edge를 생성하지 않는다.
- `remove_edge`: 기존 edge id를 제거한다.
- `replace_node_data`: 허용된 node data 전체를 새 값으로 교체한다.

Mutation validation:

- `operation_id`는 session 안에서 idempotent해야 한다.
- Backend는 base graph에 operations를 적용한 complete candidate를 발급 전에 검증하고 canonical `expected_result_graph_hash`를 계산한다.
- node id와 edge id는 충돌하면 안 된다.
- node type, parameter key와 handles는 catalog v3에 존재해야 한다.
- mutation 전체가 유효하지 않으면 일부 operation만 반환하지 않는다.
- 기존 workflow 전체 교체는 기존 edge/node 제거 뒤 새 node/edge 추가의 typed operation 묶음으로만 지원한다. Raw graph 우회 필드는 지원하지 않는다.
- auto layout 위치는 mutation operation에 포함한다. Frontend는 저장 전에 임의 위치로 다시 계산하지 않는다.
- `completion_context`는 parameter task id 또는 Knowledge resolution id만 포함할 수 있다.
- Full operations는 이 응답 밖의 DB/session/request payload에 저장하지 않는다. Persisted safe envelope에는 operation id/kind/status, catalog version, base/expected-result hash, expected workflow `updated_at`, affected node ids와 completion context만 포함한다.

### 6.2 POST `/api/v1/workflows/{workflow_id}/draft`

일반 workflow draft 저장 endpoint에 Agent Builder용 additive `mutation_context`를 전달한다. 이 endpoint는 Agent Builder base path 밖에 있지만 GraphMutation 확정의 유일한 저장 경계다.

Request excerpt:

```json
{
  "nodes": [],
  "edges": [],
  "viewport": {"x": 0, "y": 0, "zoom": 1},
  "features": {},
  "envVariables": [],
  "runtimeVariables": [],
  "mutation_context": {
    "operation_id": "uuid",
    "action": "apply",
    "expected_base_graph_hash": "sha256",
    "expected_workflow_updated_at": "ISO-8601",
    "catalog_version": 3
  }
}
```

Rules:

- Agent Builder가 발급한 operation은 `mutation_context` 없는 저장을 성공으로 인정하지 않는다.
- Backend는 workflow row를 write lock으로 조회하고 active organization과 write 권한을 다시 확인한다.
- Agent Builder save는 `Workflow` row 다음 parent `AgentBuilderRequest` row 순서로 lock을 얻어 cancel과 같은 순서로 직렬화하고 request version, operation status와 저장 metadata를 다시 읽는다. Canceled/stale operation은 graph를 쓰지 않는다.
- 저장 직전 current canonical graph hash와 workflow `updated_at`을 두 기대값과 비교한다. 하나라도 다르면 graph를 쓰지 않고 `409 stale_graph`를 반환한다.
- Backend는 request nodes/edges의 canonical hash가 persisted safe envelope의 `expected_result_graph_hash`와 같은지 검증한다. Typed operations를 DB에서 다시 읽거나 재생하지 않는다.
- Complete candidate graph는 catalog schema, node allowlist, connection policy와 structural validation을 다시 통과해야 한다.
- Backend는 final candidate graph와 Catalog v3 및 server-owned reference policy registry에서 모든 `resource_ref`, `credential_ref`, Knowledge/Collection binding, WorkflowNode `appId`/`workflowId`와 기타 resource-bearing field를 직접 추출해 `managed_reference|legacy_editor_connection|unknown`으로 분류한다. Managed reference는 resolver가 같은 transaction 안에서 현재 organization, 존재/lifecycle, required relation과 use/read/write 권한을 다시 검증한다. ADR-0045의 resolver 미구현 Slack/GitHub 연결은 persisted base graph와 canonical field 값 및 connection-relevant node data가 동일한 경우에만 carry-forward한다. Client reference 목록이나 발급 시점 allow 결과는 사용하지 않으며 Agent Builder가 legacy field를 추가·교체·삭제한 경우, unknown field, managed resolver 누락, 삭제·비활성·권한 회수·relation 변경은 전체 save와 audit를 rollback한다. Carry-forward는 credential 사용 승인이 아니며 runtime/preflight 검사를 완화하지 않는다.
- Backend는 request graph의 `configuration_state`를 신뢰하지 않고 Catalog required configuration 전체에서 각 node 상태를 다시 계산한다. `unresolved`는 저장을 차단하지 않지만 계산 결과와 node metadata가 catalog contract에 맞아야 한다.
- Graph write와 기존 `add_action_audit`의 canonical audit insert는 같은 SQLDlchemy session과 transaction에서 확정한다. 둘 중 하나라도 실패하면 rollback하고 성공을 반환하지 않는다. 신규 audit outbox나 worker는 추가하지 않는다.
- 일반 autosync를 포함한 모든 editor save는 request 최상위의 `expected_graph_hash`와 `expected_updated_at`을 제공한다. Backend는 같은 workflow row lock 안에서 두 값을 current canonical metadata와 비교하고 불일치하면 `409 stale_graph`로 닫는다. Agent Builder의 `mutation_context` 검증은 이 공통 CDS 위에 추가되며, silent overwrite, 자동 merge와 강제 덮어쓰기는 허용하지 않는다.

Canonical graph hash는 persisted nodes와 edges를 stable id 순으로 정렬하고 object key를 정렬한 JSON의 SHA-256이다. Position과 node data는 포함하고 viewport는 제외한다.

Success response:

```json
{
  "status": "success",
  "workflow_id": "uuid",
  "operation_id": "uuid",
  "graph_hash": "sha256",
  "updated_at": "ISO-8601"
}
```

`workflow_version`, `revision`처럼 현재 Workflow model에 존재하지 않는 값을 응답에 추가하지 않는다. 같은 workflow에서 두 사용자가 같은 base로 저장하면 첫 요청만 성공하고 두 번째 요청은 stale conflict다.

Canonical draft 조회도 저장 응답과 같은 `workflow_id`, `graph_hash`, DB `updated_at`을 반환한다. Agent Builder save/acknowledgement, 일반 autosync, Undo/Redo와 응답 유실 복구는 이 실제 API metadata만 사용하며 client test fixture가 존재하지 않는 revision 값을 합성하지 않는다.

### 6.3 POST `/sessions/{session_id}/graph-mutations/{operation_id}/ack`

Client가 mutation 전체를 workflow store에 원자적으로 적용하고 6.2의 CDS 저장을 완료한 뒤 canonical 결과를 확인한다. 이 endpoint는 graph를 다시 저장하지 않는다.

Request:

```json
{
  "workflow_id": "uuid",
  "graph_hash": "sha256",
  "updated_at": "ISO-8601"
}
```

Rules:

- graph 원문과 client-only Undo transaction id는 보내지 않는다.
- backend는 safe operation envelope의 workflow id, `expected_result_graph_hash`, canonical persisted graph hash, saved `result_graph_hash`와 `updated_at`을 다시 대조한다.
- 값이 다르거나 CDS save를 확인할 수 없으면 `stale_graph` 또는 `validation_failed`로 처리하고 후속 상태를 전환하지 않는다.
- Parameter update는 acknowledgement 전까지 현재 task를 완료하지 않고 다음 task를 활성화하지 않는다.
- `structure_only`와 `knowledge_binding`도 acknowledgement 전에는 완료로 기록하지 않는다.
- 같은 canonical 값의 중복 acknowledgement는 동일 응답을 반환하고 graph나 task를 중복 변경하지 않는다.

Response:

```json
{
  "operation_id": "uuid",
  "operation_status": "acknowledged",
  "graph_hash": "sha256",
  "updated_at": "ISO-8601",
  "parameter_group": {
    "group_id": "uuid",
    "status": "active",
    "tasks": []
  },
  "completed_task_id": "uuid-or-null",
  "completed_knowledge_resolution_id": "opaque-id-or-null",
  "next_task_id": "uuid-or-null"
}
```

저장 실패, stale graph 또는 validation failure에서는 operation을 `blocked`로 유지한다. `structure_only` acknowledgement는 parameter/Knowledge 관련 필드를 모두 `null`로 반환할 수 있다. `parameter_update`는 `completed_task_id`, `knowledge_binding`은 `completed_knowledge_resolution_id`를 반환한다.

### 6.4 Agent Builder History Boundary Undo/Redo

완료된 Agent Builder history boundary를 전체 Undo할 때 client는 시작 전 snapshot을 6.2 endpoint로 저장하되 다음 revert context를 사용한다. ParameterTask가 있는 완료 상태의 첫 Undo는 API를 호출하지 않고 `completed|skipped|deferred` 중 재편집 가능하고 `stable_order`가 가장 큰 task를 client presentation에서 표시하는 재진입 단계다. Persisted task status/version과 graph는 변경하지 않는다. Task가 없거나 이미 재진입 상태이면 전체 revert를 수행한다.

```json
{
  "mutation_context": {
    "operation_id": "history-boundary-operation-uuid",
    "action": "revert",
    "expected_base_graph_hash": "original-result-graph-sha256",
    "expected_workflow_updated_at": "current-ISO-8601",
    "catalog_version": 3
  }
}
```

Rules:

- Server는 boundary가 모든 graph save/acknowledgement를 마친 completed 상태인지 확인한다.
- Current canonical graph hash는 boundary의 최신 final graph hash와 일치해야 한다.
- Revert candidate graph hash는 boundary의 시작 전 base graph hash와 일치해야 한다.
- Graph revert, `add_action_audit`, boundary `reverted`, 모든 ParameterTask/Knowledge resolution `canceled` 전환을 같은 transaction에서 저장한다. `replace_workflow` candidate는 교체 전 전체 graph여야 한다.
- `parameter_update`와 `knowledge_binding` operation id로 개별 revert를 요청하면 validation failure로 거부한다.
- 같은 boundary operation id, action, candidate graph hash와 expected CDS 값을 가진 revert/redo 재시도는 idempotent하다. 이미 반영된 요청은 최초 canonical graph hash/`updated_at`을 반환하며 graph write, task/Knowledge 전환과 audit를 반복하지 않는다. 다른 context나 편집이 있으면 `409 stale_graph`로 닫는다.
- Reload 전 Redo는 같은 endpoint에 `action=redo`, boundary operation id, 현재 base graph hash/`updated_at`과 client memory의 final graph를 보낸다. Server는 final hash를 검증해 graph만 저장하며 canceled task/Knowledge 흐름을 변경하지 않는다.
- 전체 Redo 뒤 같은 memory history에서 다시 Undo하면 parameter 재진입 없이 같은 boundary를 바로 revert한다. Parameter 재진입 상태의 Redo는 API를 호출하지 않고 설정 UI를 닫는다. Redo stack은 reload 뒤 복구하지 않는다.
- Client는 revert/redo network outcome이 불명확하면 같은 context로 한 번 자동 재시도한다. 두 번째 결과도 불명확하면 canonical workflow와 boundary 상태를 조회해 반영됨, 미반영 또는 stale로 판정할 때까지 pending history를 보존한다.

## 7. Parameter Tasks

### 7.1 ParameterTask

```json
{
  "task_id": "uuid",
  "node_id": "node-slack",
  "node_type": "slackPostNode",
  "parameter_key": "channel",
  "label": "Slack 채널",
  "input_type": "resource_ref",
  "required": true,
  "defer_policy": "forbidden",
  "sensitive": false,
  "description": "메시지를 보낼 Slack 채널을 선택합니다.",
  "example": "공개 또는 비공개 채널 ID",
  "status": "active",
  "task_version": 3,
  "resolution_source": null,
  "reconfirmation_required": false,
  "validation": {
    "rule_id": "slack.channel",
    "max_length": 255
  },
  "candidates": [
    {
      "candidate_id": "opaque-resource-id",
      "kind": "resource_ref",
      "label": "사용 가능한 모델",
      "description": "provider",
      "reference_value": "provider-model-id"
    }
  ],
  "suggestions": [
    {
      "suggestion_id": "opaque-id",
      "kind": "variable_selector",
      "label": "Webhook payload message",
      "description": "Webhook 입력의 message 값을 사용합니다.",
      "source_node_id": "node-webhook",
      "output_key": "payload",
      "value_type": "string",
      "value_selector": ["node-webhook", "payload", "message"],
      "json_path": "$.message"
    }
  ]
}
```

`candidate_id`는 typed decision에 제출하는 권한 검증용 opaque id다. Graph에 저장되는 안전한
runtime reference가 candidate id와 다른 경우에만 `reference_value`를 함께 반환한다. 예를 들어
LLM model task는 DB model UUID를 candidate id로 제출하지만 graph의 `model_id`는 provider API
model id이므로 이를 `reference_value`로 사용해 재진입 control을 hydrate한다. Secret 또는 credential
config는 이 필드에 허용하지 않는다.

Task 생성 우선순위:

1. 사용자 요청에서 명시적으로 구조화된 값
2. 기존 workflow node의 저장값
3. 단일 upstream output과 catalog contract로 확정 가능한 값
4. catalog의 안전한 기본값
5. 위 순서로도 확정되지 않은 parameter는 `pending` 또는 `active` task로 생성

Catalog의 모든 configurable parameter에 task record를 만든다. 1~4에서 자동 추천된 값은 graph에
반영하고 `resolution_source=user_request|existing_graph|upstream_selector|catalog_default`를 기록하지만
task는 사용자 확인 전까지 `pending|active`로 유지한다. 실제 값은 task나 session payload에 복제하지
않고 canonical workflow graph에서 hydrate한다. 사용자는 추천 이유와 현재 값을 확인한 뒤 값이 같으면
`confirm`, 다르면 `set`을 제출한다. 후보가 여러 개면 자동 추천하지 않는다.

`reconfirmation_required=true`는 quick-to-guided 전환에서 실제 값이 저장되지 않아 다시 입력해야 하는 task에만 사용한다. 이 상태는 `resolution_source=null`이고 graph에 해당 값이 없어야 하며 `confirm`을 제공하지 않는다. 사용자가 typed `set`을 제출해 GraphMutation/CDS save/acknowledgement를 마치면 일반 completed task로 전환한다.

`defer_policy`는 `forbidden|allow_unresolved`이며 Catalog에 값이 없으면 `forbidden`이다.

Condition branch target은 `parameter_key=condition_branch:<case-id|default>`, `input_type=select` task로 발급한다. `validation.options`에는 현재 graph에서 선택 가능한 기존 node id와 `연결 안 함` sentinel을 넣고, `validation.option_labels`에는 사용자에게 표시할 안전한 node label을 넣는다. Client는 label을 표시하되 decision에는 canonical option value를 `{ "kind": "select", "value": "..." }`로 제출한다. 실제 현재 target은 node data의 server-owned branch target map에서 hydrate하며 task/session payload에 복제하지 않는다. Case 목록이 바뀐 `parameter_update`가 acknowledgement되면 server는 canonical case/default handle을 기준으로 task를 멱등 재조정한다.

### PDTCH `/sessions/{session_id}/parameter-tasks/{task_id}`

Request:

```json
{
  "operation_id": "client-generated-uuid",
  "expected_task_version": 3,
  "action": "set",
  "value": {
    "kind": "variable_selector",
    "suggestion_id": "opaque-id",
    "value_selector": ["node-webhook", "payload", "message"]
  }
}
```

지원 action:

- `set`: typed value를 적용
- `confirm`: canonical graph에 이미 반영된 자동 추천값을 변경 없이 확인
- `defer`: Catalog가 `allow_unresolved`로 허용한 parameter만 unresolved로 남김
- `skip`: optional parameter만 건너뜀
- `previous`: persisted 상태를 변경하지 않고 stable order상 이전 재편집 가능 task의 `next_task_id`를 반환

Rules:

- 일반 chat message를 parameter 값으로 해석하지 않는다.
- `credential_ref`와 `resource_ref`는 현재 사용 권한이 확인된 safe opaque id만 받으며 config/secret은 받지 않는다. 재진입 시 권한을 잃거나 삭제된 reference는 ID/label을 응답하지 않고 unavailable 상태로 표시할 수 있는 safe metadata만 반환한다.
- `credential_ref`가 비어 있어도 task를 자동 `deferred`로 만들지 않는다. 모든 configurable credential task는 `pending|active`에서 사용자 결정을 기다리고, 명시적 `defer`가 policy-allowed인 경우에만 mutation save와 acknowledgement 뒤 `deferred`가 된다.
- `variable_selector`는 server가 발급한 `suggestion_id`와 canonical selector 배열이 일치해야 한다. 임의 JSON path 문자열 또는 current graph에서 도달할 수 없는 selector는 거부한다.
- Condition branch `select`는 발급된 `validation.options` 안의 기존 node 또는 `연결 안 함`만 허용한다. 자기 자신, incoming forbidden node와 새 cycle을 만드는 target은 거부한다. Branch `set` acknowledgement 전에는 다음 branch task를 활성화하거나 Condition을 resolved로 계산하지 않는다.
- Frontend는 optional task에만 `skip`을 제공하고 required task의 `skip`은 disabled/hidden 처리한다. Backend는 UI 상태와 무관하게 required `skip`을 거부한다.
- Required/optional 여부와 무관하게 `defer_policy=forbidden`이면 defer control을 표시하지 않고 backend도 `invalid_decision`으로 거부한다.
- `defer_policy=allow_unresolved`인 defer는 해당 required configuration을 deferred로 표시하는 `parameter_update` GraphMutation을 반환한다. CDS 저장과 acknowledgement 뒤에만 task를 `deferred`로 전환하며 backend가 node 전체 required configuration에서 `configuration_state`를 다시 계산한다.
- 변경은 해당 node data에 대한 `parameter_update` GraphMutation을 반환하고 frontend가 현재 Agent Builder history boundary의 final snapshot/hash만 갱신한다. Parameter 변경마다 별도 Workflow history entry를 만들지 않는다.
- parameter 설정마다 planner LLM을 호출하지 않는다.
- task status/version과 operations를 제외한 safe operation/acknowledgement metadata는 기존 `AgentBuilderRequest.response_payload`에 저장한다. Repository는 current payload를 복사해 새 전체 객체로 재할당하며 nested dict를 제자리 변경하지 않는다.
- 실제 parameter value는 request/session payload에 저장하지 않고 workflow graph만 source of truth로 사용한다. 재진입 input은 canonical graph와 Catalog mapping에서 현재 safe 값을 hydrate하며 raw secret은 복구하지 않는다.
- Optional `skip`은 workflow graph나 GraphMutation을 만들지 않고 operation id/task version 검증 뒤 task를 명시적 `skipped` 상태로 전환해 다음 task를 활성화한다. `confirm`도 graph와 recommendation context가 발급 시점과 같으면 GraphMutation과 workflow save 없이 active task를 `completed`로 전환한다. `previous`는 graph save/acknowledgement, task status/version과 Workflow history를 변경하지 않고 `next_task_id`만 반환한다. Graph 값을 바꾸는 `set`, completed/skipped/deferred/invalid task 수정과 `allow_unresolved` defer는 GraphMutation acknowledgement를 요구한다.
- Backend는 parent `AgentBuilderRequest` row를 write lock으로 조회하고 target task id, `expected_task_version`과 action별 허용 status를 비교한다. `confirm`은 active 자동 추천 task에만 허용한다. 값 설정 `set`은 `active|completed|skipped|deferred|invalid`에 허용하며 `pending|canceled`에는 허용하지 않는다. `previous`는 current presentation task의 canonical status가 `active|completed|skipped|deferred`일 때 stable order상 이전 재편집 가능 task를 찾는다. 같은 `operation_id` 재시도는 상태 전이, GraphMutation과 next task를 반복하지 않고, 먼저 처리된 다른 decision 때문에 version이 바뀌면 `409 task_conflict`로 닫는다.
- 동일 operation id와 동일 canonical payload의 `confirm|skip|cancel|previous` 재시도와 Catalog validation으로 `invalid`가 된 `set`은 저장된 safe 최초 결과를 반환하고 task activation, DB commit과 audit를 반복하지 않는다. Full operations를 발급한 `set|defer` 응답이 CDS 저장 전에 유실되면 같은 operation 재시도는 최초 operations 대신 `409 operation_payload_unavailable`을 반환하며, recovery가 task를 같은 version으로 다시 연 뒤 새 operation id로 재입력한다. 동일 id의 payload fingerprint가 다르면 `409 task_conflict`다.
- `configuration_state`는 client decision field가 아니다. Backend는 최초 graph, set/defer/skip, persisted Undo, session recovery와 workflow test/run·deployment preflight마다 Catalog required configuration 전체를 검사한다. 하나라도 missing/deferred/invalid이면 `unresolved`, 모두 유효할 때만 `resolved`다. Optional skipped parameter는 Catalog required가 아닌 한 상태를 막지 않는다.

Response:

```json
{
  "task": {"task_id": "uuid", "status": "active", "task_version": 3},
  "graph_mutation": {
    "operation_id": "uuid",
    "kind": "parameter_update",
    "status": "pending_apply",
    "workflow_id": "uuid",
    "base_graph_hash": "sha256",
    "expected_workflow_updated_at": "ISO-8601",
    "expected_result_graph_hash": "sha256",
    "catalog_version": 3,
    "operations": [],
    "affected_node_ids": ["node-slack"],
    "completion_context": {"parameter_task_id": "uuid"}
  },
  "next_task_id": null,
  "group_status": "active",
  "awaiting_persistence_ack": true,
  "validation_issues": []
}
```

`set` 또는 기존 완료값 수정은 이 응답만으로 task를 완료하지 않는다. Client가
GraphMutation을 적용하고 CDS workflow draft save를 완료한 뒤 같은 operation id와
canonical graph hash/`updated_at`으로 acknowledgement해야 server가 현재 task를
완료하고 `next_task_id`를 반환한다. 저장 실패나 acknowledgement 유실은 현재
task를 유지하며 같은 canonical 값으로 acknowledgement를 재시도한다.

기존 completed task 수정 acknowledgement는 해당 task version과 저장 결과만 갱신한다.
이미 활성화됐거나 완료된 다음 task를 다시 생성·활성화하지 않으며 `next_task_id`는 기존
진행 상태를 가리키거나 `null`이다.

Optional `skip` response는 `graph_mutation=null`, `awaiting_persistence_ack=false`이며 현재
task를 `skipped`로 반환하고 다음 task를 활성화한다. Skipped task를 다시 열어 `set`하면
일반 parameter update 응답과 CDS save/acknowledgement를 거쳐 `completed`가 된다. Required
task의 skip은 graph와 task를 변경하지 않고 `invalid_decision`으로 거부한다.

유효한 `confirm` response도 `graph_mutation=null`, `awaiting_persistence_ack=false`이며 현재
task를 `completed`로 반환하고 다음 task를 활성화한다. 같은 operation id 재시도는 task version,
다음 task, graph write와 audit를 반복하지 않는다. Canonical graph 값이나 recommendation context가
달라졌으면 `task_conflict` 또는 validation error로 닫고 완료를 추측하지 않는다. 자동 추천 task는
값 원문이 아닌 canonical SHA-256 `recommendation_fingerprint`를 포함하며 confirm 시 현재 canonical
graph 값의 fingerprint와 대조한다. Fingerprint에는 secret 또는 값 원문을 저장하지 않는다.

## 8. Knowledge Selection

### POST `/sessions/{session_id}/knowledge-selection`

Request:

```json
{
  "resolution_id": "opaque-id",
  "selected_candidates": [
    {"candidate_id": "opaque-id", "requirement_id": "requirement-id"}
  ]
}
```

- 빈 배열은 KB 없이 진행하겠다는 명시적인 no-selection이다. 별도 no-KB candidate를 요구하거나 selection을 다시 요청하지 않는다.
- Message/session response의 `knowledge_resolution.resolution_id`는 candidate 유무와 무관하게 존재한다. Candidate가 0개여도 client는 이 값을 사용해 빈 `selected_candidates`를 제출한다.
- Knowledge 선택은 parameter task와 같은 workflow 설정 결과 container에서 처리하며, 같은 requirement에 legacy clarification selector와 direct-edit Knowledge card를 동시에 반환하거나 표시하지 않는다.
- `direct_edit_v1` candidate는 response의 `knowledge_resolution.candidates`에만 포함하고 `clarification_options`에 중복하지 않는다. Direct session의 message endpoint는 legacy `selected_knowledge_candidate`와 `selected_knowledge_candidates` 입력을 `invalid_request`로 거부한다. `pending_ack|completed` resolution에 legacy/direct 경로가 교차 제출되면 중복 저장·상태 전환·audit 없이 conflict로 닫는다.
- direct-edit response의 `parameter_group.tasks`는 `llmNode.knowledgeBases` generic `resource_ref` task를 포함하지 않는다. KB binding은 `knowledge_resolution`과 전용 selection endpoint가 단독으로 소유한다.
- Frontend와 selection service는 direct candidate가 비어 있더라도 `clarification_options`를 Knowledge 후보 fallback으로 사용하지 않는다.
- candidate id에서 KB id를 client가 추론하지 않는다.
- backend는 active organization, use 권한, lifecycle, ready version을 다시 확인한다.
- `before_graph` 선택은 통합 설정 결과의 첫 단계에서 이미 만들어진 structured plan의 KB-independent base topology와 2.14의 typed Knowledge placement를 사용해 최초 GraphMutation을 생성한다. Backend는 requirement/step reference와 Catalog capability를 다시 검증하고, 선택이 있으면 Catalog template으로 Knowledge node/data/edge를 만들며 여러 candidate를 같은 requirement binding 목록에 연결한다. 빈 선택이면 declared bridge policy로 Knowledge step을 생략하고 upstream/downstream을 연결한다. 자연어 요청이나 Planner를 다시 호출하지 않는다.
- Selected/empty candidate가 catalog/schema/connection validation을 통과하지 못하면 GraphMutation을 반환하거나 일부 graph를 저장하지 않고 `validation_failed`로 닫는다.
- `after_graph` 선택은 기존 Knowledge-capable node의 `knowledge_binding` GraphMutation만 반환한다.
- `after_graph` 선택은 graph 생성 뒤 같은 workflow 설정 결과 container에서 parameter 확인과 순차 처리한다.
- `after_graph` binding은 CDS workflow save와 canonical graph hash/`updated_at` acknowledgement 이후에만 선택 완료로 기록한다.
- 선택되지 않은 후보는 유지 가능한 UI 후보이며 선택 상태와 후보 목록은 별개다.
- 선택 요청 처리 중에는 candidate와 selected state를 canonical response에 유지하고 control만 잠근다. 저장 전 실패는 같은 resolution/card에서 재시도할 수 있다. 결과가 불명확하면 canonical session의 안전한 `messages`, `knowledge_resolution`, envelope와 graph metadata로 `pending_ack|completed|unapplied`를 판정한다. Client는 canonical message의 같은 request/resolution을 기존 대화 항목에 upsert해 stale selection card를 남기지 않는다. Typed operations, 자연어 요청과 planner는 재생하지 않는다.
- CTD는 `before_graph` 선택 시 `선택한 Knowledge Base로 생성`, 빈 선택 시 `Knowledge Base 없이 생성`, `after_graph` 선택 시 `선택 적용`, 빈 선택 시 `Knowledge Base 없이 계속`이다.

`after_graph` response:

```json
{
  "resolution_id": "opaque-id",
  "selected_candidates": [
    {"candidate_id": "opaque-id", "requirement_id": "requirement-id"}
  ],
  "graph_mutation": {
    "operation_id": "uuid",
    "kind": "knowledge_binding",
    "status": "pending_apply",
    "workflow_id": "uuid",
    "base_graph_hash": "sha256",
    "expected_workflow_updated_at": "ISO-8601",
    "expected_result_graph_hash": "sha256",
    "catalog_version": 3,
    "operations": [],
    "affected_node_ids": ["node-llm"],
    "completion_context": {"knowledge_resolution_id": "opaque-id"}
  }
}
```

## 9. Cancel

### 9.1 POST `/sessions/{session_id}/active-request/cancel`

동기식 message POST가 아직 `request_id`를 반환하지 않은 `submitting|planning` UI에서 사용한다.

```json
{
  "operation_id": "uuid"
}
```

Server는 기존 session 인증과 active organization을 확인하고 session row를 잠근다. 그 다음 terminal request를 포함한 해당 session의 safe operation metadata에서 같은 `operation_id`의 session-scoped cancel 결과를 먼저 조회한다. 저장된 결과가 있으면 그 결과가 가리키는 workflow write 권한을 다시 확인하고 `{"request_id":"uuid","status":"canceled"}`를 그대로 반환하며 현재 비종료 request를 조회하거나 변경하지 않는다.

저장된 결과가 없을 때만 비종료 request를 조회한다. 같은 session에는 비종료 request가 하나만 존재해야 하며 정확히 하나면 `Workflow -> AgentBuilderRequest` 순서로 추가 lock을 얻어 상태와 version을 다시 확인한 뒤 9.2의 동일 cancel command를 수행한다. Cancel 결과와 operation id는 canceled request의 safe idempotency metadata에 같은 transaction으로 저장한다. Active row가 없으면 `409 active_request_not_found`, legacy 이상으로 둘 이상이면 `409 active_request_ambiguous`로 닫아 임의 request를 선택하지 않는다. 따라서 응답 유실 뒤 같은 operation id를 재시도해도 과거 결과가 먼저 선택되고 그 사이 생성된 새 request는 취소되지 않는다.

취소 전에 provider 호출이 이미 시작됐다면 네트워크 강제 중단을 보장하지 않는다. 실제 응답의 usage fact는 멱등 완료할 수 있지만 planner 결과는 request에 commit하지 않고, semantic repair를 포함한 다음 attempt 예약 전 request version/status를 재검증해 추가 provider 호출을 차단한다.

### 9.2 POST `/requests/{request_id}/cancel`

RequestStatus가 `planning|clarification_required|mode_transition_required|graph_mutation_ready|parameter_configuration`인 모든 비종료 request를 취소한다. 이 endpoint는 request에 고정된 mode contract와 무관하게 호출할 수 있고 generation mode를 포함하지 않는 contract-neutral 응답 `{"request_id":"uuid","status":"canceled"}`만 반환한다. 따라서 Client rollback이나 recovery가 `mode_contract_mismatch`를 받은 경우에도 같은 인증·active organization·workflow 권한을 다시 검증한 뒤 request를 종료할 수 있다.

Server는 request에서 workflow id를 안전하게 조회한 뒤 `Workflow` row, parent `AgentBuilderRequest` row 순서로 lock을 얻고 request version을 전진시켜 늦은 planner 결과와 competing clarification/transition/task/save commit을 거부한다. 같은 transaction에서 다음 child closure를 수행한다.

- 남은 `pending|active|invalid` ParameterTask를 `canceled`로 닫고 변경되는 각 `task_version`을 정확히 한 번 증가시킨다.
- 미완료 Knowledge resolution을 `canceled`로 닫는다.
- `pending` quick-completion proposal을 `canceled`로 닫고 `proposal_version`을 정확히 한 번 증가시켜 target task 예약을 해제한다. 이미 `acknowledged|canceled|stale`인 proposal은 유지한다.
- 저장 전 `pending_apply|pending_save` operation은 `blocked`와 safe cancel reason으로 닫고 Client는 local apply를 Undo하며 acknowledgement하지 않는다.
- `pending_ack|acknowledged`처럼 CDS 저장이 확정된 operation, 완료 task 값과 persisted graph는 유지하고 자동 revert하지 않는다.

이 closure가 끝난 뒤에만 parent RequestStatus를 terminal `canceled`로 저장한다. Guided request 전체를 유지하면서 remaining quick proposal만 닫을 때는 5.3의 proposal cancel을 사용한다.

같은 request cancel 재시도는 상태와 audit를 반복하지 않고 같은 mode-free 결과를 반환한다. 이미 `canceled`면 같은 결과를 반환하고, 그 밖의 종료 상태는 변경하지 않고 `409 request_not_cancelable`을 반환한다.

### POST `/sessions/{session_id}/parameter-groups/{group_id}/cancel`

Request는 client-generated `operation_id`, 현재 `expected_task_id`와 `expected_task_version`을 포함한다. 같은 parameter group/task/version 취소는 결과가 확정될 때까지 같은 operation id를 재사용한다. Parent request row lock 안에서 값이 일치할 때만 남은 parameter task를 `canceled`로 닫고 이미 저장된 graph는 유지한다. 같은 operation/payload 재시도는 상태 전환, commit과 audit를 반복하지 않고 최초 결과를 반환하며, 응답 유실 시 한 번 재시도한 뒤 canonical canceled 상태를 조회한다. 같은 operation id에 다른 payload가 오거나 competing task decision이 먼저 처리됐으면 `409 task_conflict`다. `deferred`는 Catalog가 `allow_unresolved`로 허용한 개별 decision에만 사용한다. Graph에 남은 required unresolved configuration은 실행·배포 preflight에서 차단된다.

## 10. Errors

| HTTP | Code | Meaning |
|---|---|---|
| 400 | `invalid_decision` | task/action 조합이 유효하지 않음 |
| 400 | `unsupported_mode_contract` | `X-Agent-Builder-Mode-Contract` 값이 지원되지 않음 |
| 400 | `unsupported_generation_mode` | negotiated mode contract에서 표현할 수 없는 mode를 request 생성 전에 제출함 |
| 403 | `permission_denied` | active organization 또는 resource 권한 부족 |
| 404 | `resource_not_found` | 숨김 정책을 적용한 session/workflow/resource 없음 |
| 409 | `mode_contract_mismatch` | active request에 고정된 representation contract와 요청 header가 달라 같은 contract 재조회 또는 mode-free cancel이 필요함 |
| 409 | `request_in_progress` | 같은 session에 비종료 request가 있어 새 message request를 만들 수 없음 |
| 409 | `active_request_not_found` | session-scoped cancel 시 비종료 request가 없음 |
| 409 | `active_request_ambiguous` | legacy 이상으로 비종료 request가 둘 이상이어서 안전하게 선택할 수 없음 |
| 409 | `stale_graph` | expected base graph hash 또는 workflow `updated_at` 불일치 |
| 409 | `stale_protocol` | legacy Preview session은 direct-edit mutation을 수행할 수 없음 |
| 409 | `operation_payload_unavailable` | CDS 저장 전 유실된 full operations를 server가 재생할 수 없어 parent request terminal cancel 후 재생성 또는 현재 task 재입력이 필요함 |
| 409 | `operation_already_applied` | 다른 결과로 operation id를 중복 적용함 |
| 409 | `task_conflict` | expected task version이 current 상태와 다르거나 다른 decision이 먼저 처리됐거나 pending proposal이 target task를 예약함 |
| 409 | `mode_transition_conflict` | mode transition id/version이 stale하거나 competing transition이 먼저 처리됨 |
| 409 | `quick_completion_conflict` | 남은 설정 proposal의 request/task/graph/resource revision이 달라졌거나 원자적으로 적용할 수 없음 |
| 409 | `request_not_cancelable` | canceled 이외의 종료 request를 다시 취소하려고 함 |
| 422 | `mutation_context_required` | Agent Builder operation 저장에 CDS context가 없음 |
| 422 | `workflow_context_required` | direct-edit CDS 저장 대상 workflow가 없음 |
| 503 | `planner_unavailable` | intent model runtime 사용 불가 |

오류 응답은 raw message, parameter value, credential config, provider response를 반사하지 않는다.

## 11. Audit

- GraphMutation 발급, CDS 저장 결과, acknowledgement, stale/permission 차단, requested/effective mode, mode transition과 parameter task 상태 변경을 구분한다. Audit에는 full operations 대신 safe envelope 식별자, canonical mode, allowlisted reason code와 hash만 기록한다.
- Graph CDS save와 persisted revert save는 기존 `add_action_audit`를 graph write와 같은 transaction에 기록한다. Audit insert 실패 시 graph write도 rollback한다.
- audit metadata에는 safe ids, parameter key, action, reason만 포함한다.
- `credential_id`와 `model_id`는 permission/runtime 차단 audit에 기록할 수 있지만 credential name/config와 secret은 기록하지 않는다.
- planner와 repair 호출의 usage/cost attribution은 현재 API 계약에 포함하지 않는다. 후속 구현에서도 raw provider response나 credential config를 저장하지 않는다.

## 12. Compatibility Plan

1. MBA-228은 하나의 기능 PR에서 Catalog v3 schema/parser/parity test, GraphMutation, CDS save/acknowledgement, generic ParameterTask와 nullable session protocol migration을 구현한다.
2. Migration은 Alembic single head에 연결하고 disposable 기존 DB `upgrade head`, request 없는 null/direct session recovery와 direct-edit save/acknowledgement/recovery integration을 검증한다.
3. 신규 session은 `direct_edit_v1`을 기록한다. 기존 null Preview session은 backfill하거나 자동 변환하지 않고 `stale_protocol`로 복구하며 이전 preview/draft 적용을 금지한다.
4. 기존 Condition/Variable clarification 결과를 characterization fixture로 고정하고 catalog-derived ParameterTask/GraphMutation parity를 통과시킨 뒤 같은 기능 PR에서 Preview 전용 API/UI를 제거한다. 신규 응답은 `draft_preview`나 legacy apply action을 반환하지 않고 Preview-opened/apply route와 frontend Preview/`적용 및 저장` control이 남아 있으면 removal 검증을 실패시킨다. Preview를 수정·확장하거나 fallback으로 유지하지 않는다.
5. Frontend와 Gateway의 mixed-revision 무중단 전환, staged rollout/rollback, 배포 gate와 image artifact 검증은 별도 배포 DDR과 후속 이슈에서 수행한다.
6. 기존 intent model 권한 검증, generated model 추천과 KB 후보 표시 정책은 현재 revision에서 다시 실행한 호환 테스트로 유지하되 모델 표시 순서 변경은 MBA-228 범위에 포함하지 않는다.
7. 생성 모드 전환은 consumer-first로 도입한다. 첫 Gateway revision은 두 mode 이름을 모두 입력으로 수용하고 내부에서는 canonical로 정규화하지만, mode contract header가 없거나 `legacy-v1`인 응답에는 `configure_and_generate`를 유지한다. 새 request에는 정규화한 `mode_contract_version`을 기존 JSON에 고정하고, 값이 없는 기존 request는 `legacy-v1`로 읽으며 backfill하지 않는다.
8. 다음 Client revision은 `configure_and_generate|guided_generate`를 모두 읽되 모든 Gateway replica가 준비됐다는 배포 gate 전까지 legacy 값을 쓴다. 구형 Client와 신형 Gateway 조합이 canonical 응답을 먼저 받지 않아야 한다.
9. 모든 Gateway replica가 dual-input과 contract negotiation을 지원하고 Client dual-read gate가 확인된 뒤에만 `X-Agent-Builder-Mode-Contract: canonical-v2`를 허용한다. Request가 없는 오래 열린 session은 호출 header로 표현을 선택하지만 active request가 있으면 고정된 contract와 같은 header만 허용한다.
10. Client canonical-write 전환은 canonical-v2 협상 성공 뒤에만 수행한다. Rollback은 먼저 canonical/quick creation gate를 닫고 `mode_contract_version=canonical-v2`이면서 RequestStatus가 terminal이 아닌 request를 완료하거나 mode-free cancel로 종료해 active aggregate가 0건임을 확인한 뒤 legacy-write로 전환할 수 있다. 그러나 session GET이 반환할 수 있는 보존 기간 내 terminal request까지 포함한 `canonical-v2` retained-history aggregate가 0건이 되기 전에는 Gateway dual-input/contract-pinning, per-request contract 직렬화와 Client dual-read를 제거하거나 legacy-only Client를 배포하지 않는다. Completed quick history를 `configure_and_generate`로 projection하거나 숨기지 않는다. 두 집계는 request id/payload를 외부에 노출하지 않는다.
11. `quick_generate`, mode transition과 remaining quick completion은 canonical-v2, Gateway·Client·integration/E2E gate가 함께 준비된 revision에서만 노출한다. Client만 먼저 toggle을 노출하거나 Gateway가 미지원 mode를 암묵적으로 guided로 처리하지 않는다.
12. Quick mode는 Legacy Preview endpoint, payload 또는 저장소에 의존하지 않는다. Rollback 시 quick UI/endpoint creation gate를 먼저 닫고 canonical active request drain 뒤 기존 guided direct-edit와 `structure_only` 신규 write를 legacy 표현으로 유지한다. 보존 중 canonical terminal history가 있으면 session timeline은 각 request의 stored contract를 유지하고 dual-read Client만 이를 표시하며, legacy-only cutback은 retained-history aggregate가 0건이 된 뒤에만 허용한다.
## 2026-07-15 Direct-Edit Connection And Recovery Correction

- `direct_edit_v1` response does not include a Slack or GitHub `credential_ref` ParameterTask. Those nodes may remain unresolved and must be configured only through the existing Editor connection controls. Mail/Gmail managed credential tasks remain permission-filtered.
- Agent Builder never includes Slack/GitHub credential candidates, tokens, or raw credential values in its request or response. The external connection action is client-only navigation: no credential API, GraphMutation, workflow save, planner call, or external action is allowed.
- Canonical draft GET/POST and acknowledgement recovery use the same `graph_hash` and `updated_at`. Editor-only edge handle `displayNumber` is excluded from all graph payloads, hashes, CAS checks, and server persistence.
- A `resource_ref` or managed `credential_ref` candidate may provide both opaque `candidate_id` and graph `reference_value`. The client hydrates either representation; an unmatched value remains unavailable rather than being inferred as complete.
- Knowledge selection failure handling distinguishes permission, stale graph, task conflict, validation, pending acknowledgement, and unapplied retry states while preserving the same selection card and selected values.

## 2026-07-14 Graph Operation Dddition

`GraphMutation.operations`는 기존 node의 server-calculated layout 위치를 반영하기 위해 다음 operation을 지원한다.

```json
{
  "op": "replace_node_position",
  "node_id": "existing-node-id",
  "position": { "x": 580, "y": 0 }
}
```

이 operation은 `initial_graph`, `replace_workflow`, `graph_edit`의 canonical layout 결과에만 server가 발급한다. client가 임의 위치를 보내는 API가 아니다.

Knowledge 후보 응답은 use 권한을 통과한 active KB를 포함한다. 인덱싱 준비 상태는 candidate response 또는 knowledge-selection request의 유효성 조건이 아니며 run/deployment preflight의 조건이다. server-issued Agent Builder `mutation_context`가 있는 CAS 저장은 같은 권한/lifecycle 검사를 유지하되 retrieval readiness만 실행·배포 preflight로 미루며, 일반 Editor 저장은 retrieval-visible readiness를 계속 요구한다.

### MBA-275 Direct-Edit Safety And Relation Contract

- `set`의 typed value는 Catalog parameter 정의와 sensitivity/secret 정책을 통과해야 GraphMutation에 들어간다. secret-like 값 또는 detector 오류는 fail-closed하고 기존 `400 invalid_decision`으로 거부한다. 일반 Catalog validation issue는 HTTP 4xx가 아니라 `status=invalid`, `reason=catalog_validation_failed`인 task 결과로 저장·반환한다.
- `credential_ref`와 `resource_ref`는 서버가 검증한 opaque/canonical reference만 받는다. raw credential config, token, password와 secret-like 입력은 받지 않으며 오류 응답·audit·trace·log에도 원문을 포함하지 않는다.
- WorkflowNode 실행 admission의 필수 target은 `appId`다. `workflowId`는 기존 graph와 편집 화면을 위한 선택 metadata이며, 없거나 빈 값이어도 `appId`가 유효하면 실행 준비 상태를 차단하지 않는다. `appId`를 직접 변경하면 server는 선택된 App의 canonical Workflow ID로 `workflowId`를 정규화한다. `workflowId`를 직접 변경하거나 pair를 검증할 때는 각 resource의 organization과 권한을 확인하고 `App.workflow_id == Workflow.id`를 강제한다. malformed 또는 relation 불일치는 기존 `400 invalid_decision`, 권한 부족은 `403 permission_denied`로 매핑하며 대상 이름이나 내부 조회 결과를 반환하지 않는다. 검증 전후 graph, session revision, task 상태와 audit는 원자적으로 보존된다.
- Draft save의 CAS는 locked DB row의 최신 `graph_hash`와 `updated_at`을 기준으로 하며, 불일치는 기존 `409 stale_graph`다. lock query는 session identity map의 stale Workflow를 재사용하지 않는다.
