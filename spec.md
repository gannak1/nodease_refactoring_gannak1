# Workflow Builder Agent Spec

## CAPABILITY

Workflow Builder Agent는 workflow 생성/편집 화면에서 작은 창으로 대기하다가, 사용자가 클릭해 chat으로 요구사항을 입력하면 현재 mbased node catalog와 권한 정보를 기반으로 workflow graph draft를 자동 생성하는 기능이다. 사용자는 노드를 직접 하나씩 배치하지 않고도 초안을 만들 수 있으며, agent가 만든 결과는 preview 후 사용자가 적용한다.

## CONSTRAINTS

- 이 기능은 workflow 실행기가 아니다. 실행은 기존 workflow engine이 담당한다.
- 이 기능은 MCP server를 필수로 요구하지 않는다. 초기 MVP는 내부 API와 service를 직접 사용한다.
- Agent의 산출물은 자연어 답변만이 아니라 workflow graph draft 또는 graph patch여야 한다.
- Agent는 node class를 직접 호출하지 않는다.
- Agent는 credential raw value를 조회하거나 LLM context에 포함하지 않는다.
- Agent는 현재 사용자의 organization, role, permission 범위 안에서만 node, KB, connection을 제안한다.
- Agent는 validation 실패 graph를 자동 저장하지 않는다.
- Agent는 사용자의 명시 승인 없이 deployment를 생성하지 않는다.
- Agent는 기존 graph를 보존해야 한다. 전체 교체는 사용자가 명시적으로 요청한 경우에만 허용한다.

## IMPLEMENTATION CONTRACT

### Actors

- Workflow creator: workflow 생성/편집 화면에서 agent를 사용하는 사용자
- Builder Agent: 자연어 요청을 graph draft로 변환하는 agent service
- Workflow Backend: draft 조회, draft 저장, validation, node catalog 제공
- Workflow Engine: 저장된 graph를 실제 실행하는 기존 runtime
- Organization Policy Layer: 사용자 권한, KB 접근권, connection 접근권을 제한하는 계층

### Frontend Surface

- Workflow editor 화면에 compact agent launcher를 표시한다.
- launcher 클릭 시 chat panel을 연다.
- chat panel은 현재 workflow context를 가진다.
- agent 응답은 설명, 누락 질문, preview graph 적용 버튼을 포함한다.
- 사용자가 preview 적용을 누르면 canvas 상태를 업데이트한다.
- 저장은 기존 workflow draft 저장 UX를 따른다.

### Backend Surface

- Builder Agent API는 workflow id와 user message를 받는다.
- API는 현재 사용자 권한 context를 사용한다.
- API는 current draft, node catalog, node schema, KB 목록, connection 목록을 tool layer를 통해 조회한다.
- API는 LLM 또는 rule-based planner를 사용해 graph draft 또는 graph patch를 생성한다.
- API는 validate_workflow_graph를 호출해 결과를 검증한다.
- API는 validation result, missing fields, preview graph를 반환한다.

### Internal Tool Contract

- list_available_nodes
- get_node_schema
- get_current_draft
- validate_workflow_graph
- list_knowledge_bases
- list_connections
- preview_graph_patch
- save_workflow_draft

### Agent Response Contract

- message: 사용자에게 보여줄 짧은 설명
- status: ready, needs_input, invalid, error 중 하나
- graph_preview: 적용 가능한 graph 또는 null
- graph_patch: 기존 graph에 적용할 patch 또는 null
- missing_fields: 사용자 입력이 필요한 항목 목록
- questions: 사용자에게 물어볼 질문 목록
- validation_errors: validation 실패 목록
- selected_nodes: agent가 선택한 node type 목록

### State Transitions

- closed: 작은 창으로 대기
- open: chat panel 표시
- planning: 사용자 요청 분석 및 node 후보 선택
- needs_input: 필수 설정 부족으로 사용자 질문 대기
- preview_ready: validation 통과 graph preview 준비
- applied: 사용자가 preview를 canvas에 적용
- saved: 사용자가 기존 저장 버튼으로 draft 저장
- failed: validation 또는 tool 호출 실패

### Data Implications

- 기존 Workflow.graph 저장 구조를 재사용한다.
- Agent 전용 영속 저장은 MVP에서 필수 아님.
- 대화 이력은 MVP에서는 client state 또는 짧은 server session으로 시작할 수 있다.
- 추후에는 agent session, prompt input, tool call, validation result, graph diff를 audit log로 남길 수 있다.

### Security And Policy

- credential raw value는 절대 agent prompt, response, trace에 포함하지 않는다.
- connection은 id, display name, provider, availability 정도만 제공한다.
- KB 목록은 사용자 권한으로 필터링된 결과만 제공한다.
- agent가 만든 graph는 저장 전 validation을 반드시 거친다.
- deployment는 MVP 범위 밖이며, 추후 추가하더라도 사용자 승인 단계가 필요하다.

### Observability

- agent request id
- workflow id
- user id
- organization id
- selected node types
- validation status
- missing field count
- applied 여부
- save 여부
- error reason

## NON-GOALS

- MCP server 구현
- Slack/Jira/GitHub 외부 MCP 연동
- workflow 자동 배포
- workflow 실행 자동 반복
- 실패 로그 기반 자동 수정
- credential 생성 또는 secret 관리
- 모든 node type을 완벽히 지원하는 범용 planner

## OPEN QUESTIONS

- 첫 MVP에서 graph를 full replacement로 반환할지 patch로 반환할지 결정해야 한다.
- node schema의 source of truth를 frontend nodeRegistry로 둘지 backend registry로 둘지 결정해야 한다.
- agent 대화 이력을 저장할지, session 동안만 유지할지 결정해야 한다.
- LLM provider와 model routing 정책을 정해야 한다.
- save_draft를 agent가 호출할 수 있게 할지, UI 저장 버튼만 허용할지 결정해야 한다.
- 기존 graph가 있을 때 merge 전략을 어떻게 할지 결정해야 한다.

## HANDOFF

다음 단계는 구현 전에 node catalog와 graph validation 계약을 먼저 고정하는 것이다. MVP 구현은 "chat input -> builder agent API -> graph preview -> user apply" 흐름으로 제한하고, MCP와 자동 배포는 후속 단계로 분리한다.

## Current Implementation Addendum

- Request includes `selectedNodeId` when the user has selected a canvas node.
- Existing non-empty graphs require a selected edit anchor unless the user explicitly asks for a new or replacement workflow.
- Guardrail is available as a frontend-only shell node with no runtime executor.
- Guardrail edit requests insert a `guardrailNode` around the selected node and rewire existing edges.
- Keyword Guardrail edit requests use temporary Pass / Fail branching.
- The agent connects the normal continuation path from Fail and adds a Guardrail Pass terminal node for matched keywords.
- Response still returns `graph_preview`; patch-level response can be added later.
