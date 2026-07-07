# Budget Alert API Spec

Status: Draft
Verified Against: TBD

예산 알림 API는 기존 알림 표면(`/api/v1/notifications`)과 **분리된 하위 경로**(`/api/v1/notifications/budget*`)로 추가한다. 기존 `GET /notifications`(조직 초대)와 `GET /notifications/stream`(SSE) 계약은 변경하지 않는다. 벨 오버레이는 초대 목록과 예산 알림 목록을 클라이언트에서 병합해 표시한다 ([component_spec](./component_spec.md)).

모든 endpoint는 인증을 요구한다. 각 사용자는 자신이 수신자인 알림(제작자 또는 조직 관리자, BGA-REQ-020)만 조회/읽음/삭제할 수 있다.

## Endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| GET | `/api/v1/notifications/budget` | 현재 사용자의 예산 알림 목록(삭제되지 않은 것 전부) | 인증 사용자 |
| POST | `/api/v1/notifications/budget/read` | 현재 사용자의 안읽은 예산 알림 일괄 읽음 | 인증 사용자 |
| DELETE | `/api/v1/notifications/budget/{alert_id}` | 예산 알림 1건 삭제(수신자별 제거) | 인증 사용자(해당 항목 수신자) |
| GET | `/api/v1/notifications/stream` | 기존 SSE 재사용 — `notifications.changed` 신호 | 인증 사용자 |

- 새 목록/스트림을 별도로 만들지 않는다. 즉시성은 기존 SSE(`notifications.changed`)를 재사용하고, 신호 수신 시 클라이언트가 초대·예산 목록을 각각 refetch한다 (BGA-REQ-043). 도달 보장은 저장된 알림 기록이 담당한다.
- `X-Organization-Id` header는 요구하지 않는다. 예산 알림은 사용자 개인의 수신함이며 여러 조직의 항목이 섞일 수 있다. 조직별 노출 판정(금액 리댁션)은 항목별로 수행한다 (BGA-REQ-052).

## Request And Response Models

공통 규칙:

- 비용/예산 값은 USD이며 JSON number로 반환한다. 반올림은 클라이언트 표시 계층에서 1회만 수행한다. `usage_ratio`와 상태 판정은 반올림 전 값 기준이다 (BGT-REQ-012).
- `status`는 `at_risk` | `exceeded` 문자열이다. 예산 알림은 상향 전이만 발송하므로 `normal`은 나타나지 않는다 (BGA-REQ-010).
- `type`은 `budget.at_risk` | `budget.exceeded`이며 `status`와 대응한다. `type`은 알림 종류 구분, `status`는 배지 표시에 사용한다.
- 표시값(`usage_ratio`, `monthly_budget_usd`, `current_month_cost`)은 알림이 발생한 시점의 **스냅샷**이다. 조회 시점에 재계산하지 않는다 (BGA-REQ-031, 발생 당시 상태를 그대로 보존).

### GET /notifications/budget

Query: 없음 (알림 수가 적어 페이지네이션을 두지 않는다. 정렬은 `created_at` 내림차순.)

Response `200` — 요청자가 해당 항목 조직의 **관리자**인 경우:

```json
{
  "items": [
    {
      "id": "<uuid>",
      "type": "budget.at_risk",
      "workflow_id": "<uuid>",
      "workflow_name": "<string>",
      "organization_id": "<uuid>",
      "status": "at_risk",
      "usage_ratio": 0.923457,
      "monthly_budget_usd": 100.0,
      "current_month_cost": 92.345678,
      "read": false,
      "created_at": "<datetime>"
    }
  ]
}
```

요청자가 해당 항목 조직의 **관리자가 아닌 제작자(member)**인 경우 — 금액 두 필드를 제외한다:

```json
{
  "items": [
    {
      "id": "<uuid>",
      "type": "budget.at_risk",
      "workflow_id": "<uuid>",
      "workflow_name": "<string>",
      "organization_id": "<uuid>",
      "status": "at_risk",
      "usage_ratio": 0.923457,
      "read": false,
      "created_at": "<datetime>"
    }
  ]
}
```

- 삭제되지 않은 항목을 안읽음/읽음 구분 없이 모두 반환한다(받은함 모델, BGA-REQ-031). `read`는 현재 사용자 기준 읽음 여부다.
- 리댁션은 **항목별**로 판정한다. `monthly_budget_usd`/`current_month_cost`는 요청자가 그 항목 `organization_id`의 관리자(`has_organization_manager_permission`)일 때만 포함하고, 아니면 응답에서 제외한다 (BGA-REQ-052). 한 사용자가 A조직 관리자·B조직 제작자면 항목마다 노출이 다르다.
- 각 항목은 이미 그 사용자를 수신자로 하는 것만 반환한다. 다른 사용자의 알림은 노출하지 않는다.

### POST /notifications/budget/read

Request body: 없음.

Response `200`:

```json
{ "updated": 3 }
```

- 현재 사용자의 안읽은(`read=false`) 예산 알림을 모두 읽음 처리한다 (BGA-REQ-042, 일괄 읽음). `updated`는 이번 호출로 읽음 전환된 건수다.
- 항목별 선택 읽음은 제공하지 않는다. 오버레이 열림 시 1회 호출해 안읽음 인디케이터를 해소하는 용도다.
- 이미 모두 읽음이면 `updated=0`으로 정상 응답한다(no-op).
- 읽음 처리는 목록에서 제거하지 않는다. 읽은 항목은 계속 반환되며 클라이언트에서 흐리게 표시한다.

### DELETE /notifications/budget/{alert_id}

Response `204`: 본문 없음.

- 현재 사용자의 해당 알림 항목을 제거한다(수신자별 hard delete). 같은 전이로 발송된 다른 수신자의 항목에는 영향을 주지 않는다 (BGA-REQ-044).
- 삭제는 벨 목록에서 제거만 한다. 중복 방지 기록(전이 상태, BGA-REQ-011)을 되살리지 않으므로 삭제 후 같은 달 같은 임계로 재발송되지 않는다.
- `alert_id`가 존재하지 않거나 현재 사용자의 항목이 아니면 `404 resource.not_found`로 숨긴다 ([ADR-0010](../../decisions/ADR-0010-resource-access-403-404-policy.md)). 이미 삭제된 항목의 재삭제도 `404`다.

## 발송 (내부, HTTP 아님)

예산 알림 생성은 클라이언트 요청이 아니라 run 완료 시점의 내부 파이프라인이 수행한다 (BGA-REQ-003, 004). HTTP endpoint가 아니며 이 문서의 표면 API에 포함되지 않는다.

- `update_run_log_finish`(log_system Celery task)가 예산 알림 평가 task를 enqueue한다(한 줄 hand-off).
- 평가 task는 해당 workflow의 당월 상태를 재계산하고, 상향 전이(BGA-REQ-010)이면 전이 상태 기록을 갱신한 뒤 수신자(제작자 + 조직 관리자 전원, dedup) 알림 항목을 생성하고, 각 수신자 채널로 `notifications.changed`를 발행한다.
- 표시값 스냅샷(`usage_ratio`, `monthly_budget_usd`, `current_month_cost`)은 이 시점에 기록에 저장한다.

## Errors

| Status | 조건 |
| --- | --- |
| 401 | 미인증 |
| 404 | `DELETE`에서 존재하지 않거나 현재 사용자 소유가 아닌 `alert_id` — 존재를 숨긴다 (`resource.not_found`, ADR-0010) |
| 422 | `alert_id`가 UUID 형식이 아님 |

- `GET`/`POST`는 현재 사용자 스코프에서만 동작하므로 별도 권한 오류(403)를 두지 않는다. 리댁션은 오류가 아니라 응답 필드 포함 여부로 처리한다.

## Permissions

| Endpoint | 판정 |
| --- | --- |
| `GET /notifications/budget` | 인증 사용자. 본인 수신 항목만. 항목별 금액 노출은 그 조직 관리자 여부로 판정 |
| `POST /notifications/budget/read` | 인증 사용자. 본인 안읽음 항목만 대상 |
| `DELETE /notifications/budget/{alert_id}` | 인증 사용자. 본인 소유 항목만, 아니면 404 |

- 수신자 판정(제작자 + 조직 관리자)은 발송 시점에 확정되어 알림 항목으로 저장된다. 조회/읽음/삭제는 저장된 수신자 항목 기준이며, 발송 이후의 권한 변경은 이미 발송된 항목의 소유권에 소급 적용하지 않는다.
- 금액 리댁션(BGA-REQ-052)은 조회 시점에 요청자의 현재 관리자 권한으로 판정한다. 발송 시 관리자였더라도 조회 시점에 관리자가 아니면 금액을 노출하지 않는다.
