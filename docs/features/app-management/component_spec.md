# App Management Component Spec

Status: Draft
Verified Against: feature/mba-132 @ a843ec7

## Screens

### `/dashboard/mymodule` — 내 모듈 운영 현황

내가 접근할 수 있는 App/Workflow의 권한, 배포 상태, 최근 실행 상태를 표시한다. 데이터 원천은 `GET /apps/operations`다.

Budget Management 확장:

- row의 `app.budget_status`가 있으면 모듈명/설명 아래에 `BudgetStatusBadge`를 표시한다.
- `budget_status.status`가 `exceeded`면 실행 상태 영역에 "실행 차단" 표시를 추가하고, title/tooltip 문구는 "월 예산 초과로 실행이 차단되었습니다"를 사용한다.
- `budget_status`가 null이면 기존 row 레이아웃을 유지하고 예산 관련 텍스트를 표시하지 않는다.
- member 표면이므로 예산 금액과 당월 비용 원문은 표시하지 않는다.
- 현재 화면의 "열기"는 조회/편집 진입이므로 예산 초과 상태에서도 차단하지 않는다. 실제 실행 차단은 Gateway 실행 경로와 Workflow 편집 화면의 429 처리에서 보장한다.

## Components

- `BudgetStatusBadge`: Budget Management feature의 공용 배지를 재사용한다.

## States

- 예산 미설정(`budget_status=null`)은 오류가 아니라 정상 상태다.
- `exceeded` 표시는 UX 보조이며, 최종 보안/비용 차단 판단은 Gateway가 수행한다.

## Interactions

- 모듈 row의 열기/앱 설정/배포 상태 변경 동작은 기존 권한 조건을 따른다.
- 예산 상태 표시는 이 상호작용 조건을 바꾸지 않는다.

## Accessibility

- 예산 초과 상태는 색상뿐 아니라 "실행 차단" 텍스트로 표시한다.
- 차단 이유는 title/tooltip으로 제공한다.
