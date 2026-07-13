# Deployment API Spec

Status: Draft
Verified Against: `feature/mba-233 @ b4ff694f`

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
| POST | `/api/v1/hooks/{url_slug}` | Public webhook trigger execution or pending capture ingestion | App secret via query token, Bearer header, or `X-Webhook-Secret` |
| GET | `/api/v1/hooks/{url_slug}/capture/start` | Start a short-lived webhook payload capture session | User session + target workflow `deploy` permission |
| GET | `/api/v1/hooks/{url_slug}/capture/status?capture_id=...` | Poll one capture session and return a redacted preview once captured | User session + same requester + target workflow `deploy` permission + capture nonce |
| POST | `/api/v1/hooks/{url_slug}/capture/cancel?capture_id=...` | Cancel a pending capture session | User session + same requester + target workflow `deploy` permission + capture nonce |

## Request And Response Models

### `GET /api/v1/deployments/public/{url_slug}/info`

인증 없는 공유 화면에서 입력 폼을 구성하기 위한 metadata endpoint다. Production 기본 `DeploymentRuntimePolicy`는 active deployment가 target app 소유이고 `type`이 `webapp`, `widget`, `chatbot`인 경우에만 응답한다. API, MCP, schedule, webhook, workflow-node, unknown/empty type과 stale/cross-app active pointer는 safe `404`로 닫는다.

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
| `type` | no | `api`, `webapp`, `widget`, `chatbot`, `mcp`, `workflow_node`, `schedule`, `webhook`. Defaults to `api` |
| `config` | no | Deployment-specific config. Defaults to `{}` |
| `is_active` | no | Preview context. Defaults to `true`; inactive create may warn but does not activate |
| `graph_snapshot` | no | If omitted, server resolves the current app/workflow deployment snapshot candidate |
| `audience` | no | UI hint only. Security decisions use server-derived audience in create/enable paths |

Conversation-capable target snapshot은 별도 server-derived metadata로 immutable deployment version 또는 snapshot hash, conversation mapping version, node Memory policy version, `memory_contract_version`, `storage_generation`을 포함한다. Client `config`나 `audience`가 이 binding을 선택하거나 기존 session을 current active deployment로 rebind할 수 없다.

Preview response uses `200 OK` even when blocked:

When `is_active=false`, preview reflects inactive-save context by returning audience/lifecycle activation blockers as `status="warning"` while keeping safe reason codes and required actions. Malformed or over-limit Knowledge reference configuration and existing workflow-node structural errors remain blocked. Create with `is_active=true` and later activation/toggle use blocking `409` enforcement.

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

Response는 hidden KB/Collection/child id, name, label, path, exact denied/member count, raw graph/source metadata, raw exception을 포함하지 않는다. Public graph projection은 root와 embedded subgraph의 두 Knowledge reference 배열도 제거한다.

### Create / Activation Blocking

`POST /api/v1/deployments`에서 `is_active=true`이거나, `PATCH /api/v1/deployments/{deployment_id}/toggle`이 inactive deployment를 active로 바꾸는 경우 server-derived audience로 blocking preflight를 실행한다.

`is_active=false` 생성은 저장 가능하지만 active deployment 교체, public URL 활성화, schedule job 생성 같은 실행 부작용을 만들지 않는다.

Public `type="chatbot"`은 항상 `public_chatbot` audience로 preflight하므로 private KB 후보가 있으면 activation이 차단된다. 별도 authenticated internal Chatbot surface는 public Chatbot audience를 완화하거나 login cookie를 public route에 선택적으로 붙이는 방식으로 제공하지 않는다. 해당 기능은 별도 deployment access policy와 runtime/session namespace가 구현된 뒤 독립 preflight를 사용한다.

Selected Collection 검사는 selected ID와 active organization으로 범위를 제한하고 active lifecycle과 `sync_state != source_deleted`를 요구한다. Missing, inactive, deleted, source-deleted, cross-organization Collection은 존재 여부를 구분하지 않고 `knowledge_collection_unavailable`로 처리한다. Direct KB는 같은 lifecycle/sync 경계와 retrieval-visible completed chunk readiness를 통과해야 한다. Anonymous-public surface에서 active private Collection은 차단되며, public Collection 자체 또는 active member가 source-managed이면 별도 public source exposure primitive가 없는 현재 구현에서 fail-closed한다. Child ID나 exact membership count는 preflight port/result로 전달하지 않는다.

Conversation Memory target activation은 explicit input/output mapping, node Memory policy, immutable deployment/snapshot binding, Memory contract/storage generation과 capable Worker routing을 함께 검사한다. Schedule/webhook/API batch, workflow-node direct run과 일반 authenticated deployment run은 target session을 암묵적으로 생성하지 않는다.

Schedule records and scheduler jobs are created only for active `type="schedule"` deployments. A `scheduleTrigger` node inside any other deployment type, including `workflow_node`, does not create a schedule surface.

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

Claim 조회, 상태 변경, outcome acknowledgment와 redrive는 public API로 노출하지 않는다. Outcome acknowledgment는 protected operational CLI/job이 application use case를 호출한다.

## Errors

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
- Public Chatbot exact Origin/embed/CSP allowlist is deployment-owned versioned configuration. Client hints, wildcard, or environment fallback cannot widen it; the browser Conversation Session surface remains unavailable until this contract is implemented.
- Conversation Access Grant proves only public session access. It cannot become an execution subject, credential/billing principal, or audit actor.
- `workflow_node` deployment is not directly executable through public/API/webhook URL surfaces or authenticated deployment `run`/`run-info` endpoints. Workflow-node target inspection uses `workflowNode.data.appId` and inherits parent execution subject at runtime.
- Workflow-node target active deployment must belong to the target app, be active, and have `type="workflow_node"`. Runtime also requires a non-null parent organization context matching the target app organization.
- Public webhook trigger execution uses app secret authentication.
- Webhook capture management uses user session authentication and target workflow `deploy` permission. App secret alone cannot start, read, or cancel capture sessions.
