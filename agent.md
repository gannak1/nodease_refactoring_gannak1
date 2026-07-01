# Workflow Builder Agent

## Role

Workflow Builder Agent는 사용자의 자연어 요청을 mbased workflow graph draft로 변환하는 설계 보조 agent다. 이 agent는 workflow를 직접 실행하지 않는다. 실행은 기존 workflow engine이 담당하고, agent는 노드 선택, 연결 구성, 필수 설정 확인, validation, 사용자 확인까지를 담당한다.

## User Surface

- 위치: workflow 생성/편집 화면 안.
- 기본 상태: 화면 한쪽에 작은 floating launcher 또는 compact panel로 대기.
- 열림 상태: 사용자가 클릭하면 chat panel이 열리고, 현재 workflow canvas와 연결된 agent 대화가 시작된다.
- 적용 방식: agent가 만든 graph는 바로 저장하지 않고 preview로 보여준다. 사용자가 적용하면 canvas에 반영하고, 저장은 기존 draft 저장 흐름을 따른다.

## Goal

사용자가 "Jira 이슈가 생성되면 관련 KB를 검색하고 요약해서 Slack에 보내줘"처럼 말하면, agent는 현재 사용 가능한 node catalog를 보고 실행 가능한 workflow graph draft를 만든다.

## Inputs

- 사용자 자연어 요청
- 현재 workflow id
- 현재 workflow draft graph
- 사용 가능한 workflow node catalog
- node별 required config, input, output, connection rule
- 사용자의 organization, role, permission context
- 사용 가능한 knowledge base 목록
- 사용 가능한 connection 또는 credential의 존재 여부
- 이전 agent 대화 상태

## Outputs

- 생성 또는 수정된 workflow graph draft
- agent가 선택한 node 목록과 선택 이유
- 누락된 설정 목록
- 사용자에게 물어볼 질문 목록
- validation 결과
- canvas에 적용 가능한 graph patch 또는 full graph

## Agent State

- current_request: 사용자의 최신 요청
- current_graph: 현재 workflow draft
- planned_nodes: agent가 선택한 node 후보
- planned_edges: agent가 구성한 연결 후보
- missing_fields: Slack channel, Jira project, KB id 등 사용자 결정이 필요한 값
- validation_errors: graph validation 결과
- pending_questions: 사용자에게 물어야 할 질문
- last_preview_graph: 아직 저장되지 않은 preview graph

## Tools

Agent는 DB, node class, credential raw value에 직접 접근하지 않는다. 아래 내부 tool contract를 통해서만 작업한다.

- list_available_nodes: 현재 사용자가 사용할 수 있는 workflow node 목록 조회
- get_node_schema: 특정 node type의 입력, 출력, 필수 설정, 연결 규칙 조회
- get_current_draft: 현재 workflow draft graph 조회
- validate_workflow_graph: 생성된 graph의 구조, 필수 설정, 연결 오류 검사
- preview_graph_patch: 현재 canvas에 적용할 후보 graph 반환
- save_workflow_draft: 사용자가 승인한 graph를 draft로 저장
- list_knowledge_bases: 사용자가 접근 가능한 KB 목록 조회
- list_connections: 사용자가 접근 가능한 Slack, Jira, GitHub 등 connection 목록 조회
- get_run_logs: 추후 실패 분석 기능에서 실행 로그 조회

## Policy

- Agent는 workflow node를 직접 실행하지 않는다.
- Agent는 credential secret, Slack token, webhook raw URL, API key를 LLM context에 넣지 않는다.
- Agent는 권한 없는 KB, connection, workflow, node를 추천하지 않는다.
- Agent는 validation에 실패한 graph를 자동 저장하지 않는다.
- Agent는 배포를 자동 수행하지 않는다.
- Agent는 기존 graph를 임의로 삭제하지 않는다. 사용자가 "새로 만들어줘"라고 한 경우에만 전체 교체를 제안한다.
- Agent는 확실하지 않은 필수 설정이 있으면 추측하지 않고 질문한다.

## Planning Behavior

1. 사용자의 요청을 trigger, action, condition, data source, destination으로 분해한다.
2. 사용 가능한 node catalog에서 필요한 node type을 고른다.
3. node schema를 확인해 필수 config를 채운다.
4. 모르는 값은 missing_fields로 분류한다.
5. graph draft를 만든다.
6. validation을 실행한다.
7. validation 실패가 agent가 고칠 수 있는 구조 오류면 수정한다.
8. 사용자 결정이 필요한 값이면 질문한다.
9. validation이 통과하면 preview graph를 반환한다.
10. 사용자가 승인하면 canvas에 적용하고 draft 저장을 허용한다.

## MVP Scope

- 자연어로 새 workflow draft 생성
- 현재 workflow draft를 참고한 graph patch 생성
- node catalog 기반 node 선택
- graph validation
- 누락 설정 질문
- preview 후 사용자 승인 적용

## Later Scope

- test run 자동 실행
- run log 기반 graph 수정 제안
- 기존 workflow 예시 RAG 검색
- 팀별 workflow template 추천
- 외부 MCP client가 mbased workflow를 생성하도록 MCP server 노출
- Slack/Jira/GitHub connection metadata 탐색

## Success Criteria

- agent가 만든 graph가 validation을 통과한다.
- 사용자가 수정 없이 canvas에 적용할 수 있다.
- 필수 설정 누락 시 agent가 저장하지 않고 질문한다.
- 권한 없는 KB 또는 connection이 graph에 포함되지 않는다.
- secret raw value가 agent response, prompt, trace에 남지 않는다.

## Current Implementation Addendum

- Add a Guardrail node as a frontend-only configuration shell.
- Guardrail supports Check Text for Violations and Sanitize Text modes.
- Guardrail stores selected categories, text input, upstream selector, system message, custom policy, and custom regex.
- The workflow builder agent edits from the currently selected node when a non-empty graph already exists.
- If no node is selected in an existing graph, the agent asks for an edit anchor instead of appending another workflow branch.
- For Guardrail requests, the agent may insert the Guardrail node before or after the selected node by rewiring existing edges.
- For temporary keyword Guardrail requests, the agent configures Pass / Fail outputs.
- Pass means the keyword branch matched and routes to a Guardrail Pass terminal result.
- Fail means no keyword branch matched and continues the normal workflow path.
