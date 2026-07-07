# Budget Alert Requirements

Status: Draft
Related Features: budget-management, admin-dashboard, workflow, organization, audit-tracing

## Purpose

워크플로우 월간 예산이 위험(`at_risk`) 또는 초과(`exceeded`) 상태로 진입할 때, 워크플로우 제작자와 조직 비용 관리자가 대시보드를 직접 열어보지 않아도 상태를 선제적으로 인지하도록 in-app 알림을 발송한다.

이 feature는 [budget-management](../budget-management/requirements.md)의 판정 로직(`WorkflowBudgetService.classify_budget_usage`)과 당월 비용 집계(`get_current_month_cost`)를 원천으로 재사용하고, 새 임계값·판정 규칙·예산 저장 구조를 도입하지 않는다. budget-management requirements.md Open Question("예산 임박(at_risk) 알림 발송은 이 feature 범위 밖, 필요해지면 후속 feature로 다룬다")을 승계하는 후속 feature다.

## 현재 상태 (전제)

- **예산 상태 판정은 이미 존재한다.** `apps/gateway/services/workflow_budget_service.py`의 `classify_budget_usage`가 사용률을 `normal`(90% 미만) / `at_risk`(90% 이상 100% 이하) / `exceeded`(100% 초과)로 분류한다. 당월 경계는 KST 달력 월이다 (BGT-REQ-011, BGT-REQ-012).
- **예산 상태는 이미 대시보드에 수동적으로 노출된다.** 관리자 비용 탭 요약 카드(`at_risk_count`/`exceeded_count`)와 workflow별 상태 배지, 내 워크플로우 목록의 `budget_status` 배지가 있다. 모두 사용자가 찾아가서 보는 pull 방식이다. 이 feature는 그 상태를 선제적으로 push하는 것이 목적이다.
- **알림 인프라는 파생형(derived)이다.** `notifications` 테이블이 없다. `NotificationService.list_notifications`는 조직 초대(`OrganizationMembership` INVITED)를 조회 시점에 계산해 내려준다. `GET /notifications`(목록) + `GET /notifications/stream`(SSE `notifications.changed` 신호 → 클라이언트 재fetch) 구조다. 이 feature는 여기에 영속 알림 기록을 처음으로 추가한다.
- **표시 표면은 사이드바 프로필 메뉴 안의 벨 오버레이 한 곳이다.** 상단 상시 벨이 아니라 `apps/client/app/features/dashboard/components/Sidebar.tsx`의 프로필 드롭다운 → "알림" → `NotificationOverlay`로 열린다. 안읽음 인디케이터(dot/카운트)가 없고, 오버레이는 현재 조직 초대 전용으로 하드코딩돼 있다.
- **run 비용은 실행 완료 시 확정된다.** `apps/log_system/tasks.py`의 `update_run_log_finish`(Celery task)가 `llm_usage_logs`를 집계해 run 비용을 확정한다. 비용은 워크플로우가 실행돼야만 증가한다.
- **외부 채널 발송 인프라(SMTP/이메일/Slack/Webhook)는 없다.** `egress_guard`만 존재한다.

## User Stories

- 제작자로서, 내가 만든 워크플로우가 예산 위험/초과에 도달하면 대시보드를 열어보지 않아도 알림으로 알고 즉시 확인하고 싶다.
- 조직 비용 관리자로서, 조직 내 워크플로우가 예산 위험/초과에 도달하면 알림으로 파악해 예산 조정이나 비용 최적화(PRD 시나리오 3) 조치를 시작하고 싶다.

## Scope

### Phase 1 (이 문서)

- in-app 벨 알림으로 `at_risk` / `exceeded` 상태 진입을 발송한다.
- 수신자: 워크플로우 제작자 + 조직 관리자(owner/manager) 전원.
- 발송된 알림은 사용자가 읽을 때까지 남고, 미확인 알림 존재를 안읽음 인디케이터로 표시한다.

### 비포함 (Phase 2 이후)

- 이메일 / Slack / Webhook 등 외부 채널 발송 (발송 인프라 부재, 별도 feature).
- 조직·팀·사용자 단위 예산 알림 (budget-management와 동일하게 1차 범위 밖).
- 사용자별 알림 구독/수신 설정 UI, 알림 음소거, 항목별 개별(선택) 읽음, 알림 전용 이력 페이지, 오래된 읽은 알림 자동 정리(TTL). (항목별 X 삭제는 Phase 1 포함, BGA-REQ-044.)

## Functional Requirements

### 트리거와 감지

- BGA-REQ-001: 알림 상태는 budget-management의 `classify_budget_usage` 결과(`at_risk`/`exceeded`)를 그대로 원천으로 쓴다. 이 feature는 별도 임계값이나 판정 규칙을 만들지 않는다.
- BGA-REQ-002: 활성 예산(`is_enabled=true`이고 `monthly_budget_usd > 0`)이 아닌 워크플로우는 알림 대상에서 제외한다 (BGT-REQ-010과 동일). 예산 미설정/비활성/0 이하 예산은 판정하지 않는다.
- BGA-REQ-003: 상태 감지는 이벤트 기반이다. 워크플로우 run 비용이 확정되는 시점(`update_run_log_finish`, `llm_usage_logs` 반영 이후)에 해당 workflow의 당월 상태를 재계산한다. 실행이 없으면 비용도 증가하지 않으므로 상태 상승도 발생하지 않는다. 재계산은 budget-management의 당월 비용 집계(`get_current_month_cost`)와 동일 기준(KST 월 경계, `Decimal`)을 쓴다.
- BGA-REQ-004: 감지·발송 로직은 log_system 실행 로그 처리 경로와 분리한다. `update_run_log_finish`는 예산 알림 평가 작업을 별도 Celery task로 enqueue하는 한 줄만 추가하고, 재계산·기록·발송 로직은 그 task(전용 모듈)에 둔다. 예산 알림 task의 실패나 재시도는 run 로그 저장 task의 성공/재시도에 영향을 주지 않는다.

### 임계 전이와 중복 방지

- BGA-REQ-010: 알림은 상태가 상향 전이될 때만 발송한다: `normal → at_risk`, `normal → exceeded`, `at_risk → exceeded`. 첫 실행에서 곧바로 100%를 초과하면 최고 상태인 `exceeded` 1건만 발송하고 `at_risk`를 따로 발송하지 않는다.
- BGA-REQ-011: 같은 `(workflow, 도달 임계, 당월)` 조합에 대해 중복 발송하지 않는다. 동일 상태가 유지되는 동안 워크플로우가 반복 실행되어도 재발송하지 않는다. 감지 task가 중복 실행되어도(재시도 포함) 마지막 알린 상태 기록으로 idempotent하게 처리한다.
- BGA-REQ-012: 월 경계(KST)가 바뀌면 당월 비용이 0으로 초기화되므로 전이 상태 기록도 새 달 기준으로 초기화된다. 새 달에 다시 `at_risk`/`exceeded`에 도달하면 재발송한다.
- BGA-REQ-013: 하향 전이(`exceeded → at_risk → normal`, 예산 상향이나 월 리셋으로 인한)는 알림을 발송하지 않는다. 전이 상태 기록(마지막 알린 상태)은 당월 내 단조 증가(high-water mark)이며 하향 전이가 이 기록을 낮추지 않는다. 따라서 같은 달에 임계 아래로 내려갔다 다시 올라와도 이미 알린 임계는 재발송되지 않는다 (BGA-REQ-011). 초기화는 월 경계 변경(BGA-REQ-012)에서만 일어난다.

### 수신자

- BGA-REQ-020: 대상 수신자는 (1) 워크플로우 제작자(`workflows.created_by`)와 (2) 워크플로우 소속 조직의 관리자 전원이다. 관리자는 `has_organization_manager_permission(db, user_id, organization_id)`이 true인 사용자(owner/manager)로 판정하며, 이는 예산 설정 API 접근 권한자(BGT-REQ-003)와 동일한 경계다.
- BGA-REQ-021: 제작자가 곧 관리자이면 동일 사건에 대해 1건으로 dedup한다. 한 사용자는 하나의 전이에 대해 최대 1개의 알림만 받는다.
- BGA-REQ-022: 비활성 사용자, 조직에서 탈퇴했거나 INVITED 상태로만 남은 멤버십은 수신자에서 제외한다. `created_by` 사용자가 더 이상 조직 구성원이 아니면 제작자 알림은 생략한다.

### 저장 (알림 기록 모델)

- BGA-REQ-030: 이 feature는 두 가지 영속 구조를 additive migration으로 추가한다. 기존 예산 저장 구조(`workflow_budget`)나 판정 로직은 변경하지 않는다.
  - **전이 상태 기록**: `(workflow, 당월)`별 마지막으로 알린 상태(last notified status). 상향 전이 감지와 중복 방지(BGA-REQ-010~012)의 원천이다.
  - **알림 항목 기록**: 발송된 알림을 수신자별로 저장하고, 사용자별 읽음 여부와 삭제(제거)를 지원한다. 벨 목록 표시와 안읽음 판정의 원천이다.
- BGA-REQ-031: 발송된 알림 항목은 사용자가 삭제하기 전까지 목록에 남는다(받은함 모델). 읽은 뒤에도 목록에서 사라지지 않고 흐리게 표시된 채 남는다. 발송 후 예산이 상향되거나 월이 바뀌어 워크플로우가 정상으로 돌아가도 자동으로 사라지지 않는다 (지나간 위험도 기록으로 유지). 목록에서 제거는 BGA-REQ-044의 사용자 삭제로만 이루어진다.
- BGA-REQ-032: 워크플로우 삭제 시 관련 전이 상태 기록과 알림 항목 기록도 함께 정리한다 (예산 row가 FK cascade로 삭제되는 것과 정합).

### 표시 (in-app)

- BGA-REQ-040: 기존 벨 오버레이(`NotificationOverlay`)에 `budget.at_risk` / `budget.exceeded` 알림 타입을 추가한다. 오버레이를 조직 초대 전용에서 `type`별 분기 렌더링으로 일반화한다. 벨 진입점 위치(사이드바 프로필 메뉴 내부)는 그대로 둔다.
- BGA-REQ-041: 예산 알림 항목은 워크플로우 이름, 상태(`at_risk`/`exceeded`), 사용률(%), 해당 워크플로우로 이동하는 링크를 포함한다. 조직 초대와 달리 수락/거절 같은 인라인 액션은 없다.
- BGA-REQ-042: 미확인(안읽음) 알림이 하나라도 있으면 사이드바 프로필/벨 진입점에 안읽음 인디케이터(dot)를 표시한다. 사용자가 오버레이를 열면 그 안의 예산 알림을 일괄 읽음 처리하고 인디케이터를 해소한다. 읽은 알림은 목록에서 사라지지 않고 흐리게 남는다(BGA-REQ-031). 항목별 선택 읽음은 다루지 않는다.
- BGA-REQ-043: 상태 전이 발송 시 수신자 채널로 `notifications.changed` SSE 신호를 발행해 열려 있는 클라이언트가 목록과 안읽음 표시를 갱신하도록 한다 (기존 `publish_notifications_changed` 재사용).
- BGA-REQ-044: 각 예산 알림 항목은 X로 사용자가 직접 삭제할 수 있다. 삭제는 수신자별이며 같은 전이로 발송된 다른 수신자의 항목에는 영향을 주지 않는다. 삭제는 벨 목록에서 제거만 하고 중복 방지 기록(BGA-REQ-011)을 되살리지 않으므로, 삭제해도 같은 달 같은 임계로 재발송되지 않는다.

### Audit / 보안

- BGA-REQ-050: 알림 발송은 사용자 행위가 아닌 시스템 파생 이벤트이므로 별도 canonical audit action을 만들지 않는다. 예산 초과로 인한 실행 차단은 기존대로 `policy.block`(BGT-REQ-041)으로 기록하며, 이 feature는 그 경로를 변경하지 않는다.
- BGA-REQ-051: 예산 금액과 당월 비용 집계값은 secret이 아니므로 관리자 표면 알림에 포함할 수 있으나, credential 원문·API key·token·raw payload·`encrypted_config` 값은 알림 본문, 로그, 알림 기록, SSE payload에 노출하지 않는다 (budget-management NFR-004 일관).
- BGA-REQ-052: member 표면(관리자가 아닌 제작자) 알림에는 예산 금액과 당월 비용 원문을 담지 않는다. 사용률(%)과 상태만 노출한다 (BGT-REQ-022와 동일 경계를 API payload 수준에서 강제).

## Policies And Edge Cases

- 발송은 상향 전이 시점을 기준으로 하고, 벨 목록은 발송된 알림 기록을 기준으로 한다(읽을 때까지 유지). 조회 시점의 현재 예산 상태를 다시 계산해 목록을 재구성하지 않는다.
- budget-management의 알려진 한계(동시 실행 overshoot, 가격 미산정 모델의 `total_cost=0.0`)는 알림에도 동일하게 적용된다. 비용 반영이 지연되면 알림도 지연될 수 있다 (수용).
- 관리자가 예산을 낮춰 즉시 `exceeded`가 되는 경우처럼 예산 수정으로 임계가 바뀌는 상황에서도, 다음 run 완료 시 재계산된 현재 상태의 상향 전이 기준으로 발송을 판단한다. 예산 수정 자체는 이 feature의 감지 트리거가 아니다(감지는 run 완료 시점).
- 관리자 수가 많은 조직에서 한 전이가 다수 수신자로 팬아웃될 수 있다. 발송은 조직 관리자 수에 비례하지만, 중복 방지(BGA-REQ-011)로 동일 전이의 반복 팬아웃은 막는다.
- LLM 노드 A/B 비교(cost-optimizer, BGT-REQ-032)로 발생한 비용도 당월 집계에 포함되므로 알림 상태에 반영된다. compare 실행 자체는 차단되지 않지만 그로 인한 비용은 위험/초과 판정에 기여한다.
- SSE 신호를 놓친 클라이언트(오프라인·재접속)는 다음 `GET /notifications` 조회 때 저장된 알림 기록으로 미확인 알림을 그대로 받는다. 신호는 즉시성 보조이고, 도달 보장은 저장된 기록이 한다.

## Open Questions

- **감지 트리거 확장**: 현재는 run 완료(`update_run_log_finish`)만 트리거다. 예산을 낮춰 즉시 초과되는 경우는 다음 run이 있어야 감지된다. 예산 수정 시점 감지를 추가할지는 후속 판단으로 남긴다.
- **벨 위치 승격**: 안읽음 가시성을 더 높이려면 사이드바 프로필 메뉴 내부 벨을 상단 상시 벨로 승격하는 안이 있으나, 이번 범위에서는 위치 유지 + 안읽음 dot로 한정한다.
- **외부 채널(이메일/Slack)** 도입 시점과 발송 인프라 선택. 오프라인 수신자 도달이 필요해지는 시점에 Phase 2 feature로 분리한다.
- **알림 보존/정리 정책**: 1차는 사용자 수동 삭제(BGA-REQ-044)가 기본이다. 삭제하지 않아 쌓이는 읽은 알림을 언제까지 보관할지(TTL/자동 정리)는 데이터 증가가 문제될 때 정한다.
