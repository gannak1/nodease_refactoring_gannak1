# Agent Builder API Specification

Status: Draft

## 1. Contract Boundary

이 문서는 Accepted ADR-0045/ADR-0046의 MBA-228 direct-edit API를 정의한다. ADR-0019는 Superseded Preview 기록이며 기존 결과는 characterization fixture로만 사용하고 direct-edit parity와 필수 검증 뒤 Preview API/UI를 제거한다.

모든 endpoint는 인증과 `X-Organization-Id`를 요구한다. Client는 raw workflow graph, credential config, secret value를 Agent Builder API로 보내지 않는다. Backend는 server-loaded workflow graph hash, workflow `updated_at`과 catalog version을 기준으로 판단한다. 신규 direct-edit session의 target contract는 단일 catalog v3다. 기존 Preview protocol session은 cutover 뒤 `stale_protocol`로 복구하며 미적용 draft를 새 protocol로 변환하지 않는다.

Base path는 `/api/v1/agent-builder`다.

## 2. Common Types

### 2.1 GenerationMode

```text
configure_and_generate | structure_only
```

### 2.2 RequestStatus

```text
planning | clarification_required | graph_mutation_ready | parameter_configuration |
completed | stale | stale_protocol | validation_failed | unsupported | failed | canceled
```

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
뒤 적용·CDS 저장·acknowledgement할 수 있다. Catalog version과 generation mode는 JSON metadata를 재사용하며 별도 column이나 legacy backfill을 요구하지 않는다.

Session protocol은 additive migration으로 추가하는 nullable
`AgentBuilderSession.protocol_version`에 기록한다. MBA-228 단일 기능 PR의 신규 direct-edit
session은 `direct_edit_v1`을 저장하며 기존 null row는 backfill하거나 자동 변환하지 않는다.
Gateway는 null/`direct_edit_v1`을 함께 읽고 null Preview session을 `stale_protocol`로 복구한다.
`generation_mode`는 request마다 달라질 수 있으므로 request `response_payload`에만 기록한다.
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

Response:

```json
{
  "session_id": "uuid",
  "workflow_id": "uuid",
  "app_id": "uuid",
  "protocol_version": "direct_edit_v1",
  "default_generation_mode": "configure_and_generate",
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
- secret-like message span과 parameter value 원문은 반환하지 않는다.
- stale mutation은 safe envelope만 반환하고 client가 자동 적용하지 않는다.
- mutation metadata의 `catalog_version`이 없거나 `2`이면 legacy stale로 반환하고, `3`인 mutation만 active 후보로 복구한다.
- session row의 `protocol_version`이 null인 기존 Preview session은 `status=stale_protocol`로 반환한다. Safe 대화 이력은 표시할 수 있지만 legacy preview/draft를 적용하거나 GraphMutation으로 변환할 수 없다.
- `stale_protocol`, server가 명시한 session not found 또는 invalid session 외의 transport/5xx 오류는 terminal 상태를 의미하지 않는다. Client는 저장된 session pointer를 보존하고 같은 GET만 `1초 -> 2초 -> 4초` 간격으로 최대 세 번 재시도할 수 있다. 세 번 모두 실패하면 UI는 `결과 확인 필요`와 수동 재조회 control을 표시한다.
- `stale_protocol` 응답은 redaction을 통과한 safe conversation을 읽기 전용으로 유지하고 재제출 안내를 포함한다. Client는 legacy Preview graph/draft/apply 정보를 복원하지 않고 신규 요청용 `direct_edit_v1` session을 한 번 생성하며 같은 stale session 전환을 반복하지 않는다.
- CDS 저장 전 full operations 응답이 유실되면 server는 이를 복구·재생하지 않고 기존 envelope를 `blocked`로 닫아 `operation_payload_unavailable` reason을 반환한다. Initial/graph-edit/replace는 request를 재생성하고 parameter decision은 현재 task/version에서 새 operation id로 다시 입력한다.
- Recovery는 최신 request row를 잠근 뒤 저장 결과가 없는 `pending_apply|pending_save`만 차단한다. `pending_ack|acknowledged|blocked|reverted`는 변경하지 않으며 차단 상태, 연결 task/Knowledge 복구와 safe audit는 한 transaction에서 확정한다.
- `parameter_update` 차단은 pending decision을 제거하고 같은 task/version을 `active`로 다시 연다. Initial/graph-edit/replace parameter group은 `blocked`, Knowledge resolution은 `canceled`로 닫는다.
- CDS 저장 뒤 acknowledgement만 유실된 operation은 persisted graph hash와 envelope의 expected/saved hash, operation id와 workflow `updated_at`으로 acknowledgement를 복구할 수 있다.
- `reverted` history boundary는 active mutation으로 반환하지 않고 모든 연결 ParameterTask/Knowledge resolution을 `canceled`로 복구한다. Parameter/Knowledge operation별 `reverted` 상태는 허용하지 않으며 Redo도 canceled 흐름을 자동 완료하지 않는다.

## 5. Natural Language Request

### POST `/sessions/{session_id}/messages`

Direct-edit session의 workflow graph가 비어 있지 않은데 structured request가 완결된 `new_workflow`이면 `replace_workflow` GraphMutation을 반환한다. 명시적 전체 교체는 `request_type=modify_workflow`, `draft_mode=replace_workflow`로 구조화하며 edit target을 요구하지 않는다. 둘 다 typed remove/add operation과 동일한 CDS/acknowledgement 경계를 사용한다.

Request:

```json
{
  "message": "웹훅으로 요청을 받아 Slack으로 보내는 워크플로우를 만들어줘",
  "workflow_id": "uuid",
  "app_id": "uuid",
  "selected_node_id": "node-id-or-null",
  "selected_edge_id": "edge-id-or-null",
  "generation_mode": "configure_and_generate",
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
- `generation_mode`가 없으면 `configure_and_generate`를 사용하며 request `response_payload`에 기록한다. Request가 생성된 뒤에는 변경하지 않는다.
- selected ids는 server-loaded graph 안에 있어야 하며 target hint일 뿐 권위 graph가 아니다.
- raw graph key, raw credential config, secret parameter payload를 포함하면 422 또는 safe validation failure로 거부한다.
- 정상 request는 planner provider를 한 번 호출한다. 최초 schema-valid 결과가 semantic invariant만 위반한 경우 safe code repair를 최대 한 번 수행할 수 있다. Provider/JSON/schema 실패에는 repair하지 않는다.
- `parameter_guidance_hints`는 2.13 계약으로 검증하고 잘못된 hint를 graph/task 권위값으로 사용하지 않는다.

Success response:

```json
{
  "request_id": "uuid",
  "status": "graph_mutation_ready",
  "structured_plan": {
    "request_type": "new_workflow",
    "intent_summary": "웹훅 입력을 Slack으로 전달",
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

`configure_and_generate`의 최초 응답은 workflow가 아직 저장되지 않았으므로
`parameter_group.status=pending_save`다. client가 workflow draft 저장을 완료한
뒤 acknowledgement 요청을 보내기 전까지는 local 상태를 `pending_ack`로 표시할 수 있지만,
개별 parameter task를 활성화하거나 입력을 받으면 안 된다.

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
- 저장 직전 current canonical graph hash와 workflow `updated_at`을 두 기대값과 비교한다. 하나라도 다르면 graph를 쓰지 않고 `409 stale_graph`를 반환한다.
- Backend는 request nodes/edges의 canonical hash가 persisted safe envelope의 `expected_result_graph_hash`와 같은지 검증한다. Typed operations를 DB에서 다시 읽거나 재생하지 않는다.
- Complete candidate graph는 catalog schema, node allowlist, connection policy와 structural validation을 다시 통과해야 한다.
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
- Backend는 parent `AgentBuilderRequest` row를 write lock으로 조회하고 target task id, `expected_task_version`과 action별 허용 status를 비교한다. `confirm`은 active 자동 추천 task에만 허용한다. 값 설정 `set`은 `active|completed|skipped|deferred|invalid`에 허용하며 `pending|canceled`에는 허용하지 않는다. `previous`는 current presentation task의 canonical status가 `active|completed|skipped|deferred`일 때 stable order상 이전 재편집 가능 task를 찾는다. 같은 `operation_id` 재시도는 기존 결과를 반환하고, 먼저 처리된 다른 decision 때문에 version이 바뀌면 `409 task_conflict`로 닫는다. 충돌 요청은 GraphMutation이나 next task를 만들지 않는다.
- 동일 operation id와 동일 canonical payload의 `confirm|set|defer|skip|cancel` 재시도는 최초 결과를 반환하고 GraphMutation, task activation, DB commit과 audit를 반복하지 않는다. Catalog validation으로 `invalid`가 된 `set`도 operation result와 safe validation issue를 저장해 동일 재시도에 최초 invalid 결과를 반환한다. 동일 id의 payload fingerprint가 다르면 `409 task_conflict`다.
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

### POST `/requests/{request_id}/cancel`

Planning 중 request를 취소한다. 아직 저장되지 않은 local GraphMutation은 editor transaction을 Undo하고 acknowledgement하지 않는다. 이미 저장된 GraphMutation은 6.4의 persisted Undo 계약으로만 복구한다.

### POST `/sessions/{session_id}/parameter-groups/{group_id}/cancel`

Request는 client-generated `operation_id`, 현재 `expected_task_id`와 `expected_task_version`을 포함한다. 같은 parameter group/task/version 취소는 결과가 확정될 때까지 같은 operation id를 재사용한다. Parent request row lock 안에서 값이 일치할 때만 남은 parameter task를 `canceled`로 닫고 이미 저장된 graph는 유지한다. 같은 operation/payload 재시도는 상태 전환, commit과 audit를 반복하지 않고 최초 결과를 반환하며, 응답 유실 시 한 번 재시도한 뒤 canonical canceled 상태를 조회한다. 같은 operation id에 다른 payload가 오거나 competing task decision이 먼저 처리됐으면 `409 task_conflict`다. `deferred`는 Catalog가 `allow_unresolved`로 허용한 개별 decision에만 사용한다. Graph에 남은 required unresolved configuration은 실행·배포 preflight에서 차단된다.

## 10. Errors

| HTTP | Code | Meaning |
|---|---|---|
| 400 | `invalid_decision` | task/action 조합이 유효하지 않음 |
| 403 | `permission_denied` | active organization 또는 resource 권한 부족 |
| 404 | `resource_not_found` | 숨김 정책을 적용한 session/workflow/resource 없음 |
| 409 | `stale_graph` | expected base graph hash 또는 workflow `updated_at` 불일치 |
| 409 | `stale_protocol` | legacy Preview session은 direct-edit mutation을 수행할 수 없음 |
| 409 | `operation_payload_unavailable` | CDS 저장 전 유실된 full operations를 server가 재생할 수 없어 request 재생성 또는 현재 task 재입력이 필요함 |
| 409 | `operation_already_applied` | 다른 결과로 operation id를 중복 적용함 |
| 409 | `task_conflict` | expected task version이 current 상태와 다르거나 다른 decision이 먼저 처리됨 |
| 422 | `mutation_context_required` | Agent Builder operation 저장에 CDS context가 없음 |
| 422 | `catalog_validation_failed` | node/parameter/selector 계약 위반 |
| 422 | `workflow_context_required` | direct-edit CDS 저장 대상 workflow가 없음 |
| 422 | `secret_input_not_allowed` | Agent Builder가 받지 않는 secret 원문 입력 |
| 503 | `planner_unavailable` | intent model runtime 사용 불가 |

오류 응답은 raw message, parameter value, credential config, provider response를 반사하지 않는다.

## 11. Audit

- GraphMutation 발급, CDS 저장 결과, acknowledgement, stale/permission 차단, parameter task 상태 변경을 구분한다. Audit에는 full operations 대신 safe envelope 식별자와 hash만 기록한다.
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
