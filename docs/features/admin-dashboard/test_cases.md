# Admin Dashboard Test Cases

Status: Draft
Verified Against: TBD

[PRD](../../PRD.md) 시나리오 4와 FR-011~FR-014를 검증한다.

## Unit Tests

- (FR-012) workflow별 비용 집계가 `llm_usage_logs`의 합산과 일치한다 (`total_cost`가 NULL인 row 처리 포함).
- (FR-011) 기간 필터의 경계값 처리: 시작/끝 시각과 정확히 같은 `occurred_at` row의 포함 여부가 정의대로 동작한다.
- (FR-013) 비정상 접근 판정 로직이 `permission.denied` 계열 이벤트를 정확히 분류한다 (기준 확정 시 케이스 추가).

## API Tests

- (FR-011) audit 검색: 행위자/action/대상/기간 필터가 각각, 그리고 조합으로 동작한다. action 값은 canonical action 문자열 기준이다 ([ADR-0008](../../decisions/ADR-0008-audit-action-naming-standard.md)).
- (FR-012) 비용 집계 응답이 요청 organization scope 안의 workflow만 포함한다.
- (FR-014) 유저 비활성화 → `users.deactivated_at` 설정, 해당 action이 audit에 기록된다.
- (FR-013) 차단 이벤트 목록이 `permission.denied`와 `auth.permission_denied`를 포함하고, 404로 숨긴 scope 밖 접근은 포함하지 않는다 ([ADR-0010](../../decisions/ADR-0010-resource-access-403-404-policy.md) — audit 미기록 대상).

## E2E Tests

- **시나리오 4 완주**: audit 검색 → workflow별 비용 확인 → 비정상 접근 시도 표시 → 유저 비활성화까지 실제 데이터로 완주한다.
- 시나리오 2와의 연결: 권한 없는 실행 시도로 생긴 `permission.denied`가 대시보드 차단 이력에 표시된다.

## Permission Tests

- `auditor` 권한 사용자는 audit 조회가 가능하고, 유저 비활성화 같은 관리 액션은 거부된다.
- 일반 member(audit 권한 없음)의 대시보드 audit 조회 → 403.
- 다른 organization의 audit/비용 데이터가 응답에 포함되지 않는다.
- raw payload 조회는 대시보드 권한이 아니라 trace visibility policy와 별도 권한으로 판정된다.

## Edge Cases

- 비활성화된 유저의 후속 API 요청이 fail-closed로 거부된다.
- 비활성화된 유저가 부여받았던 user direct permission이 권한 평가에서 무시된다.
- `audit_metadata`에 저장된 값 중 secret 계열 값이 대시보드 응답에 노출되지 않는다.
- 검색 결과가 없는 기간 → 빈 목록 정상 응답.
- 관리자가 자기 자신을 비활성화하려는 시도의 처리 방침이 정의돼 있다 (거부 권장).
