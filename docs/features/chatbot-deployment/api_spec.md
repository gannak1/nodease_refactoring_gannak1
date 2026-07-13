# Chatbot Deployment API Spec

Status: Draft

챗봇 배포는 기존 배포/공개 실행 엔드포인트의 계약을 확장한다. 현재 `internal_chatbot`은 인증 deployment run/run-info endpoint에서 active membership·workflow `execute` 확인과 로그인 사용자의 execution subject 전달을 적용한다. Target private-RAG 내부 Chatbot access grant와 session namespace는 이 current contract 위에 추가되는 후속 기능이며, 동일한 완성 상태로 간주하지 않는다.

공개 route의 `inputs.memory_mode`, client `conversation_id`와 execution-log 조회는 Legacy Current Implementation이다. 인증 내부 route는 업무 `inputs`와 분리한 bounded `conversation.client_id`를 사용하지만 persistence/reader는 여전히 legacy execution-log 기반이다. 목표 session/grant/envelope/API 계약은 [Conversation Memory API spec](../conversation-memory/api_spec.md)을 따른다.

## Endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| POST | `/api/v1/deployments` | 배포 생성. `type: "chatbot"` 또는 `"internal_chatbot"` 지원 | 로그인 + workflow `deploy` 권한 |
| GET | `/api/v1/deployments/{deployment_id}/run-info` | 실행 화면용 safe 배포 정보 조회. secret/graph snapshot 제외 | 로그인 + workflow `execute` 권한 |
| POST | `/api/v1/deployments/{deployment_id}/run` | 활성 배포 snapshot을 로그인 사용자 권한 주체로 실행 | 로그인 + workflow `execute` 권한 + `application/json` |
| GET | `/api/v1/deployments/public/{url_slug}/info` | 공개 배포 정보(`type: "chatbot"` 포함) | 없음 (Legacy Current Implementation: CORS *) |
| POST | `/api/v1/run-public/{url_slug}` | 챗봇 공개 실행. `inputs.conversation_id`/`inputs.memory_mode` 수용 | 없음 (Legacy Current Implementation: CORS *) |

## Request And Response Models

### DeploymentType

`api | webapp | widget | mcp | workflow_node | schedule | webhook | chatbot | internal_chatbot`

- `chatbot` 값이 추가되었다. Postgres enum에는 멤버 이름 `CHATBOT`으로 저장되고, 응답에는 `deployment.type.value`인 `"chatbot"`(소문자)로 직렬화된다.
- `internal_chatbot`은 Postgres enum 멤버 `INTERNAL_CHATBOT`으로 저장되고 응답에는 `"internal_chatbot"`으로 직렬화된다. Public info와 `/run-public`에서는 노출·실행하지 않는다.
- Public chatbot deployment activation은 [deployment](../deployment/api_spec.md)의 preflight 계약을 따른다. `/run-public`은 사용자 subject를 주입하지 않으므로 private KB 후보가 있으면 활성 배포 create/toggle에서 `409 deployment.preflight.blocked`로 차단되어야 한다.

## Target Runtime Surface Separation

- `public_chatbot`: Public Conversation Access Grant만 사용하고 login cookie가 있어도 anonymous public-only RAG로 평가한다.
- `authenticated_internal_chatbot`: 현재는 cookie authentication, configured credentialed JSON/CORS 경계, active membership, workflow `execute`, current user KB permission으로 실행한다. 현재 구현을 CSRF token/exact-Origin 완료로 표현하지 않는다. Target에서는 별도 내부 Chatbot 이용 권한, CSRF token, exact Origin과 독립 Conversation Session namespace를 추가한다.
- 두 surface는 시각 Chatbot component만 재사용한다. Public route의 authentication/audience를 조건부 완화하거나 public grant를 execution subject로 승격하지 않는다.
- Public exact Origin/embed/CSP allowlist는 deployment-owned versioned config다. Config contract가 구현되기 전 client/environment fallback으로 browser session surface를 허용하지 않는다.

### POST /api/v1/run-public/{url_slug} (Legacy Chatbot Memory)

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
- 공개 endpoint의 `deployment.type`이 `chatbot`이면 서버가 `memory_mode`를 **항상 True로 강제**한다(클라이언트 값 무시).
- `conversation_id`는 `execution_context.conversation_id`로 전달되어 (1) 기억 조회 격리 키로 쓰이고 (2) `workflow_runs.conversation_id`에 저장된다.

Response: 기존 공개 실행과 동일. `{"status": "success", "results": { ... }}`.

### GET /api/v1/deployments/{deployment_id}/run-info (Current Generic 인증 실행 정보)

Response body:

```json
{
  "deployment_id": "UUID",
  "app_id": "UUID",
  "workflow_id": "UUID",
  "name": "사내 문서 질문 응답 봇",
  "version": 1,
  "description": "선택 설명",
  "type": "internal_chatbot",
  "input_schema": { "variables": [] },
  "output_schema": { "outputs": [] }
}
```

- 실행 화면이 입력 폼과 결과 preview를 만들 때만 사용한다.
- `auth_secret`, `graph_snapshot`, node prompt, KB hidden id 같은 내부 실행 설정은 반환하지 않는다.
- Gateway는 로그인 사용자에게 workflow `execute` 권한이 있는지 재검증한다.
- `X-Organization-Id`가 있으면 해당 active organization scope와 배포 앱의 organization이 일치해야 한다. 불일치 시 404를 반환한다.

### POST /api/v1/deployments/{deployment_id}/run (Current Generic 인증 실행)

Request body:

```json
{
  "inputs": {
    "<first_input_variable>": "사용자 메시지"
  },
  "conversation": {
    "client_id": "3f1c0000-0000-4000-8000-000000000000"
  }
}
```

- Gateway는 로그인 사용자에게 workflow `execute` 권한이 있는지 재검증한다.
- `X-Organization-Id`가 있으면 해당 active organization scope와 배포 앱의 organization이 일치해야 한다. 불일치 시 resource-hiding 정책에 따라 404를 반환한다.
- 서버는 `execution_context.execution_subject = {"type": "user", "id": current_user.id}`를 주입한다.
- LLM node RAG는 이 `execution_subject` 기준으로 Knowledge `use` 권한과 source ACL gate를 다시 평가한다.
- `conversation.client_id`는 UUID이며 extra field를 허용하지 않는다. Chatbot이 아닌 deployment에 전달하면 `400`으로 거부한다.
- `deployment.type`이 `chatbot` 또는 `internal_chatbot`이면 서버가 `memory_mode`를 항상 True로 강제하므로 신규 내부 Client는 `memory_mode`를 업무 `inputs`에 보내지 않는다.
- 인증 내부 실행에서 서버는 `deployment_id + execution_subject + client_id`를 domain-separated versioned digest로 바꿔 사용자·배포 간 memory context가 섞이지 않게 한다. raw `client_id`는 dispatch context, 응답, audit와 log에 기록하지 않는다.
- `inputs`에 workflow schema가 선언한 `conversation_id` 또는 `memory_mode`가 있으면 업무 입력으로 보존한다. typed control과 선언되지 않은 legacy `inputs.conversation_id`를 동시에 보내는 모호한 요청은 `400`으로 거부한다.
- 기존 인증 caller의 legacy reserved input은 schema collision이 없는 범위에서만 임시 호환하며 string, 최대 255자, control character 금지 조건을 적용한다. 공개 실행은 기존 visitor conversation id 계약을 유지한다.
- 요청 `Content-Type`의 media type은 정확히 `application/json`이어야 한다(`charset` parameter 허용). 누락, `text/plain`, `application/x-www-form-urlencoded`, `multipart/form-data`는 body/schema 처리나 workflow dispatch 전에 `415`로 거부한다.
- Browser credentialed JSON 호출은 configured `CORS_ORIGINS`의 명시적 HTTP(S) origin만 preflight를 통과한다. Wildcard credentialed origin은 Gateway 구성 시 거부한다. 이 현행 경계를 별도 CSRF token/exact-Origin 구현 완료로 표현하지 않는다.

Response: `{"status": "success", "results": { ... }}`.

## Legacy Current Implementation Persistence

- `workflow_runs.conversation_id` (`VARCHAR(255)`, nullable, indexed): Legacy 방문자별 대화 격리 키. `correlation_id`와 동일한 경로(`workflow_logger.create_run_log` data dict → `log_system.create_run_log`)로 저장되며 Target Conversation Session source of truth가 아니다.

## Memory Scoping

- `_build_memory_summary`(`apps/workflow_engine/.../llm_node.py`)는 `execution_context.conversation_id`가 있으면 `WorkflowRun`을 `workflow_id + conversation_id + status=SUCCESS`로 조회하고 `user_id` 필터를 사용하지 않는다. 없으면 기존 `workflow_id + user_id` 스코프를 유지한다.
- 위 규칙은 legacy 전용이다. Target은 server-issued grant 또는 authenticated session scope, dedicated Memory store, node별 policy와 current source authorization을 사용한다.

## Errors

- 공개 실행과 current generic 인증 실행 모두 404 배포 없음/비활성, 429 예산 초과, 504 타임아웃, 500 엔진 실패를 반환할 수 있다. 엔진 실패 응답 detail은 provider 오류, credential, raw payload를 노출하지 않는 고정된 safe message여야 한다. Generic 인증 실행은 추가로 400 invalid/non-object input, invalid/conflicting conversation control, non-Chatbot conversation control, 401/403 인증·권한 오류와 415 non-JSON media type을 반환할 수 있다. Client는 문서화되지 않은 임의 `detail` string을 그대로 표시하지 않는다. Target authenticated internal Chatbot의 별도 permission/error contract는 해당 기능 구현 문서에서 확정한다.

## Permissions

- 배포 생성은 workflow `deploy` 권한을 요구한다(기존과 동일).
- 공개 실행 표면(`/run-public`)은 무인증이며 `execution_subject`를 주입하지 않는다. 따라서 private Knowledge/RAG는 workflow owner 권한으로 fallback하지 않고 anonymous public-only 후보만 사용할 수 있다.
- `internal_chatbot` 인증 실행(`/deployments/{deployment_id}/run`)은 대상 workflow organization의 active membership과 workflow `execute` 권한을 요구한다. `X-Organization-Id`가 전달되면 배포 앱 organization과의 일치도 확인하며, 로그인 사용자를 RAG 실행 권한 주체로 전달한다.
- Target Conversation Session과 별도 내부 챗봇 access grant는 현재 `internal_chatbot`의 실행 주체·KB permission 재검사를 대체하지 않으며, 도입 시 별도 API 계약으로 추가한다.
