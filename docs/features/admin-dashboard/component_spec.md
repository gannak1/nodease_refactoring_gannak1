# Admin Dashboard Component Spec

Status: Draft
Verified Against: feature/mba-129 @ 4cceb58

기존 관리자 페이지 `/dashboard/admin`(`apps/client/app/dashboard/admin/page.tsx`)을 확장한다. 이 페이지는 이미 탭 구조(구성원/팀/권한/credential/knowledge/감사 로그/조직)와 공용 컴포넌트(`DashboardPageHeader`, `DashboardPanel`, `DashboardSummaryCard`)를 갖고 있다. 이 feature는 새 화면을 만들지 않고 다음을 추가/전환한다.

- 감사 로그 탭을 본인 이력(`/users/me/audit-logs`) 임시 구현에서 조직 단위 검색(`GET /admin/audit-logs`, FR-011)으로 전환
- `권한 신청` 탭 신설 (FR-014)
- `비용` 탭 신설 (FR-012)
- 상단 요약 카드 신설 (FR-015)

신청자 측 차단 팝업과 권한 신청 제출 폼(PRD FR-041)은 [organization](../organization/component_spec.md) 범위(`내 워크플로우` 화면)이며 이 문서에 포함하지 않는다.

## Screens

### `/dashboard/admin`

| 영역 | 내용 | 노출 조건 |
| --- | --- | --- |
| 상단 요약 카드 | 이번 달 조직 LLM 비용(USD), 예산 위험/초과 workflow 비율 | organization owner/manager |
| 감사 로그 탭 | 조직 audit log 검색/필터 + 상세 드로어 | audit `auditor` 이상 |
| 권한 신청 탭 | 신청 목록 + 승인/거절 | organization owner/manager |
| 비용 탭 | workflow별 사용량/비용 집계 | organization owner/manager |
| 기존 탭들 (구성원/팀/권한/credential/knowledge/조직) | 기존 구현 유지 — 이 feature 범위 아님 | 기존 기준 유지 |

- (후순위) `auditor`/`raw_auditor` 전용 사용자에게는 감사 로그 탭만 노출하고 기본 탭을 감사 로그로 한다. 요약 카드와 나머지 탭은 렌더링하지 않는다. 현재 데모 시나리오에서 auditor 전용 계정을 사용하지 않으므로 이 노출 제어는 후순위로 미룬다. 구현 전까지 admin 페이지 접근은 기존 organization manager 게이트를 유지한다.
- 프론트 노출 제어는 UX 보조이며 최종 차단은 Gateway가 수행한다 (NFR-001). 권한 없는 API 응답(403)은 안내 문구로 처리한다. auditor 전용 노출 제어가 후순위인 동안에도 이 서버 경계는 그대로 적용된다.

## Components

### AdminSummaryCards (FR-015)

- 기존 `DashboardSummaryCard`를 재사용한 카드 2장: "이번 달 LLM 비용", "예산 위험 workflow".
- 비용은 USD 소수점 2자리로 표시한다 (표시 직전 1회 반올림).
- 예산 카드가 의존하는 판정/분모는 예산 관리 feature(PRD FR-051, 문서 TBD) 확정에 종속된다. API의 `budget` 블록이 null이면 카드에 "예산 미설정" 상태를 표시한다.
- 데이터 원천: `GET /admin/summary`.

### AuditSearchTab (FR-011)

- 필터 바: 행위자(기존 `ActiveOrganizationMemberPicker` 재사용), action(canonical action 문자열 입력/선택), 대상 타입/ID, 기간(`startAt`/`endAt`, KST 기준 입력), status. 필터 초기화 버튼을 둔다.
- 결과 테이블 컬럼: 발생 시각(사용자 로컬 시간대 렌더링), 행위자, action(사용자 친화 라벨 병기 — canonical action에서 파생), 대상, status 배지.
- Pagination: `page`/`limit` 기반, 기존 목록 패턴을 따른다.
- 행 클릭 → `AuditDetailDrawer` 열림.
- 데이터 원천: `GET /admin/audit-logs`.

### AuditDetailDrawer (FR-011)

- 화면 오른쪽 사이드 드로어. 목록 맥락을 유지한 채 상세를 보여준다.
- 표시 필드: actor, action(canonical 문자열과 파생 라벨), target, status, timestamp, allowlist metadata(`request_id`, `reason` 등).
- raw payload, secret 계열 값은 표시하지 않는다 (NFR-004). raw payload 접근 UI는 이 feature 범위가 아니다 (trace visibility policy).
- 데이터 원천: `GET /admin/audit-logs/{id}`.

### PermissionRequestsTab (FR-014)

- status 필터: 기본 `pending`, `approved`/`rejected` 전환 가능.
- 테이블 컬럼: 요청자(이름/이메일), 요청 권한(`app.create`의 사용자 친화 라벨 — "workflow 생성/배포"), 신청 사유, 신청일, 상태 배지. 처리된 건은 처리자/처리 시각 표시.
- pending 행에만 `승인`/`거절` 버튼을 인라인으로 둔다.
- 버튼 클릭 → `ConfirmDialog`: 요청자, 요청 권한, 신청 사유를 재표시하고 확정을 받는다. 되돌릴 수 없는 액션이므로 즉시 처리하지 않는다.
- 확정 시 `POST /admin/permission-requests/{id}/approve|reject` 호출. 성공하면 toast(기존 sonner)로 알리고 목록을 갱신한다.
- 데이터 원천: `GET /admin/permission-requests`.

같은 탭 하단에 `보유 권한` 섹션을 둔다 (FR-014 회수 확장).

- 테이블 컬럼: 보유자(이름/이메일), 부여자, 부여일. 행별 `회수` 버튼을 인라인으로 둔다.
- organization owner/manager는 row 없이 허용되므로 이 목록에 나타나지 않는다. 섹션 설명에 이 사실을 안내하고, 빈 목록은 "부여된 App 생성 권한이 없습니다" empty state로 표시한다.
- `회수` 클릭 → `ConfirmDialog`: 보유자와 권한 라벨(`app.create`의 사용자 친화 라벨)을 재표시하고 확정을 받는다. 되돌릴 수 없는 액션이므로 즉시 처리하지 않는다.
- 확정 시 `DELETE /admin/app-creation-permissions/{permission_id}` 호출. 성공하면 toast로 알리고 보유 목록을 갱신한다. 회수된 사용자는 재신청할 수 있으므로 신청 목록도 함께 갱신한다.
- `404` 응답(이미 회수됐거나 없는 row)은 "이미 회수된 권한입니다" toast 후 목록 갱신.
- 데이터 원천: `GET /admin/app-creation-permissions`.

### UsageTab (FR-012)

- 기간 필터: 기본 이번 달(KST), `startAt`/`endAt` 지정 가능.
- 테이블 컬럼: workflow 이름, 호출 수, prompt/completion tokens, 비용(USD 2자리). 비용 내림차순 고정 정렬.
- 행에 해당 workflow로 이동하는 링크/버튼을 둔다 — 비용 최적화 실행은 workflow 문맥의 [cost-optimizer](../cost-optimizer/component_spec.md) 범위이며 이 탭은 진입만 제공한다.
- workflow별 예산 사용률 컬럼은 예산 feature 확정 후 추가한다.
- 데이터 원천: `GET /admin/usage/workflows`.

## States

- 각 탭 공통: 로딩(스켈레톤 또는 스피너), 빈 목록(안내 문구 포함 empty state), 오류(재시도 버튼).
- 검색 결과 없음은 오류가 아니라 빈 목록 상태다 (`{total: 0}`).
- 권한 신청 처리 중: 해당 행 버튼 비활성화(중복 클릭 방지). 409 응답(이미 처리된 신청)은 "이미 처리된 신청입니다" toast 후 목록 갱신.
- 권한 회수 처리 중: 확인 다이얼로그의 버튼을 비활성화한다(중복 클릭 방지, modal이 행 버튼 접근을 막는다). 404 응답(이미 회수된 권한)은 "이미 회수된 권한입니다" toast 후 목록 갱신.
- 요약 카드의 `budget` null 상태: "예산 미설정" 표시 (오류 아님).
- (후순위) auditor 전용 사용자: 감사 로그 탭 단독 노출 상태. auditor 전용 노출 제어와 함께 복원한다.
- 403 응답: 접근 권한 안내 문구 (프론트 노출 제어를 우회한 접근 대비).

## Interactions

1. 탭 전환: 기존 admin 페이지 탭 패턴을 따른다. 탭 상태는 페이지 내 state로 유지한다.
2. audit 검색: 필터 변경 → 조회 버튼 또는 디바운스 적용 → 1페이지부터 재조회.
3. audit 행 클릭 → 드로어 열림. ESC/바깥 클릭/닫기 버튼으로 닫힘.
4. 권한 신청 승인: `승인` 클릭 → ConfirmDialog → 확정 → API 호출 → 성공 toast → 목록 갱신. 거절도 동일 흐름.
5. 비용 행의 workflow 링크 클릭 → 해당 workflow 화면으로 이동.
6. 요약 카드는 페이지 진입 시 로드하고 탭 전환과 무관하게 유지한다.

## Accessibility

- 드로어와 ConfirmDialog는 포커스 트랩, ESC 닫기, 적절한 `role`(`dialog`)과 `aria-label`을 갖는다.
- 테이블은 `<th>` 헤더와 캡션을 갖고, 정렬 기준(비용 내림차순)을 시각적으로 표시한다.
- status/상태 배지는 색상 외에 텍스트를 병기한다 (색맹 대응).
- 승인/거절 버튼은 처리 중 `disabled`와 로딩 표시를 제공한다.
- 시간 표시는 `<time datetime>` 속성에 ISO 값을 유지한다 (표시는 사용자 로컬).
