# Deployment Test Cases

Status: Draft
Verified Against: TBD

## Unit Tests

- Preflight graph scanner는 LLM node RAG 옵션의 explicit/materialized KB 후보를 찾고 unsupported shape는 safe warning 또는 blocked reason으로 낮춘다.
- Runtime audience resolver는 `api`, `webapp`, `widget`, `chatbot`, `mcp`, `schedule`, `webhook`를 anonymous public-only로 판정한다.
- `workflow_node` direct public/API/webhook/authenticated run execution is rejected. Subworkflow audience resolver는 parent execution subject를 상속하고, subject가 없으면 anonymous public-only로 판정한다.
- Workflow-node target resolver는 `workflowNode.data.appId`를 사용하고 `workflowId`로 target app을 찾지 않는다.
- Workflow-node target app이 존재하고 `active_deployment_id`가 있어도 active deployment의 `type`이 `workflow_node`가 아니면 `workflow_node_target_unavailable`로 처리한다.
- Workflow-node target이 pending active candidate graph를 가리킬 때도 candidate deployment type이 `workflow_node`가 아니면 `workflow_node_target_unavailable`로 처리한다.
- Workflow-node target unavailable, cycle, depth cap 초과는 `workflow_node_inherited` audience나 inactive preview에서도 warning으로 낮추지 않고 blocked로 유지한다.
- Scheduler service는 active `type=schedule` deployment만 로드/실행하고, non-schedule deployment id로 job이 호출되면 dispatch하지 않는다.
- Preflight response sanitizer는 hidden KB id/name/path, exact denied count, raw source metadata, raw exception을 제거한다.

## API Tests

- `POST /api/v1/deployments/preflight`는 blocked 결과도 `200 OK`와 `status="blocked"`로 반환한다.
- `POST /api/v1/deployments/preflight` with `is_active=false`는 inactive 저장 context를 반영해 활성화 blocker를 `status="warning"`으로 반환하되 required action은 유지한다.
- `POST /api/v1/deployments` with `is_active=true`는 private KB가 anonymous/public 실행 surface에 포함되면 `409 deployment.preflight.blocked`를 반환한다.
- `POST /api/v1/deployments` with `is_active=false`는 같은 graph를 저장할 수 있지만 active deployment 교체, public URL 활성화, schedule job 생성을 하지 않는다.
- Inactive deployment activation/toggle은 private KB preflight 실패 시 `409 deployment.preflight.blocked`를 반환한다.
- Active deployment delete는 다른 deployment를 자동 active로 승격하지 않는다.
- Public/API run endpoint, webhook endpoint, authenticated deployment run/run-info endpoint는 `workflow_node` active deployment를 직접 실행하거나 실행 정보를 노출하지 않는다.
- Webhook endpoint는 active deployment가 `type=webhook`이 아닌 경우 API/chatbot/schedule/workflow-node 등 모든 non-webhook deployment를 dispatch 전에 safe 404로 거부한다.
- Workflow-node runtime은 target app이 조직 소속인데 parent `execution_context.organization_id`가 없거나 target app organization과 다르면 fail-closed로 실행하지 않는다.
- Workflow-node runtime은 target app organization이 없으면 legacy/ambiguous target으로 보고 fail-closed로 실행하지 않는다.
- Workflow-node runtime은 target app의 active deployment가 `type=workflow_node`가 아니면 fail-closed로 실행하지 않는다.
- Workflow-node runtime은 `workflow_node_visited_app_ids`에 target app이 이미 있거나 `workflow_node_depth`가 cap에 도달하면 DB lookup 또는 subworkflow dispatch 전에 fail-closed로 실행하지 않는다.
- Workflow-node runtime의 순환/depth/target 설정 오류는 Celery retry로 재시도하지 않고 non-retryable runtime error로 즉시 실패한다.
- Active `type=workflow_node` deployment graph에 `scheduleTrigger`가 있어도 schedule record나 scheduler job을 생성하지 않는다.
- Blocking preflight 예외는 broad catch에서 generic `400`으로 변환되지 않는다.
- Source-managed KB public 후보는 public exposure approval primitive가 없으면 blocked로 처리한다.
- Webhook capture start/status rejects unauthenticated requests.
- Webhook capture start/status rejects authenticated users without target workflow `deploy` permission.
- Webhook capture status rejects missing, wrong, expired, or different-requester `capture_id`.
- Webhook capture cancel deletes a waiting session, rejects wrong/different-requester `capture_id`, and requires target workflow `deploy` permission.
- Webhook received after capture cancel follows the normal execution path instead of the capture path.
- Webhook capture stores and returns only a redacted/capped payload preview; token, secret, authorization, cookie, password, raw payload/content fields and known token patterns such as JWT, GitHub, Slack, AWS, Google API keys, and PEM private keys are not returned as raw values. Public identifier fields such as `issue.key` and `project.key` are preserved, while secret-bearing names such as `api_key`, `secret_key`, and `access_key` are redacted. Secret-like or oversized JSON field names are sanitized before returning or storing the preview.
- Webhook capture deletes the session after the captured status is read once.

## E2E Tests

- Deployment modal은 preflight preview가 blocked인 경우 safe reason과 required actions를 표시하고 hidden KB identity를 표시하지 않는다.
- Inactive save 후 activation을 시도하면 같은 preflight blocker가 사용자에게 표시된다.

## Permission Tests

- Preflight preview는 workflow deploy/manage 권한 없이는 호출할 수 없다.
- Organization member이지만 KB `use` 권한이 없는 사용자의 private KB 후보는 authenticated run에서는 denied 또는 unavailable로 표시되고, anonymous deployment에서는 blocked로 표시된다.
- Client-supplied `audience` hint는 create/activation의 server-derived audience 차단을 완화하지 못한다.

## Edge Cases

- workflow-node target active deployment가 없으면 safe blocked/warning reason을 반환하고 target app hidden identity를 노출하지 않는다.
- workflow-node 순환 또는 depth cap 초과는 safe blocked reason으로 닫는다.
- workflow-node target이 현재 활성화 후보 app을 다시 참조하면 기존 active deployment가 아니라 candidate graph 기준으로 순환을 감지한다.
- 일부 authorized KB의 operational failure는 Knowledge partial-result 정책으로만 표시하고 preflight permission denial과 섞지 않는다.
