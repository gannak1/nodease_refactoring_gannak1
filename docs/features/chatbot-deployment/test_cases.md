# Chatbot Deployment Test Cases

Status: Draft
Verified Against: feat/implement-chat-bot-node @ 8e7dbb3

## Unit Tests

### Gateway — `apps/gateway/tests/services/test_chatbot_deployment_run.py`

- 챗봇 배포는 클라이언트가 `memory_mode`를 안 보내도 `execution_context.memory_mode`를 True로 강제하고, `conversation_id`를 그대로 전달한다.
- 챗봇 배포는 클라이언트가 `memory_mode: false`를 보내도 True로 덮어쓴다.
- 비챗봇 배포(webapp 등)는 기억모드를 강제하지 않는다(기본 False)지만 `conversation_id`는 전달한다.
- `conversation_id`가 없으면 `execution_context.conversation_id`는 None.
- `conversation_id`/`memory_mode`는 dispatch되는 워크플로우 `inputs`에서 제거된다.

### Workflow Engine — `apps/workflow_engine/tests/nodes/test_llm_memory_conversation_scope.py`

- `conversation_id`가 있으면 `_build_memory_summary`의 `WorkflowRun` 조회 필터에 `conversation_id`가 포함되고 `user_id`는 제외된다.
- `conversation_id`가 없으면 `user_id`가 포함되고 `conversation_id`는 제외된다.
- `memory_mode`가 꺼져 있으면 `WorkflowRun` 조회 자체를 하지 않는다.

### Log System — `apps/log_system/tests/test_create_run_log_conversation_id.py`

- `create_run_log`가 `data.conversation_id`를 `WorkflowRun.conversation_id`로 저장한다.
- `conversation_id`가 없으면 None으로 저장한다.

## API Tests

- `POST /deployments`에 `type: "chatbot"`으로 배포 생성 → 활성 배포 및 `url_slug` 반환.
- `GET /deployments/public/{slug}/info` → `type: "chatbot"` 직렬화 확인.

## E2E Tests

- `startNode → llmNode → answerNode` 워크플로우를 "챗봇 배포"로 배포하고 `${origin}/embed/chat/{slug}` 공유 링크 확인.
- 챗봇 링크에서 2~3턴 대화 → N턴 응답이 N-1턴 맥락을 반영(기억 동작).
- 다른 브라우저/시크릿(새 `conversation_id`)에서 열어 첫 대화 맥락이 새지 않음(방문자 격리).
- 대화 중 새로고침 후에도 서버 기억으로 맥락 유지(같은 `conversation_id`).

## Permission Tests

- 배포 생성은 `deploy` 권한 없는 사용자에게 거부(기존 deployment 권한 테스트 범위).

## Edge Cases

- 시작 노드에 `conversation_id`/`memory_mode`와 동일 이름의 입력 변수가 있으면 해당 값이 pop되어 삼켜진다.
- `localStorage` 접근 불가 시 세션 한정 임시 `conversation_id`로 폴백(대화 격리는 유지, 새로고침 시 초기화 가능).
