# Chatbot Deployment API Spec

Status: Draft
Verified Against: feat/implement-chat-bot-node @ 8e7dbb3

챗봇 배포는 신규 엔드포인트를 추가하지 않고, 기존 배포/공개 실행 엔드포인트의 계약을 확장한다.

## Endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| POST | `/api/v1/deployments` | 배포 생성. `type: "chatbot"` 지원 | 로그인 + workflow `deploy` 권한 |
| GET | `/api/v1/deployments/public/{url_slug}/info` | 공개 배포 정보(`type: "chatbot"` 포함) | 없음 (CORS *) |
| POST | `/api/v1/run-public/{url_slug}` | 챗봇 공개 실행. `inputs.conversation_id`/`inputs.memory_mode` 수용 | 없음 (CORS *) |

## Request And Response Models

### DeploymentType

`api | webapp | widget | mcp | workflow_node | schedule | webhook | chatbot`

- `chatbot` 값이 추가되었다. Postgres enum에는 멤버 이름 `CHATBOT`으로 저장되고, 응답에는 `deployment.type.value`인 `"chatbot"`(소문자)로 직렬화된다.

### POST /api/v1/run-public/{url_slug} (챗봇)

Request body:

```json
{
  "inputs": {
    "<first_input_variable>": "사용자 메시지",
    "memory_mode": true,
    "conversation_id": "3f1c… (UUIDv4)"
  }
}
```

- `memory_mode`, `conversation_id`는 `inputs` 내부 키로 전달된다.
- 서버(`DeploymentService.run_deployment`)는 dispatch 전에 두 값을 `inputs`에서 pop한다. 따라서 워크플로우 노드에는 전달되지 않는다.
- `deployment.type == chatbot`이면 서버가 `memory_mode`를 **항상 True로 강제**한다(클라이언트 값 무시).
- `conversation_id`는 `execution_context.conversation_id`로 전달되어 (1) 기억 조회 격리 키로 쓰이고 (2) `workflow_runs.conversation_id`에 저장된다.

Response: 기존 공개 실행과 동일. `{"status": "success", "results": { ... }}`.

## Persistence

- `workflow_runs.conversation_id` (`VARCHAR(255)`, nullable, indexed): 방문자별 대화 격리 키. `correlation_id`와 동일한 경로(`workflow_logger.create_run_log` data dict → `log_system.create_run_log`)로 저장된다.

## Memory Scoping

- `_build_memory_summary`(`apps/workflow_engine/.../llm_node.py`)는 `execution_context.conversation_id`가 있으면 `WorkflowRun`을 `workflow_id + conversation_id + status=SUCCESS`로 조회하고 `user_id` 필터를 사용하지 않는다. 없으면 기존 `workflow_id + user_id` 스코프를 유지한다.

## Errors

- 기존 공개 실행 에러 계약과 동일(404 배포 없음/비활성, 429 예산 초과, 504 타임아웃, 500 엔진 실패). 챗봇 전용 신규 에러 코드는 없다.

## Permissions

- 배포 생성은 workflow `deploy` 권한을 요구한다(기존과 동일). 공개 실행 표면(`/run-public`)은 무인증이다.
