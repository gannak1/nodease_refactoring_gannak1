# Budget Management Component Spec

Status: Draft
Verified Against: dev @ d7e7b7a

새 화면을 만들지 않고 기존 화면 세 곳을 확장한다. 프론트의 예산 표시/차단은 UX 보조이며 최종 차단은 Gateway가 수행한다 (NFR-001).

## Screens

### `/dashboard/admin` — 비용 탭 (관리자 예산 설정, FR-051)

[admin-dashboard component_spec](../admin-dashboard/component_spec.md)의 비용 탭(`UsageTab`) 테이블을 확장한다.

| 영역 | 내용 | 노출 조건 |
| --- | --- | --- |
| 비용 탭 테이블 예산 컬럼 | workflow별 예산(USD), 당월 사용률, 상태 배지, 예산 설정 버튼 | organization owner/manager |
| 상단 요약 카드 | 기존 `AdminSummaryCards`의 예산 카드가 실제 `budget` 블록 데이터를 표시 | organization owner/manager |

- 데이터 원천: `GET /admin/usage/workflows`의 `budget` 블록, `GET /admin/summary`.
- 예산 컬럼: 활성 예산이 없으면(`budget` null) "미설정"과 예산 설정 버튼만 표시한다.
- 예산 설정 버튼 → `BudgetEditModal` 열림.

### `/dashboard` — 내 워크플로우 목록 (FR-052)

기존 workflow 목록(`apps/client/app/dashboard/page.tsx`, 원천 `GET /apps`)의 각 row를 확장한다.

- `budget_status`가 있으면 사용률(%)과 상태 배지(`BudgetStatusBadge`)를 표시한다. null이면 아무것도 표시하지 않는다 (기존 레이아웃 유지).
- `status`가 `exceeded`면 해당 row의 실행 진입(실행 버튼/링크)에 disabled 상태와 "월 예산 초과로 실행이 차단되었습니다" tooltip을 표시한다. 편집/조회 진입은 차단하지 않는다.
- member 표면이므로 예산 금액은 표시하지 않는다 (BGT-REQ-022). 사용률과 상태만 표시한다.

### Workflow 편집 화면 — 테스트 실행

- 테스트 실행/스트림 요청이 `429 budget.exceeded`로 실패하면 "월 예산 초과로 실행이 차단되었습니다" 안내(toast/배너)를 표시한다. 일반 실행 오류(500 계열)와 구분한다.
- 편집 화면 진입 시점의 사전 차단(버튼 disable)은 선택 사항이다. 최소 요구는 429 응답의 안내 처리다.

## Components

### BudgetEditModal (신규)

- 위치: 비용 탭 예산 설정 버튼에서 열리는 모달. 기존 모달/폼 패턴을 재사용한다.
- 입력: `monthly_budget_usd`(양수, USD, 소수점 2자리), `is_enabled` 토글.
- 초기값: `GET /admin/workflow-budgets/{workflow_id}` (404면 신규 설정 폼).
- 저장: `PUT /admin/workflow-budgets/{workflow_id}`. 성공 시 비용 탭 테이블과 요약 카드를 refetch한다.
- 검증: 0 이하/비숫자 입력은 제출 전에 막고, 서버 422 응답도 필드 오류로 표시한다.

### BudgetStatusBadge (신규, 공용)

- 입력: `status` (`normal` | `at_risk` | `exceeded`), 선택적으로 `usage_ratio`.
- 표시: `normal` 기본색, `at_risk` 경고색(위험), `exceeded` 오류색(초과). 사용률은 % 정수 반올림 표시 (표시 직전 1회 반올림, 판정은 서버 값).
- 관리자 비용 탭과 내 워크플로우 목록에서 공용으로 사용한다.

### UsageTab 예산 컬럼 확장

- 기존 비용 탭 테이블에 컬럼 추가: 예산(USD, 소수점 2자리), 사용률(%), 상태(`BudgetStatusBadge`), 예산 설정 버튼.
- `budget` null인 row는 "미설정" 텍스트와 설정 버튼만 표시한다.

## States And Error Handling

- 로딩/빈 목록/오류 상태는 각 화면의 기존 패턴을 따른다.
- `budget`/`budget_status` null은 오류가 아니라 "예산 미설정" 정상 상태다.
- 예산 설정 API의 403(owner/manager 아님)은 안내 문구로 처리한다. UI 노출 제어(비용 탭 자체가 owner/manager 전용)가 선행하지만 서버 응답 처리도 유지한다.
- 429 `budget.exceeded` 처리 후에도 다른 실행 오류 처리(기존 timeout/500 처리)는 그대로 유지한다.

## 갱신이 필요한 기존 문서

- [admin-dashboard component_spec](../admin-dashboard/component_spec.md): `AdminSummaryCards`의 예산 카드 "확정 종속" 문구를 실데이터 기준으로 갱신, 비용 탭 예산 컬럼 반영.
- [app-management component_spec](../app-management/component_spec.md): 내 워크플로우 목록 row 확장 반영 (구현 시 확인).
