# Budget Alert Test Cases

Status: Draft
Verified Against: TBD

[requirements.md](requirements.md)의 BGA-REQ와 [api_spec.md](api_spec.md), [component_spec.md](component_spec.md)를 검증한다. 예산 판정/집계 자체의 경계값 검증은 [budget-management test_cases](../budget-management/test_cases.md)가 담당하고, 여기서는 그 판정을 **전이·발송·수신·표시·삭제**로 옮기는 동작과 동시성을 다룬다.

## Acceptance Criteria

### AC-1. 감지와 분리 (BGA-REQ-003, 004)

- Given 활성 예산 workflow의 run이 완료되어 비용이 확정된다, When `update_run_log_finish`가 처리되면, Then 예산 알림 평가 task가 정확히 1회 enqueue되고 run 로그 저장 자체는 기존과 동일하게 성공한다.
- Given 예산 알림 평가 task가 예외로 실패한다, When run 로그 저장 task를 확인하면, Then run 로그 저장은 성공/커밋된 상태이며 예산 task 실패가 저장 task의 성공/재시도에 영향을 주지 않는다.
- Given 실행이 한 번도 없는 활성 예산 workflow, When 시간이 지나면, Then 비용이 증가하지 않으므로 어떤 알림도 발송되지 않는다(감지 트리거는 run 완료뿐).
- Given 활성 예산이 아닌(비활성/미설정/0 이하) workflow의 run 완료, When 평가하면, Then 상태 재계산과 발송을 건너뛴다 (BGA-REQ-002).

### AC-2. 상향 전이 발송 (BGA-REQ-010)

- Given `last_notified_status`가 없음(정상), When run 완료 후 상태가 `at_risk`가 되면, Then `budget.at_risk` 알림 1건이 발송되고 전이 상태 기록이 `at_risk`로 갱신된다.
- Given `last_notified_status=at_risk`, When 상태가 `exceeded`로 오르면, Then `budget.exceeded` 알림 1건이 발송되고 기록이 `exceeded`로 갱신된다.
- Given `last_notified_status`가 없음, When 첫 run에서 곧바로 `exceeded`(100% 초과)가 되면, Then `budget.exceeded` **1건만** 발송되고 `at_risk`는 따로 발송되지 않는다. 기록은 `exceeded`다.
- Given 방금 발송한 전이, When 알림 항목을 확인하면, Then 표시값(`usage_ratio`, 관리자 대상 `monthly_budget_usd`/`current_month_cost`)이 발생 시점 스냅샷으로 저장되어 있다 (BGA-REQ-031).

### AC-3. 중복 방지·월 리셋·하향 (BGA-REQ-011~013)

- Given `last_notified_status=at_risk`, When 같은 달에 `at_risk` 상태로 run이 반복 완료되면, Then 추가 알림이 발송되지 않는다.
- Given `last_notified_status=exceeded`, When 같은 달에 `exceeded`가 유지되면, Then 추가 알림이 발송되지 않는다.
- Given 전월 `exceeded`였던 workflow, When 월이 바뀌어(KST) 당월 비용 0에서 다시 `at_risk`에 도달하면, Then 새 달 기준으로 `budget.at_risk`가 다시 발송된다.
- Given `last_notified_status=exceeded`, When 예산 상향/월 리셋으로 상태가 `at_risk`나 `normal`로 내려가면, Then 어떤 알림도 발송되지 않는다(하향 무발송).

### AC-4. 수신자 (BGA-REQ-020~022)

- Given 제작자 U0와 조직 관리자 U1, U2, When 한 전이가 발생하면, Then U0, U1, U2 각각에게 알림 항목이 1건씩 생성된다.
- Given 제작자가 곧 조직 관리자인 경우(U0=U1), When 전이가 발생하면, Then 그 사용자에게는 1건만 생성된다(중복 제거).
- Given INVITED 상태로만 남았거나 removed/suspended된 멤버십, When 수신자를 산출하면, Then 그 사용자는 수신자에서 제외된다.
- Given 제작자가 더 이상 조직 구성원이 아님, When 전이가 발생하면, Then 제작자 알림은 생략되고 관리자 알림만 생성된다.

### AC-5. 목록 조회와 리댁션 (BGA-REQ-052, api_spec)

- Given 사용자 U가 관리자인 조직 항목, When `GET /notifications/budget`를 호출하면, Then 그 항목에 `monthly_budget_usd`/`current_month_cost`가 포함된다.
- Given 사용자 U가 관리자가 아닌 제작자로 받은 항목, When 목록을 조회하면, Then 그 항목에는 금액 두 필드가 없고 `usage_ratio`/`status`만 포함된다.
- Given U가 A조직 관리자·B조직 제작자로 각각 받은 항목, When 목록을 조회하면, Then A 항목엔 금액 포함, B 항목엔 금액 제외로 항목별로 다르게 반환된다.
- Given 발송 시 관리자였으나 조회 시점에 관리자 권한이 없어진 U, When 목록을 조회하면, Then 그 항목의 금액 필드는 노출되지 않는다(조회 시점 권한 기준).
- Given 다른 사용자의 알림, When U가 목록을 조회하면, Then 반환되지 않는다(본인 수신 항목만).
- Given 모든 알림 응답, Then credential 원문, API key, token, raw payload 계열 필드가 포함되지 않는다 (BGA-REQ-051).

### AC-6. 받은함·읽음·삭제 (BGA-REQ-031, 042, 044, api_spec)

- Given 안읽음/읽음 항목이 섞여 있고 삭제된 항목이 있다, When `GET /notifications/budget`를 호출하면, Then 삭제되지 않은 항목(안읽음+읽음)이 모두 최신순으로 반환되고 각 항목의 `read`가 정확하다.
- Given 안읽은 예산 알림 3건, When `POST /notifications/budget/read`를 호출하면, Then 3건이 읽음 처리되고 `{updated:3}`을 반환하며 항목은 목록에서 사라지지 않는다.
- Given 이미 모두 읽음 상태, When `POST /notifications/budget/read`를 다시 호출하면, Then `{updated:0}`으로 정상 응답한다(no-op).
- Given 사용자 U의 알림 항목, When `DELETE /notifications/budget/{id}`를 호출하면, Then `204`로 그 항목만 제거되고, 같은 전이로 발송된 다른 수신자의 항목은 남는다.
- Given 항목을 삭제한 뒤 같은 달 같은 임계 상태가 유지된다, When 이후 run이 완료되면, Then 삭제는 중복 방지 기록을 되살리지 않으므로 재발송되지 않는다.
- Given 존재하지 않거나 본인 소유가 아닌 `alert_id`, When 삭제를 호출하면, Then `404 resource.not_found`로 숨긴다.

### AC-7. 표시·안읽음 dot·이동 (component_spec)

- Given 초대와 예산 알림이 함께 있다, When 벨 오버레이를 열면, Then 발생 시각 최신순 단일 목록으로 섞여 표시되고 각 항목이 type에 맞게 렌더링된다.
- Given 대기 중 초대가 있거나 안읽은 예산 알림이 있다, When 사이드바를 보면, Then 안읽음 dot이 표시된다.
- Given 안읽은 예산 알림과 대기 중 초대가 함께 있다, When 오버레이를 열면, Then 예산 알림은 읽음 처리되어 dot 기여가 사라지지만 초대가 남아 dot은 유지된다.
- Given 관리자로 받은 예산 알림, When 항목을 클릭하면, Then `/dashboard/admin` 비용 탭으로 이동한다.
- Given 제작자(member)로 받은 예산 알림, When 항목을 클릭하면, Then `/modules/{workflow_id}`로 이동하고 관리자 전용 화면으로 보내지 않는다.
- Given SSE `notifications.changed` 수신, When 클라이언트가 처리하면, Then 초대·예산 두 목록을 함께 refetch하고 dot을 재계산한다(새 EventSource 없음).

## Unit Tests

Gateway service/helper, log_system task, shared schema 대상 (기존 pytest 패턴). 함수명은 구현 시 확정하되 아래 케이스를 커버해야 한다.

### 전이 판정 `decide_alert_transition(last_status, new_status)`

- `None → at_risk` → 발송(threshold=at_risk).
- `None → exceeded` → 발송(threshold=exceeded), at_risk 미발송.
- `at_risk → exceeded` → 발송(threshold=exceeded).
- `at_risk → at_risk`, `exceeded → exceeded` → 미발송.
- `exceeded → at_risk`, `at_risk → normal`, `exceeded → normal` → 미발송(하향).
- `normal → normal` → 미발송.
- 판정은 순수 함수로, DB/시간 의존 없이 입력만으로 결정된다.

### 발송 파이프라인 `evaluate_budget_alert(workflow_id, now)`

- 활성 예산 아님 → 조기 반환, 집계/발송 없음.
- 활성 예산 + 상태 재계산은 budget-management `get_current_month_cost`/`classify_budget_usage`를 재사용한다(중복 판정 로직 없음).
- 상향 전이 → 전이 상태 기록 upsert + 알림 이벤트 생성 + 수신자별 항목 생성 + 수신자 채널 `publish_notifications_changed`.
- 스냅샷 저장: `usage_ratio`, `monthly_budget_usd`, `current_month_cost`가 발생 시점 값으로 항목/이벤트에 기록된다.
- 집계 예외 발생 시 예산 task만 실패하고(재시도 대상), run 로그 저장 경로와 분리된다.
- 기준 시각(`now`)을 주입받아 월 경계·월 키를 결정한다(월말/월초 테스트 가능).

### 수신자 산출 `resolve_alert_recipients(workflow)`

- 제작자(`created_by`) + `has_organization_manager_permission`이 true인 조직 구성원 전원.
- 제작자==관리자 → 1건으로 dedup.
- INVITED/suspended/removed 멤버십, 비활성 사용자 → 제외.
- 제작자가 조직 비구성원 → 제작자 제외, 관리자만.
- 관리자 0명 + 제작자만 있는 경우 → 제작자 1건.

### 리댁션 `serialize_alert_item(item, viewer)`

- viewer가 항목 조직의 관리자 → 금액 필드 포함.
- viewer가 제작자(member) → 금액 필드 제외, `usage_ratio`/`status`만.
- 항목마다 viewer의 그 조직 관리자 여부로 독립 판정(한 응답에 혼재 가능).
- 금액 필드 외 secret/credential/raw payload 계열 필드 부재.

### 목록/읽음/삭제 service

- `list_budget_alerts(user)` — 본인 수신 + 미삭제만, `created_at` 내림차순, 항목별 리댁션 적용.
- `mark_budget_alerts_read(user)` — 본인 안읽음만 읽음 전환, 전환 건수 반환, 이미 읽음이면 0(idempotent), 항목 제거 없음.
- `delete_budget_alert(user, alert_id)` — 본인 소유 항목만 hard delete, 타인/부재/이미삭제 → 404 신호, 전이 상태 기록 불변(재알림 유발 없음).

### API endpoint 연결

- `GET /notifications/budget` — 인증 필요, `X-Organization-Id` 미요구, 관리자/member 응답 shape 차이.
- `POST /notifications/budget/read` — 본문 없음, `{updated:int}` 반환, 재호출 idempotent.
- `DELETE /notifications/budget/{alert_id}` — `204`, 비UUID `422`, 타인/부재 `404`.
- 기존 `GET /notifications`(초대), `GET /notifications/stream`(SSE) 응답 계약이 변경되지 않는다(회귀).

### 스키마 `BudgetAlertItemResponse`

- 관리자 shape: `id,type,workflow_id,workflow_name,organization_id,status,usage_ratio,monthly_budget_usd,current_month_cost,read,created_at`.
- member shape: 금액 두 필드 부재.
- `type`은 `budget.at_risk`/`budget.exceeded`, `status`와 대응. `status`는 `normal` 불가.

## Concurrency Tests

동시성은 이 feature의 핵심 리스크다(팬아웃 + 재시도 + 다중 run). 아래는 "정확히 1건", "5xx 없음", "중복 없음"을 검증한다.

### 전이 중복 방지 (핵심)

- Given 같은 workflow의 두 run이 거의 동시에 완료되어 두 평가 task가 각각 상태를 `at_risk`로 계산한다(둘 다 아직 전이 기록을 못 봄), When 둘이 경합하면, Then `(workflow, at_risk, 당월)` 알림은 **정확히 1건만** 발송된다. 전이 상태 기록 갱신은 조건부 갱신/유니크 제약으로 한 쪽만 승자가 되어야 한다.
- Given `at_risk`에서 두 run이 동시에 `exceeded`로 올린다, When 두 평가가 경합하면, Then `budget.exceeded`는 정확히 1건만 발송된다.
- Given 평가 task가 at-least-once로 중복 전달되거나 재시도된다, When 같은 전이를 두 번 처리하면, Then 알림 이벤트/수신자 항목이 중복 생성되지 않는다(멱등).

### 팬아웃 멱등성

- Given 이벤트 생성 후 수신자 항목 일부만 만들고 task가 재시도된다, When 재실행되면, Then 이미 만든 수신자 항목은 중복되지 않고(예: `UNIQUE(alert_id, user_id)`) 누락분만 채워진다.
- Given 한 전이의 수신자가 N명, When 발송하면, Then 각 수신자당 항목 1건, 총 N건이며 재시도로 늘어나지 않는다.

### 월 경계 경합

- Given KST 월말 23:59:59와 월초 00:00:01에 두 run이 완료된다, When 각각 평가하면, Then 각자 자신의 KST 당월 키로 집계·전이 판정하며, 서로 다른 달의 전이가 상대 달의 중복 방지 기록에 의해 억제되지 않는다.
- Given 전월 `exceeded` 기록이 있는 workflow, When 당월 첫 `at_risk` 전이가 발생하면, Then 당월 기록이 없으므로 정상 발송된다(전월 기록이 당월 발송을 막지 않음).

### 읽음/삭제 경합

- Given 사용자가 오버레이를 여는 순간(`POST read`)과 동시에 새 알림이 SSE로 도착한다, When 둘이 겹치면, Then read는 그 시점 안읽음만 읽음 처리하고 새로 도착한 알림은 안읽음으로 남는다(5xx 없음).
- Given 같은 항목에 대한 두 번의 `DELETE`(더블클릭), When 동시에 도착하면, Then 한 요청은 `204`, 다른 요청은 `404`이며 5xx가 발생하지 않는다.
- Given `POST read`와 `DELETE`가 같은 항목에 동시에 도착한다, When 겹치면, Then 최종 상태는 삭제(제거)이거나 읽음 중 하나로 일관되며 5xx가 없다.

### 예산 변경·권한 변경 경합

- Given 평가 task 실행 중 관리자가 예산을 비활성화한다, When 겹치면, Then 결과는 발송/무발송 중 하나로 일관되고 5xx가 없다. 비활성으로 확정되면 발송하지 않는다.
- Given 평가 task 실행 중 관리자가 예산을 낮춰 임계가 바뀐다, When 겹치면, Then 재계산은 변경 전/후 어느 한 스냅샷 기준으로 일관되게 판정된다.
- Given 팬아웃 도중 관리자 한 명이 추가/제거된다, When 겹치면, Then 수신자는 발송 시점 스냅샷 기준이며(추가/제거가 소급되지 않아도 됨) 5xx가 없다.

### 워크플로우 삭제 경합

- Given workflow 삭제로 예산/전이 기록/알림 항목이 cascade 삭제되는 중 평가 task 또는 `GET /notifications/budget`가 실행된다, When 겹치면, Then 5xx 없이 완료되고, 삭제된 workflow에 대한 새 알림은 생성되지 않는다.

## Boundary Cases

경계값·극단 상태에서의 발송/무발송과 응답을 검증한다. 판정 자체의 경계값(89.99/90.00/100.00/100.000001)은 budget-management가 다루므로, 여기서는 그 경계가 **전이 발송**과 **표시/목록**으로 옮겨질 때의 동작에 집중한다.

### 임계 경계에서의 발송

- Given `normal`(89.99%)에서 run 완료로 정확히 90.00%가 된다, When 평가하면, Then `at_risk` 전이로 발송된다(90.00%는 at_risk).
- Given `normal`에서 정확히 100.00%가 된다, When 평가하면, Then `at_risk` **1건만** 발송되고 `exceeded`는 발송되지 않는다(100.00%는 초과 아님).
- Given `normal`에서 100.000001%가 된다, When 평가하면, Then `exceeded`가 발송된다(반올림 전 값 기준).
- Given `at_risk`(정확히 100.00%)에서 run 완료로 100.000001%가 된다, When 평가하면, Then `at_risk→exceeded`로 `exceeded`가 발송된다.
- Given run 완료 후에도 89.99%(90% 미만)이다, When 평가하면, Then `normal`이라 어떤 알림도 발송되지 않는다.

### 표시 반올림 경계

- Given 사용률 0.895(pre-round, `normal`), When 목록/배지를 표시하면, Then 표시상 "90%"로 반올림되어도 상태는 `normal`이고 알림은 존재하지 않는다(표시 반올림이 발송을 유발하지 않음, 판정은 서버 pre-round 값).
- Given 사용률 0.9049와 0.9050, When 표시하면, Then 각각 "90%"/"91%"로 표시 직전 1회 반올림되지만 상태 판정에는 영향이 없다.

### 전이 기록 경계 (당월 단조성, BGA-REQ-013)

- Given 당월 기록이 `at_risk`, When 같은 달에 비용이 90% 미만으로 내려갔다가 다시 90% 이상으로 오른다, Then 기록은 하향으로 낮아지지 않으므로(high-water mark) `at_risk`가 재발송되지 않는다.
- Given 당월 기록이 `exceeded`, When 같은 달에 at_risk로 내려갔다가 다시 exceeded로 오른다, Then `exceeded`는 재발송되지 않는다.
- Given 당월 기록이 `at_risk`, When 월이 바뀌어 기록이 초기화된 뒤 다시 at_risk에 도달한다, Then 새 달 기준으로 재발송된다.

### 월 경계 정각 (KST)

- Given run이 KST 당월 시작 정각(예: 7/1 00:00:00 KST = 6/30 15:00:00 UTC)에 완료된다, When 평가하면, Then 그 비용은 당월(7월) 집계에 포함되고 전이 판정·기록 키는 7월이다.
- Given run이 월말 마지막 순간(KST 7/31 23:59:59)에 완료된다, When 평가하면, Then 7월 집계·7월 키로 판정되고 8월로 넘어가지 않는다.

### 수신자 경계

- Given 조직 관리자가 0명이고 제작자만 있다, When 전이가 발생하면, Then 제작자 1건만 생성된다.
- Given 제작자가 유일한 관리자다, When 발송하면, Then dedup으로 1건만 생성된다.
- Given 관리자가 다수(예: 50명) + 제작자, When 전이가 발생하면, Then 각 1건씩 생성되고 재시도로 개수가 늘지 않는다.

### 목록/읽음/삭제 경계

- Given 알림이 하나도 없다, When `GET /notifications/budget`를 호출하면, Then `{items: []}`이고 예산발 dot 기여가 없다.
- Given 안읽음이 0건, When `POST /notifications/budget/read`를 호출하면, Then `{updated: 0}`(no-op)이다.
- Given 모든 예산 알림이 읽음 상태다, When 목록을 조회하면, Then 항목은 여전히 반환되고(받은함) 예산발 dot 기여는 없다.
- Given 목록에 예산 항목이 1건 남았다, When 그 항목을 삭제하면, Then 예산 항목은 0이 되고 예산발 dot 기여가 사라진다(초대가 없으면 dot off).

### 수치 극단

- Given 예산이 `NUMERIC(12,2)` 최대값 9999999999.99이고 당월 비용이 그 근처다, When 사용률을 계산하면, Then 오버플로 없이 정확히 판정된다(Decimal).
- Given 당월 비용이 정확히 0이다, When 평가하면, Then `normal`이라 발송되지 않는다.
- Given 초소액 예산 0.01과 비용 0.009(90%)/0.011(110%), When 판정하면, Then 각각 `at_risk`/`exceeded`로 Decimal 정밀도에서 정확히 갈린다.

## Client Tests

Vitest 기준.

- `NotificationOverlay` — 초대+예산 혼합 목록을 최신순으로 렌더링, type별 분기(초대=수락/거절, 예산=`BudgetAlertItem`).
- `BudgetAlertItem` — 이름/상태 배지(`BudgetStatusBadge`)/사용률% 반올림/발생시각 표시, 관리자 응답(금액 필드 있음)이면 금액 줄 표시·member 응답이면 미표시, X 버튼 렌더.
- 안읽음 dot — `초대 있음 || 안읽은 예산 있음`이면 표시, 오버레이 열림+읽음 후 예산 기여 제거되지만 대기 초대 있으면 유지.
- 읽음 트리거 — 오버레이 열릴 때 `POST /notifications/budget/read` 1회 호출.
- X 삭제 — 낙관적 제거, 실패 시 롤백 + 오류 안내, dot 재계산.
- 역할별 이동 — 관리자 항목 클릭 → `/dashboard/admin`, member 항목 클릭 → `/modules/{workflow_id}`(응답의 관리자 필드 유무로 구분).
- SSE — `notifications.changed` 수신 시 초대·예산 두 목록 refetch.
- 회귀 — 예산 알림 0건이면 기존 초대 UX 그대로.

## E2E / 시나리오 연결

- 제작자 U0가 만든 활성 예산 workflow가 run으로 `at_risk`에 진입 → U0와 조직 관리자 U1에게 알림. U1(관리자) 벨엔 금액 줄 포함, U0(member) 벨엔 사용률/상태만. 이어 `exceeded`로 오르면 각자 1건 더. U0가 자기 벨에서 X로 삭제해도 U1 벨엔 그대로 남고, 삭제로 재발송되지 않음. 다음 달 다시 `at_risk` 도달 시 재발송.
- PRD 시나리오 3 연결: 초과 알림을 받은 제작자가 `/modules/{id}`의 cost-optimizer로 이동해 비용 최적화(compare는 초과에도 실행 가능, BGT-REQ-032)를 시작한다.
