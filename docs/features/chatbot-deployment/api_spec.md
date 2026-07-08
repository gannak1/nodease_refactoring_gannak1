# Chatbot Deployment API Spec

Status: Draft

챗봇 배포는 기존 배포/공개 실행 엔드포인트의 계약을 확장한다. 사내 private RAG 시연처럼 로그인 사용자의 권한으로 실행해야 하는 경우에는 별도 인증 배포 실행 엔드포인트를 사용한다.

## Endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| POST | `/api/v1/deployments` | 배포 생성. `type: "chatbot"` 지원 | 로그인 + workflow `deploy` 권한 |
| GET | `/api/v1/deployments/{deployment_id}/run-info` | 실행 화면용 safe 배포 정보 조회. secret/graph snapshot 제외 | 로그인 + workflow `execute` 권한 |
| POST | `/api/v1/deployments/{deployment_id}/run` | 활성 배포 snapshot을 로그인 사용자 권한 주체로 실행 | 로그인 + workflow `execute` 권한 |
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

### GET /api/v1/deployments/{deployment_id}/run-info (인증 내부 실행 정보)

Response body:

```json
{
  "deployment_id": "UUID",
  "app_id": "UUID",
  "workflow_id": "UUID",
  "name": "사내 문서 질문 응답 봇",
  "version": 1,
  "description": "선택 설명",
  "type": "chatbot",
  "input_schema": { "variables": [] },
  "output_schema": { "outputs": [] }
}
```

- 실행 화면이 입력 폼과 결과 preview를 만들 때만 사용한다.
- `auth_secret`, `graph_snapshot`, node prompt, KB hidden id 같은 내부 실행 설정은 반환하지 않는다.
- Gateway는 로그인 사용자에게 workflow `execute` 권한이 있는지 재검증한다.
- `X-Organization-Id`가 있으면 해당 active organization scope와 배포 앱의 organization이 일치해야 한다. 불일치 시 404를 반환한다.

### POST /api/v1/deployments/{deployment_id}/run (인증 내부 실행)

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

- Gateway는 로그인 사용자에게 workflow `execute` 권한이 있는지 재검증한다.
- `X-Organization-Id`가 있으면 해당 active organization scope와 배포 앱의 organization이 일치해야 한다. 불일치 시 resource-hiding 정책에 따라 404를 반환한다.
- 서버는 `execution_context.execution_subject = {"type": "user", "id": current_user.id}`를 주입한다.
- LLM node RAG는 이 `execution_subject` 기준으로 Knowledge `use` 권한과 source ACL gate를 다시 평가한다.
- `memory_mode`, `conversation_id` 처리 규칙은 공개 챗봇 실행과 동일하다.
- 인증 내부 실행에서 `conversation_id`가 있으면 서버는 `deployment_id + execution_subject + client_conversation_id`를 해시한 내부 id로 바꿔 사용자 간 memory context가 섞이지 않게 한다. 공개 실행은 기존 visitor conversation id를 유지한다.

Response: `{"status": "success", "results": { ... }}`.

## Persistence

- `workflow_runs.conversation_id` (`VARCHAR(255)`, nullable, indexed): 방문자별 대화 격리 키. `correlation_id`와 동일한 경로(`workflow_logger.create_run_log` data dict → `log_system.create_run_log`)로 저장된다.

## Memory Scoping

- `_build_memory_summary`(`apps/workflow_engine/.../llm_node.py`)는 `execution_context.conversation_id`가 있으면 `WorkflowRun`을 `workflow_id + conversation_id + status=SUCCESS`로 조회하고 `user_id` 필터를 사용하지 않는다. 없으면 기존 `workflow_id + user_id` 스코프를 유지한다.

## Errors

- 공개 실행과 인증 내부 실행 모두 404 배포 없음/비활성, 429 예산 초과, 504 타임아웃, 500 엔진 실패를 반환할 수 있다. 엔진 실패 응답 detail은 provider 오류, credential, raw payload를 노출하지 않는 고정된 safe message여야 한다. 인증 내부 실행은 추가로 400 `inputs must be an object`, 401/403 인증·권한 오류를 반환할 수 있다.

## Permissions

- 배포 생성은 workflow `deploy` 권한을 요구한다(기존과 동일).
- 공개 실행 표면(`/run-public`)은 무인증이며 `execution_subject`를 주입하지 않는다. 따라서 private Knowledge/RAG는 workflow owner 권한으로 fallback하지 않고 anonymous public-only 후보만 사용할 수 있다.
- 인증 내부 실행(`/deployments/{deployment_id}/run`)은 workflow `execute` 권한을 요구하며, 로그인 사용자를 RAG 실행 권한 주체로 전달한다.
