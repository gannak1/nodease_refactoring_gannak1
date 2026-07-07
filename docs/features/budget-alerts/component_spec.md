# Budget Alert Component Spec

Status: Draft
Verified Against: TBD

새 화면을 만들지 않고 기존 벨 알림 표면 한 곳(사이드바 프로필 메뉴 → 알림 오버레이)을 확장한다. 초대 전용이던 오버레이를 `type`별 분기 렌더링으로 일반화하고, 예산 알림 항목과 안읽음 인디케이터를 추가한다. 프론트 표시는 UX 보조이며, 노출 경계(금액 리댁션)의 최종 판단은 Gateway가 수행한다 (BGA-REQ-052).

## Screens

### 사이드바 벨 진입점 (`Sidebar`)

`apps/client/app/features/dashboard/components/Sidebar.tsx`의 프로필 드롭다운 → "알림" 진입점과 오버레이 토글을 그대로 유지한다(위치 승격 없음, BGA-REQ-042). 여기에 다음을 추가한다.

| 영역 | 변경 |
| --- | --- |
| 프로필/벨 진입점 | 안읽음 인디케이터(dot) 추가. **초대 대기 OR 안읽은 예산 알림**이 하나라도 있으면 표시 |
| 알림 상태 | 기존 초대 목록에 더해 예산 알림 목록(`GET /notifications/budget`)을 함께 fetch·보유 |

- 안읽음 dot 조건: `invitations.length > 0 || budgetAlerts.some((a) => !a.read)`.
- 오버레이가 열리면 `POST /notifications/budget/read`를 1회 호출해 예산 알림을 일괄 읽음 처리한다. 초대는 읽음 개념이 없으므로 dot 기여는 수락/거절 시점에만 사라진다 (BGA-REQ-042).

### 알림 오버레이 (`NotificationOverlay`)

`apps/client/app/features/notifications/components/NotificationOverlay.tsx`를 초대 전용에서 다종 알림 렌더러로 일반화한다.

- 초대와 예산 알림을 **발생 시각 기준 최신순 단일 목록**으로 섞어 표시한다. 항목마다 `type`에 따라 다르게 렌더링한다 (BGA-REQ-040).
  - `organization.invitation`: 기존 렌더링 유지(조직명, 권한 라벨, 수락/거절 버튼).
  - `budget.at_risk` / `budget.exceeded`: 아래 `BudgetAlertItem`.
- 로딩/빈/오류 상태는 두 소스를 합쳐 처리하고, 둘 다 비면 기존 문구("새 알림이 없습니다.")를 유지한다.

## Components

### 안읽음 인디케이터 (Sidebar, 신규)

- 프로필/벨 진입점에 작은 dot을 표시한다. 카운트 숫자는 두지 않는다(dot만).
- 표시 조건은 위 Screens의 dot 조건과 같다. 오버레이 열림 → 예산 읽음 처리 후 예산 기여가 사라지고, 초대가 남아 있으면 dot은 유지된다.

### NotificationOverlay 일반화

- props를 초대 배열 전용에서 초대 + 예산 알림을 함께 받도록 확장한다. 항목 렌더링을 `type` 스위치로 분기한다.
- 정렬은 `created_at`(예산)과 `created_at`/`invited_at`(초대)을 합친 최신순.
- 기존 초대 액션(`acceptInvitation`/`declineInvitation`) 경로는 변경하지 않는다.

### BudgetAlertItem (신규)

예산 알림 한 건의 렌더링. 조직 초대와 달리 수락/거절 같은 인라인 액션은 없고, 이동 링크와 삭제(X)만 있다 (BGA-REQ-041, 044).

| 요소 | 내용 |
| --- | --- |
| 워크플로우 이름 | `workflow_name` |
| 상태 배지 | `BudgetStatusBadge`(`status`, `usage_ratio`) 재사용 |
| 사용률 | % 정수 반올림 표시(표시 직전 1회 반올림, 판정은 서버 값) |
| 금액 줄 (관리자만) | 응답에 `monthly_budget_usd`/`current_month_cost`가 있을 때만 `예산 / 당월 비용` 보조 줄 표시. 없으면(member 표면) 생략 (BGA-REQ-052) |
| 발생 시각 | `created_at` |
| 이동 | 항목 클릭 시 역할별 이동 (아래 Interactions) |
| 삭제 | 우상단 X 버튼 → `DELETE /notifications/budget/{id}` 후 목록에서 즉시 제거(낙관적) |

- 금액 줄 노출은 응답 필드 유무로 판정한다. 프론트가 별도 권한 계산을 하지 않고, 서버 리댁션 결과(필드 포함 여부)를 그대로 따른다.

### BudgetStatusBadge 재사용

- budget-management의 공용 배지(`apps/client/app/features/budget/components/BudgetStatusBadge.tsx`)를 그대로 사용한다. `at_risk` 경고색, `exceeded` 오류색. 예산 알림은 `normal`을 표시하지 않는다.

## Interactions

- **읽음**: 오버레이 열림 → `POST /notifications/budget/read` 1회. 읽은 예산 항목은 목록에서 사라지지 않고 흐리게(de-emphasized) 남는다 (BGA-REQ-031, 042). 안읽음 항목은 강조.
- **이동(역할별, BGA-REQ-041)**:
  - 관리자 수신 항목 → `/dashboard/admin` 비용 탭(예산 조정/비용 확인). 특정 워크플로우로 필터된 딥링크는 지원 시 적용하고, 1차는 비용 탭 랜딩까지 허용한다.
  - 제작자(member) 수신 항목 → `/modules/{workflow_id}`(워크플로우 화면, 비용 최적화 진입). 관리자 전용 화면으로 보내지 않는다.
  - 이동 대상 판정은 금액 줄과 동일하게 응답의 관리자 필드 유무로 구분한다(관리자 필드 있으면 관리자 대상).
- **삭제**: X → `DELETE /notifications/budget/{id}`. 성공 시 해당 항목만 제거한다. 같은 전이의 다른 수신자 항목·중복 방지 기록에는 영향이 없다(재알림 유발 안 함, BGA-REQ-044).
- **실시간 갱신**: 기존 SSE(`notifications.changed`) 수신 시 초대·예산 두 목록을 함께 refetch하고 dot을 재계산한다 (BGA-REQ-043). 새 EventSource를 추가하지 않는다.

## States And Error Handling

- 로딩/빈 목록/오류는 각 화면의 기존 패턴을 따른다. 두 소스 중 하나만 오류일 때의 처리(부분 실패)는 기존 오류 UI를 재사용하되, 성공한 목록은 표시한다.
- 예산 알림이 0건이고 초대만 있으면 기존 초대 UX와 동일하게 보인다(예산 관련 표시 없음).
- `POST read`/`DELETE` 실패는 낙관적 갱신을 되돌리고 기존 toast 오류 패턴으로 안내한다. dot 상태도 재계산한다.
- 금액 줄은 응답에 필드가 없으면 렌더링하지 않는다. 프론트에서 금액을 유추·계산하지 않는다.

## 관련 기존 문서

- [budget-management component_spec](../budget-management/component_spec.md): `BudgetStatusBadge`와 대시보드 예산 표시 정의. 예산 알림은 같은 배지를 재사용한다.
- [organization component_spec](../organization/component_spec.md): 조직 초대 알림 렌더링. 오버레이 일반화 시 초대 경로를 그대로 유지한다.
