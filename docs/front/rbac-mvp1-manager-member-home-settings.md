# MVP1 Manager/Member Home Settings Split

Status: Draft
Authority: Frontend Implementation Guide
Source of Truth: No
Verified Against: feature/mba-71 @ 32dd82e90400db2ea5e28b49c4fdc1d989057552

## 목적

이 문서는 `MBA-71` 프론트 작업 전에 manager와 member의 홈/설정 화면 분리 기준을 정리한다.

MVP1의 권한 모델은 전체 organization membership이 아니라 team 기반 membership을 현재 구현 기준으로 사용한다. 따라서 이 작업은 organization invitation, accept, `organization_memberships` 상태 관리를 만들지 않고, 현재 `organization`, `teams`, `team_memberships`, resource permission API로 표현 가능한 화면만 다룬다.

## 관련 기준 문서

| 영역 | 문서 |
| --- | --- |
| 문서 권위 | `docs/foundation/document-authority.md` |
| RBAC 정책 | `docs/data-model/rbac-permission-policy.md` |
| active organization | `docs/architecture/auth-rbac.md` |
| organization/team/permission API | `docs/api/organization-rbac.md` |
| app/workflow API | `docs/api/apps-workflows.md` |
| RBAC 화면 개요 | `docs/front/rbac-permission-ui-overview.md` |
| workflow 권한 UI | `docs/front/rbac-workflow-access-matrix.md` |
| RBAC API 연동 | `docs/front/rbac-permission-api-integration.md` |

## 구현 기준

### MVP1에서 사용하는 멤버 기준

MVP1에서 organization 소속은 active `team_memberships`를 통해 간접 표현된다.

| 개념 | MVP1 구현 기준 |
| --- | --- |
| organization manager | `organization.created_by` 또는 `organization.managed_by`인 user |
| organization member | active team membership으로 organization scope 안에 있는 user |
| team member | `team_memberships` row가 있고 team이 active인 user |
| workspace member | 이 문서에서는 쓰지 않는다. MVP2-0 `organization_memberships` 범위와 혼동되기 때문이다. |

### Manager/member 판정 입력

MBA-71 프론트는 `OrganizationResponse.is_manager`를 화면 분기의 기준으로 사용한다.

이 필드는 `docs/api/organization-rbac.md`의 `OrganizationResponse` 계약에 포함되어 있으며, 현재 요청 user 기준으로 계산된다.

| 조건 | `is_manager` |
| --- | --- |
| `organization.created_by == current_user.id` | `true` |
| `organization.managed_by == current_user.id` | `true` |
| 그 외 active team membership user | `false` |

프론트는 `created_by`, `managed_by`를 직접 계산하지 않는다. Settings와 Home 모두 organization API 응답의 `is_manager`를 신뢰한다.

### MVP1에서 하지 않는 것

- organization invitation API
- invitation accept flow
- `organization_memberships.membership_state`
- `invited`, `active`, `suspended`, `removed` organization member 상태 UI
- member promote/demote
- organization member remove cleanup
- full organization switcher
- team에 속하지 않은 active organization member 관리

## 현재 코드 연결 지점

| 파일 | 현재 역할 | MBA-71에서 확인할 점 |
| --- | --- | --- |
| `apps/client/app/dashboard/page.tsx` | 정적 홈 quick action 화면 | manager/member별 organization/team/workflow summary를 추가할 위치 |
| `apps/client/app/dashboard/settings/page.tsx` | Settings access/credentials/activity 탭과 RBAC 관리 UI | `organization.is_manager` 기준으로 access 탭 노출과 action 제어 |
| `apps/client/app/features/dashboard/components/Sidebar.tsx` | dashboard navigation과 organization 이름 표시 | member에게 Settings 전체 또는 조직 접근만 숨길지 결정 |
| `apps/client/lib/activeOrganization.ts` | active organization id localStorage 저장과 `X-Organization-Id` header 생성 | 홈과 설정에서 같은 active organization 기준 사용 |
| `apps/client/app/features/app/api/appApi.ts` | `/apps` API client | 홈에서 접근 가능한 app/workflow 목록 조회 |
| `apps/client/app/features/workflow/api/workflowApi.ts` | workflow 상세와 `/permissions/me` 조회 | workflow별 내 권한 badge 계산 |

## API 연동 기준

### Organization

| API | 용도 | 주의 |
| --- | --- | --- |
| `GET /api/v1/organizations` | 현재 user가 접근 가능한 organization 목록 | MVP1에서는 active team membership 기반 |
| `GET /api/v1/organizations/current` | active organization 검증 | `OrganizationResponse.is_manager`로 manager/member 화면을 분기한다. |
| `GET /api/v1/organizations/{organization_id}` | organization 상세 조회 | 필요 시 동일한 `is_manager` 계약을 사용한다. |

`organization.is_manager`는 MBA-72에서 API 계약과 백엔드 응답에 반영된 필드다. MBA-71은 별도 manager 판정 API를 만들지 않고 이 필드를 기준으로 Settings access tab, Home summary, manager-only API 호출 여부를 제어한다.

### Manager 전용 Team API

| API | 용도 | 화면 |
| --- | --- | --- |
| `GET /api/v1/users?organization_id={id}` | team 기반 active user 목록 | manager 홈, Settings access |
| `GET /api/v1/teams` | team 목록 | manager 홈, Settings access |
| `GET /api/v1/teams/{team_id}/members` | team별 member map | manager 홈, Settings access |
| `POST /api/v1/teams` | team 생성 | manager 화면 |
| `PATCH /api/v1/teams/{team_id}` | team 수정 | manager 화면 |
| `DELETE /api/v1/teams/{team_id}` | team soft delete, 즉 비활성화 | manager 화면 |
| `POST /api/v1/teams/{team_id}/members` | team member 추가 | manager 화면 |
| `DELETE /api/v1/teams/{team_id}/members/{user_id}` | team member 제거 | manager 화면 |

`GET /api/v1/teams`는 inactive team도 반환한다. 프론트는 active team과 inactive team을 구분해야 한다. MVP1에서는 inactive team을 숨기거나 `비활성` 배지로 표시한다.

### Member 홈 조회

현재 구현에는 일반 member가 자신의 team 목록만 직접 조회하는 dedicated API가 없다.

가능한 선택지는 다음 중 하나다.

| 선택지 | 설명 | 판단 |
| --- | --- | --- |
| 프론트 우회 없음 | manager 전용 `GET /teams`를 member에게 호출하지 않는다. | 권장 기본값 |
| member용 API 추가 | `GET /api/v1/teams/me` 또는 유사 endpoint로 내 team 목록을 제공한다. | 홈에서 "내 소속 team"이 필수이면 필요 |
| 제한적 화면 | member 홈에는 organization 이름과 accessible app/workflow 권한만 먼저 보여준다. | API 추가 없이 가능한 MVP1 최소 범위 |

MBA-71에서 "member가 자신이 속한 team 목록을 본다"를 반드시 만족하려면 member용 team 조회 API가 필요하다. 현재 `GET /api/v1/teams`와 `GET /api/v1/teams/{team_id}/members`는 manager 전용이므로 member 화면에서 호출하지 않는다.

따라서 MBA-71의 FE-only 기본 구현은 다음으로 제한한다.

- member Home은 organization summary와 접근 가능한 app/workflow 권한 표시를 우선 제공한다.
- member의 team 목록은 dedicated API가 생기기 전까지 섹션을 노출하지 않는다.
- member용 team 조회가 필수 요구가 되면 `GET /api/v1/teams/me` 같은 별도 BE 이슈를 만든다.

### Workflow/App 권한 표시

| API | 용도 | 주의 |
| --- | --- | --- |
| `GET /api/v1/apps` | 접근 가능한 app 목록 | app read는 organization manager 또는 primary workflow read 권한 기준 |
| `GET /api/v1/workflows/{workflow_id}/permissions/me` | 내 workflow effective permission 조회 | read 권한이 있어야 응답할 수 있으므로 `none` 상태 응답 정책은 API 문서 보강 필요 |

홈에서 app/workflow 권한 badge를 표시하려면 `/apps` 응답의 `workflow_id`가 있는 항목마다 `/workflows/{workflow_id}/permissions/me`를 호출한다. 실패한 항목은 전체 홈 로드를 깨지 말고, 해당 row에 권한 조회 실패 상태를 표시한다.

## 화면 구조

### Manager 홈

Manager 홈은 반복 사용을 위한 운영 화면이어야 한다. 기존 marketing-style quick action만 유지하지 않고, 현재 organization의 team 기반 관리 요약을 추가한다.

권장 섹션:

| 섹션 | 내용 |
| --- | --- |
| Organization summary | organization 이름, 현재 user 권한 `manager` |
| Team management summary | active team 수, inactive team 수, team별 member 수 |
| Team list | team name, active/inactive 상태, member preview, 관리 action |
| Workflow access list | app/workflow 이름, 내 권한, 관리 가능 여부 |

Manager 홈에서 destructive action을 직접 제공할 경우 확인 dialog를 유지한다. 홈에서 모든 form을 넣기보다 Settings access로 이동하는 action을 둘 수도 있다.

### Member 홈

Member 홈은 "내가 무엇을 볼 수 있고 무엇을 할 수 있는지"를 먼저 보여준다.

권장 섹션:

| 섹션 | 내용 |
| --- | --- |
| Organization summary | organization 이름, 현재 user 권한 `member` |
| My workflow access | 접근 가능한 app/workflow 목록, `viewer/operator/builder/manager` badge |
| Available actions | 권한별 실행/수정 가능 여부 |

Member에게 manager 전용 CTA를 노출하지 않는다. 권한이 부족한 action은 workflow 실행/수정처럼 이유를 알아야 하는 경우만 disabled와 설명을 사용한다.

### Settings

| 상태 | Settings 탭 |
| --- | --- |
| manager | `조직 접근`, `LLM Credentials`, `Activity` 표시 |
| member | `조직 접근` 숨김. 기본 탭은 `LLM Credentials` 또는 `Activity`로 이동 |

member가 직접 `/dashboard/settings`로 진입했을 때 `activeTab === 'access'`가 되지 않도록 초기 탭과 탭 전환을 제어한다. MBA-71 기본값은 member를 `LLM Credentials` 탭으로 보낸다. 직접 URL로 access 상태가 복원되는 구조가 생기면 permission denied state를 보여준다.

## 권한별 UI 동작

| 화면/행동 | manager | member |
| --- | --- | --- |
| Settings 조직 접근 탭 | 표시 | 숨김 또는 접근 차단 |
| team 목록 조회 | 가능 | dedicated API 없으면 미노출 |
| team 생성 | 가능 | 숨김 |
| team 수정 | 가능 | 숨김 |
| team 비활성화 | 가능 | 숨김 |
| team member 추가/제거 | 가능 | 숨김 |
| workflow permission grant/revoke | 가능 | 숨김 |
| LLM credential permission grant/revoke | 가능 | 숨김 |
| app/workflow 목록 | 접근 권한 기준 표시 | 접근 권한 기준 표시 |
| workflow 권한 badge | 표시 | 표시 |

## Error/empty/loading

| 상태 | 표시 기준 |
| --- | --- |
| loading | organization, teams, apps, permissions를 나눠 skeleton 또는 inline loading 표시 |
| empty organization | 접근 가능한 organization 없음 |
| empty team | manager에게 team 생성 CTA 제공. member에게는 "소속 team 없음" 표시 |
| inactive team | active team처럼 조작 가능한 row로 보이지 않게 숨김 또는 badge 표시 |
| permission denied | member가 manager 전용 화면/action에 접근한 경우 |
| API error | HTTP status와 action 기준 메시지. `Request failed`만 노출하지 않는다. |

## 구현 순서

MBA-71은 Settings access tab 노출 문제가 먼저 사용자에게 보이는 문제이므로 Settings를 먼저 고치고 Home을 확장한다.

| 순서 | 작업 | 기준 |
| --- | --- | --- |
| 1 | `OrganizationResponse` 프론트 타입 확인 | `is_manager`를 필수 필드로 사용 |
| 2 | Settings tab guard | member에게 `조직 접근` 탭 미노출, 기본 탭은 `LLM Credentials` |
| 3 | Settings API 호출 분리 | manager 전용 API는 `organization.is_manager === true`일 때만 호출 |
| 4 | Settings error state 정리 | member 화면에서 manager-only API 실패가 `Request failed`로 노출되지 않게 처리 |
| 5 | Manager Home 보강 | team summary, inactive team 구분, workflow access summary |
| 6 | Member Home 보강 | organization summary, 접근 가능한 app/workflow, workflow permission badge |
| 7 | QA | manager/member 계정으로 Settings와 Home을 각각 확인 |

## 구현 메모

1. `organization.is_manager`는 API 응답 계약으로 존재하므로 프론트는 이 값을 기준으로 분기한다.
2. `SettingsPage`는 manager가 아닐 때 `access` 탭을 렌더링하지 않는다.
3. `SettingsPage.loadData()`는 manager 전용 API와 공용 API를 분리 호출한다. member가 `GET /users`, `GET /teams`, permission grant list API 실패 때문에 전체 설정 화면이 깨지면 안 된다.
4. Home은 organization/app/workflow permission 조회를 병렬화하되, 개별 permission 조회 실패가 전체 Home 실패가 되지 않게 한다.
5. inactive team은 `is_active`와 `deactivated_at`을 기준으로 UI에서 구분한다.
6. member용 "내 team 목록"은 현재 API가 없으므로 MBA-71 FE-only 범위에서는 manager 전용 API를 우회 호출하지 않는다.

## QA 체크리스트

- [ ] manager 로그인 시 Settings > 조직 접근 탭이 보인다.
- [ ] manager는 team 생성, member 추가/제거, team 비활성화를 수행할 수 있다.
- [ ] manager는 workflow/LLM credential permission grant/revoke UI를 볼 수 있다.
- [ ] inactive team은 active team과 구분된다.
- [ ] member 로그인 시 Settings > 조직 접근 탭이 보이지 않는다.
- [ ] member가 설정에 직접 진입해도 manager 전용 API 실패가 전체 화면을 깨지 않는다.
- [ ] member 홈에서 접근 가능한 app/workflow 목록이 보인다.
- [ ] member 홈에서 workflow 권한 badge가 표시된다.
- [ ] member는 manager 전용 action을 사용할 수 없다.
- [ ] API 403/404가 사용자 행동 기준 메시지로 표시된다.
- [ ] 기존 LLM Credentials 탭과 Activity 탭이 깨지지 않는다.

## 남은 결정

| 항목 | 필요한 결정 |
| --- | --- |
| member용 내 team 목록 | `GET /teams/me` 같은 API를 후속 BE 이슈로 추가할지 |
| inactive team UX | 숨김과 비활성 배지 중 어느 방식을 기본으로 할지 |
| 홈 화면 배치 | 기존 quick action을 유지할지, manager/member 요약을 첫 화면 상단으로 올릴지 |
