# Security Alert API Spec

Status: Draft

Security Alert API는 `/api/v1/admin/security-alerts` 아래에 둔다. 모든 endpoint는 `auth_token` HTTP-only cookie와 `X-Organization-Id` header를 요구하며, 현재 active organization의 owner/manager만 사용할 수 있다.

탐지와 lifecycle 정책은 [ADR-0028](../../decisions/ADR-0028-security-alert-detection-and-lifecycle.md), 기능 요구사항은 [requirements.md](requirements.md)를 따른다. Active organization 해석과 scope hiding은 [ADR-0009](../../decisions/ADR-0009-active-organization-header-context.md), [ADR-0010](../../decisions/ADR-0010-resource-access-403-404-policy.md)을 따른다.

## Endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| GET | `/api/v1/admin/security-alerts` | Alert 검색·필터·pagination | organization owner/manager |
| GET | `/api/v1/admin/security-alerts/summary` | Sidebar용 open alert 요약 | organization owner/manager |
| GET | `/api/v1/admin/security-alerts/{alert_id}` | Alert 상세 조회 | organization owner/manager |
| GET | `/api/v1/admin/security-alerts/{alert_id}/audit-logs` | Alert 관련 safe audit 목록 | organization owner/manager |
| POST | `/api/v1/admin/security-alerts/{alert_id}/acknowledge` | Open alert 확인 | organization owner/manager |
| POST | `/api/v1/admin/security-alerts/{alert_id}/resolve` | Open/acknowledged alert 해결 | organization owner/manager |
| POST | `/api/v1/admin/security-alerts/{alert_id}/reopen` | Acknowledged alert를 open으로 되돌림 | organization owner/manager |

`summary` static route는 `{alert_id}` UUID route보다 먼저 등록해야 한다.

## Common Rules

### Authentication And Organization

- 모든 요청은 `X-Organization-Id`로 active organization을 지정한다.
- Header가 없으면 `400 organization.required`, UUID 형식이 아니면 `422 validation.failed`다.
- 로그인 사용자가 organization owner/manager가 아니면 `403 permission.denied`다.
- 다른 organization 또는 scope 밖 `alert_id`는 존재 여부를 숨기고 `404 resource.not_found`를 반환한다.
- Membership 정지·제거 또는 manager 강등은 다음 요청부터 즉시 반영한다.
- Client의 manager UI 차단은 보조이며 Gateway가 모든 endpoint에서 다시 검사한다.

### Pagination And Time

- Pagination은 `page`(1-base, 기본 1)와 `limit`(기본 20, 최대 100)를 사용한다.
- Paginated response는 `{ "total": <int>, "items": [...] }` 형식이다.
- `startAt`, `endAt`은 ISO 8601 datetime이다.
- Timezone offset이 없으면 KST(Asia/Seoul)로 해석하고 내부 비교는 UTC로 정규화한다.
- 기간 필터는 `startAt <= last_detected_at < endAt` 반개구간이다.
- `startAt`, `endAt`은 각각 생략할 수 있다. 둘 다 있으면 `endAt`이 `startAt`보다 커야 한다.

### Safe Actor Projection

Actor 표시값은 Alert row에 snapshot으로 저장하지 않고 현재 organization 권한 경계 안에서 조회한다.

```json
{
  "id": "<uuid>",
  "display_name": "홍길동",
  "state": "active"
}
```

`state`는 `active`, `suspended`, `removed`, `deleted` 중 하나다. 표시할 수 있는 이름이 없으면 `display_name`은 `null`이다. Email은 반환하지 않는다.

### Lifecycle Version

- Alert response의 `version`은 lifecycle 상태 전용 optimistic concurrency version이다.
- `acknowledge`, `resolve`, `reopen` 성공 시 1 증가한다.
- Cooldown occurrence count와 `last_detected_at` 갱신은 `version`을 증가시키지 않는다.
- Mutation request의 `expected_version`이 현재 version과 다르면 `409 stale_state`다.
- `409`에서는 상태 변경과 lifecycle audit을 만들지 않는다.

## Response Models

### SecurityAlertListItem

```json
{
  "id": "<uuid>",
  "organization_id": "<uuid>",
  "rule_id": "repeated_permission_denied",
  "rule_version": "v1",
  "severity": "medium",
  "status": "open",
  "policy_reason": null,
  "actor": {
    "id": "<uuid>",
    "display_name": "홍길동",
    "state": "active"
  },
  "occurrence_count": 5,
  "first_detected_at": "<datetime>",
  "last_detected_at": "<datetime>",
  "version": 1,
  "created_at": "<datetime>",
  "updated_at": "<datetime>"
}
```

Field contracts:

| Field | Type | Contract |
| --- | --- | --- |
| `id` | UUID | Alert ID |
| `organization_id` | UUID | 현재 요청 organization과 동일 |
| `rule_id` | enum | `repeated_permission_denied`, `multi_resource_permission_probe`, `repeated_policy_block` |
| `rule_version` | string | MVP는 `v1` |
| `severity` | enum | `medium`, `high` |
| `status` | enum | `open`, `acknowledged`, `resolved` |
| `policy_reason` | string/null | `repeated_policy_block`만 canonical allowlist 값, 나머지는 null |
| `actor` | SafeActor | Email 없는 현재 safe projection |
| `occurrence_count` | integer | 0 이상 |
| `first_detected_at` | datetime | 최초 threshold 충족 alert 시각 |
| `last_detected_at` | datetime | 가장 최근 연결 event 시각 |
| `version` | integer | 1 이상 lifecycle version |

Detection key, raw target 목록, raw audit metadata는 응답하지 않는다.

### SecurityAlertDetail

목록 item에 lifecycle 처리 요약과 evidence count를 추가한다.

```json
{
  "id": "<uuid>",
  "organization_id": "<uuid>",
  "rule_id": "repeated_policy_block",
  "rule_version": "v1",
  "severity": "high",
  "status": "resolved",
  "policy_reason": "rag.pii_evidence_detected",
  "actor": {
    "id": "<uuid>",
    "display_name": null,
    "state": "deleted"
  },
  "occurrence_count": 3,
  "evidence_count": 3,
  "first_detected_at": "<datetime>",
  "last_detected_at": "<datetime>",
  "version": 3,
  "acknowledged": {
    "by": {
      "id": "<uuid>",
      "display_name": "관리자",
      "state": "active"
    },
    "at": "<datetime>"
  },
  "resolution": {
    "type": "mitigated",
    "reason": "필요한 대응을 완료했습니다.",
    "by": {
      "id": "<uuid>",
      "display_name": "관리자",
      "state": "active"
    },
    "at": "<datetime>"
  },
  "created_at": "<datetime>",
  "updated_at": "<datetime>"
}
```

- Acknowledge 이력이 없으면 `acknowledged`는 `null`이다.
- 현재 resolved 상태가 아니면 `resolution`은 `null`이다.
- `reopen`은 acknowledged 상태를 open으로 되돌리며 `acknowledged` 현재 요약을 null로 만든다. 상태 변경 이력은 canonical audit에 남는다.
- Resolution reason은 저장 전에 정규화와 redaction을 거친 값만 반환한다.

## GET `/admin/security-alerts`

### Query

| Parameter | Type | Required | Default | Contract |
| --- | --- | --- | --- | --- |
| `page` | integer | no | 1 | 1 이상 |
| `limit` | integer | no | 20 | 1 이상 100 이하 |
| `severity` | enum | no | - | `medium`, `high` |
| `status` | enum | no | - | `open`, `acknowledged`, `resolved` |
| `ruleId` | enum | no | - | 지원하는 canonical rule ID |
| `actorId` | UUID | no | - | Alert subject actor |
| `startAt` | datetime | no | - | `last_detected_at` 하한 포함 |
| `endAt` | datetime | no | - | `last_detected_at` 상한 제외 |

모든 필터는 AND로 조합한다. 기본 status 필터는 없으며 모든 상태를 반환한다.

정렬은 `last_detected_at DESC`, 같은 시각이면 `id DESC`로 고정한다.

### Response `200`

```json
{
  "total": 12,
  "items": [
    {
      "id": "<uuid>",
      "organization_id": "<uuid>",
      "rule_id": "multi_resource_permission_probe",
      "rule_version": "v1",
      "severity": "high",
      "status": "open",
      "policy_reason": null,
      "actor": {
        "id": "<uuid>",
        "display_name": "홍길동",
        "state": "active"
      },
      "occurrence_count": 5,
      "first_detected_at": "<datetime>",
      "last_detected_at": "<datetime>",
      "version": 1,
      "created_at": "<datetime>",
      "updated_at": "<datetime>"
    }
  ]
}
```

## GET `/admin/security-alerts/summary`

Sidebar 전용 bounded projection이다. Query parameter를 받지 않는다.

### Response `200`

```json
{
  "open_count": 4,
  "high_open_count": 2,
  "recent_items": [
    {
      "id": "<uuid>",
      "rule_id": "repeated_permission_denied",
      "severity": "medium",
      "actor": {
        "id": "<uuid>",
        "display_name": "홍길동",
        "state": "active"
      },
      "occurrence_count": 7,
      "last_detected_at": "<datetime>"
    }
  ]
}
```

- `open_count`는 `status='open'`만 센다.
- `high_open_count`도 open 중 `severity='high'`만 센다.
- `recent_items`는 open alert를 `last_detected_at DESC`, `id DESC`로 정렬한 최대 5개다.
- `acknowledged`, `resolved`는 count와 recent items에서 제외한다.

## GET `/admin/security-alerts/{alert_id}`

### Response `200`

`SecurityAlertDetail`을 반환한다.

- 현재 request organization과 alert organization이 일치해야 한다.
- 관련 audit 원문을 inline으로 포함하지 않는다.
- 다른 organization 또는 존재하지 않는 alert는 `404 resource.not_found`다.

## GET `/admin/security-alerts/{alert_id}/audit-logs`

### Query

| Parameter | Type | Required | Default | Contract |
| --- | --- | --- | --- | --- |
| `page` | integer | no | 1 | 1 이상 |
| `limit` | integer | no | 20 | 1 이상 100 이하 |

### Response `200`

기존 `AuditLogSchema`와 같은 safe list projection을 사용한다.

```json
{
  "total": 5,
  "items": [
    {
      "id": "<uuid>",
      "occurred_at": "<datetime>",
      "actor_id": "<uuid>",
      "actor_type": "user",
      "category": "action",
      "action": "permission.denied",
      "target_type": "workflow",
      "target_id": "<opaque-id>",
      "status": "failure",
      "request_id": "<string|null>"
    }
  ]
}
```

- Alert evidence로 실제 연결된 audit만 반환한다.
- 정렬은 `occurred_at DESC`, 같은 시각이면 `id DESC`다.
- Generic `audit_metadata`, `before`, `after`, `change_summary`를 반환하지 않는다.
- Target이 safe projection 조건을 만족하지 않으면 `target_type`, `target_id`는 null로 반환한다.
- Audit detail이 필요하면 기존 `/api/v1/admin/audit-logs/{audit_log_id}` 권한과 allowlist를 다시 통과해야 한다.

## POST `/admin/security-alerts/{alert_id}/acknowledge`

`open` alert를 `acknowledged`로 변경한다.

### Request

```json
{
  "expected_version": 1
}
```

- Unknown field는 거부한다.
- 현재 status가 `open`이 아니거나 version이 다르면 `409 stale_state`다.

### Response `200`

변경 후 `SecurityAlertDetail`을 반환한다.

같은 transaction에서 처리 관리자/시각을 기록하고 `security_alert.acknowledged` audit을 생성한다.

## POST `/admin/security-alerts/{alert_id}/resolve`

`open` 또는 `acknowledged` alert를 `resolved`로 변경한다.

### Request

```json
{
  "expected_version": 2,
  "resolution_type": "mitigated",
  "reason": "사용자 접근 상태를 확인하고 필요한 대응을 완료했습니다."
}
```

| Field | Type | Required | Contract |
| --- | --- | --- | --- |
| `expected_version` | integer | yes | 1 이상, 현재 lifecycle version과 일치 |
| `resolution_type` | enum | yes | `mitigated`, `false_positive`, `accepted_risk` |
| `reason` | string | yes | 정규화 후 non-blank, 최대 500 Unicode code point |

Reason은 다음 기준을 적용한다.

- CRLF/CR을 LF로 정규화하고 앞뒤 공백을 제거한다.
- 정규화 후 blank면 `422 validation.failed`다.
- Tab/LF 외 C0/C1과 bidi override/isolate control을 거부한다.
- Shared fail-closed secret/PII redaction을 적용한다.
- Sanitization 실패 시 mutation과 reason을 저장하지 않는다.
- Query string이나 URL로 reason을 받지 않는다.

현재 status가 `open` 또는 `acknowledged`가 아니거나 version이 다르면 `409 stale_state`다.

### Response `200`

변경 후 `SecurityAlertDetail`을 반환한다.

같은 transaction에서 resolution과 처리 관리자/시각을 기록하고 `security_alert.resolved` audit을 생성한다.

## POST `/admin/security-alerts/{alert_id}/reopen`

`acknowledged` alert를 `open`으로 되돌린다. `resolved` alert는 reopen하지 않으며 이후 새 threshold 충족 시 새 alert를 만든다.

### Request

```json
{
  "expected_version": 2
}
```

현재 status가 `acknowledged`가 아니거나 version이 다르면 `409 stale_state`다.

### Response `200`

변경 후 `SecurityAlertDetail`을 반환한다. 현재 acknowledged 요약은 null이 되며 `security_alert.reopened` audit을 같은 transaction에 생성한다.

## Error Contract

Error response는 가능한 경우 다음 safe shape을 사용한다.

```json
{
  "error": {
    "code": "stale_state",
    "message": "Security alert state changed. Refresh and try again."
  },
  "request_id": "<string>"
}
```

| Status | Code | Condition |
| --- | --- | --- |
| 400 | `organization.required` | `X-Organization-Id` 누락 |
| 400 | `period.invalid` | `endAt`이 `startAt`보다 늦지 않음 |
| 401 | `auth.required` | 로그인 세션 없음/만료 |
| 403 | `permission.denied` | Scope 안이지만 현재 owner/manager가 아님 |
| 404 | `resource.not_found` | Alert 없음, 다른 organization, scope 밖 alert |
| 409 | `stale_state` | Version mismatch 또는 허용되지 않은 현재 상태 전이 |
| 422 | `validation.failed` | UUID/query/enum/body/reason 형식 오류 또는 unknown field |
| 500 | `audit.persistence_failed` | Lifecycle mutation과 canonical audit의 transaction 기록 실패 |

### Audit On Errors

- Scope 안 owner/manager 권한 부족은 target scope 확인 전 target-aware metadata 없이 `permission.denied`를 기록한다.
- 다른 organization, hidden 404, validation 실패에는 target-aware Security Alert audit을 만들지 않는다.
- `409 stale_state`에는 lifecycle mutation과 `security_alert.*` audit을 만들지 않는다.
- Lifecycle mutation audit persistence가 실패하면 mutation도 rollback하고 safe `500 audit.persistence_failed`를 반환한다.

## Notification Boundary

- Alert 생성, 활성 alert occurrence 갱신, acknowledge, resolve, reopen commit 이후 `notifications.changed`를 권한 있는 현재 organization manager 대상 channel에 발행한다.
- SSE payload는 alert detail이나 evidence를 source of truth로 전달하지 않는다.
- Client는 event를 받으면 summary와 필요한 목록/detail을 재조회한다.
- Publish 실패는 이미 commit된 Alert/lifecycle mutation을 rollback하지 않는다.
- Reconnect와 missed event 복구는 영속 summary/list 조회가 담당한다.
