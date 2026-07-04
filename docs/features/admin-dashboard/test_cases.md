# Admin Dashboard Test Cases

Status: Draft
Verified Against: TBD

[requirements.md](requirements.md)의 FR-011~FR-015와 [api_spec.md](api_spec.md), [component_spec.md](component_spec.md)를 검증한다. 신청 제출 측(FR-041)의 인수 조건은 [organization](../organization/requirements.md) 범위이며, 여기서는 관리자 측 흐름과 E2E 연결만 다룬다.

## Acceptance Criteria

### AC-1. audit log 검색/상세 (FR-011)

- Given 조직 A의 audit `auditor` 이상 권한 사용자, When `GET /admin/audit-logs`를 호출하면, Then 조직 A scope의 audit log만 `occurred_at` 내림차순으로 반환된다.
- Given 행위자/action/대상/기간/status 필터, When 각각 또는 조합(AND)으로 조회하면, Then 조건에 맞는 row만 반환된다. action 값은 canonical action 문자열 기준이다 ([ADR-0008](../../decisions/ADR-0008-audit-action-naming-standard.md)).
- Given `startAt`/`endAt` 기간 필터, When `occurred_at`이 `startAt`과 정확히 같은 row와 `endAt`과 정확히 같은 row가 있으면, Then 전자는 포함되고 후자는 제외된다 (`[start, end)`).
- Given 개별 로그 상세 조회, When `GET /admin/audit-logs/{id}`를 호출하면, Then actor, action, target, status, timestamp와 allowlist metadata만 반환되고 raw payload/secret 계열 값은 포함되지 않는다.
- Given audit 권한 없는 조직 member, When 검색/상세를 호출하면, Then `403`과 `permission.denied` audit이 기록된다.

### AC-2. workflow별 비용 집계 (FR-012)

- Given 기간 미지정 조회, When `GET /admin/usage/workflows`를 호출하면, Then 이번 달(KST 달력 월) 기준으로 집계된다.
- Given 조직 A의 `llm_usage_logs`, When 집계를 조회하면, Then workflow별 합계(prompt/completion tokens, call_count, total_cost)가 원천 row 합산과 일치하고, `total_cost`가 NULL인 row는 0으로 합산된다.
- Given 집계 결과, Then 목록은 `total_cost` 내림차순이고, 비용 값은 반올림 없이 원본 정밀도로 반환된다.
- Given 조직 B의 usage 데이터, When 조직 A로 조회하면, Then 조직 B의 workflow는 응답에 포함되지 않는다.

### AC-3. 권한 신청 목록/승인/거절 (FR-014)

- Given pending 신청이 있는 조직, When owner/manager가 `GET /admin/permission-requests`를 호출하면, Then 요청자, 요청 권한(`app.create`), 신청 사유, 신청일이 포함된 pending 목록이 기본 반환된다.
- Given pending 신청, When 승인하면, Then 같은 트랜잭션에서 (1) status가 `approved`로 바뀌고 decided_by/decided_at이 기록되고, (2) 신청자의 `user_app_creation_permissions` row가 생성되고, (3) `permission_request.approved`와 `user_app_creation_permission.created` audit이 각각 기록된다.
- Given 승인된 신청자, When App 생성(`POST /apps`)을 시도하면, Then 성공한다.
- Given pending 신청, When 거절하면, Then status가 `rejected`로 바뀌고 `permission_request.rejected` audit이 기록되며, `user_app_creation_permissions` row는 생성되지 않는다. 거절된 신청자는 재신청할 수 있다.
- Given 이미 처리된(approved/rejected) 신청, When 다시 승인/거절을 요청하면, Then `409`가 반환되고 상태와 권한 row는 변하지 않는다.

### AC-4. 조직 월간 비용/예산 위험 요약 (FR-015)

- Given 조직 A의 이번 달 usage, When `GET /admin/summary`를 호출하면, Then 이번 달(KST) 조직 LLM 비용 합계가 반환된다.
- Given KST 월 경계 근처의 usage row (예: KST 7월 1일 00:30 = UTC 6월 30일 15:30 저장), When 7월 요약을 조회하면, Then 해당 row는 7월 집계에 포함된다.
- Given 예산 관리 feature 미확정 상태, When 요약을 조회하면, Then `budget` 블록은 null/생략될 수 있고 이는 오류가 아니다.
- (예산 feature 확정 후) Given 예산이 설정된 workflow, When 사용률이 90% 이상이면 위험, 100%를 초과하면 초과로 분류되고, 반올림 전 값으로 판정된다. 예산 미설정 workflow는 판정 대상에서 제외된다.

### AC-5. 권한 경계

- Given `auditor`/`raw_auditor` 전용 사용자, Then audit 검색/상세(AC-1)만 접근할 수 있고, usage/summary/permission-requests는 `403`이다. UI에서는 감사 로그 탭만 노출된다.
- Given audit 권한 없는 일반 member, Then 모든 admin API가 `403`이다.
- Given organization owner/manager, Then 모든 admin API에 접근할 수 있다.
- Given 다른 조직의 `audit_log_id`/`request_id`, When 조회/처리를 시도하면, Then `404`로 존재가 숨겨진다 ([ADR-0010](../../decisions/ADR-0010-resource-access-403-404-policy.md)).

## Unit Tests

단위 테스트는 endpoint/TestClient보다 service/helper method 계약을 우선 검증한다. 아래 class명은 구현 경계의 권장 이름이다. 구현 과정에서 이름이 달라지더라도 동일한 책임 단위가 보존되어야 한다.

### `AdminPermissionGuard`

- `require_audit_reader(db, user, organization_id)`
  - Given organization owner/manager, When audit reader 검사를 수행하면, Then 통과한다.
  - Given audit `auditor`, When audit reader 검사를 수행하면, Then 통과한다.
  - Given audit `raw_auditor`, When audit reader 검사를 수행하면, Then 통과한다.
  - Given audit auth_state가 없고 organization member인 사용자, When audit reader 검사를 수행하면, Then `403` 예외와 `permission.denied` audit 기록 요청을 만든다.
  - Given inactive/suspended/removed membership 또는 비활성화된 team의 audit grant, When audit reader 검사를 수행하면, Then fail-closed로 `403`이다.
  - Given 사용자가 여러 team audit grant를 갖고 있고 첫 row는 `none`, 다른 row는 `auditor` 이상, When audit reader 검사를 수행하면, Then row 순서와 무관하게 통과한다.
  - Given audit reader 권한이 없는 같은 organization scope 사용자, When audit reader 검사를 수행하면, Then `permission.denied` audit은 `resource_type="audit"`, `resource_id=<organization_id>`, `organization_id=<organization_id>`, `permission_action="read"`를 포함하고 전역 `auth.permission_denied` 중복 기록은 억제된다.
- `require_org_manager(db, user, organization_id)`
  - Given organization owner/manager, When manager 검사를 수행하면, Then 통과한다.
  - Given audit `auditor` 또는 `raw_auditor`만 가진 사용자, When manager 검사를 수행하면, Then `403`이다.
  - Given 일반 active member, When manager 검사를 수행하면, Then `403`이다.
  - Given invalid `organization_id`, When manager 검사를 수행하면, Then `400` 또는 validation error로 닫힌다.
- `hide_cross_org_resource(resource_organization_id, requested_organization_id)`
  - Given 같은 organization id, When scope 검사를 수행하면, Then 통과한다.
  - Given 다른 organization id, When scope 검사를 수행하면, Then `404 resource.not_found` 예외를 반환한다.
  - Given resource가 존재하지 않는 경우와 scope 밖 resource인 경우, Then API 계층에서 같은 `404` shape로 매핑된다.

### `AdminAuditLogService`

- `resolve_period(start_at, end_at, default_month=False)`
  - Given timezone offset이 있는 ISO datetime, When 기간을 해석하면, Then UTC 비교 가능한 aware datetime으로 변환한다.
  - Given timezone offset 없는 ISO datetime, When 기간을 해석하면, Then KST(Asia/Seoul)로 해석한다.
  - Given `endAt <= startAt`, When 기간을 해석하면, Then `400`에 매핑 가능한 validation error를 반환한다.
  - Given 시작/끝이 모두 없는 audit 검색, When 기간을 해석하면, Then 기간 필터를 적용하지 않는다.
- `build_audit_filters(actor_id, action, target_type, target_id, status, period)`
  - Given 각 필터 단독 입력, When query filter를 만들면, Then 해당 column 조건만 생성한다.
  - Given 여러 필터 조합, When query filter를 만들면, Then 조건은 OR가 아니라 AND로 결합된다.
  - Given canonical action 문자열, When action filter를 만들면, Then 사용자 친화 label이 아니라 raw action 값으로 비교한다.
  - Given `startAt`과 정확히 같은 `occurred_at`, Then 포함 조건(`>=`)을 만든다.
  - Given `endAt`과 정확히 같은 `occurred_at`, Then 제외 조건(`<`)을 만든다.
- `list_audit_logs(db, user, organization_id, filters, page, limit)`
  - Given 조직 A의 로그와 조직 B의 로그가 섞여 있을 때, When 조직 A로 조회하면, Then 조직 A scope의 row만 반환한다.
  - Given 여러 row, When 조회하면, Then `occurred_at` 내림차순으로 정렬한다.
  - Given `page`/`limit`, When 조회하면, Then `{total, items}`에서 `total`은 필터 전체 건수이고 `items`는 해당 page slice다.
  - Given 결과가 없을 때, When 조회하면, Then `{total: 0, items: []}`를 반환한다.
- `get_audit_log_detail(db, user, organization_id, audit_log_id)`
  - Given 같은 조직의 log id, When 상세를 조회하면, Then actor/action/target/status/timestamp와 sanitized metadata를 반환한다.
  - Given 다른 조직의 log id, When 상세를 조회하면, Then `404`를 반환한다.
  - Given 존재하지 않는 log id, When 상세를 조회하면, Then 다른 조직 id와 구분되지 않는 `404`를 반환한다.
- `sanitize_audit_metadata(metadata)`
  - Given allowlist key(`request_id`, `reason`, `summary`, `organization_id` 등), When sanitize하면, Then 값이 유지된다.
  - Given `raw_payload`, `payload`, `encrypted_config`, `api_key`, `token`, `secret`, `password`, `authorization` 계열 key, When sanitize하면, Then key 또는 value가 응답에서 제거된다.
  - Given nested metadata 안에 secret 계열 key가 있을 때, When sanitize하면, Then 중첩 secret도 제거된다.
  - Given metadata가 `None` 또는 빈 dict, When sanitize하면, Then 빈 dict를 반환한다.

### `AdminUsageService`

- `resolve_month_period_kst(now)`
  - Given KST 2026-07-15, When 이번 달 기간을 계산하면, Then start=`2026-07-01T00:00:00+09:00`, end=`2026-08-01T00:00:00+09:00`이다.
  - Given UTC 저장 row `2026-06-30T15:30:00Z`, When 2026년 7월 KST 기간과 비교하면, Then 포함된다.
  - Given UTC 저장 row `2026-07-31T15:00:00Z`, When 2026년 8월 KST 시작 경계와 비교하면, Then 7월 집계에서는 제외된다.
- `resolve_period(start_at, end_at, default_month=True)`
  - Given 기간 미지정, When usage 조회 기간을 해석하면, Then KST 이번 달을 기본값으로 반환한다.
  - Given offset 없는 `startAt`/`endAt`, When 해석하면, Then KST 기준으로 aware datetime을 만든다.
  - Given `startAt`/`endAt` 중 한쪽만 제공, When 해석하면, Then validation error를 반환한다.
  - Given `endAt <= startAt`, When 해석하면, Then validation error를 반환한다.
- `coalesce_cost(value)`
  - Given `None`, When 비용을 합산 전 정규화하면, Then `Decimal("0")`을 반환한다.
  - Given `Decimal("12.345678")`, When 정규화하면, Then 반올림 없이 같은 값을 반환한다.
- `aggregate_workflow_usage(db, organization_id, period, page, limit)`
  - Given workflow별 usage row 여러 개, When 집계하면, Then prompt tokens/completion tokens/call_count/total_cost가 원천 row 합산과 일치한다.
  - Given workflow가 App에 연결되어 있을 때, When 집계 응답 item을 만들면, Then `workflow_name`은 `Workflow.app_id`로 연결된 `App.name`이다.
  - Given `total_cost`가 `NULL`인 row, When 집계하면, Then 0으로 합산한다.
  - Given 조직 B의 usage row, When 조직 A로 조회하면, Then 응답에 포함하지 않는다.
  - Given 집계 결과, When 정렬하면, Then `total_cost` 내림차순이다.
  - Given 비용 값 `12.345678`, When 응답 모델을 만들면, Then service 응답은 `12.345678` 원본 정밀도를 유지한다.
  - Given page/limit, When 응답을 만들면, Then `total`은 전체 workflow 집계 건수이고 `items`는 page slice다.
- `get_organization_summary(db, organization_id, now)`
  - Given 이번 달 usage row, When summary를 조회하면, Then 조직 월간 `total_cost` 합계를 반환한다.
  - Given `total_cost`가 `NULL`인 row, When summary를 조회하면, Then 0으로 합산한다.
  - Given 예산 feature가 미구현/미설정 상태, When summary를 조회하면, Then `budget`은 `None` 또는 생략 가능한 값으로 반환한다.
- `classify_budget_usage(total_cost, budget_amount)` (예산 feature 확정 후 활성화)
  - Given 사용률이 89.9999%, When 판정하면, Then 정상이다.
  - Given 사용률이 90.0000%, When 판정하면, Then 위험이다.
  - Given 사용률이 100.0000%, When 판정하면, Then 위험이며 초과는 아니다.
  - Given 사용률이 100.0001%, When 판정하면, Then 초과다.
  - Given 예산이 없거나 0 이하, When 판정하면, Then 위험/초과 판정 대상에서 제외한다 (비율의 분모 정의는 예산 feature 확정 시 결정 — requirements Open Question).

### `PermissionRequestService`

- `list_requests(db, organization_id, status, page, limit)`
  - Given status 미지정, When 목록을 조회하면, Then `pending` 신청만 기본 반환한다.
  - Given `approved` 또는 `rejected` status, When 목록을 조회하면, Then 해당 상태만 반환한다.
  - Given 조직 A/B 신청이 섞여 있을 때, When 조직 A로 조회하면, Then 조직 A 신청만 반환한다.
  - Given 여러 신청, When 조회하면, Then `created_at` 내림차순으로 정렬한다.
  - Given 목록 item을 만들 때, Then 요청자 id/name/email, `requested_permission`, `reason`, `status`, `created_at`, `decided_by`, `decided_at`을 포함한다.
- `ensure_request_processable(request, organization_id)`
  - Given pending 신청과 같은 organization id, When 처리 가능성을 확인하면, Then 통과한다.
  - Given approved/rejected 신청, When 처리 가능성을 확인하면, Then `409`에 매핑 가능한 conflict를 반환한다.
  - Given 다른 organization id의 신청, When 처리 가능성을 확인하면, Then `404`에 매핑 가능한 not found를 반환한다.
- `ensure_requester_is_active_member(db, request)`
  - Given 신청자가 active member, When 승인 전 검사를 수행하면, Then 통과한다.
  - Given 신청자가 removed/suspended/invited 상태, When 승인 전 검사를 수행하면, Then `409`를 반환한다.
  - Given 신청자 user가 deactivated 된 상태, When 승인 전 검사를 수행하면, Then `409`를 반환한다.
- `approve_request(db, request_id, organization_id, decided_by)`
  - Given pending 신청, When 승인하면, Then 같은 transaction에서 status=`approved`, `decided_by`, `decided_at`을 기록한다.
  - Given pending 신청, When 승인하면, Then `user_app_creation_permissions` row를 생성한다.
  - Given 이미 같은 user/org 권한 row가 있는 비정상 pending 신청, When 승인하면, Then `409`를 반환하고 신청 상태, 권한 row, audit은 변하지 않는다. 정상 제출 경로에서는 기존 권한 row 보유자가 pending 신청을 만들 수 없어야 한다.
  - Given 승인 성공, Then `permission_request.approved`와 `user_app_creation_permission.created` audit 이벤트를 각각 만든다.
  - Given 권한 row 생성 또는 audit 준비 중 실패, When 승인하면, Then transaction은 rollback되어 신청 상태와 권한 row가 남지 않는다.
  - Given 동시 approve/reject 경합, When 한 transaction이 먼저 처리하면, Then 나머지는 `409`이고 중복 권한 row가 없다.
- `reject_request(db, request_id, organization_id, decided_by)`
  - Given pending 신청, When 거절하면, Then status=`rejected`, `decided_by`, `decided_at`을 기록한다.
  - Given 거절 성공, Then `permission_request.rejected` audit 이벤트를 만든다.
  - Given 거절 성공, Then `user_app_creation_permissions` row는 생성하지 않는다.
  - Given rejected 신청자, When 다시 신청 제출 흐름으로 넘어가면, Then pending 중복 규칙만 없다면 재신청 가능해야 한다.
- `grant_app_creation_permission(db, request, decided_by)`
  - Given `requested_permission="app.create"`, When 권한을 부여하면, Then `user_app_creation_permissions`에 organization/user/assigned_by를 기록한다.
  - Given 지원하지 않는 requested permission, When 권한 부여를 시도하면, Then validation error로 닫는다.
  - Given organization/user가 invalid UUID, When 권한 부여를 시도하면, Then 권한 row를 생성하지 않는다.

## API Tests

- (FR-011) 검색 필터가 각각, 그리고 조합(AND)으로 동작한다. 정렬은 `occurred_at` 내림차순, pagination은 `page`/`limit`(최대 100)과 `{total, items}` 형식을 따른다.
- (FR-011) 상세 응답에 allowlist metadata만 포함되고 raw payload/secret 값이 없다.
- (FR-012) 기간 미지정 시 이번 달(KST) 기본, 응답의 `period`가 적용 기간을 반환한다. 목록은 비용 내림차순이다.
- (FR-014) 목록 기본 status 필터가 `pending`이고, `approved`/`rejected` 필터가 동작한다.
- (FR-014) 승인 성공 응답에 `status`, `decided_by`, `decided_at`이 포함된다. 승인/거절의 side effect(AC-3)가 DB와 audit에 반영된다.
- (FR-014) 이미 처리된 신청 재처리 → `409`. 동시 승인/거절 경합은 한쪽만 성공하고 나머지는 `409`를 받는다 (중복 부여 없음).
- 공통: `X-Organization-Id` 누락/invalid → `400`, `endAt ≤ startAt` → `400`, `limit > 100` → `422`, 미인증 → `401`.
- Usage 집계: `startAt`/`endAt` 중 한쪽만 제공 → `400`.
- 공통: 검색 결과 없음은 `{ "total": 0, "items": [] }` 정상 응답이다.

## E2E Tests

- **PRD 시나리오 1→2 연결 완주**: 권한 없는 신입 계정의 App 생성 차단(403) → 권한 신청 제출 → 관리자가 권한 신청 탭에서 승인 → 신입 계정 App 생성 성공 → 관리자 audit 탭에서 `permission_request.created/approved`, `user_app_creation_permission.created`, App/workflow 생성 기록 확인.
- **PRD 시나리오 2 완주**: 관리자가 audit 검색으로 권한 신청/승인, workflow 생성/배포/실행 기록을 확인하고, 상단 요약 카드에서 이번 달 조직 비용을 확인한다 (예산 위험 비율은 예산 feature 확정 후 추가).
- 비용 탭에서 비용 상위 workflow를 확인하고 해당 workflow 화면으로 이동한다 (진입만 — 비교/최적화는 cost-optimizer 범위).
- 승인 흐름 UI: 승인 버튼 → 확인 다이얼로그(요청자/권한/사유 표시) → 확정 → 성공 toast → 목록에서 pending 제거.
- 이미 처리된 신청을 다른 세션에서 재처리 → "이미 처리된 신청" 안내 후 목록 갱신.

## Permission Tests

- `auditor` 사용자: audit 검색/상세 200, usage/summary/permission-requests 전부 403 (`permission.denied` audit 기록).
- audit 권한 없는 일반 member: 모든 admin API 403.
- organization owner/manager: 모든 admin API 200.
- 다른 organization의 audit/usage/신청 데이터가 응답에 포함되지 않고, 타 조직 id 직접 조회는 404다.
- raw payload 조회는 admin API로 불가능하다 — `raw_auditor`의 `view_raw`는 trace visibility policy 경로에서만 판정된다.
- UI: `auditor` 로그인 시 감사 로그 탭만 렌더링되고 요약 카드가 표시되지 않는다 (프론트 노출 제어는 보조이며, API 403이 최종 경계임을 함께 검증).

## Edge Cases

- 검색 결과가 없는 기간/필터 조합 → 빈 목록 정상 응답, UI는 empty state 표시.
- `audit_metadata`에 저장된 secret 계열 값이 목록/상세 어디에도 노출되지 않는다 (NFR-004).
- 가격 미등록 모델의 usage(`total_cost=0.0`)는 집계에 0으로 반영된다 — "미산정 구분 불가"는 수용된 한계이며 테스트는 0 합산 동작만 검증한다.
- 예산 `budget` null 상태에서 UI 요약 카드가 "예산 미설정"을 표시한다 (오류 아님).
- 승인 시점에 신청자가 조직의 active member가 아니면(제거/정지) 승인이 `409`로 거부되고, 권한 row와 audit(`user_app_creation_permission.created`)이 생성되지 않는다.
- 멤버 제거 시 해당 user의 `user_app_creation_permissions` row가 permission cleanup으로 삭제되고, 이후 그 user의 App 생성은 다시 차단된다 (승인·제거 경합의 최종 상태 정리 — [ADR-0016](../../decisions/ADR-0016-permission-request-and-app-creation-permission.md)).
- timestamp 표시는 사용자 로컬 시간대, `<time datetime>`은 ISO 값을 유지한다.
