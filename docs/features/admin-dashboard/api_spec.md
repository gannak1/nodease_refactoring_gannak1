# Admin Dashboard API Spec

Status: Draft
Verified Against: feature/mba-188 @ 59d1cc51

검증 값은 MBA-188 audit detail의 metadata/change summary 확장에 적용한다. 기존 usage/summary/permission-request 계약의 기준은 해당 feature 문서와 git history를 따른다.

관리자 대시보드 전용 API는 `/api/v1/admin/*` prefix로 통합한다. 모든 endpoint는 인증과 `X-Organization-Id` header를 요구하고, 조회/처리 범위는 해당 organization scope로 제한한다 ([ADR-0009](../../decisions/ADR-0009-active-organization-header-context.md)). 권한 신청의 제출(신청자 측 `POST /api/v1/permission-requests`)은 [organization](../organization/api_spec.md) 범위이며 이 문서에 포함하지 않는다.

## Endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| GET | `/api/v1/admin/audit-logs` | audit log 검색/필터 (FR-011) | audit `auditor` 이상 |
| GET | `/api/v1/admin/audit-logs/{audit_log_id}` | audit log 상세 조회 (FR-011) | audit `auditor` 이상 |
| GET | `/api/v1/admin/usage/workflows` | workflow별 LLM 사용량/비용 집계 (FR-012) | organization owner/manager |
| GET | `/api/v1/admin/summary` | 조직 월간 비용, 예산 위험 요약 (FR-015) | organization owner/manager |
| GET | `/api/v1/admin/permission-requests` | 권한 신청 목록 조회 (FR-014) | organization owner/manager |
| POST | `/api/v1/admin/permission-requests/{request_id}/approve` | 권한 신청 승인 (FR-014) | organization owner/manager |
| POST | `/api/v1/admin/permission-requests/{request_id}/reject` | 권한 신청 거절 (FR-014) | organization owner/manager |
| GET | `/api/v1/admin/app-creation-permissions` | App 생성 권한 보유 목록 조회 (FR-014 회수 확장) | organization owner/manager |
| DELETE | `/api/v1/admin/app-creation-permissions/{permission_id}` | App 생성 권한 회수 (FR-014 회수 확장) | organization owner/manager |
| GET/POST | `/api/v1/admin/security-alerts/*` | Security Alert 검색·summary·상세·evidence·상태 변경 (FR-013) | organization owner/manager |

- Security Alert endpoint 전체 계약은 [Security Alert API spec](../security-alert/api_spec.md)이 소유한다. Audit list/detail endpoint를 alert 상태 저장이나 threshold 조회 API로 사용하지 않는다.
- action-style POST(`/approve`, `/reject`)는 기존 `PATCH /deployments/{id}/toggle` 같은 repo 관례를 따른다.

## Request And Response Models

공통 규칙:

- Pagination은 기존 패턴을 따른다: `page`(1-base, 기본 1), `limit`(기본 20, 최대 100), 응답은 `{ "total": <int>, "items": [...] }`.
- 기간 파라미터 `startAt`/`endAt`은 ISO 8601 datetime이다. timezone offset이 없으면 KST(Asia/Seoul)로 해석하고, 판정은 반개구간 `[startAt, endAt)`이다 (requirements 시간대/경계 규칙). Usage 집계는 기간 미지정 시 이번 달(KST) 기본값을 쓰며, 명시 기간은 `startAt`/`endAt`을 함께 제공해야 한다.
- 비용 값은 USD이며 JSON number로 반환한다. 표시 자릿수 반올림(집계 2자리, 단건 6자리)은 클라이언트 표시 계층에서 1회만 수행한다.

### GET /admin/audit-logs

Query: `page`, `limit`, `actorId`(UUID), `action`(canonical action 문자열, [ADR-0008](../../decisions/ADR-0008-audit-action-naming-standard.md)), `targetType`, `targetId`, `status`(`success`/`failure`), `startAt`, `endAt`

Response `200`: 기존 `AuditLogListResponse` 재사용.

```json
{
  "total": 42,
  "items": [
    {
      "id": "<uuid>",
      "occurred_at": "<datetime>",
      "actor_id": "<uuid|null>",
      "actor_type": "user",
      "category": "<category>",
      "action": "workflow.deploy",
      "target_type": "workflow",
      "target_id": "<id|null>",
      "status": "success",
      "request_id": "<string|null>"
    }
  ]
}
```

정렬은 `occurred_at` 내림차순 고정. 필터는 각각 독립이며 조합(AND)으로 적용된다.

### GET /admin/audit-logs/{audit_log_id}

Response `200`: 목록 항목과 동일한 필드 + `audit_metadata` 중 allowlist 값만 포함한다. 허용 key는 `organization_id`, `request_id`, sanitized `reason`, existing safe `summary`, `target_user_id`, `requested_action`, `policy_reason`, `resource_type`, `resource_id`, `team_id`, advisory `affected_resource_source_count`다. UUID field는 유효한 UUID, count는 boolean이 아닌 0 이상 integer, reason/request/action은 string, resource/policy reason은 canonical allowlist 값일 때만 반환한다. 기존 `summary`는 secret-like key를 재귀 제거한 JSON scalar/list/object 계약을 유지하고, 그 외 허용 key의 nested object나 잘못된 타입은 생략한다. Resource/team field는 scope를 확인한 policy block 또는 applied team action에서만 기록한다. raw payload, secret 계열 값, target name/email, expected/current snapshot은 포함하지 않는다 (NFR-004). raw payload 접근은 이 API가 아니라 trace visibility policy와 `raw_auditor` 권한의 별도 경로다.

응답은 optional `change_summary`를 additive하게 포함한다.

```json
{
  "change_summary": {
    "before": {
      "organization_id": "<uuid>",
      "user_id": "<uuid>",
      "membership_state": "active",
      "organization_auth_state": "member"
    },
    "after": {
      "organization_id": "<uuid>",
      "user_id": "<uuid>",
      "membership_state": "suspended",
      "organization_auth_state": "member"
    }
  }
}
```

- `change_summary`는 organization membership, team membership, user direct resource permission, App creation permission처럼 명시적으로 지원하는 target/action에만 반환한다.
- Generic AuditLog `before`/`after`를 그대로 직렬화하지 않고 target/action별 allowlist를 적용한다.
- Unknown target/action 또는 safe field가 없는 event는 `change_summary: null`이다.
- `policy.block`은 mutation이 아니므로 `change_summary: null`이다. Scoped `target_user_id`, sanitized `requested_action`/`policy_reason`/optional `reason`과 scope가 확인된 opaque resource/team id만 표시한다.
- Actor access profile/team-membership/resource/action API는 [organization API spec](../organization/api_spec.md)의 member access-management 계약을 사용한다. Audit endpoint가 RBAC mutation을 직접 수행하지 않는다.

### GET /admin/usage/workflows

Query: `page`, `limit`, `startAt`, `endAt` — 기간 미지정 시 이번 달(KST) 기본.

Response `200`:

```json
{
  "total": 12,
  "period": { "startAt": "<datetime>", "endAt": "<datetime>" },
  "items": [
    {
      "workflow_id": "<uuid>",
      "workflow_name": "<string>",
      "prompt_tokens": 12345,
      "completion_tokens": 2345,
      "call_count": 87,
      "total_cost": 12.345678,
      "budget": {
        "monthly_budget_usd": 100.0,
        "current_month_cost": 92.345678,
        "usage_ratio": 0.923457,
        "status": "at_risk"
      }
    }
  ]
}
```

- 목록 기준은 요청 organization scope 안의 App primary workflow(`apps.workflow_id`) 전체다. 기간 안에 `llm_usage_logs` row가 없는 workflow도 응답 item으로 반환하며 `prompt_tokens=0`, `completion_tokens=0`, `call_count=0`, `total_cost=0`이다.
- `total`은 기간 안에 usage가 있는 workflow 수가 아니라 organization scope 안의 응답 대상 App primary workflow 수다.
- `total_cost`가 NULL인 usage row는 0으로 합산한다.
- `workflow_name`은 primary workflow를 가리키는 App의 `apps.name`을 사용한다. `workflows` 테이블 자체에는 이름 컬럼이 없으므로 App 이름이 관리자 화면의 workflow 표시명이다.
- 정렬은 `total_cost` 내림차순 고정이며, 비용이 같은 row는 `workflow_name` 오름차순과 `workflow_id` 오름차순으로 안정적으로 정렬한다 (FR-012 비용 큰 workflow 탐색).
- 항목에서 해당 workflow 화면으로 이동하는 진입은 클라이언트 라우팅이며, 비교/최적화 실행 API는 [cost-optimizer](../cost-optimizer/api_spec.md) 범위다.
- workflow별 예산/사용률 필드는 [budget-management api_spec](../budget-management/api_spec.md)의 `budget` 블록 정의를 따른다. 활성 예산이 없으면 `budget`은 null이다.

### GET /admin/summary

Query: 없음 (이번 달 KST 고정).

Response `200`:

```json
{
  "month": "2026-07",
  "total_cost": 123.456789,
  "budget": {
    "budgeted_workflow_count": 5,
    "at_risk_count": 1,
    "exceeded_count": 1,
    "ratio": 0.4
  }
}
```

- `budget` 블록의 판정(사용률 90% 이상 위험, 100% 초과 초과)과 `ratio`의 분모(활성 예산 workflow 수)는 [budget-management api_spec](../budget-management/api_spec.md)을 따른다. 활성 예산 workflow가 0개면 `budget`은 null이다.
- Security Alert open count와 최근 alert는 `/admin/security-alerts/summary`가 제공한다. 비용/예산 `/admin/summary` 응답에 섞지 않는다.

### GET /admin/permission-requests

Query: `page`, `limit`, `status`(`pending`/`approved`/`rejected`, 기본 `pending`)

Response `200`:

```json
{
  "total": 3,
  "items": [
    {
      "id": "<uuid>",
      "user": { "id": "<uuid>", "name": "<string>", "email": "<string>" },
      "requested_permission": "app.create",
      "reason": "<string>",
      "status": "pending",
      "created_at": "<datetime>",
      "decided_by": null,
      "decided_at": null
    }
  ]
}
```

정렬은 `created_at` 내림차순.

### POST /admin/permission-requests/{request_id}/approve

Request body: 없음.

Response `200`:

```json
{ "id": "<uuid>", "status": "approved", "decided_by": "<uuid>", "decided_at": "<datetime>" }
```

Side effects ([ADR-0016](../../decisions/ADR-0016-permission-request-and-app-creation-permission.md)):

- `permission_requests.status`를 `approved`로 갱신하고 `decided_by`/`decided_at`을 기록한다.
- 신청자의 `user_app_creation_permissions` row를 생성한다.
- audit: `permission_request.approved`와 `user_app_creation_permission.created`를 하나의 트랜잭션에서 각각 기록한다.

### POST /admin/permission-requests/{request_id}/reject

Request body: 없음. (거절 사유 입력은 현재 요구사항에 없다. 필요해지면 requirements 갱신과 함께 추가한다.)

Response `200`:

```json
{ "id": "<uuid>", "status": "rejected", "decided_by": "<uuid>", "decided_at": "<datetime>" }
```

Side effects: status 갱신 + `permission_request.rejected` audit 기록. 거절된 신청자는 재신청할 수 있다 (ADR-0016).

### GET /admin/app-creation-permissions

Query: `page`, `limit`

Response `200`:

```json
{
  "total": 2,
  "items": [
    {
      "id": "<uuid>",
      "user": { "id": "<uuid>", "name": "<string>", "email": "<string>" },
      "assigned_by": "<uuid>",
      "assigned_at": "<datetime>"
    }
  ]
}
```

- `id`는 `user_app_creation_permissions` row id다. 회수(DELETE)의 path parameter로 사용한다.
- 목록은 row 보유자만 포함한다. organization owner/manager는 row 없이 App 생성이 허용되므로 목록에 나타나지 않는다 ([ADR-0016](../../decisions/ADR-0016-permission-request-and-app-creation-permission.md)).
- 신청 승인 없이 seed로 부여된 row도 포함한다.
- 정렬은 `assigned_at` 내림차순.

### DELETE /admin/app-creation-permissions/{permission_id}

Request body: 없음.

Response `200`:

```json
{ "id": "<uuid>", "user_id": "<uuid>" }
```

Side effects ([ADR-0016](../../decisions/ADR-0016-permission-request-and-app-creation-permission.md)):

- `user_app_creation_permissions` row를 삭제한다.
- audit: `user_app_creation_permission.deleted`를 기록한다 (target_type `user_app_creation_permission`, target_id는 row id, [ADR-0008](../../decisions/ADR-0008-audit-action-naming-standard.md)).
- `permission_requests`의 과거 신청 상태(approved)는 바꾸지 않는다.
- 회수 이후 해당 사용자의 App 생성(`POST /apps`)은 다시 `403 permission.denied`로 차단되고, 사용자는 `POST /permission-requests`로 재신청할 수 있다 (보유/pending 없음 조건 재충족).

존재하지 않거나 요청 organization scope 밖의 `permission_id`는 `404`로 숨긴다 ([ADR-0010](../../decisions/ADR-0010-resource-access-403-404-policy.md)). 이미 회수된 row의 재회수 요청도 같은 `404`다.

## Errors

| Status | 조건 |
| --- | --- |
| 400 | `X-Organization-Id` 누락/invalid, 잘못된 query 값 (`endAt` ≤ `startAt`, usage 집계의 `startAt`/`endAt` 한쪽만 제공 등) |
| 401 | 미인증 |
| 403 | organization scope 안이지만 권한 부족 — audit 조회 권한 없음, owner/manager 아님. `permission.denied` audit 기록 ([ADR-0010](../../decisions/ADR-0010-resource-access-403-404-policy.md)) |
| 404 | 요청 organization scope 밖의 `audit_log_id`/`request_id`/`permission_id`, 이미 회수됐거나 존재하지 않는 `permission_id` — 존재를 숨긴다 (`resource.not_found`, ADR-0010) |
| 409 | 이미 처리된(approved/rejected) 신청에 대한 approve/reject 재요청. 승인 시점에 신청자가 조직의 active member가 아닌 경우(제거/정지)의 approve |
| 422 | request 형식 오류 |

- 검색 결과 없음은 오류가 아니라 `{ "total": 0, "items": [] }` 정상 응답이다. 단, `GET /admin/usage/workflows`는 기간 안의 usage 존재 여부가 아니라 App primary workflow 존재 여부가 빈 목록 기준이다.
- 동시 승인/거절 경합은 한쪽만 성공하고 나머지는 409를 받는다 (중복 부여 방지, ADR-0016 후속 검토).

## Permissions

| Endpoint | 판정 |
| --- | --- |
| `GET /admin/audit-logs`, `GET /admin/audit-logs/{id}` | audit auth_state `auditor` 이상 (organization owner/manager는 audit matrix상 manager로 충족) |
| actor access profile/team membership/resource source/action | [organization API spec](../organization/api_spec.md) 기준 ADR-0009 organization manager 판정 |
| 나머지 전부 | organization owner/manager 전용. `auditor`/`raw_auditor`는 접근 불가 |

- 모든 판정은 Gateway service/helper 경계에서 수행한다 (NFR-001). 프론트 차단은 UX 보조일 뿐이다.
- audit `auditor` 판정은 `team_audit_permissions` 기반 audit matrix(`none < auditor < raw_auditor < manager`)를 따른다. 조직 단위 audit 조회 enforcement는 이 API가 첫 적용 지점이다.
- Audit `auditor` 판정 결과를 actor access mutation authorization으로 재사용하지 않는다 ([ADR-0023](../../decisions/ADR-0023-audit-actor-access-management-boundary.md)).
- raw payload(`view_raw`)는 이 API 범위 밖이며 trace visibility policy를 따른다.
