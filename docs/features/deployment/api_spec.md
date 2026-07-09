# Deployment API Spec

Status: Draft
Verified Against: TBD

## Endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| POST | `/api/v1/deployments/preflight` | 배포 graph snapshot과 deployment type 기준으로 runtime availability를 검사한다 | 로그인 + workflow deploy/manage 권한 |
| POST | `/api/v1/deployments` | 배포 생성. `is_active=true`이면 blocking preflight를 통과해야 한다 | 로그인 + workflow deploy/manage 권한 |
| PATCH | `/api/v1/deployments/{deployment_id}/toggle` | 배포 활성/비활성 전환. 활성화 시 blocking preflight를 통과해야 한다 | 로그인 + workflow deploy/manage 권한 |
| DELETE | `/api/v1/deployments/{deployment_id}` | 배포 삭제. active 삭제 시 자동 승격하지 않는다 | 로그인 + workflow deploy/manage 권한 |
| GET | `/api/v1/deployments/{deployment_id}/run-info` | 로그인 사용자 실행 화면에 필요한 safe deployment metadata 조회 | 로그인 + workflow execute 권한 |
| POST | `/api/v1/deployments/{deployment_id}/run` | 로그인 사용자를 execution subject로 활성 deployment snapshot 실행 | 로그인 + workflow execute 권한 |

## Request And Response Models

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

Preview response uses `200 OK` even when blocked:

When `is_active=false`, preview reflects inactive-save context by returning activation blockers as `status="warning"` while keeping safe reason codes and required actions. Create with `is_active=true` and later activation/toggle still use blocking `409` enforcement.

```json
{
  "status": "blocked",
  "audience": "anonymous_public",
  "safe_summary": {
    "blocked_reason": "private_kb_requires_execution_subject",
    "affected_node_count": 1,
    "affected_kb_count_bucket": "1"
  },
  "required_actions": [
    {
      "action": "remove_private_kb_or_use_authenticated_run",
      "label": "Private KB를 제거하거나 인증 실행 경로를 사용하세요"
    }
  ],
  "warnings": [],
  "nodes": [
    {
      "node_id": "llm-1",
      "node_type": "llmNode",
      "status": "blocked",
      "reason_codes": ["private_kb_requires_execution_subject"],
      "knowledge_base_count_bucket": "1"
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

Response는 hidden KB id/name/path, exact denied count, raw source metadata, raw exception을 포함하지 않는다.

### Create / Activation Blocking

`POST /api/v1/deployments`에서 `is_active=true`이거나, `PATCH /api/v1/deployments/{deployment_id}/toggle`이 inactive deployment를 active로 바꾸는 경우 server-derived audience로 blocking preflight를 실행한다.

`is_active=false` 생성은 저장 가능하지만 active deployment 교체, public URL 활성화, schedule job 생성 같은 실행 부작용을 만들지 않는다.

Schedule records and scheduler jobs are created only for active `type="schedule"` deployments. A `scheduleTrigger` node inside any other deployment type, including `workflow_node`, does not create a schedule surface.

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
          "affected_kb_count_bucket": "1"
        }
      }
    }
  }
}
```

- HTTP status: `409 Conflict`.
- Broad exception handling must preserve this envelope and must not wrap it as generic `400`.
- Validation failures unrelated to preflight keep existing validation error semantics.

## Permissions

- Preflight preview requires the same active organization and workflow deploy/manage permission as deployment create.
- Public/API/webhook/schedule/chatbot/mcp surfaces do not receive user KB permission unless a future service account/assigned operator policy explicitly provides an execution subject.
- `workflow_node` deployment is not directly executable through public/API/webhook URL surfaces or authenticated deployment `run`/`run-info` endpoints. Workflow-node target inspection uses `workflowNode.data.appId` and inherits parent execution subject at runtime.
- Workflow-node target active deployment must belong to the target app, be active, and have `type="workflow_node"`. Runtime also requires a non-null parent organization context matching the target app organization.
