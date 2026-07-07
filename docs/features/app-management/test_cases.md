# App Management Test Cases

Status: Draft
Verified Against: TBD

## Acceptance Criteria

### AC-1. App 목록 예산 상태 (APP-REQ-010, APP-REQ-030)

- Given 사용자가 읽을 수 있는 App의 primary workflow에 활성 예산이 있고 당월 비용이 기록되어 있다, When `GET /apps`를 호출한다, Then 해당 App의 `budget_status`는 `usage_ratio`와 `status`만 포함한다.
- Given 활성 예산이 없거나 App의 `workflow_id`가 null이다, When `GET /apps`를 호출한다, Then 해당 App의 `budget_status`는 null이고 기존 App 필드는 유지된다.
- Given App의 primary workflow에는 활성 예산이 없고 같은 `app_id`의 과거/보조 workflow에는 활성 예산이 있다, When `GET /apps`를 호출한다, Then 해당 App의 `budget_status`는 null이고 보조 workflow 상태를 표시하지 않는다.
- Given 사용자가 읽을 수 없는 App/Workflow가 있다, When `GET /apps`를 호출한다, Then 해당 리소스와 예산 상태는 응답에 포함되지 않는다.

### AC-2. 운영 현황 예산 상태 (APP-REQ-020, APP-REQ-030)

- Given `/dashboard/mymodule`에 표시되는 App row의 primary workflow에 활성 예산이 있다, When `GET /apps/operations`를 호출한다, Then `row.app.budget_status`는 `GET /apps`와 동일한 shape로 반환된다.
- Given `/dashboard/mymodule`에 표시되는 App row의 `workflow_id`가 null이고 같은 `app_id`의 과거/보조 workflow에 활성 예산이 있다, When `GET /apps/operations`를 호출한다, Then `row.app.budget_status`는 null이다.
- Given `row.app.budget_status.status`가 `exceeded`다, When 클라이언트가 `/dashboard/mymodule`을 렌더링한다, Then row는 예산 상태 badge와 "실행 차단" 표시를 보여준다.
- Given `row.app.budget_status`가 null이다, When 클라이언트가 `/dashboard/mymodule`을 렌더링한다, Then 예산 관련 텍스트 없이 기존 row 레이아웃을 유지한다.

### AC-3. Member 표면 노출 제한

- Given `GET /apps` 또는 `GET /apps/operations` 응답을 확인한다, Then `budget_status`에는 `usage_ratio`와 `status`만 포함되고 `monthly_budget_usd`, `current_month_cost`, credential, raw payload, secret 값은 포함되지 않는다.

### AC-4. 조회 성능과 동시성

- Given 여러 App row가 같은 응답에 포함된다, When `budget_status`를 계산한다, Then 응답 대상 workflow id를 모아 grouped query로 계산하고 App row마다 개별 비용 집계를 반복하지 않는다.
- Given 예산 수정/비활성화와 `GET /apps` 또는 `GET /apps/operations` 조회가 동시에 발생한다, When 응답을 생성한다, Then 요청은 5xx 없이 완료되고 각 row의 `usage_ratio`와 `status`는 같은 DB 조회 스냅샷 기준으로 일관된다.
- Given 조회 도중 App의 primary workflow 또는 예산 row가 삭제된다, When 응답을 생성한다, Then 이미 응답 대상인 App은 기존 접근 정책을 유지하고 예산 상태를 계산할 수 없으면 `budget_status=null`로 처리한다.

### AC-5. 예산 상태 경계값

- Given 예산 100 USD와 당월 비용 89.99 USD인 App, When `GET /apps` 또는 `GET /apps/operations`를 호출한다, Then `budget_status.status`는 `normal`이고 `usage_ratio`는 0.8999다.
- Given 예산 100 USD와 당월 비용 90.00 USD인 App, When 조회한다, Then `status`는 `at_risk`이고 `usage_ratio`는 0.9다.
- Given 예산 100 USD와 당월 비용 100.00 USD인 App, When 조회한다, Then `status`는 `at_risk`이고 실행 차단 표시는 표시하지 않는다.
- Given 예산 100 USD와 당월 비용 100.000001 USD인 App, When 조회한다, Then `status`는 `exceeded`이고 `/dashboard/mymodule`은 "실행 차단" 표시를 보여준다.
- Given `total_cost`가 NULL인 usage row만 있는 App, When 조회한다, Then 비용은 0으로 합산되어 `usage_ratio=0`, `status=normal`이다.
- Given KST 월 경계의 usage row가 있다, When KST 7월 기준 조회한다, Then KST 7월 1일 00:00:00 row는 포함하고 KST 8월 1일 00:00:00 row는 제외한다.

## Unit Tests

- `AppService.get_user_apps`
  - Given 활성 예산이 있는 App의 primary workflow, When App 목록을 조회하면, Then `AppResponse.budget_status`는 `usage_ratio`와 `status`만 포함한다.
  - Given 예산이 없거나 `workflow_id`가 null인 App, When App 목록을 조회하면, Then `budget_status`는 null이다.
  - Given primary workflow에는 예산이 없고 같은 `app_id`의 보조 workflow에 예산이 있는 App, When 목록을 조회하면, Then 보조 workflow 예산 상태를 `AppResponse.budget_status`로 붙이지 않는다.
  - Given 여러 App을 조회, When `budget_status`를 계산하면, Then primary workflow별 당월 비용은 grouped query로 계산하고 App별 개별 집계 쿼리를 반복하지 않는다.
  - Given 예산 수정/비활성화가 App 목록 조회와 경합한다, When service가 `budget_status`를 붙인다, Then 예외를 전파하지 않고 일관된 before/after 상태 또는 null 중 하나를 반환한다.
  - Given 경계 비용(89.99/90.00/100.00/100.000001, 예산 100), When `budget_status`를 계산하면, Then `normal`/`at_risk`/`at_risk`/`exceeded`를 반환한다.
- `AppService.list_app_operations`
  - Given 활성 예산이 있는 App의 primary workflow, When operations row를 생성하면, Then `row.app.budget_status`는 `GET /apps`와 같은 shape다.
  - Given App의 `workflow_id`가 null이고 같은 `app_id`의 보조 workflow에 예산이 있다, When operations row를 생성하면, Then `row.app.budget_status`는 null이다.
  - Given member 표면 응답, Then 예산 금액과 당월 비용 원문은 포함하지 않는다.
  - Given operations page/batch에 여러 App의 primary workflow가 포함된다, When rows를 생성하면, Then primary workflow id 기준 batch 단위 grouped query로 예산 상태를 계산한다.
  - Given KST 월초 직후(예: 2026-07-31 16:00 UTC = 2026-08-01 01:00 KST), When rows를 생성하면, Then 8월 KST 비용 기준으로 `budget_status`를 계산한다.

## API Tests

- `GET /api/v1/apps`
  - 활성 예산 workflow가 있는 App은 `budget_status.usage_ratio`와 `budget_status.status`를 반환한다.
  - 예산 미설정 App 또는 `workflow_id=null` App은 `budget_status=null`을 반환한다.
  - 같은 `app_id`의 과거/보조 workflow에 활성 예산이 있어도 primary workflow 예산이 아니면 `budget_status=null`을 반환한다.
  - 응답에는 `monthly_budget_usd`, `current_month_cost`가 포함되지 않는다.
  - 90%, 100%, 100% 초과 경계에서 `status`가 각각 `at_risk`, `at_risk`, `exceeded`로 반환된다.
- `GET /api/v1/apps/operations`
  - `/dashboard/mymodule` row의 `app.budget_status`가 활성 예산 상태를 반환한다.
  - 예산 미설정 row는 기존 운영 현황 필드를 유지하고 `app.budget_status=null`을 반환한다.
  - `row.app.workflow_id`가 null이면 같은 `app_id`의 보조 workflow 예산 상태를 노출하지 않고 `app.budget_status=null`을 반환한다.
  - 권한이 없는 App/Workflow는 기존 접근 정책대로 목록에서 제외되며, 예산 상태만으로 노출되지 않는다.
  - KST 월 경계 row 포함/제외 기준이 `GET /apps`와 동일하다.

## E2E Tests

- 빌더가 `/dashboard/mymodule`에 진입하면 예산 위험/초과 workflow row에 `BudgetStatusBadge`가 표시된다.
- 초과 상태 row는 실행 상태 영역에 "실행 차단"을 표시하지만, row 열기/조회 진입은 기존 권한 조건을 따른다.

## Permission Tests

- `budget_status`는 App/Workflow 읽기 권한을 통과한 row에만 붙는다. 권한 없는 workflow의 예산 상태는 응답에 포함하지 않는다.

## Concurrency Tests

- `GET /apps` 조회와 같은 workflow의 `PUT /admin/workflow-budgets/{workflow_id}`가 경합해도 `GET /apps`는 5xx를 반환하지 않는다. 응답은 수정 전 또는 수정 후 중 하나의 일관된 `budget_status`를 반환할 수 있다.
- `GET /apps/operations` 조회와 예산 비활성화가 경합하면 row 자체는 기존 App/Workflow 접근 정책대로 유지하고, 예산 상태는 수정 전 값 또는 null 중 하나로 반환한다.
- 동시에 여러 사용자가 `GET /apps/operations`를 호출해도 예산 조회는 read-only이며 budget/audit row를 생성하거나 갱신하지 않는다.

## Edge Cases

- 당월 비용이 없으면 활성 예산 workflow의 `usage_ratio`는 0이고 `status`는 `normal`이다.
- 비활성 예산은 `budget_status=null`로 취급한다.
- 예산 row는 활성화되어 있으나 관련 workflow가 응답 대상 App의 `workflow_id`와 연결되지 않으면 `budget_status=null`이다.
- 같은 `app_id`의 과거/보조 Workflow row에 활성 예산이 있어도 App의 primary `workflow_id`와 다르면 `budget_status`에는 반영하지 않는다.
- `monthly_budget_usd`가 0 이하인 비정상 row가 기존 데이터에 남아 있어도 member 표면에서는 `budget_status=null`로 취급한다.
- KST 월초 직후에도 `budget_status`는 현재 KST 달력 월 기준으로 계산한다.
