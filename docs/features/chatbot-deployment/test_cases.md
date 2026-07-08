# Chatbot Deployment Test Cases

Status: Draft

## Unit Tests

### Gateway — `apps/gateway/tests/services/test_chatbot_deployment_run.py`

- 챗봇 배포는 클라이언트가 `memory_mode`를 안 보내도 `execution_context.memory_mode`를 True로 강제하고, `conversation_id`를 그대로 전달한다.
- 챗봇 배포는 클라이언트가 `memory_mode: false`를 보내도 True로 덮어쓴다.
- 비챗봇 배포(webapp 등)는 기억모드를 강제하지 않는다(기본 False)지만 `conversation_id`는 전달한다.
- `conversation_id`가 없으면 `execution_context.conversation_id`는 None.
- `conversation_id`/`memory_mode`는 dispatch되는 워크플로우 `inputs`에서 제거된다.
- 공개 실행(`/run-public`)은 `execution_subject`를 주입하지 않고 workflow owner 권한으로 private RAG를 fallback하지 않는다.
- 인증 내부 실행(`/deployments/{deployment_id}/run`)은 `execution_context.execution_subject`에 로그인 사용자를 주입하고 예산 actor도 로그인 사용자로 기록한다.
- 인증 내부 실행의 `conversation_id`는 deployment, execution subject, client conversation id 기준으로 서버에서 namespace 처리되어 사용자 간 memory context가 섞이지 않는다.
- 인증 내부 실행은 활성 배포가 아니거나 app의 `active_deployment_id`와 일치하지 않는 배포를 거부한다.
- 실행 화면용 run-info는 `auth_secret`, `graph_snapshot`을 반환하지 않고 입력/출력 schema와 표시 metadata만 반환한다.
- 엔진 실패 예외 문자열에 secret-like 값이 있어도 배포 실행 응답 detail에는 원문을 노출하지 않는다.

### Workflow Engine — `apps/workflow_engine/tests/nodes/test_llm_memory_conversation_scope.py`

- `conversation_id`가 있으면 `_build_memory_summary`의 `WorkflowRun` 조회 필터에 `conversation_id`가 포함되고 `user_id`는 제외된다.
- `conversation_id`가 없으면 `user_id`가 포함되고 `conversation_id`는 제외된다.
- `memory_mode`가 꺼져 있으면 `WorkflowRun` 조회 자체를 하지 않는다.

### Log System — `apps/log_system/tests/test_create_run_log_conversation_id.py`

- `create_run_log`가 `data.conversation_id`를 `WorkflowRun.conversation_id`로 저장한다.
- `conversation_id`가 없으면 None으로 저장한다.

## API Tests

- `POST /deployments`에 `type: "chatbot"`으로 배포 생성 → 활성 배포 및 `url_slug` 반환.
- `GET /deployments/{deployment_id}/run-info`는 workflow `execute` 권한을 요구하고, active organization scope가 app organization과 다르면 404를 반환한다.
- `POST /deployments/{deployment_id}/run`은 workflow `execute` 권한을 요구하고, `inputs`가 object가 아니면 400을 반환한다.
- `GET /deployments/public/{slug}/info` → `type: "chatbot"` 직렬화 확인.

## E2E Tests

- `startNode → llmNode → answerNode` 워크플로우를 "챗봇 배포"로 배포하고 `${origin}/embed/chat/{slug}` 공유 링크 확인.
- 챗봇 링크에서 2~3턴 대화 → N턴 응답이 N-1턴 맥락을 반영(기억 동작).
- 다른 브라우저/시크릿(새 `conversation_id`)에서 열어 첫 대화 맥락이 새지 않음(방문자 격리).
- 대화 중 새로고침 후에도 서버 기억으로 맥락 유지(같은 `conversation_id`).

## Permission Tests

- 배포 생성은 `deploy` 권한 없는 사용자에게 거부(기존 deployment 권한 테스트 범위).
- 인증 내부 실행은 `execute` 권한 없는 사용자에게 거부한다.
- 공개 실행은 무인증 표면이므로 private Knowledge/RAG 후보를 anonymous public-only 경계 밖으로 확장하지 않는다.

## Edge Cases

- 시작 노드에 `conversation_id`/`memory_mode`와 동일 이름의 입력 변수가 있으면 해당 값이 pop되어 삼켜진다.
- `localStorage` 접근 불가 시 세션 한정 임시 `conversation_id`로 폴백(대화 격리는 유지, 새로고침 시 초기화 가능).
