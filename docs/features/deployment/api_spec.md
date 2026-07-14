# Deployment API Spec

Status: Draft
Verified Against: `feature/mba-219 @ 08645ea8`

## Endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| POST | `/api/v1/deployments/preflight` | 배포 graph snapshot과 deployment type 기준으로 runtime availability를 검사한다 | 로그인 + workflow deploy/manage 권한 |
| POST | `/api/v1/deployments` | 배포 생성. `is_active=true`이면 blocking preflight를 통과해야 한다 | 로그인 + workflow deploy/manage 권한 |
| PATCH | `/api/v1/deployments/{deployment_id}/toggle` | 배포 활성/비활성 전환. 활성화 시 blocking preflight를 통과해야 한다 | 로그인 + workflow deploy/manage 권한 |
| DELETE | `/api/v1/deployments/{deployment_id}` | 배포 삭제. active 삭제 시 자동 승격하지 않는다 | 로그인 + workflow deploy/manage 권한 |
| GET | `/api/v1/deployments/public/{url_slug}/info` | Public app 화면용 safe metadata 조회 | 인증 없음. 기본 policy는 `webapp`, `widget`, `chatbot`만 허용 |
| GET | `/api/v1/deployments/{deployment_id}/run-info` | 로그인 사용자 실행 화면에 필요한 safe deployment metadata 조회 | 로그인 + workflow execute 권한 |
| POST | `/api/v1/deployments/{deployment_id}/run` | 로그인 사용자를 execution subject로 활성 deployment snapshot 실행 | 로그인 + workflow execute 권한 |
| POST | `/api/v1/hooks/{url_slug}` | Public webhook trigger execution or pending capture ingestion | Exactly one App secret source: Bearer primary or `X-Webhook-Secret` compatibility header |
| GET | `/api/v1/hooks/{url_slug}/capture/start` | Start a short-lived webhook payload capture session | User session + target workflow `deploy` permission |
| GET | `/api/v1/hooks/{url_slug}/capture/status?capture_id=...` | Poll one capture session and return a redacted preview once captured | User session + same requester + target workflow `deploy` permission + capture nonce |
| POST | `/api/v1/hooks/{url_slug}/capture/cancel?capture_id=...` | Cancel a pending capture session | User session + same requester + target workflow `deploy` permission + capture nonce |

## Request And Response Models

### `GET /api/v1/deployments/public/{url_slug}/info`

인증 없는 공유 화면에서 입력 폼을 구성하기 위한 metadata endpoint다. Production 기본 `DeploymentRuntimePolicy`는 active deployment가 target app 소유이고 `type`이 `webapp`, `widget`, `chatbot`인 경우에만 응답한다. API, `internal_chatbot`, MCP, schedule, webhook, workflow-node, unknown/empty type과 stale/cross-app active pointer는 safe `404`로 닫는다.

응답은 `url_slug`, safe app name/description, deployment version/type, input/output schema만 포함하고 app secret, graph snapshot, workflow/internal organization identifier를 포함하지 않는다. Allowlist 교체는 FastAPI composition dependency에 불변 policy 객체를 명시적으로 주입하는 방식만 허용하며 환경변수 기반 확장은 지원하지 않는다.

### `POST /api/v1/deployments/preflight`

Request body:

```json
{
  "app_id": "00000000-0000-0000-0000-000000000000",
  "type": "api",
  "config": {},
  "is_active": true,
  "graph_snapshot": {
    "nodes": [],
    "edges": []
  },
  "audience": "anonymous_public"
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `app_id` | yes | Target app. Server validates active organization and deploy/manage permission |
| `type` | no | `api`, `webapp`, `widget`, `chatbot`, `internal_chatbot`, `mcp`, `workflow_node`, `schedule`, `webhook`. Defaults to `api` |
| `config` | no | Deployment-specific config. Defaults to `{}` |
| `is_active` | no | Preview context. Defaults to `true`; inactive create may warn but does not activate |
| `graph_snapshot` | no | If omitted, server resolves the current app/workflow deployment snapshot candidate |
| `audience` | no | UI hint only. Security decisions use server-derived audience in create/enable paths |

Conversation-capable target snapshot은 별도 server-derived metadata로 immutable deployment version 또는 snapshot hash, conversation mapping version, node Memory policy version, `memory_contract_version`, `storage_generation`을 포함한다. Client `config`나 `audience`가 이 binding을 선택하거나 기존 session을 current active deployment로 rebind할 수 없다.

Preview response uses `200 OK` even when blocked:

`is_active=false` preview는 Knowledge audience/lifecycle activation blocker와 null unresolved 같은 실제 미완성 managed configuration을 safe reason/action이 있는 `status="warning"`으로 낮출 수 있다. Malformed 또는 over-limit Knowledge reference, non-null unavailable Mail credential, `node_configuration_invalid`, malformed graph, workflow-node structural error와 validator unavailable은 `status="blocked"`를 유지한다. `is_active=true` 생성과 이후 활성화/toggle은 blocking `409` enforcement를 사용한다.

```json
{
  "status": "blocked",
  "audience": "anonymous_public",
  "safe_summary": {
    "blocked_reason": "private_collection_requires_execution_subject",
    "affected_node_count": 1,
    "affected_kb_count_bucket": "0",
    "affected_collection_count_bucket": "1",
    "candidate_budget_limited": false
  },
  "required_actions": [
    {
      "action": "remove_private_collection_or_use_authenticated_run",
      "label": "Private Collection을 제거하거나 인증 실행 경로를 사용하세요"
    }
  ],
  "warnings": [],
  "nodes": [
    {
      "node_id": "llm-1",
      "node_type": "llmNode",
      "status": "blocked",
      "reason_codes": ["private_collection_requires_execution_subject"],
      "knowledge_base_count_bucket": "0",
      "knowledge_collection_count_bucket": "1",
      "candidate_budget_limited": false
    }
  ]
}
```

`status` values:

| Status | Meaning |
| --- | --- |
| `passed` | Blocking issue 없음 |
| `warning` | 저장은 가능하지만 활성화 전 확인이 필요한 비차단 이슈 있음 |
| `blocked` | 활성 deployment surface에 올릴 수 없음 |

Preflight가 해석하는 LLM node graph field는 다음 두 목록이다.

- `knowledgeBases`: 최대 20개의 `{ "id": "<canonical-uuid>", "name": "<bounded-display>" }` 객체
- `knowledgeCollections`: 최대 20개의 `{ "id": "<canonical-uuid>", "safeLabel": "<optional-bounded-display>" }` 객체

Display field는 응답 표시 snapshot일 뿐 authorization이나 routing 입력이 아니다. 목록이 아닌 값, 허용되지 않은 field, non-canonical UUID, control character, 21번째 항목은 fixed configuration reason으로 차단한다.

Additive safe result fields:

| Field | Meaning |
| --- | --- |
| `safe_summary.affected_collection_count_bucket` | 이슈에 포함된 Collection 수의 안전한 bucket. 실제 hidden membership 수가 아님 |
| `safe_summary.candidate_budget_limited` | direct configured refs와 selected Collection active-member aggregate상 runtime 후보 20개 제한 가능성 |
| `nodes[].knowledge_collection_count_bucket` | 해당 node 이슈의 안전한 Collection count bucket |
| `nodes[].candidate_budget_limited` | 해당 node의 보수적 후보 제한 가능성 |

MBA-233 Knowledge reason/action code는 다음과 같다.

| Reason code | Status | Required action |
| --- | --- | --- |
| `knowledge_reference_invalid` | blocked | `fix_invalid_knowledge_references` |
| `knowledge_reference_limit_exceeded` | blocked | `reduce_knowledge_references` |
| `knowledge_base_unavailable` | blocked 또는 inactive warning | `remove_unavailable_kb_reference` |
| `knowledge_collection_unavailable` | blocked 또는 inactive warning | `remove_unavailable_collection_reference` |
| `private_kb_requires_execution_subject` | blocked 또는 inactive warning | `remove_private_kb_or_use_authenticated_run` |
| `private_collection_requires_execution_subject` | blocked 또는 inactive warning | `remove_private_collection_or_use_authenticated_run` |
| `source_public_exposure_required` | blocked 또는 inactive warning | `approve_source_public_exposure_or_remove_reference` |
| `knowledge_candidate_budget_limited` | warning | `review_knowledge_candidate_selection` |
| `workflow_node_execution_subject_inherited` | warning | `verify_parent_execution_subject` |

`knowledge_candidate_budget_limited`만 있는 preview는 `status="warning"`이며 active create를 차단하지 않는다. Runtime의 실제 candidate resolution이 current permission, membership, lifecycle, readiness, source policy와 dedupe를 다시 적용하므로 preflight boolean은 capability나 exact count가 아니다.

Response는 hidden KB/Collection/child id, name, label, path, exact denied/member count, raw graph/source metadata, Mail credential ID/name/email, Slack token/Webhook URL/channel/payload와 raw exception을 포함하지 않는다. Public graph projection은 root와 embedded subgraph의 두 Knowledge reference 배열도 제거한다.

MBA-219 managed configuration reason/action은 다음 값을 추가한다.

| Reason code | Required action |
| --- | --- |
| `node_configuration_unresolved` | `complete_node_configuration` |
| `node_configuration_invalid` | `fix_node_configuration` |
| `mail_credential_unavailable` | `select_available_mail_credential` |
| `mail_execution_subject_required` | `use_authenticated_execution_surface` |
| `mail_execution_subject_inherited` | `verify_parent_execution_subject` |
| `node_configuration_validator_unavailable` | `remove_or_update_unsupported_node` |
| `workflow_graph_invalid` | `fix_workflow_graph` |

Missing, revoked, cross-organization과 permission-denied Mail credential은 `mail_credential_unavailable` 하나로 정규화한다. Non-null unavailable credential, `node_configuration_invalid`, `workflow_graph_invalid`, WorkflowNode target/cycle 오류와 `node_configuration_validator_unavailable`은 `is_active=false`에서도 blocked로 유지한다. `credential_id=null`은 `configuration_state=unresolved`인 경우에만 inactive warning 보존 대상이다. 최상위 graph는 명시적 trigger/start node 하나, Loop body는 incoming executable edge가 없는 실행 진입점 하나를 요구한다. Graph 상한은 최상위와 모든 Loop subgraph 합산 node 1,000개, edge 5,000개, subgraph depth 16이다.

### Create / Activation Blocking

`POST /api/v1/deployments`에서 `is_active=true`이거나, `PATCH /api/v1/deployments/{deployment_id}/toggle`이 inactive deployment를 active로 바꾸는 경우 server-derived audience로 blocking preflight를 실행한다.

`is_active=false` 생성은 null unresolved 등 허용된 warning만 저장할 수 있으며 active deployment 교체, public URL 활성화, schedule job 생성 같은 실행 부작용을 만들지 않는다. 임의 non-null UUID, revoked/cross-organization/permission-denied credential은 저장하지 않는다.

`POST /api/v1/deployments/preflight` preview는 durable `permission.denied` audit을 만들지 않는다. Create/toggle enforcement에서 same-organization active credential의 `use` 거부가 확인되면 response에는 상세 원인을 노출하지 않고 resource별 audit을 정확히 한 번 기록한다.

Public `type="chatbot"`은 항상 `public_chatbot` audience로 preflight하므로 private KB 후보가 있으면 activation이 차단된다. `internal_chatbot`은 public Chatbot audience를 완화하거나 login cookie를 public route에 선택적으로 붙이지 않고 별도 authenticated surface와 runtime/session namespace를 사용한다. Server-derived `authenticated_user` preflight는 private 여부만으로 차단하지 않지만 direct KB와 Collection의 organization/lifecycle/sync/retrieval readiness는 계속 조회하고, missing 또는 unavailable reference는 generic blocker로 닫는다.

Selected Collection 검사는 selected ID와 active organization으로 범위를 제한하고 active lifecycle과 `sync_state != source_deleted`를 요구한다. Missing, inactive, deleted, source-deleted, cross-organization Collection은 존재 여부를 구분하지 않고 `knowledge_collection_unavailable`로 처리한다. Direct KB는 같은 lifecycle/sync 경계와 retrieval-visible completed chunk readiness를 통과해야 한다. Anonymous-public surface에서 active private Collection은 차단되며, public Collection 자체 또는 active member가 source-managed이면 별도 public source exposure primitive가 없는 현재 구현에서 fail-closed한다. Child ID나 exact membership count는 preflight port/result로 전달하지 않는다.

Conversation Memory target activation은 explicit input/output mapping, node Memory policy, immutable deployment/snapshot binding, Memory contract/storage generation과 capable Worker routing을 함께 검사한다. Schedule/webhook/API batch, workflow-node direct run과 일반 authenticated deployment run은 target session을 암묵적으로 생성하지 않는다.

Schedule records and scheduler jobs are created only for active `type="schedule"` deployments. A `scheduleTrigger` node inside any other deployment type, including `workflow_node`, does not create a schedule surface.

Mail, Gmail Draft, Mail Acknowledge와 Slack node는 active create/toggle에서 같은 semantic validator registry를 사용한다. Public/API/webhook/schedule 같은 subject 없는 deployment type의 Mail node는 `mail_execution_subject_required`로 차단한다. `workflow_node` 자체는 activation actor의 Mail resource usability를 검사하고 parent execution subject 상속 warning을 반환할 수 있다. LLM, HTTP와 GitHub는 이번 범위에서 기존 runtime-authoritative 정책을 유지한다.

### Public Webhook Trigger Request

Primary credential:

```http
POST /api/v1/hooks/{url_slug} HTTP/1.1
Authorization: Bearer <app-secret>
Content-Type: application/json

{"event":"created"}
```

Compatibility credential:

```http
POST /api/v1/hooks/{url_slug} HTTP/1.1
X-Webhook-Secret: <app-secret>
Content-Type: application/json

{"event":"created"}
```

한 요청에는 정확히 하나의 credential source만 사용한다. Bearer scheme은 case-insensitive하게 인식하지만 credential 값을 trim하거나 정규화하지 않는다. Credential은 1~512 ASCII bytes로 제한한다. Query `token` key가 있으면 값과 header 유효 여부를 확인하지 않고 요청 전체를 거부하며 다른 provider-owned query parameter는 금지하지 않는다.

Gateway transport는 `/api/v1/hooks` query에서 exact 또는 percent-encoded `token` field를 Uvicorn access logging 전에 제거하고 boolean presence만 endpoint에 전달한다. Token 값은 decode하거나 request state에 보존하지 않는다. 다른 query field는 원래 bytes로 보존한다.

Allowed payload media type은 case-insensitive `application/json` 또는 `application/*+json`이다. Well-formed non-charset parameter는 허용하며 `charset`이 있으면 UTF-8이어야 한다. `Content-Encoding`은 누락 또는 단일 `identity`만 허용한다.

| Limit | Value | Definition |
| --- | ---: | --- |
| Actual body | 1,048,576 bytes | ASGI stream에서 누적한 실제 byte 수 |
| Processing deadline | 5 seconds | 첫 body read 직전부터 decode, parse, complexity validation 완료까지 |
| JSON depth | 20 | Root value depth 1 |
| JSON nodes | 10,000 | Root와 모든 object member value/array element 포함 |

`Content-Length`가 상한을 넘으면 body read 전에 거부하지만 actual streamed bytes가 최종 source of truth다. Duplicate/invalid `Content-Length`, UTF-8 BOM, invalid UTF-8/JSON, `NaN`/`Infinity`, depth/node 초과를 허용하지 않는다. Root JSON은 object만 허용한다. Array, string, number, boolean과 null root는 `400 webhook.payload.invalid`로 거부하며 서버가 `{"value": ...}`로 자동 포장하지 않는다. Object 안의 nested JSON value는 그대로 보존한다.

Parsed JSON은 workflow input으로만 전달한다. Payload에 `app_id`, `organization_id`, `workflow_id`, `deployment_id`, `user_id`, `trigger_mode` 또는 `execution_context` key가 있어도 server-derived execution context를 변경하지 않는다.

Accepted execution response는 기존 envelope을 유지한다.

```json
{
  "status": "accepted",
  "message": "Webhook received, processing in background"
}
```

Pending capture session이 있으면 동일 ingress validation을 통과한 JSON의 redacted/capped preview만 capture하고 기존 captured response를 반환한다. Capture preview cap은 ingress acceptance limit과 별개다.

### Webhook Capture Start Response

```json
{
  "status": "waiting",
  "capture_id": "server-issued nonce",
  "expires_at": "2026-07-09T07:00:00+00:00",
  "message": "Capture session started"
}
```

`capture_id` is a short-lived nonce. Clients must pass it to capture status polling. It is not a replacement for user authentication or workflow permission checks.

### Webhook Capture Status Response

Waiting:

```json
{
  "status": "waiting",
  "capture_id": "server-issued nonce",
  "expires_at": "2026-07-09T07:00:00+00:00",
  "payload": null
}
```

Captured:

```json
{
  "status": "captured",
  "payload": {
    "event": "ticket.created",
    "token": "[REDACTED: sensitive value]"
  },
  "payload_redacted": true
}
```

`payload` is a redacted/capped preview for workflow test input convenience. It is not raw webhook payload storage. Sensitive keys and known secret-like value patterns are redacted, nested structures are depth/item capped, and the session is deleted after a captured status read.

### Webhook Capture Cancel Response

```json
{
  "status": "cancelled"
}
```

Cancel deletes the matching capture session immediately. A webhook received after cancellation follows the normal execution path instead of the capture path.

## Distributed Schedule Dispatch Internal Contract

MBA-187은 public Schedule API request/response와 public claim 조회 endpoint를 추가하지 않는다. `workflow.execute_scheduled_deployment`는 내부 Celery inbound adapter이며 client contract가 아니다.

내부 task payload는 opaque claim locator와 safe request correlation만 전달한다. Organization, workflow, app, deployment/version, execution subject와 graph snapshot은 queue 값을 권한 source로 사용하지 않는다. Worker는 claim과 canonical DB resource에서 이를 재구성한다.

동일 occurrence는 deterministic Celery task id를 사용하지만 broker publish 자체는 at-least-once다. Worker가 claim을 `running`으로 admission한 경우에만 engine을 시작하며 duplicate delivery는 성공 응답을 새로 만들거나 workflow를 다시 실행하지 않는다. Admission 이후 outcome unknown은 자동 replay하지 않는다.

Schedule 생성/활성화에서 cron expression 또는 timezone이 유효하지 않으면 safe `422 deployment.schedule_configuration_invalid`를 반환한다. Parser exception, timezone path 또는 raw configuration detail은 응답과 audit에 포함하지 않는다. Legacy invalid schedule은 background reconciliation에서 다른 schedule을 막지 않고 해당 row만 safe하게 격리한다.

Pending claim의 canonical deployment graph가 configuration preflight에서 blocked이면 budget 평가와 broker publish 전에 claim을 `canceled`로 전이하고 `safe_reason_code="configuration_preflight_blocked"`를 기록한다. 기존 `schedule_dispatch.canceled` audit에는 같은 safe reason만 기록하며 node/resource 상세는 기록하지 않는다. Preflight infrastructure failure는 transaction을 rollback하고 claim을 설정 오류로 영구 취소하거나 task를 발행하지 않는다.

Claim 조회, 상태 변경, outcome acknowledgment와 redrive는 public API로 노출하지 않는다. Outcome acknowledgment는 protected operational CLI/job이 application use case를 호출한다.

## Errors

Public webhook ingress errors preserve the FastAPI `{ "detail": "..." }` envelope and use static detail codes:

| Condition | Status | Detail |
| --- | ---: | --- |
| Query `token` key present | 400 | `webhook.query_secret_not_supported` |
| Multiple/duplicate credential sources | 400 | `webhook.credential_ambiguous` |
| Missing, malformed or invalid credential | 403 | `webhook.authentication_failed` |
| Unsupported/malformed media metadata or encoding | 415 | `webhook.payload.unsupported_media_type` |
| Declared or actual body too large | 413 | `webhook.payload.too_large` |
| Ingress processing deadline exceeded | 408 | `webhook.payload.timeout` |
| Invalid length, disconnect, UTF-8/JSON or complexity | 400 | `webhook.payload.invalid` |

App not found, active deployment/type/runtime policy and workflow budget failures keep their existing status/envelope. Authentication and payload failure response/logging must not include query/header secret, raw URL/query, raw body, parsed payload or parser exception text. Repository Nginx와 Gateway/Uvicorn access-log path 모두 synthetic query marker가 남지 않아야 한다.

Blocking preflight failure:

```json
{
  "detail": {
    "error": {
      "code": "deployment.preflight.blocked",
      "message": "Deployment preflight blocked activation",
      "reason_code": "private_kb_requires_execution_subject",
      "required_actions": [
        "remove_private_kb_or_use_authenticated_run"
      ],
      "preflight": {
        "status": "blocked",
        "audience": "anonymous_public",
        "safe_summary": {
          "blocked_reason": "private_kb_requires_execution_subject",
          "affected_node_count": 1,
          "affected_kb_count_bucket": "1",
          "affected_collection_count_bucket": "0",
          "candidate_budget_limited": false
        }
      }
    }
  }
}
```

- HTTP status: `409 Conflict`.
- Broad exception handling must preserve this envelope and must not wrap it as generic `400`.
- Validation failures unrelated to preflight keep existing validation error semantics.
- Missing or invalid user session on capture start/status/cancel returns `401`.
- Missing capture nonce on status returns request validation error.
- Missing capture nonce on cancel returns request validation error.
- Missing, expired, wrong, or different-requester capture session returns `404`.
- Same-scope workflow permission denial returns `403`.

## Permissions

- Preflight preview requires the same active organization and workflow deploy/manage permission as deployment create.
- Public/API/webhook/schedule/chatbot/mcp surfaces do not receive user KB permission unless a future service account/assigned operator policy explicitly provides an execution subject.
- `internal_chatbot` run/run-info requires active membership in the workflow organization and workflow `execute` permission. When `X-Organization-Id` is supplied, it must also match the deployment app organization. Run dispatch sets the current user as `execution_subject`.
- `internal_chatbot` preflight derives `authenticated_user` server-side, so a private KB reference alone does not block activation; runtime still rechecks the current user's KB permission and source ACL.
- Public Chatbot exact Origin/embed/CSP allowlist is deployment-owned versioned configuration. Client hints, wildcard, or environment fallback cannot widen it; the browser Conversation Session surface remains unavailable until this contract is implemented.
- Conversation Access Grant proves only public session access. It cannot become an execution subject, credential/billing principal, or audit actor.
- `workflow_node` deployment is not directly executable through public/API/webhook URL surfaces or authenticated deployment `run`/`run-info` endpoints. Workflow-node target inspection uses `workflowNode.data.appId` and inherits parent execution subject at runtime.
- Workflow-node target active deployment must belong to the target app, be active, and have `type="workflow_node"`. Runtime also requires a non-null parent organization context matching the target app organization.
- Public webhook trigger execution uses exactly one app secret header source. Bearer is primary and `X-Webhook-Secret` is compatibility-only; query `token` is rejected.
- Webhook capture management uses user session authentication and target workflow `deploy` permission. App secret alone cannot start, read, or cancel capture sessions.
